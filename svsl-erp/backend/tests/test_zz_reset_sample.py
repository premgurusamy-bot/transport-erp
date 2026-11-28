"""Factory reset and the sample-data backup. Runs last (it deletes the business data other test modules created)."""
from tests.conftest import ADMIN_PW, login


def _count(client, headers, name):
    return client.get(f"/api/r/{name}/summary", headers=headers).json()["total"]


def test_factory_reset_sample_backup_and_restore(client, admin):
    from app.core.deps import CurrentUser
    from app.db import SessionLocal
    from app.services import files, sample_data

    company_before = client.get("/api/company", headers=admin).json()["legal_name"]
    client.post("/api/r/customers", json={"code": "RESET-ME", "name": "Customer Removed By Reset", "billing_state_code": "33"}, headers=admin)
    assert _count(client, admin, "customers") > 0

    # confirmation and password are required
    assert client.post("/api/system/factory-reset", json={"confirm": "reset", "password": ADMIN_PW}, headers=admin).status_code == 400
    assert client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": "wrong-password1"}, headers=admin).status_code == 403

    r = client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": ADMIN_PW}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["pre_reset_backup"] and r.json()["deleted_rows"] > 0
    for name in ("customers", "vehicles", "drivers", "invoices", "vouchers", "lr"):
        assert _count(client, admin, name) == 0, name
    assert client.get("/api/company", headers=admin).json()["legal_name"] == company_before  # company profile kept
    admin = login(client, "admin", ADMIN_PW)  # users kept
    summary = client.get("/api/accounts/summary", headers=admin).json()  # system ledgers recreated
    assert summary["books_balanced"] and float(summary["receivables"]) == 0
    assert client.get("/api/audit?action=factory_reset", headers=admin).json()["total"] >= 1

    # build sample data on the now-empty database and save it as a sample backup
    db = SessionLocal()
    try:
        info = sample_data.build(db)
        db.commit()
        assert info["ledger_check"] and info["trips"] > 50 and info["invoices"] > 10
        rec = files.create_backup(db, CurrentUser(id=1, username="admin", full_name="Admin", role="Super Admin", permissions=["*"]), "sample", include_files=False, sample=True)
        db.commit()
        assert rec.status == "Verified"
        sample_path = files.backups_dir() / rec.file_name
    finally:
        db.close()

    # wipe again, change the company name, then restore the sample file asking NOT to keep users: a sample must still keep them
    assert client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": ADMIN_PW}, headers=admin).status_code == 200
    client.put("/api/company", json={"legal_name": "Company Kept Through Sample Restore"}, headers=admin)
    with open(sample_path, "rb") as fh:
        r = client.post("/api/backups/restore", data={"confirm": "RESTORE", "keep_users": "false"}, files={"file": ("A_PRIME_ERP_SAMPLE_DATA.zip", fh, "application/zip")}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["sample"] is True
    admin = login(client, "admin", ADMIN_PW)
    assert _count(client, admin, "customers") == 3 and _count(client, admin, "invoices") == info["invoices"]
    assert client.get("/api/company", headers=admin).json()["legal_name"] == "Company Kept Through Sample Restore"
    tb = client.get("/api/reports/trial_balance", headers=admin).json()
    assert tb["totals"]["debit"] == tb["totals"]["credit"]

    # and the sample can be removed again
    assert client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": ADMIN_PW}, headers=admin).status_code == 200
    assert _count(client, admin, "customers") == 0 and _count(client, admin, "lr") == 0


def test_reset_to_new_installation_and_first_run_setup(client, admin, monkeypatch):
    from app.services import licensing

    # only a Super Admin, with password and confirmation
    assert client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": "wrong-password1", "full": True}, headers=admin).status_code == 403
    first_seen = client.get("/api/licence", headers=admin).json()["first_seen"]
    r = client.post("/api/system/factory-reset", json={"confirm": "RESET", "password": ADMIN_PW, "full": True}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["full"] and r.json()["pre_reset_backup"]
    assert client.get("/api/auth/me", headers=admin).status_code == 401  # users are gone
    st = client.get("/api/setup/status").json()
    assert st["setup_needed"] is True and st["company"] == ""
    assert client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW}).status_code == 401

    body = {"company": {"legal_name": "New Customer Transports", "state_code": "29", "gstin": "", "phone": "080 1234567"},
            "admin": {"full_name": "New Owner", "username": "owner", "password": ADMIN_PW}}
    # the test client is not on this computer: refused unless remote setup is allowed
    assert client.post("/api/setup", json=body).status_code == 403
    monkeypatch.setenv("ALLOW_REMOTE_SETUP", "true")
    assert client.post("/api/setup", json={**body, "admin": {**body["admin"], "password": "short"}}).status_code == 400
    r = client.post("/api/setup", json=body)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/auth/me", headers=h).json()["username"] == "owner"
    c = client.get("/api/company", headers=h).json()
    assert c["legal_name"] == "New Customer Transports" and c["state"] == "Karnataka"
    st = client.get("/api/setup/status").json()
    assert st["setup_needed"] is False and st["company"] == "New Customer Transports" and "states" not in st
    assert client.post("/api/setup", json=body).status_code == 409  # cannot be run twice
    assert client.get("/api/accounts/summary", headers=h).json()["books_balanced"]
    lic = client.get("/api/licence", headers=h).json()
    assert lic["state"] == "trial" and lic["first_seen"] == first_seen and lic["licence_id"] is None  # the trial does not restart
    assert licensing.status(fresh=True)["state"] == "trial"
    assert client.get("/api/audit?action=setup", headers=h).json()["total"] == 1
