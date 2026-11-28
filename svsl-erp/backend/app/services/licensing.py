"""Licensing: a free trial, then licence keys issued by the software provider.

A licence key is a small signed document (Ed25519). Only the provider holds the private signing key; the app holds the
public key below and can check a key offline, so no internet connection is needed. A key names the customer, the
installation it is for (the "installation ID" shown on the Licence screen, or "*" for any installation), the plan,
the period and the number of staff users.

States
  trial          no key yet; full use for TRIAL_DAYS from the first start on this computer
  active         a valid key
  grace          the key's period ended less than GRACE_DAYS ago; full use, with a warning
  expired / trial_expired / clock_error
                 read-only: everything can be viewed, searched, printed, exported and backed up, but nothing can be
                 added or changed until a key is entered

The first-start date, the last time the app was used and the key are kept in a small file outside the database
(LICENCE_DIR) and also in the database, so deleting either one does not restart the trial. A computer clock set
back by more than two days is treated as a fault until it is corrected.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

TRIAL_DAYS = 15
GRACE_DAYS = 7
KEY_PREFIX = "APRIME1"
# key id -> raw Ed25519 public key (base64). Add a new id to rotate the provider's signing key; old keys keep working.
PUBLIC_KEYS = {"k1": "2F0OOhSXWlz/cGuu+Wj5DucuP4PHYfc864ot7oUBLgU="}
PLANS = {
    "trial": "Trial extension", "monthly": "Monthly subscription", "quarterly": "Quarterly subscription", "half_yearly": "Half-yearly subscription",
    "yearly": "Yearly subscription", "subscription": "Subscription", "perpetual": "Lifetime licence",
}
READ_ONLY_STATES = {"expired", "trial_expired", "clock_error"}
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "status": None}


# ------------------------------------------------------------------ installation identity and local file

def licence_dir() -> Path:
    from ..config import get_settings

    return Path(os.environ.get("LICENCE_DIR") or (get_settings().storage_dir.parent / "licence"))


def _machine_guid() -> str:
    if platform.system() == "Windows":
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return str(winreg.QueryValueEx(k, "MachineGuid")[0])
        except OSError:
            return ""
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            v = Path(p).read_text().strip()
            if v:
                return v
        except OSError:
            pass
    return ""


def _fmt_id(raw: str) -> str:
    h = hashlib.sha256(("aprime-erp:" + raw).encode()).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def _marker_file() -> Path:
    return licence_dir() / "aprime-install.json"


def _read_marker() -> dict:
    try:
        return json.loads(_marker_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_marker(m: dict) -> None:
    try:
        f = _marker_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, indent=1), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        pass  # read-only location: the database copy is still used


def install_id() -> str:
    """Stable ID of this installation: from APRIME_INSTALL_ID (cloud servers), else the computer's own ID."""
    env = os.environ.get("APRIME_INSTALL_ID", "").strip()
    if env:
        return _fmt_id("env:" + env)
    g = _machine_guid()
    if g:
        return _fmt_id("machine:" + g)
    m = _read_marker()
    if not m.get("random_id"):
        m["random_id"] = uuid.uuid4().hex
        _write_marker(m)
    return _fmt_id("random:" + m["random_id"])


# ------------------------------------------------------------------ keys

