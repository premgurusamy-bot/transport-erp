"""Critical end-to-end workflows 1, 2, 3, 5, 6 and 11."""
from datetime import date
from decimal import Decimal

from tests.conftest import login, loc, uniq
from tests.flows import approve_pending, deliver_all, load_and_dispatch, new_customer, new_driver, new_vehicle, quoted_booking


def test_wf1_enquiry_quote_booking_and_cost_protection(client, owner, ops, accounts, lookup):
    c = new_customer(owner, accounts)
    sales = login(client, "sales.marketing@demo.local")
    b = quoted_booking(sales, ops, c["id"], lookup)
    assert b["status"] == "confirmed" and b["lr_number"].startswith("GRL/LR/")
    # Sales cannot see internal cost/margin; ops (no quote.view_cost) neither
    q = sales.get("/api/v1/quotations")[0]
    assert "internal_cost" not in q and "owner_quote" not in q and "margin_pct" not in q
    q_internal = owner.get("/api/v1/quotations")[0]
    assert "internal_cost" in q_internal and Decimal(q_internal["floor_price"]) > Decimal(q_internal["internal_cost"])


def test_wf1b_below_floor_needs_approval_not_self(client, owner, ops, accounts, lookup):
    c = new_customer(owner, accounts)
    e = ops.post("/api/v1/enquiries", {"source": "office", "customer_id": c["id"], "service_type": "FTL", "origin_id": loc(lookup, "Coimbatore"),
                                       "destination_id": loc(lookup, "Chennai"), "goods_description": "x", "weight_kg": 3000})
    sales = login(client, "sales.marketing@demo.local")
    full = owner.post("/api/v1/quotations", {"enquiry_id": e["id"], "vehicle_option": "own"})
    floor = Decimal(full["floor_price"])
    # cap: discount beyond cap is refused outright
    r = sales.post("/api/v1/quotations", {"enquiry_id": e["id"], "selling_price": str(floor * Decimal("0.5")), "reason": "x"}, expect=422)
    assert r["error"]["code"] == "discount_cap"
    q = sales.post("/api/v1/quotations", {"enquiry_id": e["id"], "selling_price": str(floor - 50), "reason": "Strategic customer"})
    assert q["status"] == "in_preparation"  # sales sees customer-safe status
    aps = owner.get("/api/v1/approvals")
    ap = next(a for a in aps if a["kind"] == "quote_discount" and a["entity_id"] == q["id"])
    # the maker cannot approve and lacks permission anyway
    sales.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "self"}, expect=403)
    owner.post(f"/api/v1/approvals/{ap['id']}/decide", {"approve": True, "note": "Approved for volume"})
    assert next(x for x in owner.get("/api/v1/quotations") if x["id"] == q["id"])["status"] == "approved"


def test_wf2_wf3_ftl_dispatch_tracking_delay_pod_and_close(client, owner, ops, accounts, lookup):
    c = new_customer(owner, accounts)
    b = quoted_booking(ops, ops, c["id"], lookup) if False else quoted_booking(login(client, "sales.marketing@demo.local"), ops, c["id"], lookup)
    v, d = new_vehicle(owner), new_driver(owner)
    disp = login(client, "dispatcher@demo.local")
    chk = disp.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    assert chk["can_allocate"], chk
    t = disp.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    assert t["trip_mode"] == "FTL" and t["exclusive_booking_id"] == b["id"]
    # Dispatch before loading/inspection is blocked
    r = ops.post(f"/api/v1/trips/{t['id']}/dispatch", {"start_odometer": 1000}, expect=422)
    assert r["error"]["code"] == "dispatch_blocked"
    drv = load_and_dispatch(client, ops, t, d, v)
    # GPS: phone ping during trip; tracking shows live then stale-aware
    from datetime import datetime, timezone
    drv.post("/api/v1/gps/ping", {"trip_id": t["id"], "lat": 11.5, "lng": 78.0, "recorded_at": datetime.now(timezone.utc).isoformat()})
    pos = ops.get(f"/api/v1/vehicles/{v['id']}/position")
    assert pos["state"] == "live" and pos["source"] == "phone"
    drv.post(f"/api/v1/trips/{t['id']}/events", {"event": "delay", "delay_minutes": 90, "note": "Traffic at Salem"})
    deliver_all(ops, drv, t)
    closed = ops.post(f"/api/v1/trips/{t['id']}/close", {"end_odometer": 1520})
    assert closed["trip"]["status"] == "closed"
    vv = owner.get(f"/api/v1/vehicles/{v['id']}")
    assert vv["status"] == "available" and vv["odometer_km"] == 1520


