"""End-to-end: masters → trip → LR → dispatch → delivery → POD → closure → invoice → receipt → accounts."""
from datetime import date, timedelta
from decimal import Decimal

from app.core.validators import gstin_check_digit

from .conftest import lr_payload, make_contract, make_customer, make_driver, make_vehicle, uniq


def gstin(state="33", pan="AAACT1234A"):
    body = f"{state}{pan}1Z"
    return body + gstin_check_digit(body)


def full_trip(api, customer, contract_rate=12000, goods_value=30000, vehicle=None, driver=None):
    vehicle = vehicle or make_vehicle(api)
    driver = driver or make_driver(api)
    trip = api.post("/api/trips", {"customer_id": customer["id"], "from_place": "Coimbatore", "to_place": "Chennai", "vehicle_id": vehicle["id"], "driver_id": driver["id"]})
    assert trip["stage"] == "Driver Allocated"
    res = api.post("/api/lr", lr_payload(customer["id"], trip_id=trip["id"], goods_value=goods_value))
    lr = res["lr"]
    assert lr["vehicle_no"] == vehicle["registration_no"] and lr["driver_name"] == driver["name"]
    return trip, lr, vehicle, driver


def test_master_validation(api):
    r = api.post("/api/r/customers", {"code": uniq("C"), "name": "Bad GSTIN Co", "gstin": "33ABCDE1234F1Z0"}, expect=400)
    assert "GSTIN" in r.json()["detail"]
    good = api.post("/api/r/customers", {"code": uniq("C"), "name": "Good GSTIN Co", "gstin": gstin()})
    assert good["billing_state_code"] == "33" and good["ledger_id"]
    dup = api.post("/api/r/customers", {"code": good["code"], "name": "Dup"}, expect=409)
    assert "already exists" in dup.json()["detail"]
    v = make_vehicle(api)
    assert Decimal(v["payload_kg"]) == 16000
    api.post("/api/r/vehicles", {"registration_no": "INVALID", "vehicle_type": "Closed Body Truck", "ownership": "Owned"}, expect=400)
    d = make_driver(api, aadhaar_enc="123412341234")
    assert d["aadhaar_enc"] == "123412341234"  # admin has drivers:aadhaar
    assert d["ledger_id"]


