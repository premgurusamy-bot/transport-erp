"""First-run setup (company + first administrator) and the licence screen."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.audit import log
from ..core.deps import AppError, CurrentUser, _client_ip, get_current_user, require
from ..core.security import create_token, hash_password, new_session_id, password_problem
from ..core.validators import STATE_CODES, normalize, validate
from ..db import get_db
from ..models import LoginHistory, Role, User, UserSession
from ..services import licensing
from ..services import settings as app_settings

router = APIRouter(tags=["setup"])
PLACEHOLDER_COMPANY = "My Company"


def setup_needed(db: Session) -> bool:
    return db.execute(select(User.id).limit(1)).first() is None


def _setup_allowed_here(request: Request) -> bool:
    """Setup is done on the computer the ERP runs on (the desktop app opens it there). Behind a proxy or from another
    device it is refused unless ALLOW_REMOTE_SETUP=true, so nobody on the network can claim a fresh installation."""
    if os.environ.get("ALLOW_REMOTE_SETUP", "").lower() == "true":
        return True
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost") and not request.headers.get("x-forwarded-for")


@router.get("/api/setup/status")
def setup_status(request: Request, db: Session = Depends(get_db)):
    """Public: what the sign-in page needs (no business data)."""
    c = app_settings.company(db)
    name = (c.trade_name or c.legal_name or "").strip()
    needed = setup_needed(db)
    out = {"setup_needed": needed, "setup_allowed_here": _setup_allowed_here(request), "company": "" if name == PLACEHOLDER_COMPANY else name, "has_logo": bool(c.logo_path)}
    if needed:
        out["states"] = STATE_CODES
    return out


@router.post("/api/setup")
def do_setup(data: dict, request: Request, db: Session = Depends(get_db)):
    if not setup_needed(db):
        raise AppError("This installation is already set up. Sign in instead.", 409)
    if not _setup_allowed_here(request):
        raise AppError("Finish the first-time setup on the main ERP computer.", 403)
    comp, adm = data.get("company") or {}, data.get("admin") or {}
    legal = (comp.get("legal_name") or "").strip()
    if len(legal) < 2:
        raise AppError("Enter the company name")
    username = (adm.get("username") or "").strip().lower()
    if not username or not username.replace(".", "").replace("_", "").isalnum():
        raise AppError("Username may contain letters, digits, dot and underscore")
    if not (adm.get("full_name") or "").strip():
        raise AppError("Enter the administrator's name")
    problem = password_problem(adm.get("password") or "")
    if problem:
        raise AppError(problem)
    c = app_settings.company(db)
    c.legal_name = legal
    c.trade_name = (comp.get("trade_name") or "").strip() or legal
    for f in ("gstin", "pan", "email", "pincode"):
        v = normalize(f, comp.get(f))
        err = validate(f, v) if v else None
        if err:
            raise AppError(err)
        setattr(c, f, v or None)
    for f in ("address", "city", "phone", "state_code"):
        setattr(c, f, (comp.get(f) or "").strip() or None)
    if c.state_code:
        if c.state_code not in STATE_CODES:
            raise AppError("Select the state")
        c.state = STATE_CODES[c.state_code]
    if c.gstin and c.state_code and c.gstin[:2] != c.state_code:
        raise AppError("GSTIN state code does not match the company state")
    role = db.execute(select(Role).where(Role.name == "Super Admin")).scalar_one()
    u = User(username=username, full_name=adm["full_name"].strip(), email=normalize("email", adm.get("email")) or c.email, password_hash=hash_password(adm["password"]),
             role_id=role.id, must_change_password=False)
    db.add(u)
    db.flush()
    licensing.status(db, fresh=True)  # records the first start of the trial
    actor = CurrentUser(id=u.id, username=u.username, full_name=u.full_name, role=role.name, permissions=["*"], ip=_client_ip(request))
    log(db, actor, "setup", "system", None, None, {"company": legal, "admin": username}, ip=actor.ip)
    sample = None
    if data.get("sample_data"):
        from ..services import sample_data

        sample = sample_data.build(db)
    now = datetime.now(timezone.utc)
    sid, minutes = new_session_id(), get_settings().access_token_minutes
    ua = (request.headers.get("user-agent") or "")[:300]
    u.last_login_at = now
    db.add(UserSession(id=sid, user_id=u.id, created_at=now, last_seen_at=now, expires_at=now + timedelta(minutes=minutes), ip=actor.ip, user_agent=ua))
    db.add(LoginHistory(username=username, user_id=u.id, ip=actor.ip, user_agent=ua, success=True, reason="first-run setup"))
    db.commit()
    from .auth import profile

    return {"token": create_token(u.id, sid, minutes), "user": profile(u, role), "sample": bool(sample)}


@router.get("/api/licence")
def get_licence(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    st = dict(licensing.status(db))
    if not user.can("settings:write"):
        st.pop("install_id", None)
    return st


@router.post("/api/licence/activate")
def activate_licence(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    try:
        lic = licensing.activate(db, str((data or {}).get("key") or ""))
    except ValueError as e:
        raise AppError(str(e)) from None
    log(db, user, "licence_activate", "system", None, None, {"licence_id": lic["id"], "to": lic["to"], "plan": lic["plan"], "until": lic.get("until"), "users": lic.get("users")}, ip=user.ip)
    db.commit()
    return licensing.status(db, fresh=True)
