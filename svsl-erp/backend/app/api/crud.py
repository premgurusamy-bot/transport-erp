"""Generic, metadata-driven CRUD for master data. Every write is validated, permission-checked and audited."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, Text, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.audit import diff, jsonable, log, snapshot
from ..core.deps import AppError, CurrentUser, get_current_user
from ..core.security import decrypt, encrypt, mask
from ..core.validators import normalize, validate
from ..db import get_db


@dataclass
class Resource:
    model: Any
    perm: str
    label: str = "name"
    search: list[str] = field(default_factory=list)
    title: str = ""
    creatable: bool = True
    updatable: bool = True
    deletable: bool = False  # hard delete allowed (only for harmless link tables)
    write_perm: str | None = None
    restricted: dict[str, str] = field(default_factory=dict)  # field -> permission needed to see/edit
    before_save: Callable | None = None  # (db, user, obj, data, is_new)
    after_create: Callable | None = None  # (db, user, obj)
    deny_update: Callable | None = None  # (db, obj) -> message | None
    date_field: str | None = None
    default_sort: str = "-id"
    extra_filters: list[str] = field(default_factory=list)


REGISTRY: dict[str, Resource] = {}


def register(name: str, res: Resource) -> None:
    REGISTRY[name] = res


def _ftype(col) -> str:
    t = col.type
    if isinstance(t, Boolean):
        return "bool"
    if isinstance(t, Integer):
        return "int"
    if isinstance(t, Numeric):
        return "number"
    if isinstance(t, DateTime):
        return "datetime"
    if isinstance(t, Date):
        return "date"
    if isinstance(t, JSON):
        return "json"
    if isinstance(t, Text):
        return "text"
    return "string"


SYSTEM_COLS = {"id", "created_at", "updated_at", "created_by", "updated_by"}


def field_meta(res: Resource, user: CurrentUser) -> list[dict]:
    out = []
    for col in res.model.__table__.columns:
        info = col.info or {}
        if col.name in SYSTEM_COLS or col.name in ("password_hash", "totp_secret"):
            continue
        if not info.get("label") and col.name not in ("is_active",):
            continue
        perm = res.restricted.get(col.name)
        out.append({
            "name": col.name, "label": info.get("label") or col.name, "type": _ftype(col), "required": bool(info.get("required")),
            "options": info.get("options"), "ref": info.get("ref"), "readonly": bool(info.get("readonly")) or bool(perm and not user.can(perm)),
            "hidden": bool(info.get("hidden")) or bool(perm and not user.can(perm) and not info.get("secret")), "secret": bool(info.get("secret")),
            "help": info.get("help"), "group": info.get("group"), "validator": info.get("validator"),
            "max_length": getattr(col.type, "length", None),
        })
    return out


def _coerce(col, value):
    if value is None or (isinstance(value, str) and value.strip() == "" and not isinstance(col.type, (String, Text))):
        return None
    t = col.type
    label = (col.info or {}).get("label") or col.name
    try:
        if isinstance(t, Boolean):
            return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on", "y")
        if isinstance(t, Integer):
            return int(value)
        if isinstance(t, Numeric):
            d = Decimal(str(value).replace(",", ""))
            if not d.is_finite():
                raise ValueError
            if t.scale is not None:
                d = d.quantize(Decimal(1).scaleb(-t.scale))
            return d
        if isinstance(t, DateTime):
            if isinstance(value, datetime):
                return value
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if isinstance(t, Date):
            return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        if isinstance(t, JSON):
            return value
        s = str(value).strip()
        if s == "":
            return None
        if getattr(t, "length", None) and len(s) > t.length:
            raise AppError(f"{label}: maximum {t.length} characters")
        return s
    except (ValueError, InvalidOperation, TypeError):
        raise AppError(f"{label}: invalid value '{value}'")


def serialize(res: Resource, obj, user: CurrentUser) -> dict:
    out = {}
    for col in res.model.__table__.columns:
        if col.name in ("password_hash", "totp_secret"):
            continue
        v = getattr(obj, col.name)
        info = col.info or {}
        perm = res.restricted.get(col.name)
        if info.get("secret"):
            plain = decrypt(v)
            v = plain if (perm and user.can(perm)) else mask(plain)
        elif perm and not user.can(perm):
            v = None
        out[col.name] = jsonable(v)
    return out


def apply(db: Session, res: Resource, obj, data: dict, user: CurrentUser, is_new: bool) -> None:
    cols = {c.name: c for c in res.model.__table__.columns}
    for key, value in data.items():
        col = cols.get(key)
        if col is None or key in SYSTEM_COLS or key in ("password_hash", "totp_secret"):
            continue
        info = col.info or {}
        if info.get("readonly"):
            continue
        perm = res.restricted.get(key)
        if perm and not user.can(perm):
            continue
        if info.get("secret"):
            if value in (None, "") or (isinstance(value, str) and value.startswith("X")):
                continue  # masked value sent back unchanged
            setattr(obj, key, encrypt(str(value).strip()))
            continue
        v = _coerce(col, value)
        if info.get("validator"):
            v = normalize(info["validator"], v)
            err = validate(info["validator"], v)
            if err:
                raise AppError(f"{info.get('label') or key}: {err}")
        opts = info.get("options")
        if opts and v not in (None, "") and v not in opts:
            raise AppError(f"{info.get('label') or key}: choose one of {', '.join(o for o in opts if o)}")
        setattr(obj, key, v)
    for key, col in cols.items():
        info = col.info or {}
        if info.get("required") and not info.get("readonly") and getattr(obj, key) in (None, "") and col.default is None:
            raise AppError(f"{info.get('label') or key} is required")


def _query(db: Session, res: Resource, params: dict):
    m = res.model
    stmt = select(m)
    cols = {c.name: c for c in m.__table__.columns}
    q = (params.get("q") or "").strip()
    if q and res.search:
        stmt = stmt.where(or_(*[func.cast(cols[f], String).ilike(f"%{q}%") for f in res.search if f in cols]))
    for k, v in params.items():
        if k in cols and k not in ("q",) and v not in (None, ""):
            try:
                stmt = stmt.where(cols[k] == _coerce(cols[k], v))
            except AppError:
                raise AppError(f"Invalid filter {k}")
    if res.date_field and res.date_field in cols:
        if params.get("from"):
            stmt = stmt.where(cols[res.date_field] >= date.fromisoformat(params["from"]))
        if params.get("to"):
            stmt = stmt.where(cols[res.date_field] <= date.fromisoformat(params["to"]))
    return stmt


router = APIRouter(prefix="/api/r", tags=["masters"])


def get_res(name: str, user: CurrentUser, write: bool = False) -> Resource:
    res = REGISTRY.get(name)
    if not res:
        raise AppError("Unknown resource", 404)
    need = (res.write_perm or f"{res.perm}:write") if write else f"{res.perm}:read"
    if not user.can(need):
        raise AppError(f"You do not have permission ({need})", 403)
    return res


@router.get("/{name}/meta")
def meta(name: str, user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user)
    can_write = user.can(res.write_perm or f"{res.perm}:write")
    return {"name": name, "title": res.title or name.replace("_", " ").title(), "label": res.label, "fields": field_meta(res, user),
            "can_create": res.creatable and can_write, "can_update": res.updatable and can_write,
            "can_delete": can_write and (res.deletable or hasattr(res.model, "is_active")), "soft_delete": hasattr(res.model, "is_active") and not res.deletable}


@router.get("/{name}")
def list_items(name: str, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user)
    params = dict(request.query_params)
    stmt = _query(db, res, params)
    m = res.model
    if params.get("lookup"):
        cols = {c.name: c for c in m.__table__.columns}
        if "is_active" in cols and not params.get("all"):
            stmt = stmt.where(cols["is_active"].is_(True))
        rows = db.execute(stmt.order_by(cols[res.label] if res.label in cols else cols["id"]).limit(2000)).scalars().all()
        return [{"id": r.id, "label": str(getattr(r, res.label, r.id))} for r in rows]
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    sort = params.get("sort") or res.default_sort
    desc = sort.startswith("-")
    sc = m.__table__.columns.get(sort.lstrip("-"))
    if sc is None:
        sc = m.__table__.columns["id"]
    limit = min(int(params.get("limit") or 100), 1000)
    offset = int(params.get("offset") or 0)
    rows = db.execute(stmt.order_by(sc.desc() if desc else sc.asc()).limit(limit).offset(offset)).scalars().all()
    return {"items": [serialize(res, r, user) for r in rows], "total": total}


@router.get("/{name}/{item_id}")
def get_item(name: str, item_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user)
    obj = db.get(res.model, item_id)
    if not obj:
        raise AppError("Not found", 404)
    return serialize(res, obj, user)


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        msg = str(exc.orig).split("\n")[0]
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            raise AppError("A record with the same unique value already exists (" + msg.split("Key ")[-1][:120] + ")", 409)
        raise AppError("Database rejected the change: " + msg[:200], 409)


def create_record(db: Session, res: Resource, name: str, data: dict, user: CurrentUser):
    """Validate, run hooks, insert and audit one record (no commit). Used by the API and by Excel import."""
    obj = res.model()
    for col in res.model.__table__.columns:
        if col.default is not None and getattr(col.default, "is_scalar", False):
            setattr(obj, col.name, col.default.arg)
    apply(db, res, obj, data, user, True)
    if hasattr(obj, "created_by"):
        obj.created_by = user.id
    if res.before_save:
        res.before_save(db, user, obj, data, True)
    try:
        with db.begin_nested():
            db.add(obj)
            db.flush()
    except IntegrityError as exc:
        raise AppError("A record with the same unique value already exists (" + str(exc.orig).split("Key ")[-1][:120].strip() + ")", 409)
    if res.after_create:
        res.after_create(db, user, obj)
    log(db, user, "create", name, obj.id, None, snapshot(obj), ip=user.ip)
    return obj


def update_record(db: Session, res: Resource, name: str, obj, data: dict, user: CurrentUser, reason: str | None = None):
    if not res.updatable:
        raise AppError("Records of this type cannot be edited; cancel and re-enter instead", 405)
    if res.deny_update:
        msg = res.deny_update(db, obj)
        if msg:
            raise AppError(msg, 409)
    before = snapshot(obj)
    apply(db, res, obj, data, user, False)
    if hasattr(obj, "updated_by"):
        obj.updated_by = user.id
    if res.before_save:
        res.before_save(db, user, obj, data, False)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise AppError("A record with the same unique value already exists (" + str(exc.orig).split("Key ")[-1][:120].strip() + ")", 409)
    b, a = diff(before, snapshot(obj))
    if a:
        log(db, user, "update", name, obj.id, b, a, reason or data.get("_reason"), ip=user.ip)
    return obj


@router.post("/{name}")
def create_item(name: str, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user, write=True)
    if not res.creatable:
        raise AppError("Records of this type are created from their own screen", 405)
    obj = create_record(db, res, name, data, user)
    _commit(db)
    return serialize(res, obj, user)


@router.put("/{name}/{item_id}")
def update_item(name: str, item_id: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user, write=True)
    obj = db.get(res.model, item_id)
    if not obj:
        raise AppError("Not found", 404)
    update_record(db, res, name, obj, data, user)
    _commit(db)
    return serialize(res, obj, user)


@router.delete("/{name}/{item_id}")
def delete_item(name: str, item_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    res = get_res(name, user, write=True)
    obj = db.get(res.model, item_id)
    if not obj:
        raise AppError("Not found", 404)
    before = snapshot(obj)
    if res.deletable:
        db.delete(obj)
        log(db, user, "delete", name, item_id, before, None, ip=user.ip)
    elif hasattr(obj, "is_active"):
        obj.is_active = False
        log(db, user, "deactivate", name, item_id, {"is_active": True}, {"is_active": False}, ip=user.ip)
    else:
        raise AppError("This record cannot be deleted (history is preserved)", 405)
    _commit(db)
    return {"ok": True}
