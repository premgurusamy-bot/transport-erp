"""Company, settings, users & roles, audit trail, login history, notifications, backup & restore."""
from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.audit import diff, jsonable, log, snapshot
from ..core.deps import AppError, CurrentUser, get_current_user, require
from ..core.permissions import all_permissions
from ..core.security import hash_password, password_problem
from ..core.validators import STATE_CODES, normalize, validate
from ..db import get_db
from ..integrations import channels, gst_portals
from ..models import AuditLog, BackupRecord, Company, InAppNotification, LoginHistory, NotificationLog, Role, User, UserSession
from ..services import files, people
from ..services import settings as app_settings
from .crud import REGISTRY, apply, serialize

router = APIRouter(prefix="/api", tags=["admin"])


# ------------------------------------------------------------------ company & settings

@router.get("/company")
def get_company(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    c = app_settings.company(db)
    db.commit()
    out = {col.name: jsonable(getattr(c, col.name)) for col in Company.__table__.columns}
    out["logo_url"] = "/api/company/logo" if c.logo_path else None
    return out


@router.get("/company/meta")
def company_meta(user: CurrentUser = Depends(get_current_user)):
    from .crud import Resource, field_meta

    return {"fields": field_meta(Resource(Company, "company"), user), "states": STATE_CODES}


@router.put("/company")
def put_company(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("company:write"))):
    from .crud import Resource

    c = app_settings.company(db)
    before = snapshot(c)
    apply(db, Resource(Company, "company"), c, data, user, False)
    if c.gstin and c.state_code and c.gstin[:2] != c.state_code:
        raise AppError("GSTIN state code does not match the company state code")
    if c.state_code and not c.state and c.state_code in STATE_CODES:
        c.state = STATE_CODES[c.state_code]
    b, a = diff(before, snapshot(c))
    log(db, user, "update", "company", c.id, b, a, ip=user.ip)
    db.commit()
    return get_company(db, user)


@router.post("/company/logo")
async def upload_logo(file: UploadFile = File(...), db: Session = Depends(get_db), user: CurrentUser = Depends(require("company:write"))):
    content = await file.read()
    if len(content) > 2 * 1024 * 1024 or not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8\xff")):
        raise AppError("Logo must be a PNG or JPEG under 2 MB")
    ext = ".png" if content.startswith(b"\x89PNG") else ".jpg"
    name = f"logo_{secrets.token_hex(6)}{ext}"
    path = get_settings().storage_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    c = app_settings.company(db)
    c.logo_path = name
    log(db, user, "update", "company", c.id, None, {"logo": name})
    db.commit()
    return {"ok": True}


@router.get("/company/logo")
def get_logo(db: Session = Depends(get_db)):
    c = app_settings.company(db)
    if not c.logo_path or not (get_settings().storage_dir / c.logo_path).exists():
        from fastapi.responses import Response

        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#0f4c81"/>'
               '<path d="M10 38h30V20H10zM40 26h8l6 7v5h-14z" fill="#fff"/><circle cx="20" cy="42" r="5" fill="#f5a623"/><circle cx="46" cy="42" r="5" fill="#f5a623"/></svg>')
        return Response(svg, media_type="image/svg+xml")
    return FileResponse(get_settings().storage_dir / c.logo_path)


