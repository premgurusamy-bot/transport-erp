"""Trial, licence keys and the read-only mode after expiry."""
import base64
import json
from datetime import date, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services import licensing

_KEY = Ed25519PrivateKey.generate()


def make_key(iid="*", plan="yearly", until=None, users=0, to="Test Customer", kid="test", signer=None):
    payload = {"v": 1, "k": kid, "id": licensing.new_licence_id(), "to": to, "iid": iid, "plan": plan, "from": date.today().isoformat(),
               "until": until, "users": users, "issued": date.today().isoformat()}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = (signer or _KEY).sign(f"APRIME1.{body}".encode())
    return f"APRIME1.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@pytest.fixture(autouse=True)
def test_signing_key(monkeypatch):
    pub = base64.b64encode(_KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    monkeypatch.setitem(licensing.PUBLIC_KEYS, "test", pub)
    licensing.clear_cache()
    yield
    licensing.clear_cache()


def _set_state(**kw):
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        m = licensing._read_marker()
        m.update(kw)
        licensing._write_marker(m)
        d = licensing._db_state(db)
        d.update(kw)
        licensing._save_db_state(db, d)
        db.commit()
    finally:
        db.close()
    licensing.clear_cache()


def test_trial_then_read_only_then_licence(client, admin):
    st = client.get("/api/licence", headers=admin).json()
    assert st["state"] == "trial" and st["days_left"] == licensing.TRIAL_DAYS == 15 and not st["read_only"]
    iid = st["install_id"]
    try:
        # trial over: reading works, changing does not
        _set_state(first_seen=(date.today() - timedelta(days=16)).isoformat(), key=None)
        st = client.get("/api/licence", headers=admin).json()
        assert st["state"] == "trial_expired" and st["read_only"]
        assert client.get("/api/r/customers", headers=admin).status_code == 200
        r = client.post("/api/r/customers", json={"code": "LIC-1", "name": "Blocked Customer", "billing_state_code": "33"}, headers=admin)
        assert r.status_code == 402 and "trial" in r.json()["detail"].lower()
        assert client.get("/api/auth/me", headers=admin).status_code == 200

        # keys that must be refused
        bad = [make_key(iid="AAAA-BBBB-CCCC-DDDD"), make_key(signer=Ed25519PrivateKey.generate()), make_key(kid="nope"), "hello",
               make_key(until=(date.today() - timedelta(days=30)).isoformat())]
        tampered = make_key()
        parts = tampered.split(".")
        data = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        data["users"] = 999
        bad.append(".".join([parts[0], base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("="), parts[2]]))
        for k in bad:
            r = client.post("/api/licence/activate", json={"key": k}, headers=admin)
            assert r.status_code == 400, (k, r.text)

        # a genuine key for this installation (pasted with line breaks) unlocks it
        key = make_key(iid=iid, until=(date.today() + timedelta(days=365)).isoformat(), users=50)
        r = client.post("/api/licence/activate", json={"key": key[:40] + "\n" + key[40:]}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "active" and r.json()["licensed_to"] == "Test Customer" and r.json()["max_users"] == 50
        r = client.post("/api/r/customers", json={"code": "LIC-1", "name": "Allowed Customer", "billing_state_code": "33"}, headers=admin)
        assert r.status_code in (200, 201), r.text
        assert client.get("/api/audit?action=licence_activate", headers=admin).json()["total"] >= 1

        # user limit
        _set_state(key=make_key(iid=iid, until=(date.today() + timedelta(days=30)).isoformat(), users=1))
        roles = {x["name"]: x["id"] for x in client.get("/api/roles", headers=admin).json()}
        rid = roles.get("Accountant") or roles["Super Admin"]
        r = client.post("/api/users", json={"username": "over.limit", "full_name": "Over Limit", "password": "Limit@12345!", "role_id": rid}, headers=admin)
        assert r.status_code == 402 and "allows 1 staff users" in r.json()["detail"], r.text

        # grace period after the end date, then read-only
        _set_state(key=make_key(iid=iid, until=(date.today() - timedelta(days=3)).isoformat()))
        st = client.get("/api/licence", headers=admin).json()
        assert st["state"] == "grace" and not st["read_only"] and st["days_left"] == licensing.GRACE_DAYS - 3
        _set_state(key=make_key(iid=iid, until=(date.today() - timedelta(days=licensing.GRACE_DAYS + 1)).isoformat()))
        st = client.get("/api/licence", headers=admin).json()
        assert st["state"] == "expired" and st["read_only"]

        # lifetime licence
        _set_state(key=make_key(iid=iid, plan="perpetual", until=None))
        st = client.get("/api/licence", headers=admin).json()
        assert st["state"] == "active" and st["valid_until"] is None and "lifetime" in st["message"]

        # clock set back
        _set_state(last_seen=(date.today() + timedelta(days=10)).isoformat() + "T00:00:00+00:00")
        st = client.get("/api/licence", headers=admin).json()
        assert st["state"] == "clock_error" and st["read_only"]
    finally:
        _set_state(first_seen=date.today().isoformat(), key=None, last_seen=None)
    assert client.get("/api/licence", headers=admin).json()["state"] == "trial"


def test_deleting_the_local_file_does_not_restart_the_trial(client, admin):
    try:
        _set_state(first_seen=(date.today() - timedelta(days=10)).isoformat())
        licensing._marker_file().unlink()
        licensing.clear_cache()
        st = client.get("/api/licence", headers=admin).json()
        assert st["days_left"] == 5
        assert licensing._read_marker()["first_seen"] == (date.today() - timedelta(days=10)).isoformat()  # file rebuilt from the database
    finally:
        _set_state(first_seen=date.today().isoformat(), key=None, last_seen=None)


def test_setup_status_is_public_and_closed_once_set_up(client):
    r = client.get("/api/setup/status")
    assert r.status_code == 200 and r.json()["setup_needed"] is False
    assert client.post("/api/setup", json={"company": {"legal_name": "X"}, "admin": {}}).status_code == 409


def test_provider_script_keys_are_accepted(monkeypatch, tmp_path):
    """scripts/issue_licence.py and the app agree on the key format and plan periods."""
    import importlib.util
    from pathlib import Path

    from cryptography.hazmat.primitives.serialization import Encoding as E, NoEncryption, PrivateFormat

    spec = importlib.util.spec_from_file_location("issue_licence", Path(__file__).resolve().parents[2] / "scripts" / "issue_licence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pub = base64.b64encode(_KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    monkeypatch.setitem(licensing.PUBLIC_KEYS, "k1", pub)
    der = _KEY.private_bytes(E.DER, PrivateFormat.PKCS8, NoEncryption())
    key = mod.sign(der, {"v": 1, "k": "k1", "id": "AP-1", "to": "Ünicode Logistics", "iid": licensing.install_id(), "plan": "yearly",
                         "from": "2026-01-31", "until": mod.until_for("yearly", date(2026, 1, 31), None).isoformat(), "users": 3})
    lic = licensing.parse_key(key)
    assert lic["to"] == "Ünicode Logistics" and lic["until"] == "2027-01-30"
    assert mod.until_for("monthly", date(2026, 1, 31), None) == date(2026, 2, 27)
    assert mod.until_for("trial", date(2026, 1, 1), 15) == date(2026, 1, 15)
    assert mod.until_for("perpetual", date(2026, 1, 1), None) is None
