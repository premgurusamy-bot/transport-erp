"""Account groups inside the main groups, grouped statements and per-person salary ledgers."""
from decimal import Decimal

from tests.conftest import uniq


def _group_id(api, name):
    return next(g["id"] for g in api.get("/api/account-groups") if g["name"] == name)


def _find(nodes, name):
    for n in nodes:
        if n["name"] == name:
            return n
        hit = _find(n["groups"], name)
        if hit:
            return hit
    return None


def test_groups_tree_and_grouped_statements(api, client, admin):
    ie = _group_id(api, "Indirect Expenses")
    led_a = api.post("/api/r/ledgers", {"name": f"Prem Salary {uniq()}", "group_id": ie})
    led_b = api.post("/api/r/ledgers", {"name": f"Meena Salary {uniq()}", "group_id": ie})
    gname = f"Staff Salaries {uniq()}"
    g = api.post("/api/account-groups", {"name": gname, "parent_id": ie, "ledger_ids": [led_a["id"], led_b["id"]]})
    assert g["moved"] == 2
    # a sub-group inside the new group, and the path shown in pickers
    sub = api.post("/api/account-groups", {"name": f"Part-time {uniq()}", "parent_id": g["id"]})
    assert any(x["id"] == sub["id"] and x["path"].startswith("Indirect Expenses › ") for x in api.get("/api/account-groups"))

    cash = next(l for l in api.get("/api/ledgers/balances") if l["name"] == "Cash")
    api.post("/api/vouchers", {"voucher_type": "Payment", "date": "2026-11-10", "narration": "salary",
                               "lines": [{"ledger_id": led_a["id"], "debit": 12000}, {"ledger_id": led_b["id"], "debit": 8000}, {"ledger_id": cash["id"], "credit": 20000}]})

    tree = api.get("/api/account-groups/tree")
    node = _find(tree, gname)
    assert Decimal(node["total"]) == Decimal(20000) and node["ledger_count"] == 2 and not node["system"]
    assert Decimal(_find(tree, "Indirect Expenses")["total"]) >= Decimal(20000)

    detailed = api.get("/api/reports/profit_loss?start=2026-04-01&end=2026-11-30")
    summary = api.get("/api/reports/profit_loss?start=2026-04-01&end=2026-11-30&detail=0")
    grp = next(r for r in detailed["rows"] if r["head"].strip(" ") == gname)
    assert grp["_bold"] and Decimal(grp["amount"]) == Decimal(20000)
    assert any(r["head"].strip(" ") == led_a["name"] for r in detailed["rows"])
    assert any(r["head"].strip(" ") == gname for r in summary["rows"])
    assert not any(r["head"].strip(" ") == led_a["name"] for r in summary["rows"])  # folded into the group in summary
    tb = api.get("/api/reports/trial_balance?detail=0")
    assert tb["notes"] == ["Balanced"] and tb["totals"]["debit"] == tb["totals"]["credit"]
    assert api.get("/api/reports/balance_sheet")["notes"] == ["Difference: 0.00"]
    for fmt in ("pdf", "xlsx"):
        assert client.get(f"/api/reports/profit_loss?format={fmt}", headers=admin).status_code == 200

    # rename, move, delete rules
    api.put(f"/api/account-groups/{g['id']}", {"name": gname + " (office)"})
    assert api.put(f"/api/account-groups/{ie}", {"name": "Other"}, expect=400)
    assert api.put(f"/api/account-groups/{g['id']}", {"parent_id": sub["id"]}, expect=400)  # not inside itself
    assert api.put(f"/api/account-groups/{g['id']}", {"parent_id": _group_id(api, "Current Assets")}, expect=400)  # expense → asset
    assert client.delete(f"/api/account-groups/{g['id']}", headers=admin).status_code == 400  # still has ledgers
    assert client.delete(f"/api/account-groups/{sub['id']}", headers=admin).status_code == 200


def test_group_safety_rules(api):
    debtors = _group_id(api, "Sundry Debtors")
    api.post("/api/account-groups", {"name": f"Chennai debtors {uniq()}", "parent_id": debtors}, expect=400)
    income = api.post("/api/r/ledgers", {"name": f"Scrap sale {uniq()}", "group_id": _group_id(api, "Indirect Incomes")})
    g = api.post("/api/account-groups", {"name": f"Admin costs {uniq()}", "parent_id": _group_id(api, "Indirect Expenses")})
    r = api.post(f"/api/account-groups/{g['id']}/ledgers", {"ledger_ids": [income["id"]]}, expect=400)
    assert "income" in r.json()["detail"]
    cust = api.post("/api/r/customers", {"code": uniq("C"), "name": f"Group Rule Customer {uniq()}", "billing_state_code": "33"})
    r = api.post(f"/api/account-groups/{g['id']}/ledgers", {"ledger_ids": [api.get(f"/api/r/customers/{cust['id']}")["ledger_id"]]}, expect=400)
    assert "Sundry Debtors" in r.json()["detail"]
    api.post("/api/account-groups", {"name": "Indirect Expenses", "parent_id": _group_id(api, "Direct Expenses")}, expect=400)  # duplicate name


def test_group_path_in_import_and_salary_ledgers(api):
    from app.db import SessionLocal
    from app.models import AccountGroup, Ledger
    from app.services import accounting as acc

    db = SessionLocal()
    try:
        gid = acc.resolve_group_path(db, f"Indirect Expenses › Imported {uniq()} > Level 2 {uniq()}")
        g = db.get(AccountGroup, gid)
        parent = db.get(AccountGroup, g.parent_id)
        assert db.get(AccountGroup, parent.parent_id).name == "Indirect Expenses" and not g.is_system
        db.rollback()
    finally:
        db.close()
    emp = api.post("/api/r/employees", {"code": uniq("E"), "name": f"Meena {uniq()}", "joining_date": "2025-01-01", "basic": 15000})
    db = SessionLocal()
    try:
        led = db.query(Ledger).filter_by(party_type="sal_emp", party_id=emp["id"]).one()
        assert led.name == f"{emp['name']} Salary"
        assert db.get(AccountGroup, led.group_id).name == "Salaries"
    finally:
        db.close()
    assert api.post("/api/payroll/salary-ledgers")["total"] >= 1
