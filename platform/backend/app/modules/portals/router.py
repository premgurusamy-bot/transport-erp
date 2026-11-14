"""External portals (customer, vehicle owner, vendor), driver app endpoints and public website APIs.

Every query here is filtered by the caller's own customer_id / owner_id / vendor_id / driver_id (tenant isolation)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404
from app.core.db import utcnow
from app.core.deps import Principal, get_db, require
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden, NotFound
from app.core.services import get_config, next_number
from app.integrations.adapters import get_adapter
from app.modules.commercial import router as com
from app.modules.commercial.models import Booking, Enquiry, ModificationRequest, Quotation
from app.modules.finance.models import Invoice, Payment, Settlement
from app.modules.fleet.models import ComplianceItem, Driver, Vehicle
from app.modules.masters.models import Customer, Location, VehicleOwner, Vendor
from app.modules.operations.models import OwnerOffer, ProofOfDelivery, Trip, TripEvent, TripLoad
from app.modules.operations.router import trip_out
from app.modules.operations.service import position
from app.modules.platform.models import Document
from app.modules.supply.models import PurchaseOrder, PurchaseRequest, VendorInvoice

router = APIRouter(prefix="/api/v1", tags=["portals"])


def _cust(p: Principal) -> uuid.UUID:
    if not p.customer_id:
        raise Forbidden()
    return p.customer_id


# ===================================================================== customer portal
@router.get("/portal/customer/profile")
def c_profile(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    c = db.get(Customer, _cust(p))
    from app.modules.commercial.credit import exposure
    ex = exposure(db, c.id)
    return {"name": c.name, "code": c.code, "gstin": c.gstin, "billing_address": c.billing_address, "billing_cycle": c.billing_cycle,
            "outstanding": str(ex["outstanding"]), "overdue": str(ex["overdue"])}


@router.post("/portal/customer/enquiries")
def c_enquiry(body: com.EnquiryIn, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    e = com.create_enquiry(db, p, body, customer_scope=_cust(p))
    return {"code": e.code, "status": e.status, "missing_fields": e.missing_fields}


@router.get("/portal/customer/quotations")
def c_quotes(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    rows = db.execute(select(Quotation).where(Quotation.customer_id == _cust(p), Quotation.status.in_(("sent", "accepted", "expired")))
                      .order_by(Quotation.created_at.desc())).scalars()
    return [com.quote_customer_out(q) for q in rows]


@router.post("/portal/customer/quotations/{qid}/accept")
def c_accept(qid: uuid.UUID, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    q = get_or_404(db, Quotation, qid, "Quotation", lock=True)
    if q.customer_id != _cust(p):
        raise NotFound("Quotation")
    if q.status != "sent":
        raise BlockedByRule("not_sent", "This quotation is not open for acceptance")
    com.accept_quote(db, p, q, com.AcceptIn(accepted_by=p.name, channel="portal"))
    return com.quote_customer_out(q)


def _cust_booking_out(db: Session, b: Booking) -> dict:
    d = com.booking_out(db, b, internal=False)
    for k in ("credit_snapshot", "credit_status", "quotation_id", "created_via"):
        d.pop(k, None)
    return d


@router.get("/portal/customer/bookings")
def c_bookings(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    rows = db.execute(select(Booking).where(Booking.customer_id == _cust(p)).order_by(Booking.created_at.desc())).scalars()
    return [_cust_booking_out(db, b) for b in rows]


class CustomerBookingIn(com.BookingIn):
    pass


@router.post("/portal/customer/bookings")
def c_book(body: CustomerBookingIn, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    """Portal bookings must come from an accepted quotation (prices are never set by the customer)."""
    if not body.quotation_id:
        raise BlockedByRule("quote_required", "Please request a quotation first; bookings are created from accepted quotations")
    q = db.get(Quotation, body.quotation_id)
    if not q or q.customer_id != _cust(p):
        raise NotFound("Quotation")  # never reveal other tenants' quotations
    body.customer_id = _cust(p)
    b = com.create_booking(db, p, body, via="portal", customer_scope=_cust(p))
    return _cust_booking_out(db, b)


@router.get("/portal/customer/bookings/{bid}")
def c_booking(bid: uuid.UUID, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    if b.customer_id != _cust(p):
        raise NotFound("Booking")
    out = _cust_booking_out(db, b)
    tl = db.execute(select(TripLoad).where(TripLoad.booking_id == b.id, TripLoad.status != "removed")).scalars().first()
    if tl:
        t = db.get(Trip, tl.trip_id)
        pos = position(db, t.vehicle_id, t.id) if t.status in ("dispatched", "in_transit") else None
        v = db.get(Vehicle, t.vehicle_id)
        out["tracking"] = {
            "trip_status": t.status, "vehicle": v.registration, "eta": t.eta, "eta_source": t.eta_source,
            "position": {k: pos[k] for k in ("state", "lat", "lng", "recorded_at", "age_minutes")} if pos else None,
            "shared_transport": t.trip_mode == "PTL",
            "milestones": [{"event": e.event, "at": e.occurred_at, "note": e.note if e.booking_id in (None, b.id) else None}
                           for e in db.execute(select(TripEvent).where(TripEvent.trip_id == t.id, TripEvent.customer_visible.is_(True))
                                               .order_by(TripEvent.occurred_at)).scalars()
                           if e.booking_id in (None, b.id)],  # PTL: never show other consignments' milestones
        }
    pod = db.execute(select(ProofOfDelivery).where(ProofOfDelivery.booking_id == b.id)).scalar_one_or_none()
    out["pod"] = {"status": pod.status, "delivered_at": pod.delivered_at, "receiver": pod.receiver_name, "delivered_count": pod.delivered_count} if pod else None
    out["documents"] = [{"id": str(d.id), "type": d.doc_type, "filename": d.filename} for d in db.execute(select(Document).where(
        Document.customer_id == b.customer_id, Document.entity == "booking", Document.entity_id == str(b.id),
        Document.visible_to_customer.is_(True), Document.deleted_at.is_(None))).scalars()]
    return out


class ModReqIn(BaseModel):
    kind: str = Field(pattern="^(modify|cancel)$")
    changes: dict = {}
    reason: str = Field(min_length=3)


@router.post("/portal/customer/bookings/{bid}/requests")
def c_mod_request(bid: uuid.UUID, body: ModReqIn, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    if b.customer_id != _cust(p):
        raise NotFound("Booking")
    m = ModificationRequest(booking_id=b.id, requested_by=p.user_id, **body.model_dump())
    db.add(m)
    db.flush()
    from app.core.services import raise_exception_task
    raise_exception_task(db, kind="followup", severity="medium", title=f"Customer {body.kind} request on {b.code}", entity="booking",
                         entity_id=b.id, source="portal", owner_role="customer_support")
    return {"status": "requested", "note": "A change is only a request until G ROAD LINES confirms it is authorised and feasible."}


@router.get("/portal/customer/invoices")
def c_invoices(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    rows = db.execute(select(Invoice).where(Invoice.customer_id == _cust(p), Invoice.status != "cancelled").order_by(Invoice.invoice_date.desc())).scalars()
    return [{"id": str(i.id), "number": i.number, "date": i.invoice_date, "due_date": i.due_date, "total": str(i.total),
             "received": str(i.amount_received), "tds": str(i.tds_received), "status": i.status,
             "balance": str(Decimal(i.total) - Decimal(i.amount_received) - Decimal(i.tds_received))} for i in rows]


@router.get("/portal/customer/statement")
def c_statement(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    from app.modules.finance.router import customer_statement
    return customer_statement(db, _cust(p))


class PayIn(BaseModel):
    invoice_id: uuid.UUID


@router.post("/portal/customer/pay")
def c_pay(body: PayIn, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    """Creates a gateway order. Payment is confirmed ONLY by a server-side gateway confirmation + bank reconciliation."""
    inv = get_or_404(db, Invoice, body.invoice_id, "Invoice")
    if inv.customer_id != _cust(p):
        raise NotFound("Invoice")
    bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
    res = get_adapter("payment_gateway").create_order(bal, inv.number)
    return {**res.data, "mode": res.mode, "note": "MOCK gateway - no real payment can be made yet."}


@router.post("/portal/customer/complaints")
def c_complaint(body: dict, p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    from app.modules.risk.router import ComplaintIn, create_complaint
    c = create_complaint(db, p, ComplaintIn(**body), customer_scope=_cust(p))
    return {"code": c.code, "status": c.status, "response_due_at": c.response_due_at}


@router.get("/portal/customer/complaints")
def c_complaints(p: Principal = Depends(require("portal.customer")), db: Session = Depends(get_db)):
    from app.modules.risk.models import Complaint
    return [{"code": c.code, "category": c.category, "status": c.status, "resolution": c.resolution, "created_at": c.created_at}
            for c in db.execute(select(Complaint).where(Complaint.customer_id == _cust(p)).order_by(Complaint.created_at.desc())).scalars()]


@router.get("/portal/customer/users")
def c_users(p: Principal = Depends(require("portal.customer_admin")), db: Session = Depends(get_db)):
    from app.modules.platform.models import User
    return [{"id": str(u.id), "name": u.name, "email": u.email, "active": u.is_active, "roles": [r.code for r in u.roles]}
            for u in db.execute(select(User).where(User.customer_id == _cust(p))).scalars()]


class CustUserIn(BaseModel):
    name: str
    email: EmailStr
    password: str


@router.post("/portal/customer/users")
def c_add_user(body: CustUserIn, p: Principal = Depends(require("portal.customer_admin")), db: Session = Depends(get_db)):
    from app.modules.platform.router import UserIn, create_user
    u = create_user(db, p, UserIn(name=body.name, email=str(body.email), password=body.password, roles=["customer_user"], customer_id=_cust(p)))
    return {"id": str(u.id), "name": u.name}


# ===================================================================== vehicle owner portal
def _own(p: Principal) -> uuid.UUID:
    if not p.owner_id:
        raise Forbidden()
    return p.owner_id


@router.get("/portal/owner/summary")
def o_summary(p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    oid = _own(p)
    o = db.get(VehicleOwner, oid)
    vehicles = list(db.execute(select(Vehicle).where(Vehicle.owner_id == oid)).scalars())
    vout = []
    for v in vehicles:
        docs = [{"kind": c.kind, "valid_to": c.valid_to, "verification": c.verification} for c in db.execute(
            select(ComplianceItem).where(ComplianceItem.subject_type == "vehicle", ComplianceItem.subject_id == v.id, ComplianceItem.status == "current")).scalars()]
        vout.append({"id": str(v.id), "registration": v.registration, "status": v.status, "payload_kg": v.payload_kg, "documents": docs,
                     "available_from": v.available_from})
    return {"owner": {"name": o.name, "code": o.code, "kyc_status": o.kyc_status, "status": o.status}, "vehicles": vout}


class AvailabilityIn(BaseModel):
    vehicle_id: uuid.UUID
    available_from: datetime
    note: str | None = None


@router.post("/portal/owner/availability")
def o_availability(body: AvailabilityIn, p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    if v.owner_id != _own(p):
        raise NotFound("Vehicle")
    v.available_from = body.available_from
    return {"ok": True}


@router.get("/portal/owner/offers")
def o_offers(p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    return [{"id": str(o.id), "code": o.code, "lane": o.lane, "vehicle_requirement": o.vehicle_requirement, "required_on": o.required_on,
             "owner_quote": str(o.owner_quote) if o.owner_quote else None, "negotiated_rate": str(o.negotiated_rate) if o.negotiated_rate else None,
             "advance_pct": str(o.advance_pct), "status": o.status, "terms": o.terms}
            for o in db.execute(select(OwnerOffer).where(OwnerOffer.owner_id == _own(p)).order_by(OwnerOffer.created_at.desc())).scalars()]


class OwnerQuoteIn(BaseModel):
    amount: Decimal = Field(gt=0)


@router.post("/portal/owner/offers/{oid}/quote")
def o_quote(oid: uuid.UUID, body: OwnerQuoteIn, p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    o = get_or_404(db, OwnerOffer, oid, "Offer", lock=True)
    if o.owner_id != _own(p):
        raise NotFound("Offer")
    if o.status not in ("requested", "quoted"):
        raise Conflict("bad_status", f"Offer is {o.status}")
    o.owner_quote, o.status = body.amount, "quoted"
    write_audit(db, actor=p, action="owner_offer.quote", entity="owner_offer", entity_id=o.id, after={"quote": body.amount})
    return {"status": o.status}


class OwnerAcceptIn(BaseModel):
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID
    confirm_documents_valid: bool


@router.post("/portal/owner/offers/{oid}/accept")
def o_accept(oid: uuid.UUID, body: OwnerAcceptIn, p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    o = get_or_404(db, OwnerOffer, oid, "Offer", lock=True)
    oid_ = _own(p)
    if o.owner_id != oid_:
        raise NotFound("Offer")
    if o.status not in ("quoted", "negotiated"):
        raise Conflict("bad_status", f"Offer is {o.status}")
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    d = get_or_404(db, Driver, body.driver_id, "Driver")
    if v.owner_id != oid_ or (d.owner_id and d.owner_id != oid_):
        raise Forbidden("Vehicle/driver not registered under your account")
    if not body.confirm_documents_valid:
        raise BlockedByRule("documents", "Confirm the vehicle and driver documents are valid")
    o.vehicle_id, o.driver_id, o.status, o.accepted_at = v.id, d.id, "accepted", utcnow()
    write_audit(db, actor=p, action="owner_offer.accept", entity="owner_offer", entity_id=o.id,
                after={"vehicle": v.registration, "driver": d.name, "rate": o.negotiated_rate or o.owner_quote})
    return {"status": o.status, "note": "G ROAD LINES will verify documents before dispatch."}


@router.post("/portal/owner/offers/{oid}/decline")
def o_decline(oid: uuid.UUID, p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    o = get_or_404(db, OwnerOffer, oid, "Offer")
    if o.owner_id != _own(p):
        raise NotFound("Offer")
    o.status = "declined"
    return {"status": o.status}


@router.get("/portal/owner/trips")
def o_trips(p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    out = []
    for t in db.execute(select(Trip).where(Trip.owner_id == _own(p)).order_by(Trip.created_at.desc())).scalars():
        v = db.get(Vehicle, t.vehicle_id)
        # Owners see their hire, not customer freight/identity
        out.append({"code": t.code, "status": t.status, "vehicle": v.registration, "hire": str(t.owner_hire_amount),
                    "advance": str(t.owner_advance), "started": t.actual_start, "ended": t.actual_end})
    return out


@router.get("/portal/owner/settlements")
def o_settlements(p: Principal = Depends(require("portal.owner")), db: Session = Depends(get_db)):
    rows = db.execute(select(Settlement).where(Settlement.party_type == "owner", Settlement.party_id == _own(p))).scalars()
    out = []
    for s in rows:
        pays = [{"amount": str(x.amount), "status": x.status, "reference": x.bank_reference, "at": x.executed_at}
                for x in db.execute(select(Payment).where(Payment.settlement_id == s.id)).scalars()]
        out.append({"code": s.code, "gross": str(s.gross), "advances": str(s.advances), "tds": str(s.tds), "net": str(s.net_payable),
                    "paid": str(s.paid), "status": s.status, "lines": s.lines, "payments": pays})
    return out


# ===================================================================== vendor portal
def _ven(p: Principal) -> uuid.UUID:
    if not p.vendor_id:
        raise Forbidden()
    return p.vendor_id


@router.get("/portal/vendor/summary")
def v_summary(p: Principal = Depends(require("portal.vendor")), db: Session = Depends(get_db)):
    vid = _ven(p)
    v = db.get(Vendor, vid)
    rfqs = [{"id": str(r.id), "code": r.code, "category": r.category, "description": r.description, "status": r.status}
            for r in db.execute(select(PurchaseRequest).where(PurchaseRequest.status.in_(("rfq", "quotes_received")))).scalars()
            if str(vid) in (r.shortlist or [])]
    pos = [{"id": str(o.id), "code": o.code, "amount": str(o.amount), "status": o.status, "lines": o.lines}
           for o in db.execute(select(PurchaseOrder).where(PurchaseOrder.vendor_id == vid)).scalars()]
    invs = [{"code": i.code, "invoice_number": i.invoice_number, "amount": str(i.amount), "status": i.status}
            for i in db.execute(select(VendorInvoice).where(VendorInvoice.vendor_id == vid)).scalars()]
    pays = [{"amount": str(x.amount), "status": x.status, "reference": x.bank_reference}
            for x in db.execute(select(Payment).where(Payment.payee_type == "vendor", Payment.payee_id == vid)).scalars()]
    return {"vendor": {"name": v.name, "code": v.code, "approval_status": v.approval_status, "service_areas": v.service_areas},
            "rfqs": rfqs, "orders": pos, "invoices": invs, "payments": pays}


@router.post("/portal/vendor/rfqs/{rid}/quote")
def v_quote(rid: uuid.UUID, body: dict, p: Principal = Depends(require("portal.vendor")), db: Session = Depends(get_db)):
    from app.modules.supply.router import QuoteIn, add_rfq_quote
    pr = get_or_404(db, PurchaseRequest, rid, "RFQ")
    q = add_rfq_quote(db, pr, QuoteIn(**{**body, "vendor_id": _ven(p)}), "vendor_portal")
    return {"id": str(q.id), "status": "submitted"}


class PoStatusIn(BaseModel):
    status: str = Field(pattern="^(accepted|in_progress|completed)$")
    note: str | None = None


@router.post("/portal/vendor/orders/{po_id}/status")
def v_po_status(po_id: uuid.UUID, body: PoStatusIn, p: Principal = Depends(require("portal.vendor")), db: Session = Depends(get_db)):
    po = get_or_404(db, PurchaseOrder, po_id, "Order")
    if po.vendor_id != _ven(p):
        raise NotFound("Order")
    po.vendor_status_note = body.note
    if po.status in ("issued", "accepted", "in_progress"):
        po.status = body.status if body.status != "completed" else "in_progress"  # completion is confirmed by our receipt (GRN)
    return {"status": po.status}


@router.post("/portal/vendor/invoices")
def v_invoice(body: dict, p: Principal = Depends(require("portal.vendor")), db: Session = Depends(get_db)):
    from app.modules.supply.router import VendorInvoiceIn, record_vendor_invoice
    data = VendorInvoiceIn(**{**body, "vendor_id": _ven(p)})
    if data.po_id:
        po = get_or_404(db, PurchaseOrder, data.po_id, "Order")
        if po.vendor_id != _ven(p):
            raise NotFound("Order")
    vi = record_vendor_invoice(db, p, data, "vendor_portal")
    return {"code": vi.code, "status": vi.status, "match": vi.match_result}


# ===================================================================== driver app
@router.get("/driver/me")
def d_me(p: Principal = Depends(require("driver.app")), db: Session = Depends(get_db)):
    d = db.get(Driver, p.driver_id)
    if not d:
        raise NotFound("Driver")
    lic = {"number_masked": (d.licence_number or "")[-4:].rjust(len(d.licence_number or ""), "*"), "valid_to": d.licence_valid_to,
           "classes": d.licence_classes}
    return {"name": d.name, "code": d.code, "category": d.category, "status": d.status, "licence": lic,
            "trip_scoped": bool(p.scope_trip_id), "safety_note": "Do not use the phone while driving. Park safely before using the app."}


@router.get("/driver/trips")
def d_trips(p: Principal = Depends(require("driver.app")), db: Session = Depends(get_db)):
    from app.modules.operations.access import driver_trip_ids
    ids = driver_trip_ids(db, p)
    rows = db.execute(select(Trip).where(Trip.id.in_(ids)).order_by(Trip.created_at.desc()).limit(50)).scalars()
    out = []
    for t in rows:
        d = trip_out(db, t)
        for k in ("owner_hire_amount", "owner_advance", "override", "allocation_checks"):
            d.pop(k, None)
        out.append(d)
    return out


@router.get("/driver/earnings")
def d_earnings(p: Principal = Depends(require("driver.app")), db: Session = Depends(get_db)):
    from app.modules.fleet.router import driver_rules
    if p.scope_trip_id:
        raise Forbidden("Temporary trip access does not include earnings")
    return driver_rules(p.driver_id, p, db)


# ===================================================================== public website
class PublicEnquiryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    company: str | None = Field(None, max_length=200)
    phone: str = Field(pattern=r"^\+?\d{10,13}$")
    email: EmailStr | None = None
    service_type: str = Field(pattern="^(FTL|PTL)$")
    origin: str = Field(max_length=120)
    destination: str = Field(max_length=120)
    goods: str = Field(max_length=500)
    weight_kg: Decimal | None = Field(None, ge=0, le=100000)
    pickup_date: date | None = None
    consent: bool
    website: str | None = None  # honeypot: bots fill this


@router.post("/public/enquiries")
def public_enquiry(body: PublicEnquiryIn, db: Session = Depends(get_db)):
    if body.website:
        return {"ok": True}  # silently drop bots
    if not body.consent:
        raise AppError("consent_required", "Please agree to be contacted about your enquiry")
    from app.modules.platform.models import CommConsent

    class _Anon:
        user_id = None
        name = "website"
    e = Enquiry(code=next_number(db, "ENQ", "ENQ"), source="website", prospect_name=body.company or body.name, contact_name=body.name,
                contact_phone=body.phone, contact_email=str(body.email) if body.email else None, service_type=body.service_type,
                origin_text=body.origin, destination_text=body.destination, goods_description=body.goods, weight_kg=body.weight_kg,
                pickup_from=datetime.combine(body.pickup_date, datetime.min.time()).replace(tzinfo=utcnow().tzinfo) if body.pickup_date else None)
    db.add(e)
    db.flush()
    e.missing_fields = com.missing_fields(e)
    if not db.execute(select(CommConsent).where(CommConsent.recipient == body.phone, CommConsent.channel == "sms")).first():
        db.add(CommConsent(recipient=body.phone, channel="sms", opted_in=True, source="website enquiry"))
    write_audit(db, actor=_Anon(), action="enquiry.website", entity="enquiry", entity_id=e.id)
    return {"ok": True, "reference": e.code, "message": "Thank you. Our team will contact you."}


@router.get("/public/coverage")
def coverage(db: Session = Depends(get_db)):
    """Only verified service locations are published."""
    return [{"city": l.city, "state": l.state} for l in db.execute(select(Location).where(Location.service_verified.is_(True)).order_by(Location.city)).scalars()]


@router.get("/public/company")
def company(db: Session = Depends(get_db)):
    c = get_config(db, "company.profile")
    return {"name": c.get("name"), "address": c.get("address"), "phone": c.get("phone"), "services": ["FTL", "PTL"]}
