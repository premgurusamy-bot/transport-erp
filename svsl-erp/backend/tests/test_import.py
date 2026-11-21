"""Excel import with column mapping."""
import io
from decimal import Decimal

from openpyxl import Workbook

from .conftest import Api, login, uniq
from .test_security import make_user


def xlsx(rows, title="Fleet details – maintained by office"):
    wb = Workbook()
    ws = wb.active
    if title:
        ws.append([title])
        ws.append([])
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def upload(api, content, name="data.xlsx"):
    r = api.c.post("/api/import/upload", headers=api.h, files={"file": (name, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    return r.json()


def test_vehicle_import_with_own_headings(api):
    n1, n2 = uniq(), uniq()
    reg1, reg2 = f"TN 00 IM {n1[1:]:0>4}", f"TN00IM{n2[1:]:0>4}"
    content = xlsx([
        ["Lorry No", "Body Type", "Make", "Insurance Due", "FC Date", "Pollution", "Owned/Leased"],
        [reg1, "open body truck", "Ashok Leyland", "15/03/2027", "01-12-2026", "2027-01-31", "Owned"],
        [reg2, "Closed Body Truck", "Tata", "20-Apr-2027", "", "", "owned"],
        ["BADNUMBER", "Trailer (40 ft)", "BharatBenz", "31/31/2026", "", "", "Owned"],
    ])
    up = upload(api, content)
    sheet = up["sheets"][0]
    assert sheet["header_row"] == 3  # title rows skipped automatically
    p = api.post("/api/import/preview", {"file_id": up["file_id"], "sheet": sheet["name"], "header_row": 3, "target": "vehicles"})
    assert p["total"] == 3
    m = p["suggested"]
    assert m["registration_no"] == "Lorry No" and m["vehicle_type"] == "Body Type" and m["insurance_expiry"] == "Insurance Due"
    assert m["fc_expiry"] == "FC Date" and m["puc_expiry"] == "Pollution"
    m["ownership"] = "Owned/Leased"
    req = {"file_id": up["file_id"], "sheet": sheet["name"], "header_row": 3, "target": "vehicles", "mapping": m, "mode": "create"}
    v = api.post("/api/import/validate", req)
    assert v["summary"] == {"total": 3, "created": 2, "updated": 0, "skipped": 0, "errors": 1} and not v["committed"]
    bad = next(r for r in v["results"] if r["status"] == "error")
    assert bad["row"] == 6 and "Insurance" in bad["message"]
    assert api.get(f"/api/r/vehicles?q={reg2}")["total"] == 0  # validation saved nothing
    r = api.post("/api/import/run", req)
    assert not r["committed"] and "Nothing was imported" in r["message"]
    r = api.post("/api/import/run", req | {"skip_invalid": True})
    assert r["committed"] and r["summary"]["created"] == 2
    veh = api.get(f"/api/r/vehicles?q={reg1.replace(' ', '')}")["items"][0]
    assert veh["vehicle_type"] == "Open Body Truck" and veh["insurance_expiry"] == "2027-03-15" and veh["fc_expiry"] == "2026-12-01"
    # second import with new dates updates the same vehicles (matched by number, even with spaces)
    up2 = upload(api, xlsx([["Lorry No", "Insurance Due"], [reg1, "16/03/2028"]], title=None))
    r = api.post("/api/import/run", {"file_id": up2["file_id"], "header_row": 1, "target": "vehicles", "mapping": {"registration_no": "Lorry No", "insurance_expiry": "Insurance Due"}, "mode": "upsert"})
    assert r["summary"]["updated"] == 1 and r["committed"]
    assert api.get(f"/api/r/vehicles/{veh['id']}")["insurance_expiry"] == "2028-03-16"
    audit = api.get(f"/api/audit?entity=vehicles&entity_id={veh['id']}")["items"]
    assert any(a["reason"] == "Excel import" for a in audit)


def test_customers_with_reference_and_csv(api):
    code = uniq("IMPC")
    csv = f"Party Code,Party Name,GST No,Category,Credit Limit,Branch\n{code},Imported Customer Pvt Ltd,,Auto Components,\"2,50,000\",\n{code},Duplicate Row,,,,\n".encode()
    up = upload(api, csv, "parties.csv")
    p = api.post("/api/import/preview", {"file_id": up["file_id"], "header_row": 1, "target": "customers"})
    m = p["suggested"]
    assert m["code"] == "Party Code" and m["name"] == "Party Name" and m["gstin"] == "GST No" and m["credit_limit"] == "Credit Limit"
    r = api.post("/api/import/run", {"file_id": up["file_id"], "header_row": 1, "target": "customers", "mapping": m, "skip_invalid": True})
    assert r["summary"]["created"] == 1 and "Repeated" in r["results"][1]["message"]
    c = api.get(f"/api/r/customers?q={code}")["items"][0]
    assert Decimal(c["credit_limit"]) == 250000 and c["ledger_id"]  # same hooks as manual entry


def test_opening_balances_and_vouchers(api):
    led = f"Imported Party {uniq()}"
    up = upload(api, xlsx([["Account", "Dr", "Cr", "Under"], [led, "15,000", "", "Sundry Debtors"], ["Capital Account", "", "15000", ""], ["Unknown ledger X", "10", "", ""]], title=None))
    req = {"file_id": up["file_id"], "header_row": 1, "target": "opening_balances", "mapping": {"ledger": "Account", "debit": "Dr", "credit": "Cr", "group": "Under"}, "skip_invalid": True}
    r = api.post("/api/import/run", req)
    assert r["summary"]["created"] == 1 and r["summary"]["updated"] == 1 and r["summary"]["errors"] == 1
    bal = next(l for l in api.get("/api/ledgers/balances") if l["name"] == led)
    assert Decimal(bal["balance"]) == 15000
    up = upload(api, xlsx([["Vch No", "Date", "Ledger", "Debit", "Credit", "Remarks"],
                           ["J1", "01/04/2026", "Office Expenses", "500", "", "Tea"], ["J1", "01/04/2026", "Cash", "", "500", ""],
                           ["J2", "02/04/2026", "Office Expenses", "300", "", ""], ["J2", "02/04/2026", "Cash", "", "200", ""]], title=None))
    req = {"file_id": up["file_id"], "header_row": 1, "target": "vouchers", "mapping": {"voucher_ref": "Vch No", "voucher_date": "Date", "ledger": "Ledger", "debit": "Debit", "credit": "Credit", "narration": "Remarks"}}
    v = api.post("/api/import/validate", req)
    assert v["summary"]["created"] == 1 and "does not balance" in next(x for x in v["results"] if x["status"] == "error")["message"]
    r = api.post("/api/import/run", req | {"skip_invalid": True})
    assert r["committed"] and r["results"][0]["message"].startswith("JV/")


def test_templates_and_permissions(client, api):
    api.post("/api/import/templates", {"name": "Office fleet sheet", "target": "vehicles", "mapping": {"registration_no": "Lorry No"}, "header_row": 3})
    assert any(t["name"] == "Office fleet sheet" for t in api.get("/api/import/templates"))
    api.c.delete("/api/import/templates/vehicles/Office fleet sheet", headers=api.h)
    assert not any(t["name"] == "Office fleet sheet" for t in api.get("/api/import/templates"))
    disp = Api(client, login(client, make_user(api, "Dispatch Operator"), "Passw0rd!x"))
    up = upload(disp, xlsx([["Account", "Amount"], ["Cash", "100"]], title=None))
    r = disp.c.post("/api/import/run", headers=disp.h, json={"file_id": up["file_id"], "header_row": 1, "target": "opening_balances", "mapping": {"ledger": "Account", "opening_balance": "Amount"}})
    assert r.status_code == 403
    assert disp.get("/api/import/targets")["opening_balances"]["allowed"] is False
    assert api.c.get("/api/import/template/vehicles", headers=api.h).content[:2] == b"PK"


def test_accounts_summary(api):
    s = api.get("/api/accounts/summary")
    assert "cash_total" in s and "gst_net_payable" in s["taxes"] and isinstance(s["recent"], list) and s["books_balanced"] is True
