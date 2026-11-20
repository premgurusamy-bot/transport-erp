from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Role, User, UserSession
from .permissions import has_permission


class AppError(HTTPException):
    def __init__(self, message: str, status: int = 400):
        super().__init__(status_code=status, detail=message)


@dataclass
class CurrentUser:
    id: int
    username: str
    full_name: str
    role: str
    permissions: list[str]
    customer_id: int | None = None
    driver_id: int | None = None
    branch_id: int | None = None
    session_id: str | None = None
    ip: str | None = None
    language: str = "en"
    extra: dict = field(default_factory=dict)

    def can(self, perm: str) -> bool:
        return has_permission(self.permissions, perm)


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token:
        raise AppError("Not signed in", 401)
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AppError("Session expired – please sign in again", 401)
    except jwt.PyJWTError:
        raise AppError("Invalid session", 401)
    sess = db.get(UserSession, payload.get("sid"))
    now = datetime.now(timezone.utc)
    if not sess or sess.revoked_at is not None or sess.expires_at < now:
        raise AppError("Session ended – please sign in again", 401)
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise AppError("User disabled", 401)
    role = db.get(Role, user.role_id)
    if now - sess.last_seen_at > timedelta(minutes=2):
        sess.last_seen_at = now
        db.commit()
    return CurrentUser(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=role.name if role else "",
        permissions=list(role.permissions or []) if role else [],
        customer_id=user.customer_id,
        driver_id=user.driver_id,
        branch_id=user.branch_id,
        session_id=sess.id,
        ip=_client_ip(request),
        language=user.language or "en",
    )


def require(*perms: str):
    """Dependency: user must have ALL listed permissions."""

    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        for p in perms:
            if not user.can(p):
                raise AppError(f"You do not have permission for this action ({p})", 403)
        return user

    return dep


def require_any(*perms: str):
    def dep(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(user.can(p) for p in perms):
            raise AppError("You do not have permission for this action", 403)
        return user

    return dep
