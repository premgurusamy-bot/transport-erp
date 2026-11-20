from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog

SECRET_FIELDS = {"password_hash", "totp_secret", "aadhaar_enc", "bank_account_enc"}


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def snapshot(obj) -> dict:
    out = {}
    for col in obj.__table__.columns:
        if col.name in SECRET_FIELDS:
            out[col.name] = "***" if getattr(obj, col.name) else None
        else:
            out[col.name] = jsonable(getattr(obj, col.name))
    return out


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    keys = [k for k in after if before.get(k) != after.get(k) and k not in ("updated_at",)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def log(db: Session, user, action: str, entity: str, entity_id, before=None, after=None, reason: str | None = None, ip: str | None = None) -> None:
    db.add(
        AuditLog(
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None) or "system",
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=jsonable(before) if before else None,
            after=jsonable(after) if after else None,
            reason=reason,
            ip=ip,
        )
    )
