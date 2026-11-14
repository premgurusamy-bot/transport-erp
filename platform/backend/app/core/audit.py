"""Tamper-evident (hash-chained) audit trail."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.modules.platform.models import AuditLog

GENESIS = "0" * 64
SENSITIVE_KEYS = {"password", "password_hash", "otp", "otp_hash", "token", "token_hash", "pin", "secret"}


def _clean(v):
    if isinstance(v, dict):
        return {k: ("***" if k in SENSITIVE_KEYS else _clean(x)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (Decimal,)):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Enum):
        return v.value
    return v


def snapshot(obj, fields: list[str] | None = None) -> dict:
    """Serialisable snapshot of a model's columns (for before/after audit values)."""
    if obj is None:
        return {}
    cols = fields or [c.key for c in obj.__table__.columns]
    return _clean({c: getattr(obj, c, None) for c in cols})


def _digest(row: dict, prev: str) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256((prev + payload).encode()).hexdigest()


def write_audit(
    db: Session,
    *,
    actor=None,
    action: str,
    entity: str,
    entity_id=None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> AuditLog:
    # Serialise writers so the chain is linear (transaction-scoped advisory lock).
    db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
    prev = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar() or GENESIS
    at = utcnow()
    actor_id = getattr(actor, "user_id", None) or getattr(actor, "id", None)
    actor_name = getattr(actor, "name", None)
    row = {
        "at": at.isoformat(),
        "actor_id": str(actor_id) if actor_id else None,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "before": _clean(before),
        "after": _clean(after),
        "reason": reason,
    }
    log = AuditLog(
        at=at,
        actor_id=actor_id,
        actor_name=actor_name,
        action=action,
        entity=entity,
        entity_id=row["entity_id"],
        before=row["before"],
        after=row["after"],
        reason=reason,
        ip=ip,
        prev_hash=prev,
        hash=_digest(row, prev),
    )
    db.add(log)
    db.flush()
    return log


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    count = 0
    for log in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        row = {
            "at": log.at.isoformat(),
            "actor_id": str(log.actor_id) if log.actor_id else None,
            "action": log.action,
            "entity": log.entity,
            "entity_id": log.entity_id,
            "before": log.before,
            "after": log.after,
            "reason": log.reason,
        }
        if log.prev_hash != prev or _digest(row, prev) != log.hash:
            return {"ok": False, "broken_at_id": log.id, "checked": count}
        prev = log.hash
        count += 1
    return {"ok": True, "checked": count}