def test_lr_numbering_unique(api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    nos = [api.post("/api/lr", lr_payload(cust["id"]))["lr"]["lr_no"] for _ in range(4)]
    assert len(set(nos)) == 4
    seq = [int(n.rsplit("/", 1)[1]) for n in nos]
    assert seq == sorted(seq) and seq[-1] - seq[0] == 3


def test_lr_freight_from_contract_and_manual(api):
    cust = make_customer(api)
    make_contract(api, cust["id"], basis="per_piece", rate=45, min_freight=3000, loading_charge=250)
    lr = api.post("/api/lr", lr_payload(cust["id"], advance_freight=1000))["lr"]
    assert Decimal(lr["basic_freight"]) == Decimal("4500.00")  # 100 pcs × 45
    assert Decimal(lr["loading_charges"]) == 250 and Decimal(lr["total_freight"]) == Decimal("4750.00")
    assert Decimal(lr["balance_freight"]) == Decimal("3750.00")
    other = make_customer(api)
    r = api.post("/api/lr", lr_payload(other["id"]), expect=400)
    assert "rate contract" in r.json()["detail"]
    manual = api.post("/api/lr", lr_payload(other["id"], freight_mode="manual", basic_freight=8000, manual_reason="spot rate"))["lr"]
    assert Decimal(manual["total_freight"]) == 8000


def test_full_trip_lifecycle_invoice_and_accounts(api, bank):
    cust = make_customer(api, state="33")
    make_contract(api, cust["id"], rate=12000)
    trip, lr, vehicle, driver = full_trip(api, cust, goods_value=80000)
    assert api.get(f"/api/trips/{trip['id']}")["stage"] == "LR Generated"
    # dispatch blocked without e-way bill (goods value > 50,000)
    r = api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Dispatched", "start_km": 1000}, expect=400)
    assert "E-way bill" in r.json()["detail"]
    api.post(f"/api/lr/{lr['id']}/ewaybill", {"ewb_no": "123456789012"})
    t = api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Dispatched", "start_km": 1000})
    assert t["stage"] == "Dispatched"
    assert api.get(f"/api/r/vehicles/{vehicle['id']}")["status"] == "On Trip"
    # vehicle cannot be put on a second trip
    t2 = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B"})
    r = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B", "vehicle_id": vehicle["id"]}, expect=400)
    assert "already on trip" in r.json()["detail"]
    # expenses
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Toll", "amount": 2500, "paid_by": "Driver Cash"})
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Diesel", "litres": 120, "rate": 92, "odometer": 1100, "paid_by": "Company Cash"})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Delivered", "receiver_name": "Store keeper"})
    r = api.post(f"/api/trips/{trip['id']}/stage", {"stage": "POD Collected"}, expect=400)
    assert "POD not yet received" in r.json()["detail"]
    api.post(f"/api/lr/{lr['id']}/pod", {})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "POD Collected"})
    r = api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Closed", "end_km": 900}, expect=400)
    assert "less than starting" in r.json()["detail"]
    closed = api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Closed", "end_km": 1505})
    assert closed["stage"] == "Closed"
    assert closed["pnl"]["revenue"] == "12000.00"
    v = api.get(f"/api/r/vehicles/{vehicle['id']}")
    assert v["status"] == "Available" and Decimal(v["current_odometer"]) == 1505
    # invoice (default treatment GTA RCM 5%)
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "basis": "lr", "lr_ids": [lr["id"]]})
    assert inv["charge_mechanism"] == "RCM" and Decimal(inv["rcm_tax"]) == Decimal(inv["taxable_value"]) * Decimal("0.05")
    assert Decimal(inv["total"]) == Decimal(inv["taxable_value"])  # RCM tax not charged
    assert api.get(f"/api/trips/{trip['id']}")["stage"] == "Billed"
    # same LR cannot be billed twice
    r = api.post("/api/invoices", {"customer_id": cust["id"], "basis": "lr", "lr_ids": [lr["id"]]}, expect=400)
    assert "already billed" in r.json()["detail"]
    # trial balance remains balanced
    tb = api.get("/api/reports/trial_balance")
    assert tb["notes"] == ["Balanced"]
    summary = api.get(f"/api/customers/{cust['id']}/summary")
    assert Decimal(summary["outstanding"]) == Decimal(inv["total"])
    # receipt with TDS, auto-allocated
    total = Decimal(inv["total"])
    api.post("/api/receipts", {"customer_id": cust["id"], "amount": str(total - 130), "tds_amount": 130, "mode": "Bank", "bank_ledger_id": bank["ledger_id"]})
    paid = api.get(f"/api/invoices/{inv['id']}")
    assert paid["status"] == "Paid" and Decimal(paid["balance"]) == 0
    assert Decimal(api.get(f"/api/customers/{cust['id']}/summary")["outstanding"]) == 0
    # cancellation blocked once receipts are allocated
    r = api.post(f"/api/invoices/{inv['id']}/cancel", {"reason": "wrong rate"}, expect=400)
    assert "Receipts are allocated" in r.json()["detail"]


def test_gst_forward_charge_intra_and_inter_state(api):
    fcm = next(t for t in api.get("/api/r/gst_treatments")["items"] if t["code"] == "GTA_FCM_5")
    local = make_customer(api, state="33")
    make_contract(api, local["id"], rate=10000)
    lr1 = api.post("/api/lr", lr_payload(local["id"]))["lr"]
    inv = api.post("/api/invoices", {"customer_id": local["id"], "lr_ids": [lr1["id"]], "gst_treatment_id": fcm["id"]})
    assert Decimal(inv["cgst"]) == Decimal("250.00") and Decimal(inv["sgst"]) == Decimal("250.00") and Decimal(inv["igst"]) == 0
    assert Decimal(inv["total"]) == Decimal("10500.00")
    outside = make_customer(api, state="29")
    make_contract(api, outside["id"], rate=10000)
    lr2 = api.post("/api/lr", lr_payload(outside["id"]))["lr"]
    inv2 = api.post("/api/invoices", {"customer_id": outside["id"], "lr_ids": [lr2["id"]], "gst_treatment_id": fcm["id"]})
    assert inv2["is_interstate"] and Decimal(inv2["igst"]) == Decimal("500.00") and Decimal(inv2["cgst"]) == 0
    pdf = api.get(f"/api/invoices/{inv2['id']}/pdf")
    assert pdf.content[:4] == b"%PDF"


