"""Customer credit exposure and booking/dispatch credit gate (no double counting)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import money, utcnow
from app.core.services import approved, get_config
from app.modules.commercial.models import Booking
from app.modules.finance.models import Invoice, InvoiceLine, Receipt
from app.modules.masters.models import CreditProfile

OPEN_STATUSES = ("confirmed", "planned", "dispatched", "in_transit", "on_hold")
UNBILLED_STATUSES = ("delivered", "pod_verified")


def active_profile(db: Session, customer_id) -> CreditProfile | None:
    return db.execute(select(CreditProfile).where(
        CreditProfile.customer_id == customer_id, CreditProfile.status == "active",
        CreditProfile.effective_from <= utcnow()).order_by(CreditProfile.effective_from.desc()).limit(1)).scalar_one_or_none()


def booking_value(b: Booking) -> Decimal:
    extras = sum((Decimal(str(e.get("amount", 0))) for e in (b.extra_charges or [])), Decimal("0"))
    return money(Decimal(b.freight_amount) + extras)


def exposure(db: Session, customer_id, exclude_booking_id=None) -> dict:
    today = date.today()
    invs = list(db.execute(select(Invoice).where(Invoice.customer_id == customer_id,
                                                 Invoice.status.in_(("issued", "part_paid", "disputed")))).scalars())
    outstanding = Decimal("0")
    overdue = Decimal("0")
    oldest_overdue_days = 0
    disputed = Decimal("0")
    for i in invs:
        bal = Decimal(i.total) - Decimal(i.amount_received) - Decimal(i.tds_received)
        outstanding += bal
        if i.status == "disputed":
            disputed += bal
        if i.due_date < today and bal > 0:
            overdue += bal
            oldest_overdue_days = max(oldest_overdue_days, (today - i.due_date).days)
    invoiced_bookings = set(db.execute(select(InvoiceLine.booking_id).where(InvoiceLine.active.is_(True),
                                                                            InvoiceLine.booking_id.isnot(None))).scalars())
    unbilled = Decimal("0")
    open_commit = Decimal("0")
    for b in db.execute(select(Booking).where(Booking.customer_id == customer_id,
                                              Booking.status.in_(OPEN_STATUSES + UNBILLED_STATUSES))).scalars():
        if b.id == exclude_booking_id or b.id in invoiced_bookings:
            continue
        v = booking_value(b) - Decimal(b.advance_received)
        if b.status in UNBILLED_STATUSES:
            unbilled += v
        else:
            open_commit += v
    unallocated = db.execute(select(func.coalesce(func.sum(Receipt.unallocated), 0)).where(
        Receipt.customer_id == customer_id, Receipt.status == "confirmed", Receipt.is_advance.is_(False))).scalar()
    prof = active_profile(db, customer_id)
    deposit = Decimal(prof.deposit_amount) if prof else Decimal("0")
    total = money(outstanding + unbilled + open_commit - Decimal(unallocated))
    return {
        "outstanding": money(outstanding), "overdue": money(overdue), "oldest_overdue_days": oldest_overdue_days,
        "disputed": money(disputed), "unbilled_completed": money(unbilled), "open_committed": money(open_commit),
        "unallocated_receipts": money(unallocated), "deposit": money(deposit), "exposure": total,
        "limit": money(prof.limit_amount) if prof else Decimal("0.00"), "credit_days": prof.credit_days if prof else 0,
        "advance_pct": float(prof.advance_pct) if prof else 100.0, "has_profile": prof is not None,
    }


def evaluate(db: Session, booking: Booking) -> dict:
    """Returns status ok|warning|blocked|exception_approved with reasons. Pure evaluation - no side effects."""
    pol = get_config(db, "credit.policy")
    ex = exposure(db, booking.customer_id, exclude_booking_id=booking.id)
    amount = booking_value(booking) - Decimal(booking.advance_received)
    after = ex["exposure"] + amount
    cap = ex["limit"] + ex["deposit"]
    reasons: list[str] = []
    status = "ok"
    if not ex["has_profile"] or ex["limit"] <= 0:
        if Decimal(booking.advance_received) < booking_value(booking):
            status = "blocked"
            reasons.append("No approved credit limit: full advance required before confirmation")
    else:
        pct = float(after / cap * 100) if cap > 0 else 999.0
        if ex["oldest_overdue_days"] > int(pol["block_overdue_days"]):
            status = "blocked"
            reasons.append(f"Invoices overdue {ex['oldest_overdue_days']} days (policy block at {pol['block_overdue_days']})")
        if pct >= float(pol["block_at_pct"]):
            status = "blocked"
            reasons.append(f"Exposure after booking Rs {after} is {pct:.0f}% of limit Rs {cap}")
        elif pct >= float(pol["warn_at_pct"]) and status != "blocked":
            status = "warning"
            reasons.append(f"Exposure after booking is {pct:.0f}% of limit")
        req_adv = money(booking_value(booking) * Decimal(str(ex["advance_pct"])) / 100)
        if req_adv > Decimal(booking.advance_received):
            status = "blocked" if status != "blocked" else status
            reasons.append(f"Advance Rs {req_adv} required, received Rs {booking.advance_received}")
    if status == "blocked" and approved(db, "credit_exception", booking.id):
        status = "exception_approved"
        reasons.append("Authorised credit exception on record")
    return {"status": status, "reasons": reasons, "exposure_before": str(ex["exposure"]), "booking_amount": str(amount),
            "exposure_after": str(after), "limit": str(ex["limit"]), "deposit": str(ex["deposit"]),
            "breakdown": {k: str(v) if isinstance(v, Decimal) else v for k, v in ex.items()}, "checked_at": utcnow().isoformat()}


def new_profile_id() -> uuid.UUID:
    return uuid.uuid4()
