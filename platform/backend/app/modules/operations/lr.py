"""Lorry Receipt (LR) numbering/versioning and e-way bill applicability workflow."""
from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.errors import AppError
from app.core.services import get_config, next_number
from app.integrations.adapters import get_adapter
from app.modules.commercial.models import Booking
from app.modules.masters.models import Customer, Location
from app.modules.operations.models import EwayBill, LorryReceipt


def lr_content(db: Session, b: Booking, vehicle_reg: str | None = None) -> dict:
    o, d = db.get(Location, b.origin_id), db.get(Location, b.destination_id)
    company = get_config(db, "company.profile")
    cust = db.get(Customer, b.customer_id)
    return {
        "company": company.get("name"), "company_gstin": company.get("gstin"),
        "booking": b.code, "service_type": b.service_type, "customer": cust.name if cust else None,
        "consignor": {"name": b.consignor_name, "address": b.consignor_address, "gstin": b.consignor_gstin},
        "consignee": {"name": b.consignee_name, "address": b.consignee_address, "gstin": b.consignee_gstin},
        "from": f"{o.city}, {o.state}" if o else None, "to": f"{d.city}, {d.state}" if d else None,
        "goods": b.goods_description, "packages": b.package_count, "weight_kg": str(b.weight_kg),
        "declared_value": str(b.declared_value) if b.declared_value is not None else None,
        "vehicle": vehicle_reg, "gst_paid_by": "Consignee/Consignor under RCM" if b.gst_mode == "RCM" else "Transporter (FCM)",
        "freight": "As agreed" if b.service_type == "PTL" else str(b.freight_amount),
        "terms": "Subject to G ROAD LINES standard terms. Goods carried at owner's risk unless insured.",
        "language": "en/ta",
    }


def issue_lr(db: Session, actor, b: Booking, vehicle_reg: str | None = None) -> LorryReceipt:
    existing = db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id,
                                                     LorryReceipt.status != "cancelled")).scalar_one_or_none()
    if existing:
        return existing
    lr = LorryReceipt(number=next_number(db, "LR", "GRL/LR"), booking_id=b.id, content=lr_content(db, b, vehicle_reg),
                      verify_token=secrets.token_urlsafe(16))
    db.add(lr)
    db.flush()
    write_audit(db, actor=actor, action="lr.issue", entity="lr", entity_id=lr.id, after={"number": lr.number, "booking": b.code})
    return lr


def amend_lr(db: Session, actor, lr: LorryReceipt, changes: dict, reason: str) -> LorryReceipt:
    if lr.status == "cancelled":
        raise AppError("lr_cancelled", "Cancelled LR cannot be amended")
    if not reason:
        raise AppError("reason_required", "Amendment reason required")
    before = dict(lr.content)
    lr.content = {**lr.content, **changes}
    lr.version += 1
    lr.status = "amended"
    lr.amendments = [*lr.amendments, {"version": lr.version, "at": utcnow().isoformat(), "by": str(actor.user_id),
                                      "reason": reason, "changes": changes}]
    write_audit(db, actor=actor, action="lr.amend", entity="lr", entity_id=lr.id, before=before, after=lr.content, reason=reason)
    return lr


def eway_applicability(b: Booking, threshold: Decimal = Decimal("50000")) -> tuple[bool, str]:
    """Indicative rule only. Thresholds/exemptions vary by state and goods - configurable and to be verified."""
    if b.declared_value is None:
        return True, "Declared value missing - treat as applicable until confirmed"
    if Decimal(b.declared_value) > threshold:
        return True, f"Consignment value Rs {b.declared_value} exceeds configured threshold Rs {threshold}"
    return False, f"Consignment value below configured threshold Rs {threshold} (verify state/goods exemptions)"


def ensure_eway(db: Session, actor, b: Booking, vehicle_reg: str | None, km: float, use_provider: bool) -> EwayBill:
    ew = db.execute(select(EwayBill).where(EwayBill.booking_id == b.id, EwayBill.status.in_(("pending", "active", "not_required"))))\
        .scalars().first()
    applicable, why = eway_applicability(b)
    if ew is None:
        ew = EwayBill(booking_id=b.id, applicable=applicable, applicability_reason=why,
                      status="pending" if applicable else "not_required")
        db.add(ew)
    if applicable and use_provider and ew.status == "pending":
        res = get_adapter("eway").generate({"booking": b.code, "value": str(b.declared_value)}, km)
        ew.number = res.data["number"]
        ew.valid_from = datetime.fromisoformat(res.data["valid_from"])
        ew.valid_until = datetime.fromisoformat(res.data["valid_until"])
        ew.source, ew.status, ew.vehicle_registration = "provider_mock", "active", vehicle_reg
    db.flush()
    return ew


def eway_ok_for_dispatch(ew: EwayBill | None) -> tuple[bool, str]:
    if ew is None:
        return False, "E-way bill applicability not assessed"
    if ew.status == "not_required":
        return True, "E-way bill not required (per configured rule)"
    if ew.status != "active" or not ew.number:
        return False, "E-way bill required but not generated/entered"
    if ew.valid_until and ew.valid_until < utcnow():
        return False, "E-way bill has expired"
    return True, f"E-way bill {ew.number} valid until {ew.valid_until}"
