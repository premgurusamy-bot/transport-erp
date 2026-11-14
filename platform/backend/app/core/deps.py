"""Request dependencies: DB session, authenticated principal, permission checks and record scoping."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, utcnow
from app.core.errors import Forbidden, Unauthorized
from app.core.security import token_hash
from app.modules.platform.models import Session as UserSession
from app.modules.platform.models import TempDriverAccess, User


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@dataclass
class Principal:
    user_id: uuid.UUID
    name: str
    roles: set[str]
    permissions: set[str]
    session_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    scope_trip_id: uuid.UUID | None = None
    ip: str | None = None
    app: str = "web"
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> uuid.UUID:
        return self.user_id

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def is_internal(self) -> bool:
        return not (self.customer_id or self.owner_id or self.vendor_id or self.scope_trip_id or "ca_auditor" in self.roles)


def principal_for_user(user: User, session: UserSession | None = None, ip: str | None = None) -> Principal:
    perms: set[str] = set()
    for r in user.roles:
        perms.update(r.permissions or [])
    return Principal(
        user_id=user.id,
        name=user.name,
        roles={r.code for r in user.roles},
        permissions=perms,
        session_id=session.id if session else None,
        customer_id=user.customer_id,
        owner_id=user.owner_id,
        vendor_id=user.vendor_id,
        driver_id=user.driver_id,
        scope_trip_id=session.scope_trip_id if session else None,
        ip=ip,
    )


def current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise Unauthorized()
    th = token_hash(auth[7:].strip())
    sess = db.execute(select(UserSession).where(UserSession.token_hash == th)).scalar_one_or_none()
    now = utcnow()
    if not sess or sess.revoked_at or sess.expires_at < now:
        raise Unauthorized("Session expired. Please sign in again.")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise Unauthorized("Account disabled")
    if user.access_valid_to and user.access_valid_to < now:
        raise Unauthorized("Access period has ended")
    if user.access_valid_from and user.access_valid_from > now:
        raise Unauthorized("Access period has not started")
    if sess.scope_trip_id:
        grant = db.execute(
            select(TempDriverAccess).where(
                TempDriverAccess.trip_id == sess.scope_trip_id, TempDriverAccess.driver_id == user.driver_id
            )
        ).scalars().first()
        if not grant or grant.revoked_at or grant.expires_at < now:
            raise Unauthorized("Trip access has ended")
    p = principal_for_user(user, sess, request.client.host if request.client else None)
    p.app = request.headers.get("x-grl-app", "web")
    return p


def require(*perms: str):
    """Dependency: principal must hold ALL listed permissions."""

    def _dep(p: Principal = Depends(current_principal)) -> Principal:
        missing = [x for x in perms if x not in p.permissions]
        if missing:
            raise Forbidden(f"Missing permission: {', '.join(missing)}")
        return p

    return _dep


def require_any(*perms: str):
    def _dep(p: Principal = Depends(current_principal)) -> Principal:
        if not any(x in p.permissions for x in perms):
            raise Forbidden(f"Requires one of: {', '.join(perms)}")
        return p

    return _dep
