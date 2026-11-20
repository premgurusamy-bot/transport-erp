import pyotp

from .conftest import Api, login, lr_payload, make_contract, make_customer, make_driver, make_vehicle, uniq


def role_id(api, name):
    return next(r["id"] for r in api.get("/api/roles") if r["name"] == name)


def make_user(api, role, **kw):
    uname = uniq("user").lower()
    api.post("/api/users", {"username": uname, "full_name": uname, "password": "Passw0rd!x", "role_id": role_id(api, role), "must_change_password": False, **kw})
    return uname


def test_unauthenticated_and_bad_token(client):
    assert client.get("/api/r/customers").status_code == 401
    assert client.get("/api/r/customers", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert client.get("/api/health").status_code == 200


def test_password_rules_and_lockout(client, api):
    r = api.post("/api/users", {"username": uniq("weak").lower(), "full_name": "x", "password": "12345678", "role_id": role_id(api, "Accountant")}, expect=400)
    uname = make_user(api, "Accountant")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": uname, "password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": uname, "password": "Passw0rd!x"})
    assert r.status_code == 423  # locked
    uid = next(u["id"] for u in api.get("/api/users") if u["username"] == uname)
    api.put(f"/api/users/{uid}", {"unlock": True})
    assert client.post("/api/auth/login", json={"username": uname, "password": "Passw0rd!x"}).status_code == 200
    hist = api.get("/api/login-history")
    assert any(h["username"] == uname and not h["success"] for h in hist)


def test_logout_revokes_session(client, api):
    uname = make_user(api, "Accountant")
    h = login(client, uname, "Passw0rd!x")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/auth/me", headers=h).status_code == 401


def test_two_factor(client, api):
    uname = make_user(api, "Accountant")
    h = login(client, uname, "Passw0rd!x")
    secret = client.post("/api/auth/2fa/setup", headers=h).json()["secret"]
    assert client.post("/api/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 400
    assert client.post("/api/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    r = client.post("/api/auth/login", json={"username": uname, "password": "Passw0rd!x"})
    assert r.status_code == 401 and r.json()["detail"] == "OTP_REQUIRED"
    assert client.post("/api/auth/login", json={"username": uname, "password": "Passw0rd!x", "otp": "123456"}).status_code == 401
    login(client, uname, "Passw0rd!x", pyotp.TOTP(secret).now())


def test_role_permissions(client, api):
    disp = Api(client, login(client, make_user(api, "Dispatch Operator"), "Passw0rd!x"))
    cust = make_customer(api)
    make_contract(api, cust["id"])
    lr = disp.post("/api/lr", lr_payload(cust["id"]))["lr"]  # dispatcher can create LR
    assert disp.c.post(f"/api/lr/{lr['id']}/cancel", headers=disp.h, json={"reason": "not allowed"}).status_code == 403
    assert disp.c.get("/api/vouchers", headers=disp.h).status_code == 403
    assert disp.c.get("/api/users", headers=disp.h).status_code == 403
    assert disp.c.post("/api/r/customers", headers=disp.h, json={"code": "Z1", "name": "Z"}).status_code == 403
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "lr_ids": [lr["id"]]})
    acct = Api(client, login(client, make_user(api, "Accountant"), "Passw0rd!x"))
    assert acct.c.post(f"/api/invoices/{inv['id']}/cancel", headers=acct.h, json={"reason": "permitted test"}).status_code == 200
    assert acct.c.post("/api/backups/restore", headers=acct.h, data={"confirm": "RESTORE"}).status_code == 403
    # Accountant cannot create a Super Admin user
    assert acct.c.post("/api/users", headers=acct.h, json={"username": "hacker", "full_name": "h", "password": "Passw0rd!x", "role_id": role_id(api, "Super Admin")}).status_code == 403
    gm = Api(client, login(client, make_user(api, "General Manager"), "Passw0rd!x"))
    r = gm.c.post("/api/users", headers=gm.h, json={"username": "gmmade", "full_name": "x", "password": "Passw0rd!x", "role_id": role_id(api, "Super Admin")})
    assert r.status_code == 403


def test_sensitive_fields_masked(client, api):
    d = make_driver(api, aadhaar_enc="987698769876", bank_account_enc="5555444433332222")
    disp = Api(client, login(client, make_user(api, "Dispatch Operator"), "Passw0rd!x"))
    seen = disp.get(f"/api/r/drivers/{d['id']}")
    assert seen["aadhaar_enc"] == "XXXXXXXX9876" and seen["bank_account_enc"].endswith("2222") and seen["bank_account_enc"].startswith("X")
    hr = Api(client, login(client, make_user(api, "HR Manager"), "Passw0rd!x"))
    assert hr.get(f"/api/r/drivers/{d['id']}")["aadhaar_enc"] == "987698769876"
    emp = api.post("/api/r/employees", {"code": uniq("E"), "name": "Clerk", "joining_date": "2025-01-01", "basic": 20000})
    fm = Api(client, login(client, make_user(api, "Fleet Manager"), "Passw0rd!x"))
    assert fm.c.get(f"/api/r/employees/{emp['id']}", headers=fm.h).status_code == 403
    acct = Api(client, login(client, make_user(api, "Accountant"), "Passw0rd!x"))
    from app.db import SessionLocal
    from app.models import Driver

    db = SessionLocal()
    raw = db.get(Driver, d["id"]).aadhaar_enc
    db.close()
    assert "9876" not in raw  # encrypted at rest


def test_customer_portal_isolation(client, api):
    a, b = make_customer(api), make_customer(api)
    for c in (a, b):
        make_contract(api, c["id"])
    lr_a = api.post("/api/lr", lr_payload(a["id"]))["lr"]
    lr_b = api.post("/api/lr", lr_payload(b["id"]))["lr"]
    inv_b = api.post("/api/invoices", {"customer_id": b["id"], "lr_ids": [lr_b["id"]]})
    uname = make_user(api, "Customer", customer_id=a["id"])
    p = Api(client, login(client, uname, "Passw0rd!x"))
    ships = p.get("/api/portal/shipments")
    assert {s["lr_no"] for s in ships} == {lr_a["lr_no"]}
    assert p.c.get(f"/api/portal/lr/{lr_b['id']}/pdf", headers=p.h).status_code == 404
    assert p.c.get(f"/api/portal/invoices/{inv_b['id']}/pdf", headers=p.h).status_code == 404
    assert p.c.get(f"/api/portal/lr/{lr_a['id']}/pdf", headers=p.h).status_code == 200
    assert p.c.get("/api/lr", headers=p.h).status_code == 403
    assert p.c.get("/api/r/customers", headers=p.h).status_code == 403
    bk = p.post("/api/portal/bookings", {"pickup_address": "Plant 1", "drop_address": "Chennai DC", "required_date": "2099-01-01"})
    assert bk["booking_no"]
    assert all(x["customer_id"] == a["id"] for x in p.get("/api/portal/bookings"))
    p.post("/api/portal/complaints", {"subject": "Late", "description": "Delivery was late", "consignment_id": lr_a["id"]})
    assert p.c.post("/api/portal/complaints", headers=p.h, json={"subject": "x", "description": "y", "consignment_id": lr_b["id"]}).status_code == 404
    st = p.get("/api/portal/statement")
    assert "Statement" in st["title"]


def test_driver_app_isolation_and_flow(client, api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    d1, d2 = make_driver(api), make_driver(api)
    v1, v2 = make_vehicle(api), make_vehicle(api)
    t1 = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B", "vehicle_id": v1["id"], "driver_id": d1["id"]})
    t2 = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B", "vehicle_id": v2["id"], "driver_id": d2["id"]})
    lr = api.post("/api/lr", lr_payload(cust["id"], trip_id=t1["id"]))["lr"]
    app_user = make_user(api, "Driver", driver_id=d1["id"])
    drv = Api(client, login(client, app_user, "Passw0rd!x"))
    mine = drv.get("/api/driver/trips")
    assert [t["id"] for t in mine] == [t1["id"]]
    assert drv.c.get(f"/api/driver/trips/{t2['id']}", headers=drv.h).status_code == 404
    detail = drv.get(f"/api/driver/trips/{t1['id']}")
    assert "total_freight" not in detail["lrs"][0]
    assert drv.c.post("/api/driver/location", headers=drv.h, json={"lat": 11.0, "lng": 76.9}).status_code == 403  # no consent yet
    drv.post(f"/api/driver/trips/{t1['id']}/stage", {"stage": "Loading"})
    drv.post(f"/api/driver/trips/{t1['id']}/stage", {"stage": "Dispatched", "start_km": 1000})
    drv.post("/api/driver/consent", {"consent": True})
    assert drv.post("/api/driver/location", {"lat": 11.0168, "lng": 76.9558})["stored"]
    drv.post(f"/api/driver/trips/{t1['id']}/expense", {"category": "Parking", "amount": 150})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = drv.c.post(f"/api/driver/trips/{t1['id']}/pod", headers=drv.h, data={"lr_id": str(lr["id"]), "receiver_name": "Gate"}, files={"file": ("pod.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert api.get(f"/api/lr/{lr['id']}")["status"] == "POD Received"
    drv.post(f"/api/driver/trips/{t1['id']}/incident", {"kind": "Breakdown", "description": "Tyre burst near Salem"})
    assert drv.c.get("/api/r/vehicles", headers=drv.h).status_code == 403
    exp = api.get(f"/api/trips/{t1['id']}")["expenses"]
    assert exp[0]["entered_via"] == "Driver App" and exp[0]["approved"] is False


def test_audit_trail_on_master_changes(api):
    c = make_customer(api)
    api.put(f"/api/r/customers/{c['id']}", {"credit_limit": 250000, "_reason": "Reviewed"})
    a = api.get(f"/api/audit?entity=customers&entity_id={c['id']}")["items"]
    upd = next(x for x in a if x["action"] == "update")
    assert upd["after"]["credit_limit"] == "250000.00" and upd["reason"] == "Reviewed"
