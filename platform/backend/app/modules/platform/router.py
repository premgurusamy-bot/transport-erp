"""Authentication, users/roles, settings, audit, approvals, documents, notifications, integrations, tasks."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.audit import verify_chain, write_audit
from app.core.config import get_settings
from app.core.crud import get_or_404
from app.core.db import utcnow
from app.core.deps import Principal, current_principal, get_db, principal_for_user, require, require_any
from app.core.errors import AppError, Forbidden, NotFound, Unauthorized
from app.core.notify import queue
from app.core.rbac import PERMISSIONS
from app.core.security import (
    hash_password, mask, new_otp, new_token, otp_hash, password_problems, sign, token_hash, verify_password,
    verify_signature,
)
from app.core.services import CONFIG_DEFAULTS, decide_approval, get_config, set_config
from app.integrations.adapters import REGISTRY, STATUS_ONLY
from app.modules.platform.models import (
    ApprovalRequest, AuditLog, ConfigValue, Document, IntegrationProvider, LoginAttempt, Notification, OtpChallenge, Role,
    Task, TempDriverAccess, User,
)
from app.modules.platform.models import Session as UserSession

router = APIRouter(prefix="/api/v1", tags=["platform"])


# ===================================================================== auth
class LoginIn(BaseModel):
    identifier: str = Field(min_length=3, max_length=160)  # email or phone
    password: str = Field(min_length=1, max_length=200)
    device: str | None = None


def _check_lockout(db: Session, ident: str):
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.login_lock_minutes)
    fails = db.execute(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.identifier == ident, LoginAttempt.success.is_(False), LoginAttempt.at >= since
        )
    ).scalar()
    if fails >= s.login_max_failures:
        raise AppError("locked", f"Too many failed attempts. Try again after {s.login_lock_minutes} minutes.", status=429)


def _issue_session(db: Session, user: User, request: Request, device: str | None, scope_trip_id=None, hours=None):
    token = new_token()
    sess = UserSession(user_id=user.id, token_hash=token_hash(token), device=(device or "")[:200],
                       ip=request.client.host if request.client else None, scope_trip_id=scope_trip_id,
                       expires_at=utcnow() + timedelta(hours=hours or get_settings().session_hours))
    db.add(sess)
    user.last_login_at = utcnow()
    db.flush()
    return token, sess


def _me(user: User, p: Principal) -> dict:
    return {
        "id": str(user.id), "name": user.name, "email": user.email, "phone": user.phone, "language": user.language,
        "roles": sorted(p.roles), "permissions": sorted(p.permissions),
        "customer_id": str(user.customer_id) if user.customer_id else None,
        "owner_id": str(user.owner_id) if user.owner_id else None,
        "vendor_id": str(user.vendor_id) if user.vendor_id else None,
        "driver_id": str(user.driver_id) if user.driver_id else None,
        "scope_trip_id": str(p.scope_trip_id) if p.scope_trip_id else None,
    }


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ident = body.identifier.strip().lower()
    _check_lockout(db, ident)
    user = db.execute(select(User).where(or_(func.lower(User.email) == ident, User.phone == ident))).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else None) and user is not None and user.is_active
    db.add(LoginAttempt(identifier=ident, success=bool(ok), ip=request.client.host if request.client else None))
    if not ok:
        db.commit()  # persist the failed attempt even though we raise
        raise Unauthorized("Wrong email/phone or password")
    token, sess = _issue_session(db, user, request, body.device)
    write_audit(db, actor=user, action="auth.login", entity="user", entity_id=user.id, ip=sess.ip)
    return {"token": token, "expires_at": sess.expires_at, "user": _me(user, principal_for_user(user, sess))}


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=10, max_length=15)


@router.post("/auth/otp/request")
def otp_request(body: OtpRequestIn, db: Session = Depends(get_db)):
    """OTP sign-in for drivers (and temporary attached drivers). Response is identical whether or not the phone exists."""
    user = db.execute(select(User).where(User.phone == body.phone, User.is_active.is_(True))).scalar_one_or_none()
    out = {"sent": True, "message": "If this phone is registered, an OTP has been sent."}
    if not user:
        return out
    recent = db.execute(select(func.count()).select_from(OtpChallenge).where(
        OtpChallenge.target == body.phone, OtpChallenge.created_at >= utcnow() - timedelta(minutes=10))).scalar()
    if recent >= 5:
        raise AppError("rate_limited", "Too many OTP requests. Wait 10 minutes.", status=429)
    otp = new_otp()
    db.add(OtpChallenge(purpose="login", target=body.phone, ref_id=user.id, otp_hash=otp_hash(otp, "login"),
                        expires_at=utcnow() + timedelta(minutes=5)))
    queue(db, channel="sms", recipient=body.phone, template="login_otp", otp=otp)
    if get_settings().expose_dev_otp:
        out["dev_otp"] = otp  # DEVELOPMENT ONLY (MOCK SMS). Disabled outside development by config validation.
    return out


class OtpVerifyIn(BaseModel):
    phone: str
    otp: str = Field(min_length=4, max_length=8)
    device: str | None = None


def verify_otp(db: Session, purpose: str, target: str, otp: str) -> OtpChallenge:
    ch = db.execute(select(OtpChallenge).where(
        OtpChallenge.purpose == purpose, OtpChallenge.target == target, OtpChallenge.consumed_at.is_(None)
    ).order_by(OtpChallenge.created_at.desc()).limit(1)).scalar_one_or_none()
    if not ch or ch.expires_at < utcnow():
        raise AppError("otp_expired", "OTP expired. Request a new one.")
    ch.attempts += 1
    if ch.attempts > 5:
        ch.consumed_at = utcnow()
        db.commit()
        raise AppError("otp_locked", "Too many wrong attempts. Request a new OTP.", status=429)
    if ch.otp_hash != otp_hash(otp, purpose):
        db.commit()
        raise AppError("otp_wrong", "Wrong OTP")
    ch.consumed_at = utcnow()
    return ch


@router.post("/auth/otp/verify")
def otp_verify(body: OtpVerifyIn, request: Request, db: Session = Depends(get_db)):
    ch = verify_otp(db, "login", body.phone, body.otp)
    user = db.get(User, ch.ref_id)
    if not user or not user.is_active:
        raise Unauthorized()
    scope_trip = None
    if user.driver_id and {r.code for r in user.roles} <= {"attached_driver"}:
        # Attached/temporary drivers only get trip-scoped access while a grant is active
        grant = db.execute(select(TempDriverAccess).where(
            TempDriverAccess.driver_id == user.driver_id, TempDriverAccess.revoked_at.is_(None),
            TempDriverAccess.expires_at > utcnow()).order_by(TempDriverAccess.created_at.desc())).scalars().first()
        if not grant:
            raise Forbidden("No active trip assigned to this phone")
        scope_trip = grant.trip_id
    token, sess = _issue_session(db, user, request, body.device, scope_trip_id=scope_trip)
    write_audit(db, actor=user, action="auth.login_otp", entity="user", entity_id=user.id)
    return {"token": token, "expires_at": sess.expires_at, "user": _me(user, principal_for_user(user, sess))}


@router.post("/auth/logout")
def logout(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    s = db.get(UserSession, p.session_id)
    if s:
        s.revoked_at = utcnow()
    return {"ok": True}


@router.get("/auth/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _me(db.get(User, p.user_id), p)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    user = db.get(User, p.user_id)
    if not verify_password(body.current_password, user.password_hash):
        raise AppError("wrong_password", "Current password is wrong")
    probs = password_problems(body.new_password)
    if probs:
        raise AppError("weak_password", "Password needs " + ", ".join(probs))
    user.password_hash = hash_password(body.new_password)
    # Revoke all other sessions
    for s in db.execute(select(UserSession).where(UserSession.user_id == user.id, UserSession.id != p.session_id)).scalars():
        s.revoked_at = utcnow()
    write_audit(db, actor=p, action="auth.change_password", entity="user", entity_id=user.id)
    return {"ok": True}


# ===================================================================== users & roles
class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str | None = None
    phone: str | None = None
    password: str | None = None
    roles: list[str]
    customer_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    access_valid_from: datetime | None = None
    access_valid_to: datetime | None = None
    access_purpose: str | None = None


def _user_out(u: User) -> dict:
    return {"id": str(u.id), "name": u.name, "email": u.email, "phone": u.phone, "is_active": u.is_active,
            "roles": [r.code for r in u.roles], "customer_id": u.customer_id, "owner_id": u.owner_id,
            "vendor_id": u.vendor_id, "driver_id": u.driver_id, "last_login_at": u.last_login_at,
            "access_valid_to": u.access_valid_to, "access_purpose": u.access_purpose}


def create_user(db: Session, actor, body: UserIn) -> User:
    if not body.email and not body.phone:
        raise AppError("identifier_required", "Email or phone is required")
    roles = list(db.execute(select(Role).where(Role.code.in_(body.roles))).scalars())
    if len(roles) != len(set(body.roles)):
        raise AppError("unknown_role", "One or more roles do not exist")
    codes = {r.code for r in roles}
    if codes & {"customer_admin", "customer_user"} and not body.customer_id:
        raise AppError("scope_required", "Customer users must be linked to a customer")
    if "vehicle_owner" in codes and not body.owner_id:
        raise AppError("scope_required", "Owner users must be linked to an owner")
    if "vendor_user" in codes and not body.vendor_id:
        raise AppError("scope_required", "Vendor users must be linked to a vendor")
    if codes & {"driver", "attached_driver"} and not body.driver_id:
        raise AppError("scope_required", "Driver users must be linked to a driver")
    if "ca_auditor" in codes and not (body.access_valid_to and body.access_purpose):
        raise AppError("scope_required", "CA/auditor access needs a purpose and an end date")
    if body.password:
        probs = password_problems(body.password)
        if probs:
            raise AppError("weak_password", "Password needs " + ", ".join(probs))
    u = User(name=body.name, email=body.email.lower() if body.email else None, phone=body.phone,
             password_hash=hash_password(body.password) if body.password else None,
             customer_id=body.customer_id, owner_id=body.owner_id, vendor_id=body.vendor_id, driver_id=body.driver_id,
             employee_id=body.employee_id, access_valid_from=body.access_valid_from,
             access_valid_to=body.access_valid_to, access_purpose=body.access_purpose)
    u.roles = roles
    db.add(u)
    db.flush()
    write_audit(db, actor=actor, action="user.create", entity="user", entity_id=u.id,
                after={"name": u.name, "roles": sorted(codes)})
    return u


@router.get("/users")
def list_users(p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return [_user_out(u) for u in db.execute(select(User).order_by(User.name)).scalars()]


@router.post("/users")
def add_user(body: UserIn, p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    return _user_out(create_user(db, p, body))


class UserRolesIn(BaseModel):
    roles: list[str]
    reason: str


@router.put("/users/{user_id}/roles")
def set_roles(user_id: uuid.UUID, body: UserRolesIn, p: Principal = Depends(require("users.manage")),
              db: Session = Depends(get_db)):
    u = get_or_404(db, User, user_id, "User")
    before = [r.code for r in u.roles]
    u.roles = list(db.execute(select(Role).where(Role.code.in_(body.roles))).scalars())
    # Role change revokes sessions so new permissions apply immediately
    for s in db.execute(select(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))).scalars():
        s.revoked_at = utcnow()
    write_audit(db, actor=p, action="user.roles", entity="user", entity_id=u.id, before={"roles": before},
                after={"roles": body.roles}, reason=body.reason)
    return _user_out(u)


@router.post("/users/{user_id}/deactivate")
def deactivate(user_id: uuid.UUID, body: UserRolesIn | None = None, p: Principal = Depends(require("users.manage")),
               db: Session = Depends(get_db)):
    u = get_or_404(db, User, user_id, "User")
    if u.id == p.user_id:
        raise AppError("self", "You cannot deactivate yourself")
    u.is_active = False
    for s in db.execute(select(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))).scalars():
        s.revoked_at = utcnow()
    write_audit(db, actor=p, action="user.deactivate", entity="user", entity_id=u.id, reason=body.reason if body else None)
    return {"ok": True}


@router.get("/roles")
def list_roles(p: Principal = Depends(require_any("users.manage", "settings.read")), db: Session = Depends(get_db)):
    return {"roles": [{"code": r.code, "name": r.name, "permissions": r.permissions, "is_external": r.is_external}
                      for r in db.execute(select(Role).order_by(Role.name)).scalars()],
            "permissions": PERMISSIONS}


class RolePermsIn(BaseModel):
    permissions: list[str]
    reason: str


@router.put("/roles/{code}")
def update_role(code: str, body: RolePermsIn, p: Principal = Depends(require("users.manage")), db: Session = Depends(get_db)):
    role = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
    if role is None:
        raise NotFound("Role")
    bad = [x for x in body.permissions if x not in PERMISSIONS]
    if bad:
        raise AppError("unknown_permission", f"Unknown permissions: {bad}")
    if role.is_external and any(not x.startswith(("portal.", "driver.app", "sync.", "ca.", "ai.use")) for x in body.permissions):
        raise AppError("external_role", "External roles may only hold portal/app permissions")
    before = list(role.permissions)
    role.permissions = sorted(set(body.permissions))
    write_audit(db, actor=p, action="role.update", entity="role", entity_id=code, before={"permissions": before},
                after={"permissions": role.permissions}, reason=body.reason)
    return {"ok": True}


# ===================================================================== settings
@router.get("/settings")
def list_settings(p: Principal = Depends(require("settings.read")), db: Session = Depends(get_db)):
    out = []
    for key in sorted(CONFIG_DEFAULTS):
        latest = db.execute(select(ConfigValue).where(ConfigValue.key == key).order_by(ConfigValue.version.desc()).limit(1)).scalar_one_or_none()
        out.append({"key": key, "value": get_config(db, key), "version": latest.version if latest else 0,
                    "effective_from": latest.effective_from if latest else None, "is_default": latest is None})
    return out


@router.get("/settings/{key}/history")
def setting_history(key: str, p: Principal = Depends(require("settings.read")), db: Session = Depends(get_db)):
    return [{"version": r.version, "value": r.value, "effective_from": r.effective_from, "reason": r.reason,
             "changed_by": r.changed_by, "at": r.created_at}
            for r in db.execute(select(ConfigValue).where(ConfigValue.key == key).order_by(ConfigValue.version.desc())).scalars()]


class SettingIn(BaseModel):
    value: dict | list | str | int | float | bool | None
    reason: str = Field(min_length=3)
    effective_from: datetime | None = None


# Settings that only the Owner/Director may change (financial & safety policy)
OWNER_ONLY_SETTINGS = {"pricing.min_margin_pct", "pricing.max_discount_pct", "ptl.max_discount_pct", "credit.policy",
                       "approval.thresholds", "ai.budget"}


@router.put("/settings/{key}")
def update_setting(key: str, body: SettingIn, p: Principal = Depends(require("settings.write")), db: Session = Depends(get_db)):
    if key not in CONFIG_DEFAULTS:
        raise NotFound("Setting")
    if key in OWNER_ONLY_SETTINGS and "owner_director" not in p.roles:
        raise Forbidden("Only the Owner/Director can change this policy setting")
    row = set_config(db, key, body.value, p, body.reason, body.effective_from)
    return {"key": key, "version": row.version}


# ===================================================================== audit
@router.get("/audit")
def audit_list(entity: str | None = None, entity_id: str | None = None, limit: int = 200,
               p: Principal = Depends(require("audit.read")), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return [{"id": a.id, "at": a.at, "actor": a.actor_name, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "before": a.before, "after": a.after, "reason": a.reason}
            for a in db.execute(q).scalars()]


@router.get("/audit/verify")
def audit_verify(p: Principal = Depends(require("audit.read")), db: Session = Depends(get_db)):
    return verify_chain(db)


# ===================================================================== approvals
def _apr_out(a: ApprovalRequest) -> dict:
    return {"id": str(a.id), "code": a.code, "kind": a.kind, "entity": a.entity, "entity_id": a.entity_id, "title": a.title,
            "amount": a.amount, "payload": a.payload, "status": a.status, "required_permission": a.required_permission,
            "maker_id": a.maker_id, "maker_reason": a.maker_reason, "checker_id": a.checker_id,
            "checker_note": a.checker_note, "origin": a.origin, "created_at": a.created_at, "decided_at": a.decided_at}


@router.get("/approvals")
def approvals(status: str = "pending", p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(ApprovalRequest).where(ApprovalRequest.status == status).order_by(ApprovalRequest.created_at.desc())
    rows = db.execute(q).scalars()
    # Users see requests they can decide, plus their own
    return [_apr_out(a) for a in rows if p.can(a.required_permission) or a.maker_id == p.user_id or p.can("approvals.read")]


class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: uuid.UUID, body: DecideIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return _apr_out(decide_approval(db, p, approval_id, body.approve, body.note))


# ===================================================================== documents
def can_read_document(db: Session, p: Principal, d: Document) -> bool:
    if d.deleted_at:
        return False
    if p.can("documents.read") and p.is_internal:
        return True
    if p.customer_id:
        return d.visible_to_customer and d.customer_id == p.customer_id
    if p.driver_id and d.visible_to_driver:
        from app.modules.operations.access import driver_can_see_entity
        return driver_can_see_entity(db, p, d.entity, d.entity_id)
    if p.owner_id and d.entity == "vehicle":
        from app.modules.fleet.models import Vehicle
        v = db.get(Vehicle, uuid.UUID(d.entity_id))
        return bool(v and v.owner_id == p.owner_id)
    if p.vendor_id and d.entity == "vendor":
        return d.entity_id == str(p.vendor_id)
    return False


def doc_out(d: Document) -> dict:
    return {"id": str(d.id), "doc_type": d.doc_type, "entity": d.entity, "entity_id": d.entity_id, "filename": d.filename,
            "content_type": d.content_type, "size": d.size, "version": d.version, "valid_to": d.valid_to,
            "doc_number": d.doc_number, "review_status": d.review_status, "extracted": d.extracted,
            "extracted_label": "EXTRACTED - NOT VERIFIED" if d.extracted else None, "created_at": d.created_at,
            "legal_hold": d.legal_hold}


def save_document(db: Session, p: Principal, *, data: bytes, filename: str, content_type: str, doc_type: str, entity: str,
                  entity_id: str, customer_id=None, visible_to_customer=False, visible_to_driver=False, lat=None,
                  lng=None, captured_at=None, doc_number=None, valid_to=None) -> Document:
    storage.validate_upload(content_type, data)
    key, sha = storage.put(data)
    prev = db.execute(select(func.max(Document.version)).where(
        Document.entity == entity, Document.entity_id == entity_id, Document.doc_type == doc_type)).scalar() or 0
    d = Document(doc_type=doc_type, entity=entity, entity_id=entity_id, filename=storage.safe_filename(filename),
                 content_type=content_type, size=len(data), sha256=sha, storage_key=key, version=prev + 1,
                 uploaded_by=p.user_id, customer_id=customer_id, visible_to_customer=visible_to_customer,
                 visible_to_driver=visible_to_driver, captured_lat=lat, captured_lng=lng, captured_at=captured_at,
                 doc_number=doc_number, valid_to=valid_to)
    db.add(d)
    db.flush()
    write_audit(db, actor=p, action="document.upload", entity=entity, entity_id=entity_id,
                after={"document_id": str(d.id), "doc_type": doc_type, "sha256": sha})
    return d


@router.post("/documents")
async def upload_document(
    request: Request, file: UploadFile = File(...), doc_type: str = Form(...), entity: str = Form(...),
    entity_id: str = Form(...), doc_number: str | None = Form(None), valid_to: datetime | None = Form(None),
    lat: float | None = Form(None), lng: float | None = Form(None), captured_at: datetime | None = Form(None),
    p: Principal = Depends(current_principal), db: Session = Depends(get_db),
):
    from app.modules.operations.access import upload_allowed
    customer_id, vis_c, vis_d = upload_allowed(db, p, entity, entity_id, doc_type)
    data = await file.read()
    d = save_document(db, p, data=data, filename=file.filename or "upload", content_type=file.content_type or "",
                      doc_type=doc_type, entity=entity, entity_id=entity_id, customer_id=customer_id,
                      visible_to_customer=vis_c, visible_to_driver=vis_d, lat=lat, lng=lng, captured_at=captured_at,
                      doc_number=doc_number, valid_to=valid_to)
    if doc_type in ("expense_receipt", "fuel_receipt") and file.content_type == "text/plain":
        d.extracted = REGISTRY["ocr"].extract(data.decode(errors="ignore")).data
    return doc_out(d)


@router.get("/documents")
def list_documents(entity: str, entity_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    docs = db.execute(select(Document).where(Document.entity == entity, Document.entity_id == entity_id,
                                             Document.deleted_at.is_(None)).order_by(Document.created_at.desc())).scalars()
    return [doc_out(d) for d in docs if can_read_document(db, p, d)]


@router.get("/documents/{doc_id}/link")
def document_link(doc_id: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d or not can_read_document(db, p, d):
        raise NotFound("Document")
    write_audit(db, actor=p, action="document.access", entity="document", entity_id=d.id)
    return {"url": f"/api/v1/files/{d.id}?sig={sign(str(d.id), 300)}", "expires_in": 300}


@router.get("/files/{doc_id}")
def download(doc_id: uuid.UUID, sig: str, db: Session = Depends(get_db)):
    if not verify_signature(str(doc_id), sig):
        raise Forbidden("Link expired")
    d = db.get(Document, doc_id)
    if not d or d.deleted_at:
        raise NotFound("Document")
    return Response(content=storage.get(d.storage_key), media_type=d.content_type,
                    headers={"Content-Disposition": f'inline; filename="{d.filename}"', "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "private, no-store"})


class ReviewIn(BaseModel):
    status: str
    note: str | None = None


@router.post("/documents/{doc_id}/review")
def review_document(doc_id: uuid.UUID, body: ReviewIn, p: Principal = Depends(require("documents.write")),
                    db: Session = Depends(get_db)):
    d = get_or_404(db, Document, doc_id, "Document")
    if body.status not in ("verified", "rejected"):
        raise AppError("bad_status", "status must be verified or rejected")
    before = d.review_status
    d.review_status = body.status
    write_audit(db, actor=p, action="document.review", entity="document", entity_id=d.id,
                before={"review_status": before}, after={"review_status": body.status}, reason=body.note)
    return doc_out(d)


# ===================================================================== notifications
@router.get("/notifications/mine")
def my_notifications(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.execute(select(Notification).where(Notification.user_id == p.user_id, Notification.channel == "in_app")
                      .order_by(Notification.created_at.desc()).limit(100)).scalars()
    return [{"id": str(n.id), "body": n.body, "subject": n.subject, "entity": n.entity, "entity_id": n.entity_id,
             "read": n.read_at is not None, "at": n.created_at} for n in rows]


@router.post("/notifications/{nid}/read")
def mark_read(nid: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != p.user_id:
        raise NotFound("Notification")
    n.read_at = utcnow()
    return {"ok": True}


@router.get("/notifications")
def notification_log(status: str | None = None, p: Principal = Depends(require("settings.read")), db: Session = Depends(get_db)):
    q = select(Notification).order_by(Notification.created_at.desc()).limit(300)
    if status:
        q = q.where(Notification.status == status)
    return [{"id": str(n.id), "channel": n.channel, "template": n.template, "recipient": mask(n.recipient, 4),
             "status": n.status, "provider": n.provider, "error": n.error, "requires_approval": n.requires_approval,
             "at": n.created_at, "body": n.body if n.template not in ("login_otp", "pod_otp") else "(OTP hidden)"}
            for n in db.execute(q).scalars()]


@router.post("/notifications/{nid}/approve")
def approve_notification(nid: uuid.UUID, p: Principal = Depends(require_any("complaint.write", "settings.write")),
                         db: Session = Depends(get_db)):
    from app.core.notify import deliver
    n = get_or_404(db, Notification, nid, "Notification")
    if n.status != "held":
        raise AppError("not_held", "Only held messages need approval")
    n.approved_by, n.status = p.user_id, "queued"
    deliver(db, n)
    write_audit(db, actor=p, action="notification.approve", entity="notification", entity_id=n.id)
    return {"status": n.status}


# ===================================================================== integrations
@router.get("/integrations")
def integrations(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = {r.kind: r for r in db.execute(select(IntegrationProvider)).scalars()}
    out = []
    for kind, a in REGISTRY.items():
        r = rows.get(kind)
        out.append({"kind": kind, "adapter": a.name, "mode": a.mode, "live_verified": bool(r and r.verified_live_at),
                    "last_success_at": r.last_success_at if r else None, "last_error": r.last_error if r else None})
    for kind, note in STATUS_ONLY.items():
        out.append({"kind": kind, "adapter": "-", "mode": "MOCK", "live_verified": False, "note": note})
    return out


# ===================================================================== tasks / exceptions
def task_out(t: Task) -> dict:
    return {"id": str(t.id), "code": t.code, "kind": t.kind, "severity": t.severity, "title": t.title, "detail": t.detail,
            "source": t.source, "entity": t.entity, "entity_id": t.entity_id, "owner_role": t.owner_role,
            "assignee_id": t.assignee_id, "due_at": t.due_at, "status": t.status, "blocking": t.blocking,
            "escalated": t.escalated, "created_at": t.created_at, "closure_reason": t.closure_reason}


@router.get("/tasks")
def list_tasks(status: str = "open", entity: str | None = None, entity_id: str | None = None,
               p: Principal = Depends(require_any("controltower.read", "approvals.read")), db: Session = Depends(get_db)):
    q = select(Task).order_by(Task.created_at.desc()).limit(500)
    if status != "all":
        q = q.where(Task.status != "closed") if status == "open" else q.where(Task.status == status)
    if entity:
        q = q.where(Task.entity == entity)
    if entity_id:
        q = q.where(Task.entity_id == entity_id)
    return [task_out(t) for t in db.execute(q).scalars()]


class CloseTaskIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/tasks/{task_id}/close")
def close_task(task_id: uuid.UUID, body: CloseTaskIn, p: Principal = Depends(require_any("controltower.read")),
               db: Session = Depends(get_db)):
    t = get_or_404(db, Task, task_id, "Task")
    if t.blocking and t.severity == "critical" and "owner_director" not in p.roles and "operations_manager" not in p.roles:
        raise Forbidden("Critical blocking exceptions can be closed only by Operations Manager or Owner")
    t.status, t.closed_at, t.closure_reason = "closed", utcnow(), body.reason
    write_audit(db, actor=p, action="task.close", entity="task", entity_id=t.id, reason=body.reason)
    return task_out(t)


@router.post("/tasks/{task_id}/assign")
def assign_task(task_id: uuid.UUID, user_id: uuid.UUID, p: Principal = Depends(require("controltower.read")),
                db: Session = Depends(get_db)):
    t = get_or_404(db, Task, task_id, "Task")
    t.assignee_id, t.status = user_id, "in_progress"
    return task_out(t)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "time": utcnow(), "env": get_settings().env}
