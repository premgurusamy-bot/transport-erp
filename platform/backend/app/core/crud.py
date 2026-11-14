"""Small helpers shared by routers."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import NotFound


def get_or_404(db: Session, model, obj_id, what: str | None = None, lock: bool = False):
    if isinstance(obj_id, str):
        try:
            obj_id = uuid.UUID(obj_id)
        except ValueError:
            raise NotFound(what or model.__name__)
    if lock:
        from sqlalchemy import select
        obj = db.execute(select(model).where(model.id == obj_id).with_for_update()).scalar_one_or_none()
    else:
        obj = db.get(model, obj_id)
    if obj is None:
        raise NotFound(what or model.__name__)
    return obj


def to_dict(obj, exclude: set[str] | None = None) -> dict:
    out = {}
    for c in obj.__table__.columns:
        if exclude and c.key in exclude:
            continue
        v = getattr(obj, c.key)
        if isinstance(v, uuid.UUID):
            v = str(v)
        out[c.key] = v
    return out


def normalize_name(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\b(m/s|messrs|pvt|private|ltd|limited|llp|co|company|and|&)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def dec(v) -> Decimal:
    return Decimal(str(v or 0))


def as_date(v) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])
