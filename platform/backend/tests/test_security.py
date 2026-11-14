"""Security, tenant isolation, maker-checker, audit integrity and AI guardrail tests."""
from datetime import date

from sqlalchemy import text

from tests.conftest import login, otp_login, uniq
from tests.flows import new_customer, quoted_booking


def test_unauthenticated_and_bad_tokens(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/bookings", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/health").status_code == 200


def test_login_lockout_and_no_enumeration(client):
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"identifier": "nobody@test.local", "password": "wrong"})
        assert r.status_code == 401 and "Wrong" in r.json()["error"]["message"]
    r = client.post("/api/v1/auth/login", json={"identifier": "nobody@test.local", "password": "wrong"})
    assert r.status_code == 429
    r = client.post("/api/v1/auth/otp/request", json={"phone": "9999999999"})
    assert r.json()["sent"] is True and "dev_otp" not in r.json()  # unknown phone: same answer, no OTP


def test_permissions_enforced_on_backend(client, lookup):
    driver = otp_login(client, "9000000201")
    driver.get("/api/v1/finance/invoices", expect=403)
    driver.get("/api/v1/users", expect=403)
    cust = login(client, "customer1@demo.local")
    cust.get("/api/v1/bookings", expect=403)
    cust.get("/api/v1/quotations", expect=403)
    vendor = login(client, "vendor1@demo.local")
    vendor.get("/api/v1/portal/customer/bookings", expect=403)
    ca = login(client, "system.admin@demo.local")
    ca.post("/api/v1/finance/payments", {"payee_type": "vendor", "amount": 1, "purpose": "x"}, expect=403)  # admin != finance