def test_wf5_ftl_exclusivity(client, owner, ops, accounts, lookup):
    c1, c2 = new_customer(owner, accounts), new_customer(owner, accounts)
    sales = login(client, "sales.marketing@demo.local")
    b1 = quoted_booking(sales, ops, c1["id"], lookup, weight=2000)
    b2 = quoted_booking(sales, ops, c2["id"], lookup, weight=1000)
    v, d = new_vehicle(owner), new_driver(owner)
    r = ops.post("/api/v1/trips", {"booking_ids": [b1["id"], b2["id"]], "vehicle_id": v["id"], "driver_id": d["id"]}, expect=422)
    assert any(x["check"] == "ftl_exclusive" for x in r["error"]["details"])
    # Override cannot bypass a legal/exclusivity check
    r = ops.post("/api/v1/trips", {"booking_ids": [b1["id"], b2["id"]], "vehicle_id": v["id"], "driver_id": d["id"],
                                   "override_checks": ["ftl_exclusive"], "override_reason": "try"}, expect=422)
    assert any(x["check"] == "ftl_exclusive" for x in r["error"]["details"])


def test_capacity_and_compliance_gates(client, owner, ops, accounts, lookup):
    c = new_customer(owner, accounts, limit=5000000)
    sales = login(client, "sales.marketing@demo.local")
    b = quoted_booking(sales, ops, c["id"], lookup, weight=9000)
    small, d = new_vehicle(owner, payload=7000), new_driver(owner)
    r = ops.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": small["id"], "driver_id": d["id"]})
    assert not r["can_allocate"] and any(x["check"] == "payload" for x in r["blocking"])
    nodocs = new_vehicle(owner, payload=12000, compliance=False)
    r = ops.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": nodocs["id"], "driver_id": d["id"]})
    assert any(x["check"].startswith("compliance_") for x in r["blocking"])
    # Critical defect blocks
    big = new_vehicle(owner, payload=12000)
    from app.modules.fleet.router import CRITICAL_ITEMS
    ck = {k: "ok" for k in CRITICAL_ITEMS}
    ck["brakes"] = "defect"
    owner.post("/api/v1/inspections", {"vehicle_id": big["id"], "kind": "periodic", "checklist": ck})
    r = ops.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": big["id"], "driver_id": d["id"]})
    assert any(x["check"] == "safety_defects" for x in r["blocking"])
    # Release by a different authorised person restores availability
    defect = next(x for x in owner.get("/api/v1/defects") if x["vehicle_id"] == big["id"])
    owner.post(f"/api/v1/defects/{defect['id']}/release", {"note": "Brakes repaired and tested"}, expect=403)  # reporter can't release
    fm = login(client, "fleet.maintenance@demo.local")
    fm.post(f"/api/v1/defects/{defect['id']}/release", {"note": "Brakes repaired and tested"})
    r = ops.post("/api/v1/allocation/check", {"booking_ids": [b["id"]], "vehicle_id": big["id"], "driver_id": d["id"]})
    assert r["can_allocate"], r


def test_wf11_credit_limit_warning_block_exception(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts, limit=20000)
    e = ops.post("/api/v1/enquiries", {"source": "office", "customer_id": c["id"], "service_type": "FTL", "origin_id": loc(lookup, "Coimbatore"),
                                       "destination_id": loc(lookup, "Chennai"), "goods_description": "x", "weight_kg": 3000})
    q = owner.post("/api/v1/quotations", {"enquiry_id": e["id"]})
    owner.post(f"/api/v1/quotations/{q['id']}/accept", {"accepted_by": "Buyer"})
    b = ops.post("/api/v1/bookings", {"quotation_id": q["id"], "consignor_name": "A", "consignee_name": "B", "goods_description": "x",
                                      "weight_kg": 3000})
    res = ops.post(f"/api/v1/bookings/{b['id']}/confirm")
    assert res["confirmed"] is False and res["credit"]["status"] == "blocked"
    ops.post(f"/api/v1/bookings/{b['id']}/credit-exception", {"reason": "Long-standing customer, cheque in transit"})
    approve_pending(owner, "credit_exception", b["id"])
    res = ops.post(f"/api/v1/bookings/{b['id']}/confirm")
    assert res["confirmed"] and res["credit"]["status"] == "exception_approved"
    # No profile at all → full advance required
    c2 = new_customer(owner, accounts, with_credit=False)
    m = ops.post("/api/v1/bookings", {"customer_id": c2["id"], "service_type": "FTL", "origin_id": loc(lookup, "Coimbatore"),
                                      "destination_id": loc(lookup, "Erode"), "consignor_name": "A", "consignee_name": "B", "goods_description": "x",
                                      "weight_kg": 1000, "freight_amount": 8000, "manual_price_reason": "Contract rate"})
    assert ops.post(f"/api/v1/bookings/{m['id']}/confirm")["credit"]["status"] == "blocked"
    exp = accounts.get(f"/api/v1/customers/{c['id']}/credit")["exposure"]
    assert Decimal(exp["open_committed"]) > 0


