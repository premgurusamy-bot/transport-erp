"""Generic, permission-checked, audited CRUD endpoints for master-data style tables.

Payloads are validated with a Pydantic model generated from the table definition (types, lengths, required).
Hard deletes are not offered; records are deactivated via their status/is_active field.
"""

import datetime as dt
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import ConfigDict, Field, create_model
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, select
from sqlalchemy.orm import Session

from app.core.audit import snapshot, write_audit
from app.core.crud import get_or_404, to_dict
from app.core.deps import Principal, get_db, require
from app.core.services import next_number

SYSTEM_FIELDS = {"id", "created_at", "updated_at"}


def _py_type(col):
    t = col.type
    if isinstance(t, Boolean):
        return bool
    if isinstance(t, Integer):
        return int
    if isinstance(t, Numeric):
        return Decimal
    if isinstance(t, DateTime):
        return dt.datetime
    if isinstance(t, Date):
        return dt.date
    if isinstance(t, (String, Text)):
        return str
    try:
        pt = t.python_type
        if pt is uuid.UUID:
            return uuid.UUID
        if pt in (dict, list):
            return Any
        if pt is float:
            return float
    except NotImplementedError:
        pass
    return Any


def schema_for(model, *, exclude: set[str], partial: bool, name: str, extra: dict | None = None):
    fields = dict(extra or {})
    for col in model.__table__.columns:
        if col.key in exclude or col.key in SYSTEM_FIELDS:
            continue
        py = _py_type(col)
        max_len = getattr(col.type, "length", None) if py is str else None
        required = (not partial) and not col.nullable and col.default is None and col.server_default is None
        if required:
            fields[col.key] = (py, Field(..., max_length=max_len) if max_len else ...)
        else:
            fields[col.key] = (Optional[py], Field(None, max_length=max_len) if max_len else None)
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


def register_crud(
    router: APIRouter,
    path: str,
    model,
    *,
    read_perm: str,
    write_perm: str,
    code_field: str | None = None,
    code_prefix: str | None = None,
    readonly_fields: set[str] | None = None,
    hidden_fields: set[str] | None = None,
    before_save: Callable[[Session, Principal, Any, dict, bool], None] | None = None,
    order_by: str | None = None,
    search_fields: tuple[str, ...] = ("name",),
    extra_fields: dict | None = None,
):
    ro = set(readonly_fields or set())
    if code_field and code_prefix:
        ro.add(code_field)
    hidden = set(hidden_fields or set())
    CreateIn = schema_for(model, exclude=ro, partial=False, name=f"{model.__name__}Create",
                         extra=extra_fields)
    UpdateIn = schema_for(model, exclude=ro | ({code_field} if code_field else set()), partial=True,
                          name=f"{model.__name__}Update", extra=extra_fields)
    entity = model.__tablename__

    def out(o):
        return to_dict(o, exclude=hidden)

    @router.get(f"/{path}", name=f"list_{entity}")
    def list_(q: str | None = None, limit: int = 500, p: Principal = Depends(require(read_perm)),
              db: Session = Depends(get_db)):
        stmt = select(model)
        if q:
            conds = [getattr(model, f).ilike(f"%{q}%") for f in search_fields if hasattr(model, f)]
            if conds:
                from sqlalchemy import or_
                stmt = stmt.where(or_(*conds))
        col = getattr(model, order_by or (search_fields[0] if hasattr(model, search_fields[0]) else "id"))
        return [out(o) for o in db.execute(stmt.order_by(col).limit(min(limit, 2000))).scalars()]

    @router.get(f"/{path}/{{obj_id}}", name=f"get_{entity}")
    def get_(obj_id: uuid.UUID, p: Principal = Depends(require(read_perm)), db: Session = Depends(get_db)):
        return out(get_or_404(db, model, obj_id))

    @router.post(f"/{path}", name=f"create_{entity}")
    def create_(body: CreateIn = Body(...), p: Principal = Depends(require(write_perm)), db: Session = Depends(get_db)):
        data = body.model_dump(exclude_unset=True)
        obj = model()
        if before_save:
            before_save(db, p, obj, data, True)
        cols = set(model.__table__.columns.keys())
        for k, v in data.items():
            if k in cols:
                setattr(obj, k, v)
        if code_field and code_prefix and not getattr(obj, code_field, None):
            setattr(obj, code_field, next_number(db, code_prefix, code_prefix, fy_bound=False))
        db.add(obj)
        db.flush()
        write_audit(db, actor=p, action=f"{entity}.create", entity=entity, entity_id=obj.id, after=snapshot(obj))
        return out(obj)

    @router.patch(f"/{path}/{{obj_id}}", name=f"update_{entity}")
    def update_(obj_id: uuid.UUID, body: UpdateIn = Body(...), p: Principal = Depends(require(write_perm)),
                db: Session = Depends(get_db)):
        obj = get_or_404(db, model, obj_id, lock=True)
        data = body.model_dump(exclude_unset=True)
        before = snapshot(obj, [k for k in data if k in model.__table__.columns.keys()])
        if before_save:
            before_save(db, p, obj, data, False)
        cols = set(model.__table__.columns.keys())
        for k, v in data.items():
            if k in cols:
                setattr(obj, k, v)
        db.flush()
        write_audit(db, actor=p, action=f"{entity}.update", entity=entity, entity_id=obj.id, before=before,
                    after=snapshot(obj, [k for k in data if k in model.__table__.columns.keys()]))
        return out(obj)

    return CreateIn, UpdateIn