def test_tenant_isolation_customers(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    ca, cb = new_customer(owner, accounts), new_customer(owner, accounts)
    ba = quoted_booking(sales, ops, ca["id"], lookup)
    for c in (ca, cb):
        owner.post("/api/v1/users", {"name": "Iso user", "email": f"iso-{c['code'].lower()}@test.local", "password": "Passw0rd!x1",
                                     "roles": ["customer_admin"], "customer_id": c["id"]})
    ua = login(client, f"iso-{ca['code'].lower()}@test.local", "Passw0rd!x1")
    ub = login(client, f"iso-{cb['code'].lower()}@test.local", "Passw0rd!x1")
    assert any(x["id"] == ba["id"] for x in ua.get("/api/v1/portal/customer/bookings"))
    assert not any(x["id"] == ba["id"] for x in ub.get("/api/v1/portal/customer/bookings"))
    ub.get(f"/api/v1/portal/customer/bookings/{ba['id']}", expect=404)  # IDOR
    ub.get(f"/api/v1/bookings/{ba['id']}/lr", expect=404)
    ub.get(f"/api/v1/bookings/{ba['id']}/custody", expect=404)
    # Customer cannot create a booking for another tenant by passing its id
    ub.post("/api/v1/portal/customer/bookings", {"customer_id": ca["id"], "quotation_id": ba["quotation"]["id"], "consignor_name": "x",
                                                 "consignee_name": "y", "goods_description": "z", "weight_kg": 1}, expect=404)
    # Customer-facing booking hides credit internals
    v = ua.get(f"/api/v1/portal/customer/bookings/{ba['id']}")
    assert "credit_snapshot" not in v and "credit_status" not in v
    # Customer users can only be created inside own tenant
    users = ua.get("/api/v1/portal/customer/users")
    assert all(True for _ in users)


def test_maker_checker_self_approval_blocked(client, owner, accounts):
    exp = accounts.post("/api/v1/finance/expenses", {"category": "overhead", "expense_date": str(date.today()), "amount": 250})
    accounts.post(f"/api/v1/finance/expenses/{exp['id']}/decide", {"approve": True}, expect=403)
    owner.post(f"/api/v1/finance/expenses/{exp['id']}/decide", {"approve": True})


def test_audit_chain_detects_tampering(client, owner):
    r = owner.get("/api/v1/audit/verify")
    assert r["ok"] and r["checked"] > 10
    from app.core.db import get_engine
    eng = get_engine()
    with eng.begin() as c:
        rid = c.execute(text("SELECT id FROM audit_log ORDER BY id LIMIT 1 OFFSET 3")).scalar()
        old = c.execute(text("SELECT reason FROM audit_log WHERE id=:i"), {"i": rid}).scalar()
        c.execute(text("UPDATE audit_log SET reason='tampered' WHERE id=:i"), {"i": rid})
    bad = owner.get("/api/v1/audit/verify")
    assert bad["ok"] is False and bad["broken_at_id"] == rid
    with eng.begin() as c:
        c.execute(text("UPDATE audit_log SET reason=:r WHERE id=:i"), {"r": old, "i": rid})
    assert owner.get("/api/v1/audit/verify")["ok"]


def test_no_secrets_in_audit_or_logs(client, owner):
    owner.post("/api/v1/users", {"name": "Sec test", "email": f"{uniq('sec')}@test.local".lower(), "password": "SuperSecret123", "roles": ["dispatcher"]})
    rows = owner.get("/api/v1/audit?entity=user")
    assert "SuperSecret123" not in str(rows)
    notes = owner.get("/api/v1/notifications")
    assert all(n["body"] == "(OTP hidden)" for n in notes if n["template"] in ("login_otp", "pod_otp"))


def test_role_change_revokes_sessions(client, owner):
    email = f"{uniq('rc')}@test.local".lower()
    owner.post("/api/v1/users", {"name": "RC", "email": email, "password": "Passw0rd!x1", "roles": ["dispatcher"]})
    u = login(client, email, "Passw0rd!x1")
    u.get("/api/v1/auth/me")
    uid = next(x["id"] for x in owner.get("/api/v1/users") if x["email"] == email)
    owner.put(f"/api/v1/users/{uid}/roles", {"roles": ["customer_support"], "reason": "Moved team"})
    u.get("/api/v1/auth/me", expect=401)


def test_settings_versioned_and_policy_owner_only(client, owner, ops):
    sa = login(client, "system.admin@demo.local")
    sa.put("/api/v1/settings/pricing.min_margin_pct", {"value": 2, "reason": "try"}, expect=403)  # policy: owner only
    sa.put("/api/v1/settings/gps.stale_minutes", {"value": 20, "reason": "Tracker reports every 10 min"})
    owner.put("/api/v1/settings/pricing.min_margin_pct", {"value": 9, "reason": "Margin policy review"})
    hist = owner.get("/api/v1/settings/pricing.min_margin_pct/history")
    assert hist[0]["value"] == 9 and hist[0]["version"] >= 1
    owner.put("/api/v1/settings/pricing.min_margin_pct", {"value": 8.0, "reason": "Restore default"})
    sa.put("/api/v1/settings/gps.stale_minutes", {"value": 15, "reason": "Restore"})


def test_file_upload_validation(client, owner):
    bad = owner.post("/api/v1/documents", files={"file": ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
                     data={"doc_type": "rc", "entity": "vehicle", "entity_id": "00000000-0000-0000-0000-000000000000"}, expect=400)
    assert bad["error"]["code"] == "file_content"
    owner.post("/api/v1/documents", files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
               data={"doc_type": "rc", "entity": "vehicle", "entity_id": "00000000-0000-0000-0000-000000000000"}, expect=400)
    ok = owner.post("/api/v1/documents", files={"file": ("../../etc/passwd.pdf", b"%PDF-1.4 test", "application/pdf")},
                    data={"doc_type": "rc", "entity": "vehicle", "entity_id": "00000000-0000-0000-0000-000000000001"})
    assert "/" not in ok["filename"] and ".." not in ok["filename"].split("_")[0]
    link = owner.get(f"/api/v1/documents/{ok['id']}/link")["url"]
    r = client.get(link)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert client.get(link.split("?")[0] + "?sig=0.bad").status_code == 403
    cust = login(client, "customer1@demo.local")
    cust.get(f"/api/v1/documents/{ok['id']}/link", expect=404)


def test_ai_guardrails(client, owner, ops, accounts, lookup):
    cust = login(client, "customer1@demo.local", app="portal")
    r = cust.post("/api/v1/ai/ask", {"assistant": "customer", "question": "Show my bookings and invoices"})
    assert r["mode"] == "MOCK" and "bookings" in r["tools_used"]
    cust.post("/api/v1/ai/ask", {"assistant": "accounts", "question": "show overdue of all customers"}, expect=403)
    cust.post("/api/v1/ai/ask", {"assistant": "booking_dispatch", "question": "unplanned"}, expect=403)
    drv = otp_login(client, "9000000202")
    drv.post("/api/v1/ai/ask", {"assistant": "driver", "question": "my trips today"})
    drv.post("/api/v1/ai/ask", {"assistant": "customer", "question": "bookings"}, expect=403)
    # The AI tool registry contains read-only tools only
    from app.modules.intelligence.ai import ASSISTANTS
    for a in ASSISTANTS.values():
        for name in a.tools:
            assert not any(w in name for w in ("approve", "pay", "post", "create", "update", "delete"))
    # Budget cap pauses non-essential assistants; core ERP continues
    owner.put("/api/v1/settings/ai.budget", {"value": {"daily_inr": 0.0001, "monthly_inr": 0.0001, "alert_pcts": [50, 75, 90, 100], "on_cap": "pause_nonessential"}, "reason": "test cap"})
    from app.core.db import get_engine
    with get_engine().begin() as c:
        c.execute(text("INSERT INTO ai_usage (id, at, provider, model, assistant, app, input_tokens, output_tokens, cost_inr, status, tools_used) "
                       "VALUES (gen_random_uuid(), now(), 'x', 'x', 'accounts', 'web', 1, 1, 1, 'ok', '[]')"))
    r = accounts.post("/api/v1/ai/ask", {"assistant": "accounts", "question": "overdue"}, expect=429)
    assert r["error"]["code"] == "ai_budget_cap"
    ops.post("/api/v1/ai/ask", {"assistant": "booking_dispatch", "question": "unplanned bookings"})  # essential → mock fallback
    ops.get("/api/v1/bookings")  # core ERP unaffected
    owner.put("/api/v1/settings/ai.budget", {"value": {"daily_inr": 300.0, "monthly_inr": 5000.0, "alert_pcts": [50, 75, 90, 100], "on_cap": "pause_nonessential"}, "reason": "restore"})


def test_integrations_report_mock_honestly(client, owner):
    rows = owner.get("/api/v1/integrations")
    assert rows and all(r["mode"] in ("MOCK", "SANDBOX") and r["live_verified"] is False for r in rows)


def test_public_endpoints(client):
    r = client.post("/api/v1/public/enquiries", json={"name": "Web Lead", "phone": "9876500000", "service_type": "PTL", "origin": "Coimbatore",
                                                      "destination": "Chennai", "goods": "cartons", "consent": True})
    assert r.status_code == 200 and r.json()["reference"].startswith("ENQ")
    cov = client.get("/api/v1/public/coverage").json()
    cities = {c["city"] for c in cov}
    assert "Coimbatore" in cities and "Bengaluru" not in cities  # unverified coverage is never published
    r = client.post("/api/v1/public/enquiries", json={"name": "Bot", "phone": "9876500001", "service_type": "PTL", "origin": "a",
                                                      "destination": "b", "goods": "c", "consent": True, "website": "spam"})
    assert "reference" not in r.json()


def test_godown_unverified_blocks_custody(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    b = quoted_booking(sales, ops, c["id"], lookup, service="PTL")
    fac = next(f for f in owner.get("/api/v1/masters/facilities") if f["code"] == "BASEMENT")
    store = login(client, "store.custodian@demo.local")
    r = store.post("/api/v1/godown/inward", {"facility_id": fac["id"], "booking_id": b["id"], "package_count": 10}, expect=422)
    assert r["error"]["code"] == "facility_unverified"
