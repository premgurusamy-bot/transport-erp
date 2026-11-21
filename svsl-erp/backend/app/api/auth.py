from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta, timezone

import qrcode
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.audit import log
from ..core.deps import AppError, CurrentUser, _client_ip, get_current_user
from ..core.permissions import all_permissions
from ..core.security import (
    create_token, hash_password, new_session_id, new_totp_secret, password_problem, totp_uri, verify_password, verify_totp,
)
from ..db import get_db
from ..models import LoginHistory, Role, User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])
MAX_FAILS, LOCK_MINUTES = 5, 15


def profile(user: User, role: Role | None) -> dict:
    return {"id": user.id, "username": user.username, "full_name": user.full_name, "email": user.email, "role": role.name if role else None,
            "permissions": role.permissions if role else [], "customer_id": user.customer_id, "driver_id": user.driver_id, "branch_id": user.branch_id,
            "language": user.language or "en", "totp_enabled": user.totp_enabled, "must_change_password": user.must_change_password}


@router.post("/login")
def login(data: dict, request: Request, db: Session = Depends(get_db)):
    username = (data.get("username") or "").strip().lower()
    password = data.get("password") or ""
    ip, ua = _client_ip(request), (request.headers.get("user-agent") or "")[:300]
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    def fail(reason: str, msg: str = "Invalid username or password", status: int = 401):
        db.add(LoginHistory(username=username, user_id=user.id if user else None, ip=ip, user_agent=ua, success=False, reason=reason))
        db.commit()
        raise AppError(msg, status)

    if not user:
        fail("unknown user")
    if not user.is_active:
        fail("disabled", "This account is disabled")
    if user.locked_until and user.locked_until > now:
        fail("locked", f"Too many failed attempts. Try again after {user.locked_until.astimezone().strftime('%H:%M')}", 423)
    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= MAX_FAILS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        fail("bad password")
    if user.totp_enabled:
        code = str(data.get("otp") or "").strip()
        if not code:
            raise AppError("OTP_REQUIRED", 401)
        if not verify_totp(user.totp_secret, code):
            fail("bad otp", "Invalid authenticator code")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    sid = new_session_id()
    minutes = get_settings().access_token_minutes
    db.add(UserSession(id=sid, user_id=user.id, created_at=now, last_seen_at=now, expires_at=now + timedelta(minutes=minutes), ip=ip, user_agent=ua))
    db.add(LoginHistory(username=username, user_id=user.id, ip=ip, user_agent=ua, success=True))
    db.commit()
    role = db.get(Role, user.role_id)
    return {"token": create_token(user.id, sid, minutes), "user": profile(user, role)}


@router.post("/logout")
def logout(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    s = db.get(UserSession, user.session_id)
    if s:
        s.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True}


@router.get("/me")
def me(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    u = db.get(User, user.id)
    return profile(u, db.get(Role, u.role_id))


@router.post("/download-link")
def download_link(data: dict, user: CurrentUser = Depends(get_current_user)):
    """Short-lived (2 minute) link for one GET path, for app download managers that cannot send headers."""
    import jwt as pyjwt

    path = str(data.get("path") or "")
    path_only = path.split("?", 1)[0]
    if not path_only.startswith("/api/") or ".." in path_only:
        raise AppError("Invalid path")
    now = datetime.now(timezone.utc)
    tok = pyjwt.encode({"sub": str(user.id), "sid": user.session_id, "typ": "dl", "path": path_only, "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=2)).timestamp())}, get_settings().secret_key, algorithm="HS256")
    sep = "&" if "?" in path else "?"
    return {"url": f"{path}{sep}dlt={tok}"}


@router.get("/permissions")
def permissions(user: CurrentUser = Depends(get_current_user)):
    return all_permissions()


@router.post("/change-password")
def change_password(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    u = db.get(User, user.id)
    if not verify_password(data.get("old_password") or "", u.password_hash):
        raise AppError("Current password is wrong")
    problem = password_problem(data.get("new_password") or "")
    if problem:
        raise AppError(problem)
    u.password_hash = hash_password(data["new_password"])
    u.must_change_password = False
    for s in db.query(UserSession).filter(UserSession.user_id == u.id, UserSession.id != user.session_id, UserSession.revoked_at.is_(None)):
        s.revoked_at = datetime.now(timezone.utc)
    log(db, user, "change_password", "users", u.id)
    db.commit()
    return {"ok": True}


@router.post("/2fa/setup")
def twofa_setup(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    u = db.get(User, user.id)
    if u.totp_enabled:
        raise AppError("Two-factor authentication is already enabled")
    u.totp_secret = new_totp_secret()
    db.commit()
    uri = totp_uri(u.totp_secret, u.username)
    buf = io.BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return {"secret": u.totp_secret, "uri": uri, "qr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}


@router.post("/2fa/enable")
def twofa_enable(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    u = db.get(User, user.id)
    if not u.totp_secret or not verify_totp(u.totp_secret, data.get("code") or ""):
        raise AppError("Code does not match – check the time on your phone and try again")
    u.totp_enabled = True
    log(db, user, "enable_2fa", "users", u.id)
    db.commit()
    return {"ok": True}


@router.post("/2fa/disable")
def twofa_disable(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    u = db.get(User, user.id)
    if not verify_password(data.get("password") or "", u.password_hash):
        raise AppError("Password is wrong")
    u.totp_enabled, u.totp_secret = False, None
    log(db, user, "disable_2fa", "users", u.id)
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def my_sessions(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    rows = db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(timezone.utc)).order_by(UserSession.last_seen_at.desc())
    return [{"id": s.id[:8], "full_id": s.id, "current": s.id == user.session_id, "created_at": s.created_at, "last_seen_at": s.last_seen_at, "ip": s.ip, "user_agent": s.user_agent} for s in rows]


@router.delete("/sessions/{sid}")
def end_session(sid: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    s = db.get(UserSession, sid)
    if not s or (s.user_id != user.id and not user.can("users:write")):
        raise AppError("Session not found", 404)
    s.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}