def test_wf6_expenses_invoice_bank_receipt_recon_profitability(client, owner, ops, accounts, lookup):
    c = new_customer(owner, accounts)
    sales = login(client, "sales.marketing@demo.local")
    b = quoted_booking(sales, ops, c["id"], lookup, selling=30000)
    v, d = new_vehicle(owner), new_driver(owner)
    t = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    drv = load_and_dispatch(client, ops, t, d, v, start_odo=5000)
    # Driver records toll expense from the app; fuel entry
    exp = drv.post("/api/v1/finance/expenses", {"category": "toll", "expense_date": str(date.today()), "amount": 1100, "trip_id": t["id"],
                                                "paid_by": "driver_cash", "bill_number": uniq("TL")})
    from datetime import datetime, timezone
    drv.post("/api/v1/fuel", {"vehicle_id": v["id"], "trip_id": t["id"], "filled_at": datetime.now(timezone.utc).isoformat(), "odometer_km": 5100,
                              "litres": 80, "rate": 92.5, "station": "IOC Salem", "bill_number": uniq("F")})
    deliver_all(ops, drv, t)
    # Closure blocked until expenses reviewed
    r = ops.post(f"/api/v1/trips/{t['id']}/close", {"end_odometer": 5510}, expect=422)
    assert "not reviewed" in str(r)
    for e in accounts.get(f"/api/v1/finance/expenses?trip_id={t['id']}&status=submitted"):
        owner.post(f"/api/v1/finance/expenses/{e['id']}/decide", {"approve": True})
    ops.post(f"/api/v1/trips/{t['id']}/close", {"end_odometer": 5510})
    inv = accounts.post("/api/v1/finance/invoices", {"customer_id": c["id"], "booking_ids": [b["id"]]})
    assert Decimal(inv["total"]) == Decimal("30000.00") and inv["gst_mode"] == "RCM"
    accounts.post("/api/v1/finance/invoices", {"customer_id": c["id"], "booking_ids": [b["id"]]}, expect=422)  # no duplicate invoice
    # Customer pays by NEFT; bank statement CSV import matches it
    bank = owner.get("/api/v1/masters/company-bank-accounts")
    bank_id = next(x["id"] for x in bank if not x["is_cash"])
    ref = uniq("UTR")
    rc = accounts.post("/api/v1/finance/receipts", {"customer_id": c["id"], "amount": 29700, "tds_amount": 300, "mode": "neft", "reference": ref,
                                                    "receipt_date": str(date.today()), "company_bank_id": bank_id,
                                                    "allocations": [{"invoice_id": inv["id"], "amount": 29700, "tds_amount": 300}]})
    assert rc["status"] == "unconfirmed"
    csv = f"Date,Narration,Ref No,Withdrawal,Deposit,Balance\n{date.today():%d/%m/%Y},NEFT-{c['name'][:20]},{ref},,29700.00,129700.00\n" \
          f"{date.today():%d/%m/%Y},UNKNOWN PARTY TRF,{uniq('X')},,5000.00,134700.00\n"
    res = accounts.post("/api/v1/finance/bank/import", files={"file": ("stmt.csv", csv, "text/csv")}, data={"company_bank_id": bank_id})
    assert res["matching"]["auto_confirmed"] >= 1
    inv2 = accounts.get(f"/api/v1/finance/invoices/{inv['id']}")
    assert inv2["status"] == "paid" and Decimal(inv2["balance"]) == 0
    unmatched = accounts.get("/api/v1/finance/bank/transactions?status=unmatched,suggested")
    assert any("UNKNOWN" in x["description"] for x in unmatched)  # unidentified credit is NOT a customer payment
    tb = accounts.get("/api/v1/finance/reports/trial-balance")
    assert tb["balanced"], tb
    bs = owner.get(f"/api/v1/finance/reports/balance-sheet?as_of={date.today()}")
    assert bs["balanced"], bs
    p = owner.get(f"/api/v1/finance/reports/trip/{t['id']}/profitability")
    assert Decimal(p["revenue"]) == Decimal("30000.00") and Decimal(p["direct_costs"]["toll"]) == Decimal("1100.00")
    assert "fuel" in p["direct_costs"] and Decimal(p["gross_contribution"]) < Decimal(p["revenue"])
