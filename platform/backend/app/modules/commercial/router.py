"""Enquiries, quotations, bookings, credit profiles, modification requests."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.audit import snapshot, write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, get_db, require
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.notify import queue
from app.core.services import (
    approved, get_config, next_number, on_approval, raise_exception_task, request_approval,
)
from app.modules.commercial import credit as creditsvc
from app.modules.commercial.models import Booking, BookingVersion, Enquiry, ModificationRequest, Package, Quotation
from app.modules.commercial.pricing import compute_costs, margin
from app.modules.fleet.models import Vehicle
from app.modules.masters.models import Contact, CreditProfile, Customer, GoodsCategory, Location, RouteDistance
from app.modules.operations.lr import issue_lr
from app.modules.operations.models import LorryReceipt, TripLoad

router = APIRouter(prefix="/api/v1", tags=["commercial"])

ENQUIRY_REQUIRED = ["origin", "destination", "service_type", "goods_description", "weight_kg", "pickup_from", "contact"]


# ===================================================================== enquiries
class EnquiryIn(BaseModel):
    source: str = Field(pattern="^(office|phone|whatsapp|email|website|referral|portal)$")
    campaign: str | None = None
    customer_id: uuid.UUID | None = None
    prospect_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    service_type: str = Field(pattern="^(FTL|PTL)$")
    service_level: str = Field("standard", pattern="^(standard|priority|time_critical)$")
    origin_id: uuid.UUID | None = None
    destination_id: uuid.UUID | None = None
    origin_text: str | None = None
    destination_text: str | None = None
    pickup_from: datetime | None = None
    pickup_to: datetime | None = None
    deliver_by: datetime | None = None
    goods_category_id: uuid.UUID | None = None
    goods_description: str | None = None
    package_count: int | None = Field(None, ge=0)
    weight_kg: Decimal | None = Field(None, ge=0)
    volume_cft: Decimal | None = Field(None, ge=0)
    dimensions: list[dict] | None = None
    declared_value: Decimal | None = Field(None, ge=0)
    handling: list[str] = []
    vehicle_requirement: str | None = None
    required_documents: list[str] = []
    next_action: str | None = None
    next_action_at: datetime | None = None
    raw_text: str | None = None


def missing_fields(e: Enquiry) -> list[str]:
    m = []
    if not (e.origin_id or e.origin_text):
        m.append("origin")
    if not (e.destination_id or e.destination_text):
        m.append("destination")
    if not e.goods_description:
        m.append("goods_description")
    if not e.weight_kg:
        m.append("weight_kg")
    if not e.pickup_from:
        m.append("pickup_from")
    if not (e.contact_phone or e.contact_email or e.customer_id):
        m.append("contact")
    return m


def find_duplicate(db: Session, e: Enquiry) -> Enquiry | None:
    since = utcnow() - timedelta(days=3)
    q = select(Enquiry).where(Enquiry.created_at >= since, Enquiry.id != e.id, Enquiry.status != "duplicate")
    conds = []
    if e.contact_phone:
        conds.append(Enquiry.contact_phone == e.contact_phone)
    if e.customer_id:
        conds.append(Enquiry.customer_id == e.customer_id)
    if not conds:
        return None
    for o in db.execute(q.where(or_(*conds))).scalars():
        if o.origin_id == e.origin_id and o.destination_id == e.destination_id and o.service_type == e.service_type:
            return o
    return None


def create_enquiry(db: Session, actor, body: EnquiryIn, *, customer_scope: uuid.UUID | None = None) -> Enquiry:
    data = body.model_dump()
    if customer_scope:
        data["customer_id"] = customer_scope
        data["source"] = "portal"
    e = Enquiry(code=next_number(db, "ENQ", "ENQ"), owner_user_id=getattr(actor, "user_id", None), **data)
    db.add(e)
    db.flush()
    e.missing_fields = missing_fields(e)
    dup = find_duplicate(db, e)
    if dup:
        e.duplicate_of = dup.id
    e.lead_class = "hot" if (e.declared_value or 0) > 500000 or e.service_level == "time_critical" else "warm"
    write_audit(db, actor=actor, action="enquiry.create", entity="enquiry", entity_id=e.id, after={"code": e.code, "source": e.source})
    return e


def enquiry_out(e: Enquiry) -> dict:
    d = to_dict(e)
    d["possible_duplicate_of"] = d.pop("duplicate_of")
    return d


@router.post("/enquiries")
def post_enquiry(body: EnquiryIn, p: Principal = Depends(require("crm.write")), db: Session = Depends(get_db)):
    return enquiry_out(create_enquiry(db, p, body))


@router.get("/enquiries")
def list_enquiries(status: str | None = None, p: Principal = Depends(require("crm.read")), db: Session = Depends(get_db)):
    q = select(Enquiry).order_by(Enquiry.created_at.desc()).limit(500)
    if status:
        q = q.where(Enquiry.status == status)
    return [enquiry_out(e) for e in db.execute(q).scalars()]


@router.get("/enquiries/{eid}")
def get_enquiry(eid: uuid.UUID, p: Principal = Depends(require("crm.read")), db: Session = Depends(get_db)):
    e = get_or_404(db, Enquiry, eid)
    out = enquiry_out(e)
    out["quotations"] = [quote_internal_out(q) if p.can("quote.view_cost") else quote_customer_out(q)
                         for q in db.execute(select(Quotation).where(Quotation.enquiry_id == e.id).order_by(Quotation.created_at)).scalars()]
    return out


class EnquiryUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(new|qualifying|quoted|won|lost|duplicate|on_hold)$")
    next_action: str | None = None
    next_action_at: datetime | None = None
    lost_reason: str | None = None
    lead_class: str | None = None
    customer_id: uuid.UUID | None = None
    origin_id: uuid.UUID | None = None
    destination_id: uuid.UUID | None = None
    weight_kg: Decimal | None = None
    goods_description: str | None = None
    pickup_from: datetime | None = None
    declared_value: Decimal | None = None


@router.patch("/enquiries/{eid}")
def update_enquiry(eid: uuid.UUID, body: EnquiryUpdate, p: Principal = Depends(require("crm.write")), db: Session = Depends(get_db)):
    e = get_or_404(db, Enquiry, eid)
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "lost" and not data.get("lost_reason"):
        raise AppError("reason_required", "Give the reason the enquiry was lost")
    before = snapshot(e, list(data))
    for k, v in data.items():
        setattr(e, k, v)
    e.missing_fields = missing_fields(e)
    write_audit(db, actor=p, action="enquiry.update", entity="enquiry", entity_id=e.id, before=before, after=data)
    return enquiry_out(e)


# ===================================================================== quotations
class QuoteIn(BaseModel):
    enquiry_id: uuid.UUID
    vehicle_option: str = Field("own", pattern="^(own|attached)$")
    vehicle_type_id: uuid.UUID | None = None
    distance_km: Decimal | None = Field(None, gt=0)
    market_rate: Decimal | None = Field(None, ge=0)
    owner_quote: Decimal | None = Field(None, ge=0)
    negotiated_owner_rate: Decimal | None = Field(None, ge=0)
    direct_expenses: list[dict] = []  # [{code, label, amount}] e.g. hamali, crane
    selling_price: Decimal | None = Field(None, gt=0)
    extra_charges: list[dict] = []
    validity_days: int | None = Field(None, ge=1, le=60)
    delivery_window: str | None = None
    payment_terms: str | None = None
    assumptions: str | None = None
    exclusions: str | None = None
    customer_responsibilities: str | None = None
    reason: str | None = None  # needed for below-floor request


def _distance(db: Session, e: Enquiry, km: Decimal | None) -> tuple[Decimal, Decimal | None]:
    if km:
        return km, None
    if e.origin_id and e.destination_id:
        rd = db.execute(select(RouteDistance).where(
            or_((RouteDistance.origin_id == e.origin_id) & (RouteDistance.destination_id == e.destination_id),
                (RouteDistance.origin_id == e.destination_id) & (RouteDistance.destination_id == e.origin_id)))).scalars().first()
        if rd:
            return Decimal(rd.km), rd.toll_estimate
        o, d = db.get(Location, e.origin_id), db.get(Location, e.destination_id)
        if o and d and o.lat and d.lat:
            from app.integrations.adapters import get_adapter
            return Decimal(str(get_adapter("maps").distance((o.lat, o.lng), (d.lat, d.lng)).data["km"])), None
    raise AppError("distance_required", "Distance is unknown for this lane - enter distance_km")


def _ref_vehicle(db: Session) -> dict:
    v = db.execute(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.payload_kg.desc())).scalars().first()
    if not v:
        return {"payload_kg": 7000, "volume_cft": 22 * 7.5 * 7, "floor_sqft": 22 * 7.5}
    h = Decimal(v.height_ft or 7)
    return {"payload_kg": v.payload_kg, "volume_cft": float(v.length_ft * v.width_ft * h), "floor_sqft": float(v.length_ft * v.width_ft)}


def quote_internal_out(q: Quotation) -> dict:
    return to_dict(q)


CUSTOMER_QUOTE_FIELDS = ["id", "number", "version", "service_type", "service_level", "selling_price", "extra_charges",
                         "gst_mode", "valid_until", "delivery_window", "payment_terms", "assumptions", "exclusions",
                         "customer_responsibilities", "ptl_disclosure", "status", "accepted_at", "distance_km"]


def quote_customer_out(q: Quotation) -> dict:
    """Never exposes internal cost, owner quote, floor or margin."""
    d = to_dict(q)
    out = {k: d[k] for k in CUSTOMER_QUOTE_FIELDS}
    if out["status"] in ("draft", "pending_approval"):
        out["status"] = "in_preparation"
    return out


def _fill_quote(db: Session, q: Quotation, e: Enquiry, body: QuoteIn):
    km, toll = _distance(db, e, body.distance_km)
    try:
        c = compute_costs(db, service_type=e.service_type, vehicle_option=body.vehicle_option, distance_km=km,
                          declared_value=e.declared_value, owner_quote=body.owner_quote,
                          negotiated_owner_rate=body.negotiated_owner_rate, direct_expenses=body.direct_expenses,
                          toll_estimate=toll, weight_kg=e.weight_kg, volume_cft=e.volume_cft, ref_vehicle=_ref_vehicle(db))
    except ValueError:
        raise AppError("owner_quote_required", "Attached vehicle option needs the owner's quote")
    q.distance_km = km
    q.cost_breakdown = {"lines": c["lines"], "min_margin_pct": c["min_margin_pct"]}
    q.internal_cost = c["internal_cost"]
    q.direct_expenses = c["direct_expenses"]
    q.floor_price = c["floor_price"]
    q.list_price = c["suggested_price"]
    q.ptl_allocation = c["allocation"]
    q.market_rate = body.market_rate
    q.owner_quote = body.owner_quote
    q.negotiated_owner_rate = body.negotiated_owner_rate
    q.vehicle_option = body.vehicle_option
    q.vehicle_type_id = body.vehicle_type_id
    q.selling_price = money(body.selling_price or c["suggested_price"])
    q.extra_charges = [{**x, "amount": str(money(x.get("amount", 0)))} for x in body.extra_charges]
    q.expected_contribution, q.margin_pct = margin(q.selling_price, q.internal_cost)
    q.discount_pct = ((q.list_price - q.selling_price) / q.list_price * 100).quantize(Decimal("0.01")) if q.list_price and q.selling_price < q.list_price else Decimal("0")
    q.below_floor = q.selling_price < q.floor_price
    q.valid_until = utcnow() + timedelta(days=body.validity_days or int(get_config(db, "pricing.default_validity_days")))
    for f in ("delivery_window", "payment_terms", "assumptions", "exclusions", "customer_responsibilities"):
        if getattr(body, f) is not None:
            setattr(q, f, getattr(body, f))
    if e.service_type == "PTL":
        q.ptl_disclosure = ("This is a SHARED (part truck load) service. Your goods will travel with other customers' "
                            "consignments. Your identity, goods details and rates are kept confidential.")
    cap_key = "ptl.max_discount_pct" if e.service_type == "PTL" else "pricing.max_discount_pct"
    cap = Decimal(str(get_config(db, cap_key)))
    if q.discount_pct > cap:
        raise BlockedByRule("discount_cap", f"Discount {q.discount_pct}% exceeds the management cap of {cap}%",
                            details=[{"check": "discount_cap", "cap_pct": str(cap)}])


@router.post("/quotations")
def create_quote(body: QuoteIn, p: Principal = Depends(require("quote.write")), db: Session = Depends(get_db)):
    e = get_or_404(db, Enquiry, body.enquiry_id, "Enquiry")
    q = Quotation(number=next_number(db, "QTN", "QTN"), version=1, enquiry_id=e.id, customer_id=e.customer_id,
                  service_type=e.service_type, service_level=e.service_level, prepared_by=p.user_id, selling_price=Decimal("0"),
                  valid_until=utcnow())
    _fill_quote(db, q, e, body)
    db.add(q)
    db.flush()
    _route_approval(db, p, q, body.reason)
    e.status = "quoted" if e.status in ("new", "qualifying") else e.status
    write_audit(db, actor=p, action="quotation.create", entity="quotation", entity_id=q.id,
                after={"number": q.number, "selling": q.selling_price, "cost": q.internal_cost, "below_floor": q.below_floor})
    return quote_internal_out(q) if p.can("quote.view_cost") else quote_customer_out(q)


def _route_approval(db: Session, p, q: Quotation, reason: str | None):
    if q.below_floor:
        if not reason:
            raise AppError("reason_required", "Price is below the approved floor - give a reason to request approval")
        ar = request_approval(db, p, kind="quote_discount", entity="quotation", entity_id=q.id,
                              title=f"Below-floor price {q.number} v{q.version}: Rs {q.selling_price} vs floor Rs {q.floor_price}",
                              required_permission="quote.approve_discount", amount=q.floor_price - q.selling_price,
                              payload={"margin_pct": str(q.margin_pct), "cost": str(q.internal_cost)}, reason=reason)
        q.status, q.approval_id = "pending_approval", ar.id
    else:
        q.status = "approved"


@on_approval("quote_discount")
def _quote_decided(db: Session, actor, ar):
    q = db.get(Quotation, uuid.UUID(ar.entity_id))
    if q and q.status == "pending_approval":
        q.status = "approved" if ar.status == "approved" else "rejected"


@router.post("/quotations/{qid}/revise")
def revise_quote(qid: uuid.UUID, body: QuoteIn, p: Principal = Depends(require("quote.write")), db: Session = Depends(get_db)):
    old = get_or_404(db, Quotation, qid, "Quotation", lock=True)
    if old.status in ("accepted", "superseded"):
        raise Conflict("not_revisable", f"Quotation is {old.status}")
    e = db.get(Enquiry, old.enquiry_id)
    q = Quotation(number=old.number, version=old.version + 1, enquiry_id=e.id, customer_id=e.customer_id,
                  service_type=e.service_type, service_level=e.service_level, prepared_by=p.user_id,
                  selling_price=Decimal("0"), valid_until=utcnow())
    _fill_quote(db, q, e, body)
    old.status = "superseded"
    db.add(q)
    db.flush()
    _route_approval(db, p, q, body.reason)
    write_audit(db, actor=p, action="quotation.revise", entity="quotation", entity_id=q.id,
                before={"version": old.version, "selling": old.selling_price}, after={"version": q.version, "selling": q.selling_price})
    return quote_internal_out(q)


@router.get("/quotations")
def list_quotes(p: Principal = Depends(require("quote.read")), db: Session = Depends(get_db)):
    rows = db.execute(select(Quotation).order_by(Quotation.created_at.desc()).limit(500)).scalars()
    return [quote_internal_out(q) if p.can("quote.view_cost") else quote_customer_out(q) for q in rows]


@router.post("/quotations/{qid}/send")
def send_quote(qid: uuid.UUID, p: Principal = Depends(require("quote.write")), db: Session = Depends(get_db)):
    q = get_or_404(db, Quotation, qid, "Quotation")
    if q.status != "approved":
        raise BlockedByRule("not_approved", f"Quotation must be approved before sending (status: {q.status})")
    q.status = "sent"
    e = db.get(Enquiry, q.enquiry_id)
    if e.contact_email or e.contact_phone:
        queue(db, channel="email" if e.contact_email else "whatsapp", recipient=e.contact_email or e.contact_phone,
              template="generic", text=f"Quotation {q.number} v{q.version}: Rs {q.selling_price} + applicable taxes. "
                                       f"Valid until {q.valid_until:%d-%m-%Y}.", entity="quotation", entity_id=q.id)
    write_audit(db, actor=p, action="quotation.send", entity="quotation", entity_id=q.id)
    return quote_customer_out(q)


class AcceptIn(BaseModel):
    accepted_by: str = Field(min_length=2)
    channel: str = Field("office", pattern="^(office|portal|email|whatsapp|phone)$")


def accept_quote(db: Session, actor, q: Quotation, body: AcceptIn) -> Quotation:
    if q.status not in ("sent", "approved"):
        raise BlockedByRule("not_acceptable", f"Quotation status {q.status} cannot be accepted")
    if q.valid_until < utcnow():
        q.status = "expired"
        raise BlockedByRule("expired", "Quotation validity has expired - a revised quotation is needed")
    q.status, q.accepted_at, q.accepted_by, q.acceptance_channel = "accepted", utcnow(), body.accepted_by, body.channel
    e = db.get(Enquiry, q.enquiry_id)
    e.status = "won"
    write_audit(db, actor=actor, action="quotation.accept", entity="quotation", entity_id=q.id,
                after={"accepted_by": body.accepted_by, "channel": body.channel})
    return q


@router.post("/quotations/{qid}/accept")
def accept(qid: uuid.UUID, body: AcceptIn, p: Principal = Depends(require("quote.write")), db: Session = Depends(get_db)):
    q = accept_quote(db, p, get_or_404(db, Quotation, qid, "Quotation", lock=True), body)
    return quote_internal_out(q)


# ===================================================================== bookings
class BookingIn(BaseModel):
    customer_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    service_type: str | None = Field(None, pattern="^(FTL|PTL)$")
    service_level: str = Field("standard", pattern="^(standard|priority|time_critical)$")
    ptl_consent: bool = False
    consignor_name: str
    consignor_address: str | None = None
    consignor_gstin: str | None = None
    consignee_name: str
    consignee_address: str | None = None
    consignee_phone: str | None = None
    consignee_gstin: str | None = None
    origin_id: uuid.UUID | None = None
    destination_id: uuid.UUID | None = None
    pickup_from: datetime | None = None
    pickup_to: datetime | None = None
    deliver_by: datetime | None = None
    goods_category_id: uuid.UUID | None = None
    goods_description: str
    package_count: int = Field(1, ge=1, le=10000)
    weight_kg: Decimal = Field(gt=0)
    volume_cft: Decimal | None = Field(None, ge=0)
    floor_sqft: Decimal | None = Field(None, ge=0)
    max_package_length_ft: Decimal | None = Field(None, ge=0)
    stackable: bool = True
    fragile: bool = False
    declared_value: Decimal | None = Field(None, ge=0)
    handling: list[str] = []
    required_body_type: str | None = None
    instructions: str | None = None
    loading_by: str = Field("customer", pattern="^(customer|company|vendor)$")
    unloading_by: str = Field("customer", pattern="^(customer|company|vendor)$")
    freight_amount: Decimal | None = Field(None, gt=0)
    extra_charges: list[dict] = []
    payment_terms: str | None = None
    advance_received: Decimal = Field(Decimal("0"), ge=0)
    cancellation_terms: str | None = None
    manual_price_reason: str | None = None

    @model_validator(mode="after")
    def _chk(self):
        if not self.quotation_id and not (self.customer_id and self.origin_id and self.destination_id and self.service_type):
            raise ValueError("Without a quotation, customer, origin, destination and service type are required")
        return self


def booking_out(db: Session, b: Booking, internal: bool = True) -> dict:
    d = to_dict(b)
    lr = db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id, LorryReceipt.status != "cancelled")).scalar_one_or_none()
    d["lr_number"] = lr.number if lr else None
    o, de = db.get(Location, b.origin_id), db.get(Location, b.destination_id)
    d["origin"] = f"{o.city}" if o else None
    d["destination"] = f"{de.city}" if de else None
    cust = db.get(Customer, b.customer_id)
    d["customer_name"] = cust.name if cust else None
    if not internal:
        d.pop("credit_snapshot", None)
    return d


def _validate_goods(db: Session, b: Booking) -> list[dict]:
    issues = []
    if b.goods_category_id:
        g = db.get(GoodsCategory, b.goods_category_id)
        if g and b.service_type == "PTL" and not g.ptl_allowed:
            issues.append({"check": "ptl_goods", "ok": False, "message": f"{g.name} cannot be carried in shared (PTL) loads"})
        if g and (g.hazard_class or g.requires_special_approval) and not approved(db, "special_cargo", b.id):
            issues.append({"check": "special_cargo", "ok": False,
                           "message": f"{g.name} needs verified legal/insurance/operational capability and special approval"})
    if b.service_type == "PTL" and not b.ptl_consent:
        issues.append({"check": "ptl_consent", "ok": False, "message": "Customer must be told and agree that PTL transport is shared"})
    if b.pickup_to and b.pickup_from and b.pickup_to < b.pickup_from:
        issues.append({"check": "windows", "ok": False, "message": "Pickup window end is before start"})
    if b.deliver_by and b.pickup_from and b.deliver_by < b.pickup_from:
        issues.append({"check": "windows", "ok": False, "message": "Delivery deadline is before pickup"})
    return issues


def _feasibility(db: Session, b: Booking) -> dict:
    vehicles = list(db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars())
    fits = [v for v in vehicles if v.payload_kg >= float(b.weight_kg)
            and (not b.max_package_length_ft or v.length_ft >= b.max_package_length_ft)
            and (not b.required_body_type or v.body_type == b.required_body_type)]
    own = [v.registration for v in fits if v.ownership == "own"]
    return {"own_vehicles_that_fit": own, "attached_vehicles_that_fit": [v.registration for v in fits if v.ownership == "attached"],
            "feasible": bool(fits), "note": None if fits else "No registered vehicle fits - source an attached vehicle with adequate legal payload/dimensions"}


def create_booking(db: Session, actor, body: BookingIn, *, via: str = "office", customer_scope=None) -> Booking:
    data = body.model_dump(exclude={"quotation_id", "manual_price_reason"})
    q = None
    if body.quotation_id:
        q = get_or_404(db, Quotation, body.quotation_id, "Quotation")
        if q.status != "accepted":
            raise BlockedByRule("quote_not_accepted", "Only an accepted quotation can become a booking")
        if q.valid_until < q.accepted_at - timedelta(seconds=1):
            raise BlockedByRule("quote_expired", "Quotation was accepted after validity")
        if db.execute(select(Booking).where(Booking.quotation_id == q.id, Booking.status != "cancelled")).first():
            raise Conflict("already_booked", "This quotation already has a booking")
        e = db.get(Enquiry, q.enquiry_id)
        data.update(customer_id=data["customer_id"] or q.customer_id or e.customer_id, service_type=q.service_type,
                    service_level=q.service_level, origin_id=data["origin_id"] or e.origin_id,
                    destination_id=data["destination_id"] or e.destination_id, freight_amount=q.selling_price,
                    extra_charges=q.extra_charges, gst_mode=q.gst_mode,
                    payment_terms=data["payment_terms"] or q.payment_terms)
        if not data["customer_id"]:
            raise AppError("customer_required", "Create the customer record before booking (enquiry was from a prospect)")
    else:
        if not data.get("freight_amount"):
            raise AppError("price_required", "Freight amount is required for a manual booking")
        if not body.manual_price_reason:
            raise AppError("reason_required", "Manual bookings without a quotation need a reason (e.g. contract rate)")
    if customer_scope and data["customer_id"] != customer_scope:
        raise Forbidden()
    cust = get_or_404(db, Customer, data["customer_id"], "Customer")
    data.setdefault("gst_mode", cust.gst_mode)
    b = Booking(code=next_number(db, "BKG", "BKG"), quotation_id=q.id if q else None, created_via=via, status="draft", **data)
    db.add(b)
    db.flush()
    issues = _validate_goods(db, b)
    if issues:
        raise BlockedByRule("booking_validation", "Booking cannot be created", details=issues)
    write_audit(db, actor=actor, action="booking.create", entity="booking", entity_id=b.id,
                after={"code": b.code, "service_type": b.service_type, "freight": b.freight_amount,
                       "manual_reason": body.manual_price_reason})
    return b


@router.post("/bookings")
def post_booking(body: BookingIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    b = create_booking(db, p, body)
    out = booking_out(db, b)
    out["feasibility"] = _feasibility(db, b)
    return out


@router.get("/bookings")
def list_bookings(status: str | None = None, service_type: str | None = None, customer_id: uuid.UUID | None = None,
                  p: Principal = Depends(require("booking.read")), db: Session = Depends(get_db)):
    q = select(Booking).order_by(Booking.created_at.desc()).limit(1000)
    if status:
        q = q.where(Booking.status.in_(status.split(",")))
    if service_type:
        q = q.where(Booking.service_type == service_type)
    if customer_id:
        q = q.where(Booking.customer_id == customer_id)
    return [booking_out(db, b) for b in db.execute(q).scalars()]


@router.get("/bookings/{bid}")
def get_booking(bid: uuid.UUID, p: Principal = Depends(require("booking.read")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    out = booking_out(db, b)
    out["packages"] = [to_dict(x) for x in db.execute(select(Package).where(Package.booking_id == b.id).order_by(Package.seq)).scalars()]
    out["versions"] = [to_dict(v) for v in db.execute(select(BookingVersion).where(BookingVersion.booking_id == b.id)).scalars()]
    out["trip_loads"] = [to_dict(t) for t in db.execute(select(TripLoad).where(TripLoad.booking_id == b.id)).scalars()]
    out["feasibility"] = _feasibility(db, b)
    out["credit"] = b.credit_snapshot
    return out


def confirm_booking(db: Session, actor, b: Booking) -> dict:
    if b.status not in ("draft", "on_hold"):
        raise Conflict("bad_status", f"Booking is {b.status}")
    issues = _validate_goods(db, b)
    if issues:
        raise BlockedByRule("booking_validation", "Booking failed validation", details=issues)
    c = creditsvc.evaluate(db, b)
    b.credit_status, b.credit_snapshot = c["status"], c
    if c["status"] == "blocked":
        b.status = "on_hold"
        raise_exception_task(db, severity="high", title=f"Credit block on booking {b.code}", entity="booking", entity_id=b.id,
                             source="credit_gate", detail="; ".join(c["reasons"]), owner_role="accounts", blocking=True)
        db.flush()
        return {"confirmed": False, "credit": c}
    b.status = "confirmed"
    # Packages with QR labels (needed for PTL; created for FTL too for custody counts)
    if not db.execute(select(Package.id).where(Package.booking_id == b.id)).first():
        for i in range(1, b.package_count + 1):
            db.add(Package(booking_id=b.id, label=f"{b.code}-{i:03d}", seq=i, stackable=b.stackable, fragile=b.fragile))
    lr = issue_lr(db, actor, b)
    cust = db.get(Customer, b.customer_id)
    o, d = db.get(Location, b.origin_id), db.get(Location, b.destination_id)
    contact = db.execute(select(Contact).where(Contact.customer_id == b.customer_id)).scalars().first()
    if contact and (contact.email or contact.phone):
        queue(db, channel="email" if contact.email else "sms", recipient=contact.email or contact.phone,
              template="booking_confirmed", code=b.code, origin=o.city, destination=d.city,
              service="Shared transport (PTL)." if b.service_type == "PTL" else "Exclusive vehicle (FTL).",
              entity="booking", entity_id=b.id)
    write_audit(db, actor=actor, action="booking.confirm", entity="booking", entity_id=b.id,
                after={"credit": c["status"], "lr": lr.number, "customer": cust.code})
    return {"confirmed": True, "credit": c, "lr_number": lr.number}


@router.post("/bookings/{bid}/confirm")
def confirm(bid: uuid.UUID, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking", lock=True)
    res = confirm_booking(db, p, b)
    return {**res, "booking": booking_out(db, b)}


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/bookings/{bid}/credit-exception")
def credit_exception(bid: uuid.UUID, body: ReasonIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    if b.credit_status != "blocked":
        raise AppError("not_blocked", "Booking is not credit-blocked")
    ar = request_approval(db, p, kind="credit_exception", entity="booking", entity_id=b.id,
                          title=f"Credit exception for {b.code}", required_permission="credit.approve",
                          amount=creditsvc.booking_value(b), payload=b.credit_snapshot, reason=body.reason)
    return {"approval": ar.code}


class SpecialCargoIn(BaseModel):
    reason: str
    legal_verified: bool
    insurance_verified: bool
    operations_verified: bool


@router.post("/bookings/{bid}/special-cargo-approval")
def special_cargo(bid: uuid.UUID, body: SpecialCargoIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    if not (body.legal_verified and body.insurance_verified and body.operations_verified):
        raise BlockedByRule("not_verified", "Legal, insurance and operational capability must all be verified first")
    ar = request_approval(db, p, kind="special_cargo", entity="booking", entity_id=bid, title="Special/hazardous cargo authorisation",
                          required_permission="quote.approve_discount", payload=body.model_dump(), reason=body.reason)
    return {"approval": ar.code}


class BookingModifyIn(BaseModel):
    reason: str = Field(min_length=3)
    pickup_from: datetime | None = None
    pickup_to: datetime | None = None
    deliver_by: datetime | None = None
    consignee_name: str | None = None
    consignee_address: str | None = None
    consignee_phone: str | None = None
    package_count: int | None = Field(None, ge=1)
    weight_kg: Decimal | None = Field(None, gt=0)
    instructions: str | None = None
    extra_charges: list[dict] | None = None
    freight_amount: Decimal | None = Field(None, gt=0)


def modify_booking(db: Session, actor, b: Booking, changes: dict, reason: str):
    if b.status not in ("draft", "confirmed", "on_hold", "planned"):
        raise BlockedByRule("not_modifiable", f"Booking in status {b.status} cannot be modified; raise an exception instead")
    if "freight_amount" in changes and b.quotation_id and not actor.can("quote.approve_discount"):
        raise Forbidden("Price changes on quoted bookings need a revised quotation or pricing approval")
    db.add(BookingVersion(booking_id=b.id, version=b.version, snapshot=snapshot(b), reason=reason,
                          changed_by=actor.user_id, changed_at=utcnow()))
    before = snapshot(b, list(changes))
    for k, v in changes.items():
        setattr(b, k, v)
    b.version += 1
    if b.status in ("confirmed", "planned") and ("weight_kg" in changes or "freight_amount" in changes or "extra_charges" in changes):
        c = creditsvc.evaluate(db, b)
        b.credit_status, b.credit_snapshot = c["status"], c
    write_audit(db, actor=actor, action="booking.modify", entity="booking", entity_id=b.id, before=before, after=changes, reason=reason)


@router.patch("/bookings/{bid}")
def patch_booking(bid: uuid.UUID, body: BookingModifyIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking", lock=True)
    modify_booking(db, p, b, body.model_dump(exclude_unset=True, exclude={"reason"}), body.reason)
    return booking_out(db, b)


class CancelIn(BaseModel):
    reason_code: str
    reason: str = Field(min_length=3)
    cancellation_charge: Decimal = Field(Decimal("0"), ge=0)


def cancel_booking(db: Session, actor, b: Booking, body: CancelIn):
    if b.status in ("dispatched", "in_transit", "delivered", "pod_verified", "invoiced", "closed", "cancelled"):
        raise BlockedByRule("not_cancellable", f"Booking in status {b.status} cannot be cancelled here")
    for tl in db.execute(select(TripLoad).where(TripLoad.booking_id == b.id, TripLoad.status == "planned")).scalars():
        tl.status = "removed"
        from app.modules.operations.models import Trip
        t = db.get(Trip, tl.trip_id)
        if t and t.exclusive_booking_id == b.id:
            t.status, t.cancel_reason, t.exclusive_booking_id = "cancelled", body.reason, None
            from app.modules.operations.service import release_trip_resources
            release_trip_resources(db, t)
    for lr in db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id, LorryReceipt.status != "cancelled")).scalars():
        lr.status, lr.cancel_reason = "cancelled", body.reason
    b.status, b.cancel_reason = "cancelled", f"{body.reason_code}: {body.reason}"
    if body.cancellation_charge > 0:
        b.extra_charges = [*b.extra_charges, {"code": "cancellation", "label": "Cancellation charge", "amount": str(body.cancellation_charge)}]
    write_audit(db, actor=actor, action="booking.cancel", entity="booking", entity_id=b.id, reason=body.reason,
                after={"reason_code": body.reason_code, "charge": body.cancellation_charge})


@router.post("/bookings/{bid}/cancel")
def post_cancel(bid: uuid.UUID, body: CancelIn, p: Principal = Depends(require("booking.cancel")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking", lock=True)
    cancel_booking(db, p, b, body)
    return booking_out(db, b)


class ConvertIn(BaseModel):
    new_quotation_id: uuid.UUID
    customer_consent_reference: str = Field(min_length=3)
    reason: str


@router.post("/bookings/{bid}/convert-to-ptl")
def convert_to_ptl(bid: uuid.UUID, body: ConvertIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    """FTL → PTL only with explicit recorded consent, a revised accepted quotation and re-booking."""
    b = get_or_404(db, Booking, bid, "Booking", lock=True)
    if b.service_type != "FTL":
        raise AppError("not_ftl", "Booking is not FTL")
    q = get_or_404(db, Quotation, body.new_quotation_id, "Quotation")
    if q.service_type != "PTL" or q.status != "accepted" or q.customer_id != b.customer_id:
        raise BlockedByRule("revised_quote_required", "An accepted PTL quotation for the same customer is required")
    cancel_booking(db, p, b, CancelIn(reason_code="CONVERT_PTL", reason=f"Converted to PTL: {body.reason}"))
    nb = Booking(**{k: v for k, v in snapshot(b).items() if k not in ("id", "code", "created_at", "updated_at", "status",
                                                                     "cancel_reason", "credit_status", "credit_snapshot", "version")})
    nb.id = uuid.uuid4()
    nb.code = next_number(db, "BKG", "BKG")
    nb.service_type, nb.ptl_consent, nb.quotation_id, nb.freight_amount = "PTL", True, q.id, q.selling_price
    nb.status = "draft"
    for k in ("weight_kg", "freight_amount", "volume_cft", "floor_sqft", "declared_value", "max_package_length_ft",
              "advance_received", "advance_required"):
        if getattr(nb, k) is not None:
            setattr(nb, k, Decimal(str(getattr(nb, k))))
    for k in ("pickup_from", "pickup_to", "deliver_by", "delivered_at", "pod_verified_at"):
        v = getattr(nb, k)
        if isinstance(v, str):
            setattr(nb, k, datetime.fromisoformat(v))
    for k in ("customer_id", "branch_id", "origin_id", "destination_id", "goods_category_id"):
        v = getattr(nb, k)
        if isinstance(v, str):
            setattr(nb, k, uuid.UUID(v))
    db.add(nb)
    db.flush()
    write_audit(db, actor=p, action="booking.convert_ptl", entity="booking", entity_id=nb.id,
                after={"from": b.code, "to": nb.code, "consent": body.customer_consent_reference}, reason=body.reason)
    return booking_out(db, nb)


# ----------------------------------------------------------------- modification requests (customer)
@router.get("/modification-requests")
def list_mods(p: Principal = Depends(require("booking.read")), db: Session = Depends(get_db)):
    return [to_dict(m) for m in db.execute(select(ModificationRequest).order_by(ModificationRequest.created_at.desc())).scalars()]


class ModDecisionIn(BaseModel):
    approve: bool
    note: str = Field(min_length=2)
    charges: Decimal = Decimal("0")


@router.post("/modification-requests/{mid}/decide")
def decide_mod(mid: uuid.UUID, body: ModDecisionIn, p: Principal = Depends(require("booking.write")), db: Session = Depends(get_db)):
    m = get_or_404(db, ModificationRequest, mid, "Request")
    if m.status != "requested":
        raise Conflict("decided", "Already decided")
    b = get_or_404(db, Booking, m.booking_id, "Booking", lock=True)
    if body.approve:
        if m.kind == "cancel":
            cancel_booking(db, p, b, CancelIn(reason_code="CUSTOMER", reason=m.reason, cancellation_charge=body.charges))
        else:
            allowed = {k: v for k, v in m.changes.items() if k in BookingModifyIn.model_fields and k != "reason"}
            for k in ("pickup_from", "pickup_to", "deliver_by"):
                if isinstance(allowed.get(k), str):
                    allowed[k] = datetime.fromisoformat(allowed[k])
            modify_booking(db, p, b, allowed, f"Customer request: {m.reason}")
    m.status, m.decided_by, m.decision_note, m.charges = ("approved" if body.approve else "rejected"), p.user_id, body.note, body.charges
    return to_dict(m)


# ===================================================================== credit profiles
class CreditIn(BaseModel):
    customer_id: uuid.UUID
    limit_amount: Decimal = Field(ge=0)
    credit_days: int = Field(ge=0, le=180)
    advance_pct: Decimal = Field(Decimal("0"), ge=0, le=100)
    deposit_amount: Decimal = Field(Decimal("0"), ge=0)
    risk_category: str = Field("medium", pattern="^(low|medium|high)$")
    effective_from: datetime | None = None
    reason: str = Field(min_length=3)


@router.post("/credit-profiles")
def propose_credit(body: CreditIn, p: Principal = Depends(require("credit.write")), db: Session = Depends(get_db)):
    cp = CreditProfile(**body.model_dump(exclude={"effective_from"}), effective_from=body.effective_from or utcnow(),
                       status="pending", proposed_by=p.user_id)
    db.add(cp)
    db.flush()
    request_approval(db, p, kind="credit_limit", entity="credit_profile", entity_id=cp.id,
                     title=f"Credit limit Rs {body.limit_amount} / {body.credit_days} days", required_permission="credit.approve",
                     amount=body.limit_amount, reason=body.reason)
    return to_dict(cp)


@on_approval("credit_limit")
def _credit_decided(db: Session, actor, ar):
    cp = db.get(CreditProfile, uuid.UUID(ar.entity_id))
    if ar.status == "approved":
        for old in db.execute(select(CreditProfile).where(CreditProfile.customer_id == cp.customer_id,
                                                          CreditProfile.status == "active")).scalars():
            old.status = "superseded"
        cp.status, cp.approved_by = "active", actor.user_id
    else:
        cp.status = "rejected"


@on_approval("credit_exception")
def _credit_exc(db: Session, actor, ar):
    b = db.get(Booking, uuid.UUID(ar.entity_id))
    if ar.status == "approved" and b and b.status == "on_hold":
        b.credit_status = "exception_approved"


@router.get("/customers/{cid}/credit")
def customer_credit(cid: uuid.UUID, p: Principal = Depends(require("credit.read")), db: Session = Depends(get_db)):
    ex = creditsvc.exposure(db, cid)
    hist = [to_dict(c) for c in db.execute(select(CreditProfile).where(CreditProfile.customer_id == cid)
                                           .order_by(CreditProfile.created_at.desc())).scalars()]
    return {"exposure": ex, "profiles": hist}
