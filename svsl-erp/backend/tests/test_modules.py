"""Warehouse, alerts, compliance, payroll, documents, FASTag, backup/restore, reports & exports."""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from openpyxl import Workbook

from .conftest import lr_payload, make_contract, make_customer, make_driver, make_vehicle, uniq


def test_warehouse_inward_outward_and_billing(api):
    cust = make_customer(api)
    wh = api.post("/api/r/warehouses", {"code": uniq("W"), "name": f"Godown {uniq()}"})
    item = api.post("/api/r/items", {"sku": uniq("SKU"), "name": "Brake drum", "uom": "NOS", "customer_id": cust["id"], "batch_tracked": True})
    r = api.post("/api/warehouse/docs", {"doc_type": "Inward", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-01", "lines": [{"item_id": item["id"], "qty": 100}]}, expect=400)
    assert "Batch" in r.json()["detail"]
    api.post("/api/warehouse/docs", {"doc_type": "Inward", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-01", "vehicle_no": "TN00TS9999", "lines": [{"item_id": item["id"], "qty": 100, "batch_no": "B1"}]})
    api.post("/api/warehouse/docs", {"doc_type": "Outward", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-11", "lines": [{"item_id": item["id"], "qty": 40, "batch_no": "B1"}]})
    r = api.post("/api/warehouse/docs", {"doc_type": "Outward", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-12", "lines": [{"item_id": item["id"], "qty": 61, "batch_no": "B1"}]}, expect=400)
    assert "available" in r.json()["detail"]
    api.post("/api/warehouse/docs", {"doc_type": "Damage", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-15", "lines": [{"item_id": item["id"], "qty": 2, "batch_no": "B1", "remarks": "dented"}]})
    api.post("/api/warehouse/docs", {"doc_type": "Count", "warehouse_id": wh["id"], "customer_id": cust["id"], "doc_date": "2026-04-30", "lines": [{"item_id": item["id"], "qty": 57, "batch_no": "B1"}]})
    bal = api.get(f"/api/warehouse/stock?warehouse_id={wh['id']}")
    assert Decimal(bal[0]["balance"]) == 57
    scan = api.get(f"/api/warehouse/scan/ITEM:{item['sku']}|BATCH:B1")
    assert scan["type"] == "item" and scan["batch_no"] == "B1"
    assert api.get(f"/api/warehouse/labels?item_id={item['id']}&batch_no=B1").content[:4] == b"%PDF"
    wtreat = next(t for t in api.get("/api/r/gst_treatments")["items"] if t["code"] == "WAREHOUSE_18")
    api.post("/api/r/warehouse_rate_cards", {"customer_id": cust["id"], "warehouse_id": wh["id"], "storage_basis": "per_unit_day", "storage_rate": 1, "handling_in_rate": 5, "handling_out_rate": 5, "effective_from": "2026-04-01", "gst_treatment_id": wtreat["id"]})
    lines = api.post("/api/invoices/preview-warehouse", {"customer_id": cust["id"], "period_from": "2026-04-01", "period_to": "2026-04-30"})
    storage = Decimal(lines[0]["amount"])
    # 100 units × 10 days (1–10) + 60 × 4 (11–14) + 58 × 15 (15–29) + 57 × 1 (30)
    assert storage == Decimal(100 * 10 + 60 * 4 + 58 * 15 + 57)
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "basis": "warehouse", "period_from": "2026-04-01", "period_to": "2026-04-30", "gst_treatment_id": wtreat["id"], "invoice_date": "2026-04-30"})
    assert Decimal(inv["cgst"]) > 0 and inv["sac"] == "996729"
    reg = api.get(f"/api/reports/stock_movements?start=2026-04-01&end=2026-04-30&warehouse_id={wh['id']}")
    assert len(reg["rows"]) == 4  # inward, outward, damage, count adjustment


def test_document_expiry_alerts(api):
    v = make_vehicle(api, insurance_expiry=str(date.today() + timedelta(days=5)), fc_expiry=str(date.today() - timedelta(days=1)))
    d = make_driver(api, licence_expiry=str(date.today() + timedelta(days=10)))
    alerts = api.get("/api/alerts")
    titles = " | ".join(a["title"] for a in alerts)
    assert f"{v['registration_no']}: Insurance expires" in titles
    assert f"{v['registration_no']}: Fitness certificate expired" in titles
    assert f"{d['name']}: driving licence expires" in titles
    crit = next(a for a in alerts if v["registration_no"] in a["title"] and "Fitness" in a["title"])
    assert crit["severity"] == "critical"
    created = api.post("/api/alerts/run")["created"]
    assert created > 0
    assert api.post("/api/alerts/run")["created"] == 0  # deduplicated
    assert any(v["registration_no"] in n["title"] for n in api.get("/api/notifications"))
    # expired FC blocks allocation
    cust = make_customer(api)
    r = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B", "vehicle_id": v["id"]}, expect=400)
    assert "expired" in r.json()["detail"]


def test_compliance_never_auto_completes(api):
    tasks = api.get("/api/compliance/tasks")
    assert tasks and all(t["status"] == "Pending" for t in tasks)
    t = tasks[0]
    r = api.put(f"/api/compliance/tasks/{t['id']}", {"status": "Acknowledged"}, expect=400)
    assert "ARN" in r.json()["detail"]
    r = api.put(f"/api/compliance/tasks/{t['id']}", {"status": "Acknowledged", "arn": "AA3304260012345"}, expect=400)
    assert "Upload" in r.json()["detail"]
    ok = api.put(f"/api/compliance/tasks/{t['id']}", {"status": "Filed - Awaiting Ack", "arn": "AA3304260012345", "filed_on": str(date.today())})
    assert ok["status"] == "Filed - Awaiting Ack"


def test_documents_versions_and_access(client, api):
    pdf1 = b"%PDF-1.4 first"
    r = client.post("/api/documents/upload", headers=api.h, data={"title": "RC Book", "doc_type": "RC Book", "entity_type": "vehicle", "expiry_date": "2030-01-01"}, files={"file": ("rc.pdf", pdf1, "application/pdf")})
    assert r.status_code == 200, r.text
    did = r.json()["id"]
    r = client.post("/api/documents/upload", headers=api.h, data={"document_id": str(did)}, files={"file": ("rc2.pdf", b"%PDF-1.4 second", "application/pdf")})
    assert r.json()["current_version"] == 2
    assert client.get(f"/api/documents/{did}/download?version=1", headers=api.h).content == pdf1
    assert len(api.get(f"/api/documents/{did}/versions")) == 2
    bad = client.post("/api/documents/upload", headers=api.h, data={"title": "x", "doc_type": "Other"}, files={"file": ("x.pdf", b"\x89PNG fake", "application/pdf")})
    assert bad.status_code == 400
    exe = client.post("/api/documents/upload", headers=api.h, data={"title": "x", "doc_type": "Other"}, files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert exe.status_code == 400
    search = api.get("/api/r/documents?q=RC")
    assert any(d["id"] == did for d in search["items"])


def test_payroll(api):
    emp = api.post("/api/r/employees", {"code": uniq("E"), "name": "Payroll Clerk", "joining_date": "2025-01-01", "basic": 16000, "hra": 4000, "other_allowances": 0, "pf_applicable": True, "esi_applicable": True, "pt_applicable": True})
    api.post("/api/r/salary_advances", {"employee_id": emp["id"], "advance_date": "2026-01-05", "amount": 3000, "monthly_recovery": 1000, "mode": "Cash"})
    rows = [{"id": emp["id"], "status": "Absent"}]
    api.post("/api/attendance", {"person_type": "employee", "date": "2026-01-10", "rows": rows})
    for d in range(1, 32):
        if d != 10:
            api.post("/api/attendance", {"person_type": "employee", "date": f"2026-01-{d:02d}", "rows": [{"id": emp["id"], "status": "Present"}]})
    res = api.post("/api/payroll/2026-01/compute")
    slip = next(s for s in res["slips"] if s["person_id"] == emp["id"] and s["person_type"] == "employee")
    assert Decimal(slip["paid_days"]) == 30
    gross = Decimal("20000") * 30 / 31
    assert abs(Decimal(slip["gross"]) - gross) < 1
    assert Decimal(slip["pf_employee"]) == Decimal(1800)  # 12% of min(15483.87, 15000)
    assert Decimal(slip["esi_employee"]) == 146  # ceil(0.75% of 19354.84)
    assert Decimal(slip["advance_recovery"]) == 1000
    posted = api.post("/api/payroll/2026-01/post")
    assert posted["run"]["status"] == "Posted"
    api.post("/api/payroll/2026-01/compute", expect=400)
    assert api.get("/api/reports/trial_balance")["notes"] == ["Balanced"]


def test_fastag_import_and_matching(client, api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    v, d = make_vehicle(api), make_driver(api)
    t = api.post("/api/trips", {"customer_id": cust["id"], "from_place": "A", "to_place": "B", "vehicle_id": v["id"], "driver_id": d["id"]})
    api.post("/api/lr", lr_payload(cust["id"], trip_id=t["id"]))
    api.post(f"/api/trips/{t['id']}/stage", {"stage": "Dispatched", "start_km": 1000})
    wb = Workbook()
    ws = wb.active
    ws.append(["Transaction ID", "Transaction Date Time", "Vehicle Number", "Plaza Name", "Amount", "Type"])
    from datetime import timezone
    now = (datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(minutes=1)).strftime("%d-%m-%Y %H:%M:%S")
    ws.append([uniq("TX"), now, v["registration_no"], "Test Plaza", 455, "Debit"])
    ws.append([uniq("TX"), now, "TN00ZZ0000", "Other Plaza", 300, "Debit"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/fastag/import", headers=api.h, files={"file": ("fastag.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2 and r.json()["matched_to_trips"] == 1
    r2 = client.post("/api/fastag/import", headers=api.h, files={"file": ("fastag.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r2.json()["duplicates_skipped"] == 2
    f = next(x for x in api.get(f"/api/fastag?vehicle_id={v['id']}"))
    api.post(f"/api/fastag/{f['id']}/post-to-trip")
    trip = api.get(f"/api/trips/{t['id']}")
    assert any(e["category"] == "Toll" and e["paid_by"] == "FASTag" for e in trip["expenses"])


def test_reports_run_and_export(api):
    keys = [r["key"] for r in api.get("/api/reports")]
    assert len(keys) >= 35
    for k in keys:
        extra = ""
        if k == "ledger":
            extra = "&ledger_id=" + str(next(l for l in api.get("/api/ledgers/balances") if l["name"] == "Cash")["id"])
        if k == "customer_statement":
            extra = "&customer_id=" + str(api.get("/api/r/customers")["items"][0]["id"])
        r = api.c.get(f"/api/reports/{k}?start=2026-01-01&end={date.today()}{extra}", headers=api.h)
        assert r.status_code == 200, f"{k}: {r.text}"
        assert "columns" in r.json()
    for fmt, magic in (("xlsx", b"PK"), ("pdf", b"%PDF"), ("csv", b"\xef\xbb\xbf")):
        r = api.c.get(f"/api/reports/vehicle_profitability?format={fmt}", headers=api.h)
        assert r.status_code == 200 and r.content.startswith(magic)
    tally = api.c.get(f"/api/tally/vouchers?start=2026-01-01&end={date.today()}", headers=api.h)
    assert tally.content[:2] == b"PK"
    assert api.c.get("/api/export/all", headers=api.h).content[:2] == b"PK"
    dash = api.get("/api/dashboard")
    assert dash["fleet"]["total"] >= 1 and "receivables" in dash and len(dash["trend"]) == 6


def test_lr_pdf_formats_and_verification(client, api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    lr = api.post("/api/lr", lr_payload(cust["id"]))["lr"]
    assert api.c.get(f"/api/lr/{lr['id']}/pdf", headers=api.h).content[:4] == b"%PDF"
    assert api.c.get(f"/api/lr/{lr['id']}/pdf?fmt=thermal", headers=api.h).content[:4] == b"%PDF"
    url = lr["verify_url"].split("8000", 1)[1] if "8000" in lr["verify_url"] else lr["verify_url"]
    page = client.get(url)
    assert "Genuine" in page.text
    assert "could not be verified" in client.get(url.replace("?s=", "?s=0")).text
    share = api.post(f"/api/lr/{lr['id']}/share", {"channel": "whatsapp_link", "to": "9876543210"})
    assert share["url"].startswith("https://wa.me/919876543210")
    mail = api.post(f"/api/lr/{lr['id']}/share", {"channel": "email", "to": "test@example.com"})
    assert mail["status"] == "not_configured"


def test_einvoice_not_faked(api):
    cust = make_customer(api)
    make_contract(api, cust["id"])
    lr = api.post("/api/lr", lr_payload(cust["id"]))["lr"]
    inv = api.post("/api/invoices", {"customer_id": cust["id"], "lr_ids": [lr["id"]]})
    r = api.post(f"/api/invoices/{inv['id']}/einvoice", expect=409)
    assert "not configured" in r.json()["detail"]
    assert api.get(f"/api/invoices/{inv['id']}")["irn"] is None
    j = api.get(f"/api/invoices/{inv['id']}/einvoice-json")
    assert j["TranDtls"]["RegRev"] == "Y"


def test_backup_and_restore(client, api):
    cust = make_customer(api, name="Before Backup Co")
    b = api.post("/api/backups", {"note": "test"})
    assert b["status"] == "Verified"
    api.put(f"/api/r/customers/{cust['id']}", {"name": "Changed After Backup"})
    extra = make_customer(api)
    r = client.post("/api/backups/restore", headers=api.h, data={"confirm": "nope", "backup_id": str(b["id"])})
    assert r.status_code == 400
    r = client.post("/api/backups/restore", headers=api.h, data={"confirm": "RESTORE", "backup_id": str(b["id"])})
    assert r.status_code == 200, r.text
    assert r.json()["pre_restore_backup"].endswith("pre_restore.zip")
    assert api.get(f"/api/r/customers/{cust['id']}")["name"] == "Before Backup Co"
    assert api.c.get(f"/api/r/customers/{extra['id']}", headers=api.h).status_code == 404
    # numbering continues without duplicates after restore
    make_contract(api, cust["id"])
    api.post("/api/lr", lr_payload(cust["id"]))
    lst = api.get("/api/backups")
    assert any(x["kind"] == "pre_restore" for x in lst)
    assert api.post(f"/api/backups/{b['id']}/verify")["ok"]
