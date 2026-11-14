"""Cross-cutting services: configuration store, numbering, approvals, tasks/exceptions."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import utcnow
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.modules.platform.models import ApprovalRequest, ConfigValue, NumberSequence, Task

# --------------------------------------------------------------------------------------------
# Configuration (versioned, effective-dated). Defaults are conservative and documented in
# ASSUMPTIONS.md; every one can be changed in Settings by an authorised user.
# --------------------------------------------------------------------------------------------
CONFIG_DEFAULTS: dict[str, object] = {
    "company.profile": {"name": "G ROAD LINES", "gstin": None, "pan": None, "state_code": "33",
                        "state": "Tamil Nadu", "address": "Office address to be configured", "phone": None},
    "pricing.min_margin_pct": 8.0,          # quote below this contribution margin needs approval
    "pricing.max_discount_pct": 10.0,       # absolute cap even with approval (owner_director may raise)
    "pricing.default_validity_days": 7,
    "pricing.cost_rates": {                 # internal cost model, INR
        "own_fuel_per_km": 22.0, "own_maintenance_per_km": 4.5, "own_driver_per_day": 900.0,
        "own_fixed_per_day": 1800.0, "deadhead_pct": 30.0, "toll_per_km": 2.2, "insurance_risk_pct": 0.1,
        "km_per_day": 350,
    },
    "ptl.allocation_formula": {"version": 1, "method": "hybrid", "weights": {"weight": 0.5, "volume": 0.3, "floor": 0.2}},
    "ptl.max_discount_pct": 15.0,
    "ptl.capacity_reserve_pct": 5.0,
    "ptl.service_levels": {"standard": {"window_hours": 72}, "priority": {"window_hours": 48}, "time_critical": {"window_hours": 24}},
    "credit.policy": {"warn_at_pct": 80.0, "block_at_pct": 100.0, "block_overdue_days": 60, "default_days": 30},
    "approval.thresholds": {  # INR amounts above which the second-level permission is required
        "expense": 5000, "procurement": 10000, "repair": 15000, "advance": 5000, "payment": 0, "refund": 0,
        "write_off": 0, "settlement": 0,
    },
    "fuel.anomaly": {"mileage_drop_pct": 20.0, "max_fill_over_tank_pct": 2.0, "duplicate_window_hours": 6},
    "maintenance.intervals": {"service_km": 10000, "service_days": 90},
    "gps.stale_minutes": 15,
    "gps.long_stop_minutes": 60,
    "compliance.alert_days": [30, 15, 7, 1],
    "retention.days": {"gps_pings": 365, "notifications": 730, "camera_clips": 90},
    "notification.daily_cap_per_recipient": 10,
    "ai.budget": {"daily_inr": 300.0, "monthly_inr": 5000.0, "alert_pcts": [50, 75, 90, 100], "on_cap": "pause_nonessential"},
    "ai.routing": {"default": "mock", "fallback": "mock"},
    "marketing.daily_autopublish_cap": 2,
    "driver.duty": {"max_driving_hours_day": 10, "min_rest_hours": 8},
    "backup.targets": {"rpo_hours": 24, "rto_hours": 8, "status": "proposed - not yet tested"},
    "billing.default_cycle": "per_lr",
    "payroll.statutory": {"pf_employee_pct": 12.0, "pf_wage_ceiling": 15000, "esi_employee_pct": 0.75, "esi_wage_limit": 21000,
                          "pt_monthly": 0, "_note": "Placeholders - verify current PF/ESI/PT rules with your CA/consultant"},
    "bank.auto_confirm_exact": True,
    "eway.value_threshold": 50000,
    "tax.gst_rates": {"freight_gta_rcm": 0.0, "freight_gta_fcm": 12.0, "freight_gta_fcm_low": 5.0, "services": 18.0,
                      "_note": "Configurable. Verify current GST notifications with your CA before use."},
    "tax.tds_rates": {"194C_individual": 1.0, "194C_other": 2.0, "_note": "Verify with CA"},
}


def get_config(db: Session, key: str, at: datetime | None = None):
    q = select(ConfigValue).where(ConfigValue.key == key)
    if at:
        q = q.where(ConfigValue.effective_from <= at)
    row = db.execute(q.order_by(ConfigValue.version.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        return CONFIG_DEFAULTS.get(key)
    return row.value


def set_config(db: Session, key: str, value, actor, reason: str, effective_from: datetime | None = None) -> ConfigValue:
    if not reason:
        raise AppError("reason_required", "A reason is required for configuration changes")
    current = db.execute(
        select(ConfigValue).where(ConfigValue.key == key).order_by(ConfigValue.version.desc()).limit(1)
    ).scalar_one_or_none()
    before = current.value if current else CONFIG_DEFAULTS.get(key)
    row = ConfigValue(
        key=key, version=(current.version + 1) if current else 1, value=value,
        effective_from=effective_from or utcnow(), changed_by=actor.user_id, reason=reason,
    )
    db.add(row)
    db.flush()
    write_audit(db, actor=actor, action="config.change", entity="config", entity_id=key,
                before={"value": before}, after={"value": value, "version": row.version}, reason=reason)
    return row


# --------------------------------------------------------------------------------------------
# Numbering with financial-year control (April-March, India). Row lock prevents duplicates.
# --------------------------------------------------------------------------------------------
def financial_year(d: date | datetime | None = None) -> str:
    d = d or utcnow()
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def next_number(db: Session, series: str, prefix: str, fy_bound: bool = True, width: int = 5, when=None) -> str:
    fy = financial_year(when) if fy_bound else "-"
    seq = db.execute(
        select(NumberSequence).where(NumberSequence.series == series, NumberSequence.fy == fy).with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = NumberSequence(series=series, fy=fy, last=0)
        db.add(seq)
        db.flush()
        seq = db.execute(
            select(NumberSequence).where(NumberSequence.series == series, NumberSequence.fy == fy).with_for_update()
        ).scalar_one()
    seq.last += 1
    db.flush()
    n = str(seq.last).zfill(width)
    return f"{prefix}/{fy}/{n}" if fy_bound else f"{prefix}-{n}"


# --------------------------------------------------------------------------------------------
# Maker-checker approvals
# --------------------------------------------------------------------------------------------
def request_approval(
    db: Session, actor, *, kind: str, entity: str, entity_id, title: str, required_permission: str,
    amount: Decimal | None = None, payload: dict | None = None, reason: str | None = None, origin: str = "human",
) -> ApprovalRequest:
    existing = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.kind == kind, ApprovalRequest.entity_id == str(entity_id), ApprovalRequest.status == "pending"
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    ar = ApprovalRequest(
        code=next_number(db, "APR", "APR"), kind=kind, entity=entity, entity_id=str(entity_id), title=title,
        amount=amount, payload=payload, required_permission=required_permission, maker_id=actor.user_id,
        maker_reason=reason, origin=origin,
    )
    db.add(ar)
    db.flush()
    write_audit(db, actor=actor, action="approval.request", entity="approval", entity_id=ar.id,
                after={"kind": kind, "entity_id": str(entity_id), "amount": amount, "origin": origin}, reason=reason)
    return ar


def decide_approval(db: Session, actor, approval_id: uuid.UUID, approve: bool, note: str | None) -> ApprovalRequest:
    ar = db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval_id).with_for_update()).scalar_one_or_none()
    if not ar:
        raise NotFound("Approval request")
    if ar.status != "pending":
        raise Conflict("already_decided", f"This request is already {ar.status}")
    if ar.maker_id == actor.user_id:
        raise Forbidden("You cannot approve your own request (maker-checker)", code="self_approval")
    if not actor.can(ar.required_permission):
        raise Forbidden(f"Approval requires permission {ar.required_permission}")
    if not approve and not note:
        raise AppError("reason_required", "Give a reason for rejection")
    ar.status = "approved" if approve else "rejected"
    ar.checker_id = actor.user_id
    ar.checker_note = note
    ar.decided_at = utcnow()
    db.flush()
    write_audit(db, actor=actor, action=f"approval.{ar.status}", entity="approval", entity_id=ar.id,
                after={"kind": ar.kind, "entity_id": ar.entity_id}, reason=note)
    # Notify the registered handler (domain modules register callbacks)
    handler = APPROVAL_HANDLERS.get(ar.kind)
    if handler:
        handler(db, actor, ar)
    return ar


def approved(db: Session, kind: str, entity_id) -> ApprovalRequest | None:
    return db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.kind == kind, ApprovalRequest.entity_id == str(entity_id), ApprovalRequest.status == "approved"
        ).order_by(ApprovalRequest.decided_at.desc()).limit(1)
    ).scalar_one_or_none()


APPROVAL_HANDLERS: dict[str, callable] = {}


def on_approval(kind: str):
    def deco(fn):
        APPROVAL_HANDLERS[kind] = fn
        return fn

    return deco


# --------------------------------------------------------------------------------------------
# Exceptions / tasks
# --------------------------------------------------------------------------------------------
def raise_exception_task(
    db: Session, *, kind: str = "exception", severity: str, title: str, entity: str | None = None, entity_id=None,
    source: str | None = None, detail: str | None = None, owner_role: str | None = None, blocking: bool = False,
    due_at: datetime | None = None,
) -> Task:
    # De-duplicate identical open exceptions
    existing = db.execute(
        select(Task).where(Task.status != "closed", Task.title == title, Task.entity_id == (str(entity_id) if entity_id else None))
    ).scalar_one_or_none()
    if existing:
        return existing
    t = Task(code=next_number(db, "TSK", "TSK"), kind=kind, severity=severity, title=title, detail=detail, source=source,
             entity=entity, entity_id=str(entity_id) if entity_id else None, owner_role=owner_role, blocking=blocking,
             due_at=due_at)
    db.add(t)
    db.flush()
    return t


def open_blocking_tasks(db: Session, entity: str, entity_id) -> list[Task]:
    return list(db.execute(
        select(Task).where(Task.entity == entity, Task.entity_id == str(entity_id), Task.status != "closed", Task.blocking.is_(True))
    ).scalars())