@router.get("/settings")
def get_settings_all(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    data = app_settings.all_settings(db)
    if not user.can("settings:read"):
        data = {k: v for k, v in data.items() if k in ("language", "branding", "lr", "invoice")}
    return data


@router.put("/settings/{key}")
def put_setting(key: str, value: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    if key not in app_settings.DEFAULTS:
        raise AppError("Unknown settings section", 404)
    before = app_settings.get(db, key)
    if key == "accounts" and value.get("lock_before"):
        date.fromisoformat(str(value["lock_before"]))
    after = app_settings.set_(db, key, value, user.id)
    log(db, user, "update", "settings", key, before, after, ip=user.ip)
    db.commit()
    return after


@router.get("/integrations/status")
def integration_status(user: CurrentUser = Depends(get_current_user)):
    return {
        "email": channels.email_configured(), "whatsapp": channels.whatsapp_configured(), "sms": channels.sms_configured(),
        "einvoice_irp": gst_portals.irp_configured(), "ewaybill_api": gst_portals.ewb_configured(),
        "fastag": False, "gps": False,
        "notes": {
            "fastag": "No direct FASTag API is connected. Import statements (CSV/Excel) downloaded from your issuer bank's portal.",
            "gps": "Live tracking uses consented location pings from the driver app. A GPS vendor API can be added once credentials are available.",
        },
    }


# ------------------------------------------------------------------ users & roles

def _user_out(u: User, roles: dict) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "mobile": u.mobile, "role_id": u.role_id, "role": roles.get(u.role_id),
            "branch_id": u.branch_id, "customer_id": u.customer_id, "driver_id": u.driver_id, "language": u.language, "is_active": u.is_active,
            "totp_enabled": u.totp_enabled, "last_login_at": jsonable(u.last_login_at), "locked": bool(u.locked_until and u.locked_until > datetime.now(timezone.utc))}


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:read"))):
    roles = {r.id: r.name for r in db.query(Role)}
    return [_user_out(u, roles) for u in db.query(User).order_by(User.username)]


def _check_role_assignment(db: Session, user: CurrentUser, role_id: int) -> Role:
    role = db.get(Role, int(role_id or 0))
    if not role:
        raise AppError("Select a role")
    if "*" in (role.permissions or []) and "*" not in user.permissions:
        raise AppError("Only a Super Admin can create Super Admin / Owner users", 403)
    return role


@router.post("/users")
def create_user(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:write"))):
    username = (data.get("username") or "").strip().lower()
    if not username or not username.replace(".", "").replace("_", "").isalnum():
        raise AppError("Username may contain letters, digits, dot and underscore")
    if db.execute(select(User).where(User.username == username)).first():
        raise AppError("Username already exists", 409)
    problem = password_problem(data.get("password") or "")
    if problem:
        raise AppError(problem)
    role = _check_role_assignment(db, user, data.get("role_id"))
    if role.name == "Customer" and not data.get("customer_id"):
        raise AppError("Select the customer this portal user belongs to")
    if role.name == "Driver" and not data.get("driver_id"):
        raise AppError("Select the driver for this app user")
    for f, k in (("email", "email"), ("mobile", "mobile")):
        err = validate(k, normalize(k, data.get(f)))
        if err:
            raise AppError(err)
    u = User(username=username, full_name=data.get("full_name") or username, email=normalize("email", data.get("email")), mobile=normalize("mobile", data.get("mobile")),
             password_hash=hash_password(data["password"]), role_id=role.id, branch_id=data.get("branch_id") or None, customer_id=data.get("customer_id") or None,
             driver_id=data.get("driver_id") or None, language=data.get("language") or "en", must_change_password=bool(data.get("must_change_password", True)), created_by=user.id)
    db.add(u)
    db.flush()
    log(db, user, "create", "users", u.id, None, {"username": username, "role": role.name}, ip=user.ip)
    db.commit()
    return _user_out(u, {role.id: role.name})


@router.put("/users/{uid}")
def update_user(uid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:write"))):
    u = db.get(User, uid)
    if not u:
        raise AppError("Not found", 404)
    target_role = db.get(Role, u.role_id)
    if target_role and "*" in (target_role.permissions or []) and "*" not in user.permissions:
        raise AppError("Only a Super Admin can change this user", 403)
    before = {"role_id": u.role_id, "is_active": u.is_active, "full_name": u.full_name}
    if "role_id" in data:
        u.role_id = _check_role_assignment(db, user, data["role_id"]).id
    for f in ("full_name", "branch_id", "customer_id", "driver_id", "language"):
        if f in data:
            setattr(u, f, data[f] or None)
    for f in ("email", "mobile"):
        if f in data:
            v = normalize(f, data[f])
            err = validate(f, v)
            if err:
                raise AppError(err)
            setattr(u, f, v)
    if "is_active" in data:
        if uid == user.id and not data["is_active"]:
            raise AppError("You cannot disable your own account")
        u.is_active = bool(data["is_active"])
        if not u.is_active:
            for s in db.query(UserSession).filter(UserSession.user_id == u.id, UserSession.revoked_at.is_(None)):
                s.revoked_at = datetime.now(timezone.utc)
    if data.get("password"):
        problem = password_problem(data["password"])
        if problem:
            raise AppError(problem)
        u.password_hash = hash_password(data["password"])
        u.must_change_password = True
        u.locked_until = None
    if data.get("unlock"):
        u.locked_until, u.failed_logins = None, 0
    if data.get("reset_2fa"):
        u.totp_enabled, u.totp_secret = False, None
    log(db, user, "update", "users", u.id, before, {"role_id": u.role_id, "is_active": u.is_active, "full_name": u.full_name, "password_reset": bool(data.get("password"))}, ip=user.ip)
    db.commit()
    return _user_out(u, {r.id: r.name for r in db.query(Role)})


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if not (user.can("users:read") or user.can("settings:read")):
        raise AppError("Not permitted", 403)
    return [{"id": r.id, "name": r.name, "description": r.description, "permissions": r.permissions, "is_system": r.is_system} for r in db.query(Role).order_by(Role.id)]


@router.get("/roles/catalogue")
def perm_catalogue(user: CurrentUser = Depends(require("users:read"))):
    return all_permissions()


@router.post("/roles")
def create_role(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:write"))):
    perms = [p for p in data.get("permissions") or [] if p in all_permissions()]
    if not (data.get("name") or "").strip():
        raise AppError("Role name is required")
    r = Role(name=data["name"].strip(), description=data.get("description"), permissions=perms, is_system=False, created_by=user.id)
    db.add(r)
    db.flush()
    log(db, user, "create", "roles", r.id, None, {"name": r.name, "permissions": perms}, ip=user.ip)
    db.commit()
    return {"id": r.id}


@router.put("/roles/{rid}")
def update_role(rid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:write"))):
    r = db.get(Role, rid)
    if not r:
        raise AppError("Not found", 404)
    if "*" in (r.permissions or []):
        raise AppError("Full-access roles cannot be edited")
    before = {"permissions": r.permissions, "name": r.name}
    if "permissions" in data:
        r.permissions = [p for p in data["permissions"] if p in all_permissions()]
    if data.get("name") and not r.is_system:
        r.name = data["name"].strip()
    if "description" in data:
        r.description = data["description"]
    log(db, user, "update", "roles", r.id, before, {"permissions": r.permissions, "name": r.name}, ip=user.ip)
    db.commit()
    return {"ok": True}


@router.get("/audit")
def audit_trail(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("audit:read"))):
    p = request.query_params
    q = db.query(AuditLog)
    if p.get("entity"):
        q = q.filter(AuditLog.entity == p["entity"])
    if p.get("entity_id"):
        q = q.filter(AuditLog.entity_id == p["entity_id"])
    if p.get("username"):
        q = q.filter(AuditLog.username == p["username"])
    if p.get("action"):
        q = q.filter(AuditLog.action == p["action"])
    if p.get("from"):
        q = q.filter(AuditLog.at >= datetime.fromisoformat(p["from"]).replace(tzinfo=timezone.utc))
    if p.get("to"):
        q = q.filter(AuditLog.at < datetime.fromisoformat(p["to"] + "T23:59:59").replace(tzinfo=timezone.utc))
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).limit(min(int(p.get("limit") or 200), 1000)).offset(int(p.get("offset") or 0)).all()
    return {"total": total, "items": [{"id": a.id, "at": a.at, "username": a.username, "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "before": a.before, "after": a.after, "reason": a.reason, "ip": a.ip} for a in rows]}


@router.get("/login-history")
def login_history(db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:read"))):
    return [{"at": h.at, "username": h.username, "success": h.success, "reason": h.reason, "ip": h.ip, "user_agent": h.user_agent} for h in db.query(LoginHistory).order_by(LoginHistory.id.desc()).limit(500)]


@router.get("/sessions")
def all_sessions(db: Session = Depends(get_db), user: CurrentUser = Depends(require("users:read"))):
    users = {u.id: u.username for u in db.query(User)}
    rows = db.query(UserSession).filter(UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(timezone.utc)).order_by(UserSession.last_seen_at.desc())
    return [{"id": s.id, "username": users.get(s.user_id), "created_at": s.created_at, "last_seen_at": s.last_seen_at, "ip": s.ip, "user_agent": s.user_agent} for s in rows]


# ------------------------------------------------------------------ notifications & alerts

@router.get("/notifications")
def my_notifications(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    if user.customer_id or user.driver_id:
        return []
    rows = db.query(InAppNotification).filter(or_(InAppNotification.user_id.is_(None), InAppNotification.user_id == user.id)).order_by(InAppNotification.id.desc()).limit(100).all()
    return [{"id": n.id, "at": n.at, "title": n.title, "body": n.body, "link": n.link, "severity": n.severity, "read": user.id in (n.read_by or [])} for n in rows]


@router.post("/notifications/read")
def mark_read(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    ids = data.get("ids")
    q = db.query(InAppNotification)
    if ids:
        q = q.filter(InAppNotification.id.in_(ids))
    for n in q:
        if user.id not in (n.read_by or []):
            n.read_by = list(n.read_by or []) + [user.id]
    db.commit()
    return {"ok": True}


@router.get("/notifications/log")
def notification_log(db: Session = Depends(get_db), user: CurrentUser = Depends(require("notifications:read"))):
    return [{"at": n.at, "event": n.event, "channel": n.channel, "recipient": n.recipient, "status": n.status, "error": n.error, "subject": n.subject, "body": n.body} for n in db.query(NotificationLog).order_by(NotificationLog.id.desc()).limit(500)]


@router.post("/notifications/test")
def test_channel(data: dict, user: CurrentUser = Depends(require("settings:write"))):
    ch, to = data.get("channel"), data.get("to")
    if not to:
        raise AppError("Enter a recipient")
    if ch == "email":
        status, err = channels.send_email(to, "SVL ERP test message", "This is a test message from the ERP.")
    elif ch == "whatsapp":
        status, err = channels.send_whatsapp(to, "This is a test message from the ERP.", data.get("template"))
    elif ch == "sms":
        status, err = channels.send_sms(to, "SVL ERP test message")
    else:
        raise AppError("Unknown channel")
    return {"status": status, "error": err}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: CurrentUser = Depends(require("dashboard:read"))):
    return jsonable(people.current_alerts(db))


@router.post("/alerts/run")
def alerts_run(db: Session = Depends(get_db), user: CurrentUser = Depends(require("dashboard:read"))):
    n = people.run_alerts(db)
    db.commit()
    return {"created": n}


# ------------------------------------------------------------------ backup

@router.get("/backups")
def list_backups(db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:read"))):
    return [{"id": b.id, "at": b.at, "kind": b.kind, "file_name": b.file_name, "size_bytes": b.size_bytes, "sha256": b.sha256, "status": b.status, "tables": b.tables, "rows": b.rows, "pg_dump_file": b.pg_dump_file, "note": b.note} for b in db.query(BackupRecord).order_by(BackupRecord.id.desc()).limit(200)]


@router.post("/backups")
def make_backup(data: dict | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:write"))):
    rec = files.create_backup(db, user, "manual", include_files=(data or {}).get("include_files", True), note=(data or {}).get("note"))
    log(db, user, "backup", "backup", rec.id, None, {"file": rec.file_name, "status": rec.status})
    db.commit()
    return {"id": rec.id, "file_name": rec.file_name, "status": rec.status, "rows": rec.rows, "pg_dump_file": rec.pg_dump_file}


@router.get("/backups/{bid}/download")
def download_backup(bid: int, kind: str = "zip", db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:write"))):
    b = db.get(BackupRecord, bid)
    if not b:
        raise AppError("Not found", 404)
    name = b.pg_dump_file if kind == "dump" else b.file_name
    if not name or not (files.backups_dir() / name).exists():
        raise AppError("Backup file is not available on this server", 404)
    log(db, user, "download", "backup", b.id)
    db.commit()
    return FileResponse(files.backups_dir() / name, filename=name)


@router.post("/backups/{bid}/verify")
def verify(bid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:read"))):
    b = db.get(BackupRecord, bid)
    if not b:
        raise AppError("Not found", 404)
    ok, problems = files.verify_backup(files.backups_dir() / b.file_name)
    b.status = "Verified" if ok else "Corrupted"
    db.commit()
    return {"ok": ok, "problems": problems}


@router.post("/backups/restore")
async def restore(confirm: str = Form(...), backup_id: int | None = Form(None), keep_users: bool = Form(True), file: UploadFile | None = File(None),
                  db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:restore"))):
    if confirm != "RESTORE":
        raise AppError("Type RESTORE to confirm")
    if file is not None:
        content = await file.read()
        path = files.backups_dir() / f"UPLOADED_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{Path(file.filename or 'backup.zip').name}"
        path.write_bytes(content)
    elif backup_id:
        b = db.get(BackupRecord, backup_id)
        if not b:
            raise AppError("Backup not found", 404)
        path = files.backups_dir() / b.file_name
    else:
        raise AppError("Choose a backup or upload a backup file")
    result = files.restore_backup(db, user, path, keep_users=keep_users)
    return result


@router.post("/system/factory-reset")
def factory_reset(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:restore"))):
    """Delete all business data (e.g. after training with sample data). Users, company profile and settings are kept."""
    from ..core.security import verify_password
    from ..models import User

    if (data or {}).get("confirm") != "RESET":
        raise AppError("Type RESET to confirm")
    me = db.get(User, user.id)
    if not me or not verify_password(str((data or {}).get("password") or ""), me.password_hash):
        raise AppError("Your password is not correct", 403)
    return files.factory_reset(db, user)


# ------------------------------------------------------------------ document layouts

@router.get("/layouts")
def get_layouts(db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:read"))):
    from ..services import layouts

    return {"layouts": layouts.get(db), "defaults": layouts.DEFAULTS, "documents": layouts.DOCS}


@router.put("/layouts/{doc}")
def put_layout(doc: str, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    from ..services import layouts

    before = layouts.get(db, doc)
    after = layouts.save(db, doc, data, user.id)
    b, a = diff(jsonable(before), jsonable(after))
    log(db, user, "update", "layouts", doc, b, a, ip=user.ip)
    db.commit()
    return after


@router.post("/layouts/{doc}/reset")
def reset_layout(doc: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    from ..services import layouts

    if doc not in layouts.DEFAULTS:
        raise AppError("Unknown document type", 404)
    out = layouts.reset(db, doc, user.id)
    log(db, user, "reset", "layouts", doc, ip=user.ip)
    db.commit()
    return out


@router.post("/layouts/{doc}/preview")
def preview_layout(doc: str, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:read"))):
    """PDF with the (unsaved) layout, using the latest real document – or a clearly marked sample."""
    from fastapi.responses import Response

    from ..services import layouts, pdf
    from ..services.samples import sample_invoice, sample_lr

    draft = layouts._merge(layouts.DEFAULTS[doc], layouts.validate(doc, data)) | {"_assets": layouts.get(db)["_assets"]} if doc in layouts.DEFAULTS else None
    if draft is None:
        raise AppError("Unknown document type", 404)
    company = app_settings.company(db)
    if doc == "invoice":
        inv, cust, lines, bank, treat = sample_invoice(db)
        out = pdf.invoice_pdf(inv, company, cust, lines, bank, treat, None, draft)
    elif doc in ("lr", "thermal"):
        lr, cust, items, points = sample_lr(db)
        out = pdf.lr_pdf(lr, company, cust, items, points, None, "thermal" if doc == "thermal" else "A4", draft if doc == "lr" else None, draft if doc == "thermal" else None)
    else:
        from ..services.reports import trial_balance_report
        from ..core.numbering import financial_year, fy_bounds

        s, e = fy_bounds(financial_year(date.today()))
        out = pdf.report_pdf(trial_balance_report(db, s, date.today()), company, draft)
    db.rollback()
    return Response(out, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="preview-{doc}.pdf"'})


@router.post("/layouts/assets/{name}")
async def upload_layout_asset(name: str, file: UploadFile = File(...), db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    from ..services import layouts

    if name not in ("signature", "stamp"):
        raise AppError("Unknown image", 404)
    content = await file.read()
    if len(content) > 2 * 1024 * 1024 or not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8\xff")):
        raise AppError("Use a PNG (transparent background works best) or JPEG under 2 MB")
    ext = ".png" if content.startswith(b"\x89PNG") else ".jpg"
    fname = f"{name}_{secrets.token_hex(6)}{ext}"
    (get_settings().storage_dir).mkdir(parents=True, exist_ok=True)
    (get_settings().storage_dir / fname).write_bytes(content)
    layouts.set_asset(db, name, fname, user.id)
    log(db, user, "upload", "layouts", name, None, {"file": fname}, ip=user.ip)
    db.commit()
    return {"ok": True}


@router.delete("/layouts/assets/{name}")
def delete_layout_asset(name: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:write"))):
    from ..services import layouts

    layouts.set_asset(db, name, None, user.id)
    log(db, user, "delete", "layouts", name, ip=user.ip)
    db.commit()
    return {"ok": True}


@router.get("/layouts/assets/{name}")
def get_layout_asset(name: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("settings:read"))):
    from ..services import layouts

    f = layouts.get(db)["_assets"].get(name)
    if not f or not (get_settings().storage_dir / f).exists():
        raise AppError("Not uploaded", 404)
    return FileResponse(get_settings().storage_dir / f)
