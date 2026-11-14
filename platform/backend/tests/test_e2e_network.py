"""Critical workflows 4 (PTL), 7 (attached owner), 8 (driver remuneration), 9 (renewal), 10 (incident/claim), 12 (offline sync)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tests.conftest import login, otp_login, uniq
from tests.flows import (
    approve_pending, deliver_all, load_and_dispatch, new_customer, new_driver, new_vehicle, quoted_booking,
)


def test_wf4_ptl_consolidation_scans_confidentiality(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c1, c2 = new_customer(owner, accounts), new_customer(owner, accounts)
    b1 = quoted_booking(sales, ops, c1["id"], lookup, service="PTL", dest="Chennai", weight=2000, packages=4, floor=40)
    b2 = quoted_booking(sales, ops, c2["id"], lookup, service="PTL", dest="Chennai", weight=2500, packages=3, floor=50)
    # incompatible goods are excluded by the engine
    v, d = new_vehicle(owner, payload=7000), new_driver(owner)
    prop = ops.post("/api/v1/consolidation/proposals", {"vehicle_id": v["id"], "booking_ids": [b1["id"], b2["id"]]})
    p0 = prop["proposals"][0]
    assert set(p0["booking_ids"]) == {b1["id"], b2["id"]} and "PROVISIONAL" in p0["status"]
    t = ops.post("/api/v1/trips", {"booking_ids": p0["booking_ids"], "vehicle_id": v["id"], "driver_id": d["id"]})
    assert t["trip_mode"] == "PTL" and len(t["loads"]) == 2 and t["load_plan"]["utilisation"]["weight_pct"] > 60
    # A package from another trip scanned here is flagged
    drv = otp_login(client, d["phone"])
    other = quoted_booking(sales, ops, c1["id"], lookup, service="PTL", dest="Madurai", weight=100, packages=1)
    lbl = ops.get(f"/api/v1/bookings/{other['id']}/labels")[0]["label"]
    s = drv.post("/api/v1/scans", {"label": lbl, "trip_id": t["id"], "stage": "loaded"})
    assert s["result"] == "wrong_trip"
    ops.post(f"/api/v1/tasks/{next(x['id'] for x in ops.get('/api/v1/tasks?entity=trip&entity_id=' + t['id']) if 'wrong trip' in x['title'])}/close",
             {"reason": "Package removed from vehicle"})
    drv = load_and_dispatch(client, ops, t, d, v)
    # Customer 1 sees only its own consignment - never customer 2
    cu1 = login(client, "customer1@demo.local")  # demo customer is a different tenant entirely
    cu1.get(f"/api/v1/portal/customer/bookings/{b1['id']}", expect=404)
    from app.modules.platform.router import UserIn  # noqa: F401
    owner.post("/api/v1/users", {"name": "C1 user", "email": f"{uniq('c1')}@test.local".lower(), "password": "Passw0rd!x1",
                                 "roles": ["customer_user"], "customer_id": c1["id"]})
    u = [x for x in owner.get("/api/v1/users") if x["customer_id"] == c1["id"]][0]
    cust = login(client, u["email"], "Passw0rd!x1")
    view = cust.get(f"/api/v1/portal/customer/bookings/{b1['id']}")
    assert view["tracking"]["shared_transport"] is True
    cust.get(f"/api/v1/portal/customer/bookings/{b2['id']}", expect=404)
    cust.get(f"/api/v1/trips/{t['id']}", expect=404)  # raw trip (with all loads) is not exposed to customers
    assert all(b2["code"] not in str(m) for m in view["tracking"]["milestones"])
    # Separate POD per consignment; partial delivery creates an exception
    drv.post(f"/api/v1/trips/{t['id']}/events", {"event": "departed"})
    drv.post("/api/v1/pod", {"trip_id": t["id"], "booking_id": b1["id"], "delivered_count": 4, "receiver_name": "R1",
                             "photo_document_ids": [], "signature_document_id": None, "otp": drv.post("/api/v1/pod/otp", {"trip_id": t["id"], "booking_id": b1["id"]})["dev_otp"]})
    drv.post("/api/v1/pod", {"trip_id": t["id"], "booking_id": b2["id"], "delivered_count": 2, "receiver_name": "R2", "condition": "short",
                             "otp": drv.post("/api/v1/pod/otp", {"trip_id": t["id"], "booking_id": b2["id"]})["dev_otp"]})
    tasks = ops.get(f"/api/v1/tasks?entity=booking&entity_id={b2['id']}")
    assert any("Delivery exception" in x["title"] and x["blocking"] for x in tasks)
    assert ops.get(f"/api/v1/trips/{t['id']}")["status"] == "delivered"


def test_ptl_incompatible_goods_rejected(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    r = ops.post("/api/v1/enquiries", {"source": "office", "customer_id": c["id"], "service_type": "PTL", "goods_description": "acid"})
    hz = next(g["id"] for g in lookup["goods_categories"] if g["label"].startswith("Hazardous"))
    e = ops.post("/api/v1/enquiries", {"source": "office", "customer_id": c["id"], "service_type": "PTL", "goods_category_id": hz,
                                       "origin_id": lookup["locations"][0]["id"], "destination_id": lookup["locations"][1]["id"],
                                       "goods_description": "Class 8", "weight_kg": 500})
    q = owner.post("/api/v1/quotations", {"enquiry_id": e["id"], "distance_km": 100})
    owner.post(f"/api/v1/quotations/{q['id']}/accept", {"accepted_by": "Buyer X"})
    res = ops.post("/api/v1/bookings", {"quotation_id": q["id"], "consignor_name": "a", "consignee_name": "b", "goods_description": "acid",
                                        "weight_kg": 500, "ptl_consent": True, "goods_category_id": hz}, expect=422)
    checks = {x["check"] for x in res["error"]["details"]}
    assert {"ptl_goods", "special_cargo"} <= checks


def test_wf7_attached_vehicle_owner_flow_and_settlement(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    b = quoted_booking(sales, ops, c["id"], lookup, weight=9000, selling=60000)
    own = owner.post("/api/v1/masters/owners", {"name": f"TEST Owner {uniq('')}", "phone": "9" + uniq("")[:9].replace("A", "1"), "kyc_status": "verified"})
    av = new_vehicle(owner, payload=15000, ownership="attached", owner_id=own["id"], vclass="HGV")
    ad = new_driver(owner, category="attached", owner_id=own["id"])
    owner.post("/api/v1/users", {"name": "Owner user", "email": f"{uniq('own')}@test.local".lower(), "password": "Passw0rd!x1",
                                 "roles": ["vehicle_owner"], "owner_id": own["id"]})
    oe = next(x for x in owner.get("/api/v1/users") if x["owner_id"] == own["id"])["email"]
    portal = login(client, oe, "Passw0rd!x1")
    offer = ops.post("/api/v1/owner-offers", {"owner_id": own["id"], "booking_id": b["id"], "lane": "Coimbatore → Chennai"})
    # Without owner acceptance, allocation is blocked
    r = ops.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": av["id"], "driver_id": ad["id"]})
    assert any(x["check"] == "owner_acceptance" for x in r["blocking"])
    portal.post(f"/api/v1/portal/owner/offers/{offer['id']}/quote", {"amount": 45000})
    ops.post(f"/api/v1/owner-offers/{offer['id']}/negotiate", {"negotiated_rate": 42000, "advance_pct": 20})
    portal.post(f"/api/v1/portal/owner/offers/{offer['id']}/accept", {"vehicle_id": av["id"], "driver_id": ad["id"], "confirm_documents_valid": True})
    t = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": av["id"], "driver_id": ad["id"]})
    assert t["fleet_type"] == "attached" and Decimal(t["owner_hire_amount"]) == Decimal("42000.00") and Decimal(t["owner_advance"]) == Decimal("8400.00")
    # Attached driver gets trip-scoped OTP access
    drv = load_and_dispatch(client, ops, t, ad, av, start_odo=0)
    assert drv.get("/api/v1/driver/me")["trip_scoped"] is True
    drv.get("/api/v1/driver/earnings", expect=403)
    deliver_all(ops, drv, t)
    ops.post(f"/api/v1/trips/{t['id']}/close", {})
    # Access revoked after completion
    drv.get("/api/v1/driver/trips", expect=401)
    # Owner sees own trip hire, not customer freight
    ot = portal.get("/api/v1/portal/owner/trips")
    assert ot[0]["hire"] == "42000.00" and "freight" not in str(ot)
    # Settlement → approval (maker-checker) → payment needs approved bank account
    s = accounts.post("/api/v1/finance/settlements/owner", {"owner_id": own["id"], "trip_ids": [t["id"]]})
    assert Decimal(s["net_payable"]) == Decimal("42000") - Decimal("8400") - Decimal(s["tds"])
    accounts.post(f"/api/v1/finance/settlements/{s['id']}/submit")
    approve_pending(owner, "settlement", s["id"])
    r = accounts.post("/api/v1/finance/payments", {"payee_type": "owner", "payee_id": own["id"], "amount": s["net_payable"],
                                                   "purpose": "Owner settlement", "settlement_id": s["id"]}, expect=422)
    assert r["error"]["code"] == "no_verified_bank"
    ops2 = login(client, "operations.manager@demo.local")
    bank = ops2.post("/api/v1/masters/bank-accounts", {"party_type": "owner", "party_id": own["id"], "account_name": own["name"],
                                                       "account_number": "123456789012", "ifsc": "SBIN0001234", "reason": "Owner onboarding"})
    assert bank["account_number"].endswith("9012") and bank["account_number"].startswith("*") and bank["status"] == "pending"
    ap = next(a for a in owner.get("/api/v1/approvals") if a["kind"] == "bank_account" and a["entity_id"] == bank["id"])
    ops2.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "self"}, expect=403)  # maker cannot approve
    sysadmin = login(client, "system.admin@demo.local")
    sysadmin.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "x"}, expect=403)  # lacks masters.approve
    r = accounts.post("/api/v1/finance/payments", {"payee_type": "owner", "payee_id": own["id"], "amount": s["net_payable"],
                                                   "purpose": "Owner settlement", "settlement_id": s["id"]}, expect=422)
    assert r["error"]["code"] == "no_verified_bank"  # still pending
    owner.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "Verified cancelled cheque"})
    pay = accounts.post("/api/v1/finance/payments", {"payee_type": "owner", "payee_id": own["id"], "amount": s["net_payable"],
                                                     "purpose": "Owner settlement", "settlement_id": s["id"]})
    accounts.post(f"/api/v1/finance/payments/{pay['id']}/execute", {"via": "bank_api"}, expect=403)  # no approval/permission
    approve_pending(owner, "payment", pay["id"])
    ex = owner.post(f"/api/v1/finance/payments/{pay['id']}/execute", {"via": "bank_api"})
    assert ex["status"] == "executed" and "SIMULATED" in ex["mode_label"]
    again = owner.post(f"/api/v1/finance/payments/{pay['id']}/execute", {"via": "bank_api"})
    assert again["bank_reference"] == ex["bank_reference"]  # idempotent
    st = portal.get("/api/v1/portal/owner/settlements")
    assert st[0]["status"] == "paid"
    assert accounts.get("/api/v1/finance/reports/trial-balance")["balanced"]


def test_wf8_driver_duty_to_remuneration(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    hr = login(client, "hr@demo.local")
    v, d = new_vehicle(owner), new_driver(owner)
    for comp, rate in (("per_trip", 500), ("per_km", 2), ("duty_day", 300)):
        r = hr.post("/api/v1/remuneration-rules", {"driver_id": d["id"], "component": comp, "rate": rate, "effective_from": str(date.today()),
                                                   "reason": "Initial agreement"})
        hr.post("/api/v1/approvals/" + next(a["id"] for a in hr.get("/api/v1/approvals") if a["entity_id"] == r["id"]) + "/decide",
                {"approve": True, "note": "x"}, expect=403)
        approve_pending(owner, "remuneration_rule", r["id"])
    b = quoted_booking(sales, ops, c["id"], lookup)
    t = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    drv = load_and_dispatch(client, ops, t, d, v, start_odo=2000)
    drv.post("/api/v1/finance/expenses", {"category": "hamali", "expense_date": str(date.today()), "amount": 400, "trip_id": t["id"],
                                          "paid_by": "driver_cash"})
    deliver_all(ops, drv, t)
    for e in accounts.get(f"/api/v1/finance/expenses?trip_id={t['id']}&status=submitted"):
        owner.post(f"/api/v1/finance/expenses/{e['id']}/decide", {"approve": True})
    res = ops.post(f"/api/v1/trips/{t['id']}/close", {"end_odometer": 2500})
    earn = res["driver_earning"]
    assert Decimal(earn["gross"]) == Decimal("500") + Decimal("1000") + Decimal("300")
    mine = drv.get("/api/v1/driver/earnings")
    assert mine["summary"]["pending_approval"] == "1800.00"
    accounts.post(f"/api/v1/driver-earnings/{earn['id']}/submit", {})
    approve_pending(owner, "driver_earning", earn["id"])
    s = accounts.post("/api/v1/finance/settlements/driver", {"driver_id": d["id"], "earning_ids": [earn["id"]]})
    assert Decimal(s["net_payable"]) == Decimal("1800") + Decimal("400")  # earning + cash expense reimbursement
    # Driver disputes → human review only
    g = drv.post("/api/v1/grievances", {"topic": "remuneration", "description": "Waiting hours not included", "entity": "trip", "entity_id": t["id"]})
    assert g["status"] == "open"
    # Driver cannot see another driver's trips
    d2 = new_driver(owner)
    other = otp_login(client, d2["phone"])
    other.get(f"/api/v1/trips/{t['id']}", expect=404)


def test_wf9_compliance_renewal_requires_owner_approval(client, owner, ops, accounts):
    v = new_vehicle(owner)
    comp = login(client, "compliance.coordinator@demo.local")
    item = next(x for x in comp.get(f"/api/v1/compliance?subject_id={v['id']}") if x["kind"] == "insurance")
    ren = comp.post("/api/v1/compliance/renewals", {"compliance_item_id": item["id"]})
    ren = comp.post(f"/api/v1/compliance/renewals/{ren['id']}/quote", {"quote_amount": 38000})
    assert ren["status"] == "pending_approval"
    body = {"payment_reference": "UTR123", "new_valid_from": str(date.today()), "new_valid_to": str(date.today() + timedelta(days=365)), "new_number": "POL-2"}
    comp.post(f"/api/v1/compliance/renewals/{ren['id']}/complete", body, expect=422)
    ap = next(a for a in owner.get("/api/v1/approvals") if a["entity_id"] == ren["id"])
    ops.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "x"}, expect=403)  # only Owner/Director
    owner.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "Renew with same insurer"})
    done = comp.post(f"/api/v1/compliance/renewals/{ren['id']}/complete", body)
    assert done["compliance"]["valid_to"] == str(date.today() + timedelta(days=365)) and done["expense"].startswith("EXP")
    current = [x for x in comp.get(f"/api/v1/compliance?subject_id={v['id']}") if x["kind"] == "insurance"]
    assert len(current) == 1 and current[0]["number"] == "POL-2"


def test_wf10_incident_claim_financial_treatment(client, owner, ops, accounts, lookup):
    inc = ops.post("/api/v1/incidents", {"kind": "cargo_damage", "severity": "high", "occurred_at": datetime.now(timezone.utc).isoformat(),
                                         "description": "Cartons wet due to rain ingress"})
    pol = owner.post("/api/v1/insurance-policies", {"kind": "git_cargo", "insurer": "TEST Insurer", "policy_number": uniq("GIT"),
                                                    "valid_from": str(date.today() - timedelta(days=10)), "valid_to": str(date.today() + timedelta(days=300)),
                                                    "deductible": 5000, "notification_deadline_hours": 48})
    det = ops.get(f"/api/v1/incidents/{inc['id']}")
    assert det["applicable_policies"] and "Possible relevance only" in det["applicable_policies"][0]["note"]
    cl = ops.post("/api/v1/claims", {"incident_id": inc["id"], "policy_id": pol["id"], "direction": "insurer", "gross_loss": 60000, "claimed_amount": 55000})
    assert cl["notify_deadline"] is not None and Decimal(cl["deductible"]) == Decimal("5000")
    ops.post(f"/api/v1/claims/{cl['id']}/progress", {"status": "notified", "insurer_claim_number": "INS-77"})
    ops.post(f"/api/v1/claims/{cl['id']}/financial-treatment", {"customer_compensation": 60000, "insurance_receivable": 50000, "reason": "Survey assessed 50k"})
    ops.post(f"/api/v1/approvals/{next(a['id'] for a in owner.get('/api/v1/approvals') if a['entity_id'] == cl['id'])}/decide",
             {"approve": True, "note": "x"}, expect=403)
    approve_pending(owner, "claim_finance", cl["id"])
    accounts.post(f"/api/v1/claims/{cl['id']}/cash-received", {"amount": 50000, "reference": "INS-STL"})
    final = next(x for x in ops.get("/api/v1/claims") if x["id"] == cl["id"])
    assert Decimal(final["cash_received"]) == Decimal("50000") and Decimal(final["customer_compensation"]) == Decimal("60000")
    assert accounts.get("/api/v1/finance/reports/trial-balance")["balanced"]


def test_wf12_offline_sync_idempotent(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    b = quoted_booking(sales, ops, c["id"], lookup)
    v, d = new_vehicle(owner), new_driver(owner)
    t = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    drv = load_and_dispatch(client, ops, t, d, v)
    base = datetime.now(timezone.utc) - timedelta(hours=3)
    events = [
        {"client_event_id": uniq("evt-"), "device_id": "phone-1", "event_type": "trip_event", "occurred_at": (base + timedelta(minutes=5)).isoformat(),
         "payload": {"trip_id": t["id"], "event": "departed"}},
        {"client_event_id": uniq("evt-"), "device_id": "phone-1", "event_type": "gps_ping", "occurred_at": (base + timedelta(minutes=10)).isoformat(),
         "payload": {"trip_id": t["id"], "lat": 11.2, "lng": 77.5}},
        {"client_event_id": uniq("evt-"), "device_id": "phone-1", "event_type": "expense", "occurred_at": (base + timedelta(minutes=20)).isoformat(),
         "payload": {"trip_id": t["id"], "category": "toll", "expense_date": str(date.today()), "amount": 350, "paid_by": "driver_cash"}},
        {"client_event_id": uniq("evt-"), "device_id": "phone-1", "event_type": "gps_ping", "occurred_at": base.isoformat(),
         "payload": {"trip_id": t["id"], "lat": 999, "lng": 77.5}},  # invalid → rejected, others still applied
    ]
    r1 = drv.post("/api/v1/sync/events", {"events": events})["results"]
    statuses = {x["client_event_id"]: x["status"] for x in r1}
    assert list(statuses.values()).count("applied") == 3 and list(statuses.values()).count("rejected") == 1
    r2 = drv.post("/api/v1/sync/events", {"events": events})["results"]
    assert all(x["replay"] for x in r2)
    exps = accounts.get(f"/api/v1/finance/expenses?trip_id={t['id']}")
    assert len([e for e in exps if e["category"] == "toll" and e["amount"] == "350.00"]) == 1  # not duplicated
    trip = ops.get(f"/api/v1/trips/{t['id']}")
    dep = [e for e in trip["events"] if e["event"] == "departed"][0]
    assert dep["occurred_at"].startswith((base + timedelta(minutes=5)).isoformat()[:16]) and dep["source"] == "app_offline"