def test_credit_and_debit_notes(api):
    fcm = next(t for t in api.get("/api/r/gst_treatments")["items"] if t["code"] == "GTA_FCM_5")
    cust = make_customer(api)
    make_contract(api, cust["id"], rate=20000)
    lr = api.post("/api/lr", lr_payload(cust["id"]))["lr"]
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "lr_ids": [lr["id"]], "gst_treatment_id": fcm["id"]})
    assert Decimal(inv["total"]) == Decimal("21000.00")
    cn = api.post("/api/invoices", {"doc_type": "credit_note", "customer_id": cust["id"], "reference_invoice_id": inv["id"], "reason": "Shortage claim", "lines": [{"description": "Shortage deduction", "amount": 2000}]})
    assert Decimal(cn["total"]) == Decimal("2100.00") and cn["status"] == "Adjusted"
    after = api.get(f"/api/invoices/{inv['id']}")
    assert Decimal(after["balance"]) == Decimal("18900.00")
    r = api.post("/api/invoices", {"doc_type": "credit_note", "customer_id": cust["id"], "reference_invoice_id": inv["id"], "reason": "too much", "lines": [{"description": "x", "amount": 19000}]}, expect=400)
    assert "cannot exceed" in r.json()["detail"]
    dn = api.post("/api/invoices", {"doc_type": "debit_note", "customer_id": cust["id"], "reference_invoice_id": inv["id"], "reason": "Detention charges", "lines": [{"description": "Detention 2 days", "amount": 5000}]})
    assert Decimal(dn["total"]) == Decimal("5250.00")
    out = Decimal(api.get(f"/api/customers/{cust['id']}/summary")["outstanding"])
    assert out == Decimal("21000") - Decimal("2100") + Decimal("5250")
    assert api.get("/api/reports/trial_balance")["notes"] == ["Balanced"]
    # cancelling the original requires cancelling notes first
    r = api.post(f"/api/invoices/{inv['id']}/cancel", {"reason": "Wrong customer"}, expect=400)
    assert "first" in r.json()["detail"]
    api.post(f"/api/invoices/{cn['id']}/cancel", {"reason": "Raised by mistake"})
    api.post(f"/api/invoices/{dn['id']}/cancel", {"reason": "Raised by mistake"})
    cancelled = api.post(f"/api/invoices/{inv['id']}/cancel", {"reason": "Wrong customer"})
    assert cancelled["status"] == "Cancelled"
    assert api.get(f"/api/lr/{lr['id']}")["invoice_id"] is None
    assert Decimal(api.get(f"/api/customers/{cust['id']}/summary")["outstanding"]) == 0
    assert api.get("/api/reports/trial_balance")["notes"] == ["Balanced"]
    # invoice number is never reused
    lr_inv = api.post("/api/invoices", {"customer_id": cust["id"], "lr_ids": [lr["id"]], "gst_treatment_id": fcm["id"]})
    assert lr_inv["invoice_no"] != inv["invoice_no"]


def test_consolidated_and_monthly_contract_invoices(api):
    cust = make_customer(api)
    make_contract(api, cust["id"], rate=5000)
    ids = [api.post("/api/lr", lr_payload(cust["id"]))["lr"]["id"] for _ in range(3)]
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "basis": "consolidated", "lr_ids": ids})
    assert Decimal(inv["taxable_value"]) == 15000 and len(inv["lines"]) == 3
    mcust = make_customer(api)
    mc = make_contract(api, mcust["id"], basis="monthly_fixed", rate=165000, monthly_trips_included=2, extra_trip_rate=6000)
    for _ in range(3):
        api.post("/api/trips", {"customer_id": mcust["id"], "from_place": "Plant", "to_place": "Warehouse", "trip_date": "2026-04-10"})
    m = api.post("/api/invoices", {"customer_id": mcust["id"], "basis": "monthly_contract", "contract_id": mc["id"], "period_from": "2026-04-01", "period_to": "2026-04-30", "invoice_date": "2026-04-30"})
    assert Decimal(m["taxable_value"]) == Decimal("171000.00")
    r = api.post("/api/invoices", {"customer_id": mcust["id"], "basis": "monthly_contract", "contract_id": mc["id"], "period_from": "2026-04-01", "period_to": "2026-04-30"}, expect=400)
    assert "already billed" in r.json()["detail"]


