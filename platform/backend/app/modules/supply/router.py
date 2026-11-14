"""Procurement (request → shortlist → RFQ → comparison → approval → PO → receipt → invoice 3-way match → payment request),
inventory and godown operations."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.resource import register_crud
from app.core.services import get_config, next_number, on_approval, raise_exception_task, request_approval
from app.modules.commercial.models import Booking
from app.modules.finance.posting import EXPENSE_ACCOUNT, post_voucher
from app.modules.masters.models import Facility, Vendor
from app.modules.operations.service import record_custody
from app.modules.supply.models import (
    GodownEntry, GoodsReceipt, InventoryItem, PurchaseOrder, PurchaseRequest, RfqQuote, StockMovement, VendorInvoice,
)

router = APIRouter(prefix="/api/v1", tags=["supply"])

register_crud(router, "inventory-items", InventoryItem, read_perm="inventory.read", write_perm="inventory.write", code_field="code",
              code_prefix="ITM", readonly_fields={"qty_on_hand", "avg_cost"})


# ===================================================================== procurement
class PRIn(BaseModel):
    category: str
    description: str
    items: list[dict] = []
    estimated_amount: Decimal = Field(Decimal("0"), ge=0)
    vehicle_id: uuid.UUID | None = None
    job_card_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    emergency: bool = False
    emergency_reason: str | None = None


@router.post("/procurement/requests")
def create_pr(body: PRIn, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    if body.emergency and not body.emergency_reason:
        raise AppError("reason_required", "Emergency purchases need a reason and evidence; they are reviewed retrospectively")
    pr = PurchaseRequest(code=next_number(db, "PR", "PR"), requested_by=p.user_id, **body.model_dump())
    db.add(pr)
    db.flush()
    if body.emergency:
        pr.status = "retro_review"
        raise_exception_task(db, kind="followup", severity="medium", title=f"Retrospective review of emergency purchase {pr.code}",
                             entity="purchase_request", entity_id=pr.id, source="procurement", owner_role="owner_director")
    return to_dict(pr)


class ShortlistIn(BaseModel):
    vendor_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/procurement/requests/{rid}/rfq")
def send_rfq(rid: uuid.UUID, body: ShortlistIn, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    pr = get_or_404(db, PurchaseRequest, rid, "Request")
    bad = [str(v) for v in body.vendor_ids if (db.get(Vendor, v) is None or db.get(Vendor, v).approval_status != "approved")]
    if bad:
        raise BlockedByRule("vendor_not_approved", "Only approved vendors can be shortlisted", details=bad)
    pr.shortlist, pr.status = [str(v) for v in body.vendor_ids], "rfq"
    return to_dict(pr)


class QuoteIn(BaseModel):
    vendor_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    tax_amount: Decimal = Field(Decimal("0"), ge=0)
    delivery_days: int | None = None
    notes: str | None = None


def add_rfq_quote(db: Session, pr: PurchaseRequest, body: QuoteIn, via: str) -> RfqQuote:
    if str(body.vendor_id) not in (pr.shortlist or []):
        raise Forbidden("Vendor is not shortlisted for this request")
    if pr.status not in ("rfq", "quotes_received"):
        raise Conflict("closed", "RFQ is closed")
    q = RfqQuote(request_id=pr.id, submitted_via=via, **body.model_dump())
    db.add(q)
    pr.status = "quotes_received"
    db.flush()
    return q


@router.post("/procurement/requests/{rid}/quotes")
def office_quote(rid: uuid.UUID, body: QuoteIn, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    return to_dict(add_rfq_quote(db, get_or_404(db, PurchaseRequest, rid, "Request"), body, "office"))


@router.get("/procurement/requests/{rid}/comparison")
def comparison(rid: uuid.UUID, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    pr = get_or_404(db, PurchaseRequest, rid, "Request")
    quotes = list(db.execute(select(RfqQuote).where(RfqQuote.request_id == pr.id)).scalars())
    rows = []
    for q in sorted(quotes, key=lambda x: Decimal(x.amount) + Decimal(x.tax_amount)):
        v = db.get(Vendor, q.vendor_id)
        rows.append({**to_dict(q), "vendor": v.name, "total": str(Decimal(q.amount) + Decimal(q.tax_amount)), "score": v.score})
    return {"request": to_dict(pr), "quotes": rows, "lowest": rows[0]["vendor"] if rows else None}


class SelectIn(BaseModel):
    quote_id: uuid.UUID
    reason: str = Field(min_length=3)


@router.post("/procurement/requests/{rid}/select")
def select_quote(rid: uuid.UUID, body: SelectIn, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    pr = get_or_404(db, PurchaseRequest, rid, "Request", lock=True)
    q = get_or_404(db, RfqQuote, body.quote_id, "Quote")
    if q.request_id != pr.id:
        raise AppError("mismatch", "Quote is for another request")
    for other in db.execute(select(RfqQuote).where(RfqQuote.request_id == pr.id)).scalars():
        other.selected = other.id == q.id
    total = Decimal(q.amount) + Decimal(q.tax_amount)
    thr = Decimal(str(get_config(db, "approval.thresholds")["procurement"]))
    if total > thr:
        request_approval(db, p, kind="procurement", entity="purchase_request", entity_id=pr.id, title=f"Procurement {pr.code}: Rs {total}",
                         required_permission="procurement.approve", amount=total, reason=body.reason)
        pr.status = "pending_approval"
    else:
        pr.status = "approved"
    return to_dict(pr)


@on_approval("procurement")
def _pr_decided(db, actor, ar):
    pr = db.get(PurchaseRequest, uuid.UUID(ar.entity_id))
    pr.status = "approved" if ar.status == "approved" else "rejected"


@router.post("/procurement/requests/{rid}/po")
def issue_po(rid: uuid.UUID, p: Principal = Depends(require("procurement.write")), db: Session = Depends(get_db)):
    pr = get_or_404(db, PurchaseRequest, rid, "Request", lock=True)
    if pr.status != "approved":
        raise BlockedByRule("not_approved", f"Request is {pr.status}; approval required before ordering")
    q = db.execute(select(RfqQuote).where(RfqQuote.request_id == pr.id, RfqQuote.selected.is_(True))).scalar_one_or_none()
    if not q:
        raise AppError("no_quote", "Select a quote first")
    lines = pr.items or [{"name": pr.description, "qty": 1}]
    po = PurchaseOrder(code=next_number(db, "PO", "PO"), request_id=pr.id, vendor_id=q.vendor_id,
                       kind="po" if pr.items else "work_order", lines=lines, amount=q.amount, tax_amount=q.tax_amount, issued_by=p.user_id)
    db.add(po)
    pr.status = "ordered"
    db.flush()
    write_audit(db, actor=p, action="po.issue", entity="purchase_order", entity_id=po.id, after={"code": po.code, "amount": q.amount})
    return to_dict(po)


@router.get("/procurement/requests")
def list_prs(p: Principal = Depends(require_any("procurement.write", "procurement.approve")), db: Session = Depends(get_db)):
    return [to_dict(x) for x in db.execute(select(PurchaseRequest).order_by(PurchaseRequest.created_at.desc())).scalars()]


@router.get("/procurement/orders")
def list_pos(p: Principal = Depends(require_any("procurement.write", "accounts.read")), db: Session = Depends(get_db)):
    return [to_dict(x) for x in db.execute(select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())).scalars()]


class GrnIn(BaseModel):
    lines: list[dict]  # [{name, item_id?, qty_received, qty_accepted, note}]
    accepted_amount: Decimal = Field(ge=0)
    evidence_document_ids: list[uuid.UUID] = []


@router.post("/procurement/orders/{po_id}/receipt")
def goods_receipt(po_id: uuid.UUID, body: GrnIn, p: Principal = Depends(require_any("inventory.write", "procurement.write")), db: Session = Depends(get_db)):
    po = get_or_404(db, PurchaseOrder, po_id, "PO", lock=True)
    if po.status in ("cancelled", "closed"):
        raise Conflict("bad_status", f"PO is {po.status}")
    if po.issued_by == p.user_id and Decimal(po.amount) > Decimal(str(get_config(db, "approval.thresholds")["procurement"])):
        raise Forbidden("Receipt of a large order must be recorded by someone other than the buyer", code="self_approval")
    g = GoodsReceipt(code=next_number(db, "GRN", "GRN"), po_id=po.id, lines=body.lines, accepted_amount=body.accepted_amount,
                     evidence_document_ids=[str(x) for x in body.evidence_document_ids], inspected_by=p.user_id)
    db.add(g)
    db.flush()
    for l in body.lines:
        if l.get("item_id") and Decimal(str(l.get("qty_accepted", 0))) > 0:
            item = db.get(InventoryItem, uuid.UUID(str(l["item_id"])))
            qty = Decimal(str(l["qty_accepted"]))
            unit = Decimal(str(l.get("unit_cost", 0))) or (Decimal(po.amount) / max(Decimal("1"), qty))
            _stock_in(db, p, item, qty, unit, grn_id=g.id)
    po.status = "completed"
    return to_dict(g)


def _stock_in(db, p, item: InventoryItem, qty: Decimal, unit: Decimal, **kw):
    total_val = Decimal(item.qty_on_hand) * Decimal(item.avg_cost) + qty * unit
    item.qty_on_hand = Decimal(item.qty_on_hand) + qty
    item.avg_cost = money(total_val / item.qty_on_hand) if item.qty_on_hand else Decimal("0")
    db.add(StockMovement(item_id=item.id, kind="receipt", qty=qty, unit_cost=unit, by_user=p.user_id, **kw))


class VendorInvoiceIn(BaseModel):
    vendor_id: uuid.UUID
    po_id: uuid.UUID | None = None
    invoice_number: str
    invoice_date: date
    amount: Decimal = Field(gt=0)
    tax_amount: Decimal = Field(Decimal("0"), ge=0)
    document_id: uuid.UUID | None = None


def three_way_match(db: Session, vi: VendorInvoice) -> dict:
    if not vi.po_id:
        return {"ok": False, "checks": [{"check": "po", "ok": False, "message": "No PO/work order referenced"}]}
    po = db.get(PurchaseOrder, vi.po_id)
    grns = list(db.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)).scalars())
    accepted = sum((Decimal(g.accepted_amount) for g in grns), Decimal("0"))
    tol = Decimal("1.00")
    checks = [
        {"check": "vendor", "ok": po.vendor_id == vi.vendor_id, "message": "Vendor matches PO"},
        {"check": "receipt", "ok": bool(grns), "message": f"{len(grns)} receipt(s)/service proof recorded"},
        {"check": "amount_vs_po", "ok": Decimal(vi.amount) <= Decimal(po.amount) + tol, "message": f"Invoice {vi.amount} vs PO {po.amount}"},
        {"check": "amount_vs_receipt", "ok": Decimal(vi.amount) <= accepted + tol, "message": f"Invoice {vi.amount} vs accepted {accepted}"},
        {"check": "tax", "ok": Decimal(vi.tax_amount) <= Decimal(po.tax_amount) + tol, "message": f"Tax {vi.tax_amount} vs PO {po.tax_amount}"},
    ]
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def record_vendor_invoice(db: Session, p, body: VendorInvoiceIn, via: str) -> VendorInvoice:
    if db.execute(select(VendorInvoice).where(VendorInvoice.vendor_id == body.vendor_id, VendorInvoice.invoice_number == body.invoice_number)).first():
        raise Conflict("duplicate_invoice", "This vendor invoice number is already recorded")
    vi = VendorInvoice(code=next_number(db, "VIN", "VIN"), submitted_via=via, **body.model_dump())
    db.add(vi)
    db.flush()
    vi.match_result = three_way_match(db, vi)
    vi.status = "matched" if vi.match_result["ok"] else "mismatch"
    if not vi.match_result["ok"]:
        raise_exception_task(db, severity="medium", title=f"Vendor invoice {vi.invoice_number} failed 3-way match", entity="vendor_invoice",
                             entity_id=vi.id, source="procurement", owner_role="accounts")
    return vi


@router.post("/vendor-invoices")
def post_vendor_invoice(body: VendorInvoiceIn, p: Principal = Depends(require("accounts.post")), db: Session = Depends(get_db)):
    return to_dict(record_vendor_invoice(db, p, body, "office"))


@router.get("/vendor-invoices")
def list_vendor_invoices(p: Principal = Depends(require("accounts.read")), db: Session = Depends(get_db)):
    return [to_dict(v) for v in db.execute(select(VendorInvoice).order_by(VendorInvoice.created_at.desc())).scalars()]


class ApproveVIIn(BaseModel):
    tds_amount: Decimal = Field(Decimal("0"), ge=0)
    note: str | None = None


@router.post("/vendor-invoices/{vid}/approve")
def approve_vendor_invoice(vid: uuid.UUID, body: ApproveVIIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    vi = get_or_404(db, VendorInvoice, vid, "Vendor invoice", lock=True)
    if vi.status not in ("matched", "mismatch"):
        raise Conflict("bad_status", f"Invoice is {vi.status}")
    if vi.status == "mismatch" and not body.note:
        raise AppError("reason_required", "Invoice failed 3-way match - approval requires a documented reason")
    po = db.get(PurchaseOrder, vi.po_id) if vi.po_id else None
    pr = db.get(PurchaseRequest, po.request_id) if po and po.request_id else None
    acct = "1400" if po and po.kind == "po" and pr and pr.items and any(i.get("item_id") for i in pr.items) else EXPENSE_ACCOUNT.get(pr.category if pr else "other", "5900")
    lines = [{"account": acct, "debit": vi.amount, "vehicle_id": pr.vehicle_id if pr else None, "party_type": "vendor", "party_id": vi.vendor_id}]
    if vi.tax_amount:
        lines.append({"account": "1210", "debit": vi.tax_amount})
    if body.tds_amount:
        lines.append({"account": "2110", "credit": body.tds_amount})
    lines.append({"account": "2010", "credit": Decimal(vi.amount) + Decimal(vi.tax_amount) - body.tds_amount, "party_type": "vendor", "party_id": vi.vendor_id})
    v = post_voucher(db, p, vtype="purchase", vdate=vi.invoice_date, narration=f"Vendor invoice {vi.invoice_number}", lines=lines,
                     source_entity="vendor_invoice", source_id=vi.id, approved_by=p.user_id)
    vi.status, vi.voucher_id, vi.tds_amount = "approved", v.id, body.tds_amount
    if po:
        po.status = "invoiced"
    write_audit(db, actor=p, action="vendor_invoice.approve", entity="vendor_invoice", entity_id=vi.id, reason=body.note)
    return to_dict(vi)


# ===================================================================== vendors scorecard
class ScoreIn(BaseModel):
    quality: int = Field(ge=1, le=5)
    price: int = Field(ge=1, le=5)
    punctuality: int = Field(ge=1, le=5)
    availability: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    compliance: int = Field(ge=1, le=5)
    invoice_accuracy: int = Field(ge=1, le=5)
    response: int = Field(ge=1, le=5)
    complaints: int = Field(0, ge=0)
    note: str | None = None


@router.post("/vendors/{vid}/score")
def score_vendor(vid: uuid.UUID, body: ScoreIn, p: Principal = Depends(require("vendor.write")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vendor, vid, "Vendor")
    hist = (v.score or {}).get("history", [])
    entry = {**body.model_dump(), "at": utcnow().isoformat(), "by": str(p.user_id)}
    hist.append(entry)
    dims = ["quality", "price", "punctuality", "availability", "safety", "compliance", "invoice_accuracy", "response"]
    avg = {d: round(sum(h[d] for h in hist) / len(hist), 2) for d in dims}
    v.score = {"history": hist[-20:], "average": avg, "overall": round(sum(avg.values()) / len(dims), 2)}
    return to_dict(v)


class VendorApprovalIn(BaseModel):
    status: str = Field(pattern="^(approved|suspended)$")
    reason: str = Field(min_length=3)


@router.post("/vendors/{vid}/approval")
def vendor_approval(vid: uuid.UUID, body: VendorApprovalIn, p: Principal = Depends(require("procurement.approve")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vendor, vid, "Vendor")
    before = v.approval_status
    v.approval_status = body.status
    write_audit(db, actor=p, action="vendor.approval", entity="vendor", entity_id=v.id, before={"status": before}, after={"status": body.status}, reason=body.reason)
    return to_dict(v)


# ===================================================================== inventory movements
class IssueIn(BaseModel):
    item_id: uuid.UUID
    qty: Decimal = Field(gt=0)
    kind: str = Field("issue", pattern="^(issue|return|damaged|adjust|stocktake)$")
    vehicle_id: uuid.UUID | None = None
    job_card_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    serial: str | None = None
    reason: str | None = None
    counted_qty: Decimal | None = None


@router.post("/inventory/movements")
def stock_move(body: IssueIn, p: Principal = Depends(require("inventory.write")), db: Session = Depends(get_db)):
    item = get_or_404(db, InventoryItem, body.item_id, "Item", lock=True)
    if body.kind == "issue":
        if not (body.vehicle_id or body.job_card_id or body.trip_id):
            raise AppError("target_required", "Issue must be against a vehicle, job card or trip")
        if Decimal(item.qty_on_hand) < body.qty:
            raise BlockedByRule("insufficient_stock", f"Only {item.qty_on_hand} {item.uom} in stock")
        qty = -body.qty
    elif body.kind == "return":
        qty = body.qty
    elif body.kind == "damaged":
        qty = -body.qty
    elif body.kind == "stocktake":
        if body.counted_qty is None:
            raise AppError("count_required", "counted_qty required for stocktake")
        qty = body.counted_qty - Decimal(item.qty_on_hand)
    else:
        if not body.reason:
            raise AppError("reason_required", "Adjustments need a reason")
        qty = body.qty
    m = StockMovement(item_id=item.id, kind=body.kind, qty=qty, unit_cost=item.avg_cost, vehicle_id=body.vehicle_id,
                      job_card_id=body.job_card_id, trip_id=body.trip_id, serial=body.serial, reason=body.reason, by_user=p.user_id)
    db.add(m)
    item.qty_on_hand = Decimal(item.qty_on_hand) + qty
    value = money(abs(qty) * Decimal(item.avg_cost))
    if body.kind == "issue" and value > 0:
        from app.modules.fleet.models import Vehicle
        v = db.get(Vehicle, body.vehicle_id) if body.vehicle_id else None
        post_voucher(db, p, vtype="journal", vdate=date.today(), narration=f"Stores issue {item.name} x {body.qty}",
                     lines=[{"account": "5040" if item.category in ("tyre", "battery") else "5030", "debit": value,
                             "vehicle_id": body.vehicle_id, "trip_id": body.trip_id, "cost_centre": f"VEH:{v.registration}" if v else None},
                            {"account": "1400", "credit": value}], source_entity="stock_movement", source_id=m.id)
    if body.kind in ("damaged", "stocktake") and value > 0:
        lines = [{"account": "5900", "debit": value}, {"account": "1400", "credit": value}] if qty < 0 else \
                [{"account": "1400", "debit": value}, {"account": "5900", "credit": value}]
        post_voucher(db, p, vtype="journal", vdate=date.today(), narration=f"Stock {body.kind} {item.name}", lines=lines,
                     source_entity="stock_movement", source_id=m.id)
    db.flush()
    alert = Decimal(item.qty_on_hand) < Decimal(item.min_qty)
    if alert:
        raise_exception_task(db, kind="alert", severity="low", title=f"Reorder {item.name}: {item.qty_on_hand} below min {item.min_qty}",
                             entity="inventory_item", entity_id=item.id, source="inventory", owner_role="store_custodian")
    return {**to_dict(item), "reorder_alert": alert}


# ===================================================================== godown
class GodownInIn(BaseModel):
    facility_id: uuid.UUID
    booking_id: uuid.UUID
    package_count: int = Field(ge=0)
    condition: str = Field("good", pattern="^(good|damaged|wet|open)$")
    location: str | None = None
    storage_rate_per_day: Decimal = Decimal("0")
    handling_cost: Decimal = Decimal("0")
    photo_document_ids: list[uuid.UUID] = []


@router.post("/godown/inward")
def godown_inward(body: GodownInIn, p: Principal = Depends(require("godown.write")), db: Session = Depends(get_db)):
    f = get_or_404(db, Facility, body.facility_id, "Facility")
    if not f.verified:
        raise BlockedByRule("facility_unverified", f"{f.name} is not verified for commercial storage/custody. Verification of approved "
                            "building use, fire safety, structure, access and local authority requirements is required first.")
    b = get_or_404(db, Booking, body.booking_id, "Booking")
    g = GodownEntry(code=next_number(db, "GRN-G", "GDN"), **{**body.model_dump(), "photo_document_ids": [str(x) for x in body.photo_document_ids]})
    db.add(g)
    record_custody(db, p, booking=b, trip=None, event="godown_in", package_count=body.package_count, condition=body.condition,
                   facility_id=f.id, to_party=f.name, photo_ids=g.photo_document_ids)
    db.flush()
    return to_dict(g)


class GodownOutIn(BaseModel):
    outward_count: int = Field(ge=0)
    trip_id: uuid.UUID | None = None


@router.post("/godown/{gid}/outward")
def godown_outward(gid: uuid.UUID, body: GodownOutIn, p: Principal = Depends(require("godown.write")), db: Session = Depends(get_db)):
    from app.modules.operations.models import Trip
    g = get_or_404(db, GodownEntry, gid, "Godown entry", lock=True)
    if g.status != "in_stock":
        raise Conflict("bad_status", f"Entry is {g.status}")
    b = db.get(Booking, g.booking_id)
    t = db.get(Trip, body.trip_id) if body.trip_id else None
    g.outward_at, g.outward_trip_id, g.outward_count = utcnow(), body.trip_id, body.outward_count
    g.status = "dispatched" if body.outward_count == g.package_count else "discrepancy"
    f = db.get(Facility, g.facility_id)
    record_custody(db, p, booking=b, trip=t, event="godown_out", package_count=body.outward_count, condition="good", facility_id=f.id,
                   from_party=f.name)
    days = max(1, (g.outward_at - g.inward_at).days + 1)
    return {**to_dict(g), "storage_days": days, "storage_charge": str(money(Decimal(g.storage_rate_per_day) * days))}


@router.get("/godown/stock")
def godown_stock(p: Principal = Depends(require("godown.read")), db: Session = Depends(get_db)):
    return [to_dict(g) for g in db.execute(select(GodownEntry).where(GodownEntry.status == "in_stock")).scalars()]