def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def parse_key(key: str) -> dict:
    """Check a licence key's signature and return its contents. Raises ValueError when the key is not genuine."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    key = "".join((key or "").split())  # keys pasted from e-mail / WhatsApp may be wrapped
    parts = key.split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise ValueError("This is not an A Prime Transport ERP licence key")
    try:
        data = json.loads(_b64d(parts[1]))
        sig = _b64d(parts[2])
    except (ValueError, json.JSONDecodeError):
        raise ValueError("The licence key is damaged – copy it again in full") from None
    pub = PUBLIC_KEYS.get(str(data.get("k")))
    if not pub:
        raise ValueError("The licence key was signed with an unknown key")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(sig, f"{parts[0]}.{parts[1]}".encode())
    except InvalidSignature:
        raise ValueError("The licence key is not genuine or was changed") from None
    for f in ("id", "to", "iid", "plan"):
        if not data.get(f):
            raise ValueError("The licence key is incomplete")
    data["key"] = key
    return data


def _fp(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ state kept in the database and the local file

def _db_state(db: Session) -> dict:
    from ..models import AppSetting

    row = db.get(AppSetting, "licence")
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def _save_db_state(db: Session, value: dict) -> None:
    from ..models import AppSetting

    row = db.get(AppSetting, "licence")
    if row is None:
        db.add(AppSetting(key="licence", value=value))
    else:
        row.value = value
    db.flush()


def _today() -> date:
    return datetime.now().date()


def _merge(db: Session, write: bool) -> dict:
    """Bring the database copy and the local file in line; the local file wins for the key."""
    m, d = _read_marker(), _db_state(db)
    firsts = [x for x in (m.get("first_seen"), d.get("first_seen")) if x]
    first = min(firsts) if firsts else _today().isoformat()
    lasts = [x for x in (m.get("last_seen"), d.get("last_seen")) if x]
    prev_last = max(lasts) if lasts else None
    key = m["key"] if "key" in m else d.get("key")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    last = max(prev_last, now) if prev_last else now
    stale = not prev_last or (datetime.fromisoformat(last) - datetime.fromisoformat(prev_last)).total_seconds() > 3600  # write hourly at most
    if write:
        if stale or m.get("first_seen") != first or "key" not in m or m.get("key") != key:
            m.update(first_seen=first, key=key, last_seen=last)
            _write_marker(m)
        if stale or d.get("first_seen") != first or d.get("key") != key:
            d.update(first_seen=first, key=key, last_seen=last)
            _save_db_state(db, d)
    return {"first_seen": first, "key": key, "_last_before": prev_last}


def compute(db: Session, write: bool = True) -> dict:
    marker = _merge(db, write)
    iid = install_id()
    today = _today()
    out: dict = {"install_id": iid, "trial_days": TRIAL_DAYS, "grace_days": GRACE_DAYS, "first_seen": marker["first_seen"], "max_users": 0,
                 "licensed_to": None, "licence_id": None, "plan": None, "plan_label": None, "valid_from": None, "valid_until": None, "key_error": None}
    last = marker.get("_last_before")
    if last and datetime.now(timezone.utc) < datetime.fromisoformat(last) - timedelta(days=2):
        out.update(state="clock_error", read_only=True, days_left=None,
                   message="The computer's date is earlier than the last time A Prime Transport ERP was used. Correct the date and time in Windows settings, then restart the app.")
        return out
    lic = None
    if marker.get("key"):
        try:
            lic = parse_key(marker["key"])
            if lic["iid"] not in ("*", iid):
                out["key_error"] = "The saved licence key is for another installation."
                lic = None
        except ValueError as e:
            out["key_error"] = str(e)
    if lic:
        until = date.fromisoformat(lic["until"]) if lic.get("until") else None
        out.update(licensed_to=lic["to"], licence_id=lic["id"], plan=lic["plan"], plan_label=PLANS.get(lic["plan"], lic["plan"]), valid_from=lic.get("from"),
                   valid_until=lic.get("until"), max_users=int(lic.get("users") or 0))
        if until is None:
            out.update(state="active", read_only=False, days_left=None, message=f"Licensed to {lic['to']} – lifetime licence.")
        elif today <= until:
            left = (until - today).days
            out.update(state="active", read_only=False, days_left=left,
                       message=f"Licensed to {lic['to']} until {until.strftime('%d %b %Y')}." + (f" Renew within {left} day{'s' if left != 1 else ''}." if left <= 15 else ""))
        elif (today - until).days <= GRACE_DAYS:
            left = GRACE_DAYS - (today - until).days
            out.update(state="grace", read_only=False, days_left=left,
                       message=f"Your {out['plan_label'].lower()} ended on {until.strftime('%d %b %Y')}. Renew within {left} day{'s' if left != 1 else ''} – after that the ERP becomes read-only.")
        else:
            out.update(state="expired", read_only=True, days_left=0,
                       message=f"Your {out['plan_label'].lower()} ended on {until.strftime('%d %b %Y')}. The ERP is read-only until a renewal key is entered.")
        return out
    start = date.fromisoformat(marker["first_seen"])
    ends = start + timedelta(days=TRIAL_DAYS)
    left = (ends - today).days
    out["trial_ends"] = ends.isoformat()
    if left > 0:
        out.update(state="trial", read_only=False, days_left=left, message=f"Free trial – {left} day{'s' if left != 1 else ''} left. Enter a licence key before {ends.strftime('%d %b %Y')} to keep working.")
    else:
        out.update(state="trial_expired", read_only=True, days_left=0, message="The free trial has ended. The ERP is read-only until a licence key is entered.")
    return out


def status(db: Session | None = None, fresh: bool = False) -> dict:
    """Cached for a minute (it is checked on every change request)."""
    with _lock:
        if not fresh and _cache["status"] and time.monotonic() - _cache["at"] < 60:
            return _cache["status"]
    own = db is None
    if own:
        from ..db import SessionLocal

        db = SessionLocal()
    try:
        st = compute(db)
        db.commit()
    finally:
        if own:
            db.close()
    with _lock:
        _cache.update(at=time.monotonic(), status=st)
    return st


def clear_cache() -> None:
    with _lock:
        _cache.update(at=0.0, status=None)


def activate(db: Session, key: str) -> dict:
    lic = parse_key(key)
    iid = install_id()
    if lic["iid"] not in ("*", iid):
        raise ValueError(f"This key is for installation {lic['iid']}, but this installation is {iid}. Ask your provider for a key for {iid}.")
    if lic.get("until") and (_today() - date.fromisoformat(lic["until"])).days > GRACE_DAYS:
        raise ValueError(f"This key ended on {lic['until']}. Ask your provider for a renewal key.")
    m = _read_marker()
    hist = m.get("history") or []
    hist.append({"id": lic["id"], "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fp": _fp(lic["key"])})
    m.update(key=lic["key"], history=hist[-50:])
    if not m.get("first_seen"):
        m["first_seen"] = _db_state(db).get("first_seen") or _today().isoformat()
    _write_marker(m)
    d = _db_state(db)
    d.update(key=lic["key"], first_seen=m["first_seen"])
    _save_db_state(db, d)
    clear_cache()
    return lic


def remove_key(db: Session) -> None:
    """Used by "reset to a new installation": the key belonged to the previous customer. The trial does not restart."""
    m = _read_marker()
    m["key"] = None
    _write_marker(m)
    d = _db_state(db)
    d["key"] = None
    _save_db_state(db, d)
    clear_cache()


def staff_user_limit_check(db: Session, adding: int = 1) -> None:
    """Portal (customer) and driver-app logins are not counted."""
    from ..models import User

    st = status(db)
    limit = int(st.get("max_users") or 0)
    if not limit:
        return
    n = db.query(User).filter(User.is_active.is_(True), User.customer_id.is_(None), User.driver_id.is_(None)).count()
    if n + adding > limit:
        raise ValueError(f"Your licence allows {limit} staff users and {n} are active. Deactivate a user or ask your provider for a licence with more users.")


# Change requests still allowed when the ERP is read-only: signing in/out, own password, the licence itself,
# first-run setup, backups (create, download, restore) and factory reset, and marking notifications read.
READ_ONLY_ALLOWED = ("/api/auth/", "/api/licence", "/api/setup", "/api/backups", "/api/system/", "/api/notifications/read", "/api/health",
                     "/api/freight/calculate", "/api/invoices/preview-warehouse", "/api/import/templates")  # the last three only calculate / download


def blocks(method: str, path: str) -> bool:
    return method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/") and not path.startswith(READ_ONLY_ALLOWED)


def new_licence_id() -> str:  # used by tests / the provider script
    return f"AP-{_today():%Y%m%d}-{secrets.token_hex(2).upper()}"