def test_lr_amend_and_cancel_with_audit(api):
    cust = make_customer(api)
    make_contract(api, cust["id"], basis="per_tonne", rate=1000)
    lr = api.post("/api/lr", lr_payload(cust["id"]))["lr"]
    assert Decimal(lr["total_freight"]) == 5000
    r = api.post(f"/api/lr/{lr['id']}/amend", {"changes": {"weight_kg": 6000}, "reason": "", "authorized_by": "GM"}, expect=400)
    am = api.post(f"/api/lr/{lr['id']}/amend", {"changes": {"weight_kg": 6000, "items": [{"description": "Auto parts", "packages": 10, "quantity": 100, "weight_kg": 6000}]}, "reason": "Weighbridge slip corrected", "authorized_by": "General Manager"})
    assert Decimal(am["total_freight"]) == 6000 and am["revision"] == 1 and len(am["amendments"]) == 1
    assert am["amendments"][0]["before"]["total_freight"] == "5000.00"
    c = api.post(f"/api/lr/{lr['id']}/cancel", {"reason": "Customer cancelled booking"})
    assert c["status"] == "Cancelled"
    audit = api.get(f"/api/audit?entity=consignments&entity_id={lr['id']}")
    assert {a["action"] for a in audit["items"]} >= {"create", "amend", "cancel"}
    r = api.post(f"/api/lr/{lr['id']}/amend", {"changes": {"remarks": "x"}, "reason": "after cancel", "authorized_by": "GM"}, expect=400)


def test_driver_advance_and_settlement(api, bank):
    cust = make_customer(api)
    make_contract(api, cust["id"], rate=9000)
    driver = make_driver(api)
    trip, lr, vehicle, _ = full_trip(api, cust, driver=driver)
    api.post("/api/r/driver_advances", {"driver_id": driver["id"], "advance_date": str(date.today()), "amount": 3000, "trip_id": trip["id"], "mode": "Cash"})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Dispatched", "start_km": 1000})
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Toll", "amount": 1200, "paid_by": "Driver Cash"})
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Food", "amount": 300, "paid_by": "Driver Cash"})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Closed", "end_km": 1500, "pod_all": True})
    p = api.get(f"/api/drivers/{driver['id']}/settlement-preview")
    # 1 day: bata 400 + food 100 + trip allowance 200 = 700 earnings; driver paid 1500; advance 3000
    assert Decimal(p["earnings"]) == 700 and Decimal(p["totals"]["driver_paid"]) == 1500 and Decimal(p["advances_total"]) == 3000
    assert Decimal(p["net_payable"]) == Decimal("-800.00")
    s = api.post(f"/api/drivers/{driver['id']}/settle", {"pay_mode": "Cash"})
    assert Decimal(s["net_payable"]) == Decimal("-800.00")
    ledger = api.get(f"/api/r/drivers/{driver['id']}")["ledger_id"]
    bal = next(l for l in api.get("/api/ledgers/balances") if l["id"] == ledger)
    assert Decimal(bal["balance"]) == Decimal("800.00")  # driver still owes ₹800
    again = api.post(f"/api/drivers/{driver['id']}/settle", {}, expect=400)
    assert api.get("/api/reports/trial_balance")["notes"] == ["Balanced"]


def test_vehicle_profitability_and_mileage(api):
    cust = make_customer(api)
    make_contract(api, cust["id"], rate=20000)
    trip, lr, vehicle, driver = full_trip(api, cust)
    api.post("/api/fuel", {"vehicle_id": vehicle["id"], "litres": 50, "rate": 90, "odometer": 1000, "payment_mode": "Cash", "full_tank": True})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Dispatched", "start_km": 1000})
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Diesel", "litres": 100, "rate": 90, "odometer": 1400, "paid_by": "Company Cash", "full_tank": True})
    api.post(f"/api/trips/{trip['id']}/expenses", {"category": "Toll", "amount": 1500, "paid_by": "Company Cash"})
    api.post(f"/api/trips/{trip['id']}/stage", {"stage": "Closed", "end_km": 1400, "pod_all": True})
    rep = api.get(f"/api/reports/vehicle_profitability?start={date.today() - timedelta(days=1)}&end={date.today()}")
    row = next(r for r in rep["rows"] if r["vehicle"] == vehicle["registration_no"])
    assert Decimal(row["revenue"]) == 20000
    assert Decimal(row["trip_expenses"]) == Decimal("10500.00")  # 9000 diesel + 1500 toll
    assert Decimal(row["fuel_other"]) == Decimal("4500.00")
    assert Decimal(row["profit"]) == Decimal("5000.00")
    m = api.get(f"/api/fuel/mileage/{vehicle['id']}")
    assert Decimal(m[-1]["kmpl"]) == Decimal("4.00")  # 400 km / 100 L


def test_manual_voucher_must_balance_and_reversal(api, bank):
    cash = next(l for l in api.get("/api/ledgers/balances") if l["name"] == "Cash")["id"]
    office = next(l for l in api.get("/api/ledgers/balances") if l["name"] == "Office Expenses")["id"]
    r = api.post("/api/vouchers", {"voucher_type": "Payment", "lines": [{"ledger_id": office, "debit": 500}, {"ledger_id": cash, "credit": 400}]}, expect=400)
    assert "does not balance" in r.json()["detail"]
    r = api.post("/api/vouchers", {"voucher_type": "Contra", "lines": [{"ledger_id": office, "debit": 500}, {"ledger_id": cash, "credit": 500}]}, expect=400)
    v = api.post("/api/vouchers", {"voucher_type": "Payment", "narration": "Stationery", "lines": [{"ledger_id": office, "debit": 500}, {"ledger_id": cash, "credit": 500}]})
    rev = api.post(f"/api/vouchers/{v['id']}/cancel", {"reason": "Duplicate entry"})
    assert api.get(f"/api/vouchers/{v['id']}")["status"] == "Cancelled"
    assert api.get(f"/api/vouchers/{rev['reversal_id']}")["status"] == "Reversal"
    api.post(f"/api/vouchers/{v['id']}/cancel", {"reason": "again"}, expect=400)
    pl = api.get("/api/reports/profit_loss")
    bs = api.get("/api/reports/balance_sheet")
    assert bs["notes"] == ["Difference: 0.00"]


def test_vendor_bill_and_payment(api):
    vendor = api.post("/api/r/vendors", {"code": uniq("V"), "name": f"Workshop {uniq()}", "category": "Workshop / Repairs", "state_code": "33"})
    bill = api.post("/api/vendor-bills", {"vendor_id": vendor["id"], "bill_no": "W-101", "lines": [{"description": "Clutch overhaul", "amount": 10000, "gst_rate": 18}], "tds_amount": 100})
    assert Decimal(bill["cgst"]) == 900 and Decimal(bill["total"]) == 11800
    api.post("/api/vendor-bills", {"vendor_id": vendor["id"], "bill_no": "W-101", "lines": [{"description": "dup", "amount": 1}]}, expect=400)
    api.post("/api/vendor-payments", {"vendor_id": vendor["id"], "amount": 11700, "mode": "Cash"})
    b = next(x for x in api.get(f"/api/vendor-bills?vendor_id={vendor['id']}"))
    assert b["status"] == "Paid"
    assert api.get("/api/reports/trial_balance")["notes"] == ["Balanced"]


def test_maintenance_job_and_reminders(api):
    v = make_vehicle(api, current_odometer=50000)
    api.post("/api/r/maintenance_schedules", {"vehicle_id": v["id"], "task": "Engine Oil", "interval_km": 10000, "last_done_km": 40500, "last_done_date": str(date.today() - timedelta(days=30)), "remind_before_km": 500})
    due = api.get("/api/maintenance/due")
    assert any(d["vehicle_id"] == v["id"] and d["task"] == "Engine Oil" for d in due)
    job = api.post("/api/maintenance/jobs", {"vehicle_id": v["id"], "category": "Engine Oil", "job_type": "Preventive", "odometer": 50000})
    assert api.get(f"/api/r/vehicles/{v['id']}")["status"] == "Maintenance"
    api.post(f"/api/maintenance/jobs/{job['id']}/complete", {"labour_amount": 800, "parts": [{"name": "Engine oil 15W40", "qty": 18, "rate": 320}], "payment_mode": "Cash"})
    assert api.get(f"/api/r/vehicles/{v['id']}")["status"] == "Available"
    assert not any(d["vehicle_id"] == v["id"] and d["task"] == "Engine Oil" for d in api.get("/api/maintenance/due"))
    t = api.post("/api/r/tyres", {"serial_no": uniq("TY"), "brand": "Brand", "cost": 18000})
    api.post(f"/api/tyres/{t['id']}/action", {"action": "Fitted", "vehicle_id": v["id"], "position": "FL", "odometer": 50000})
    api.post(f"/api/tyres/{t['id']}/action", {"action": "Removed", "odometer": 90000})
    h = api.get(f"/api/tyres/{t['id']}/history")
    assert Decimal(h["tyre"]["total_km"]) == 40000 and Decimal(h["cost_per_km"]) == Decimal("0.45")
