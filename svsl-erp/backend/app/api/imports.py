"""Excel/CSV import with column mapping, and the Accounts home summary."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable
from ..core.deps import AppError, CurrentUser, get_current_user, require
from ..core.money import D, ZERO, r2
from ..db import get_db
from ..services import exports, importer

router = APIRouter(prefix="/api", tags=["import, accounts"])


@router.get("/import/targets")
def import_targets(user: CurrentUser = Depends(get_current_user)):
    return {k: v | {"allowed": user.can(v["perm"])} for k, v in importer.targets().items()}


@router.post("/import/upload")
async def import_upload(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise AppError("File is larger than 25 MB")
    return importer.parse_upload(file.filename or "upload.xlsx", content)


@router.post("/import/preview")
def import_preview(data: dict, user: CurrentUser = Depends(get_current_user)):
    p = importer.preview(data.get("file_id"), data.get("sheet"), int(data.get("header_row") or 1))
    if data.get("target"):
        p["suggested"] = importer.suggest(data["target"], p["headers"])
    return p


@router.post("/import/validate")
def import_validate(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return jsonable(importer.run(db, user, data, commit=False))


@router.post("/import/run")
def import_run(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return jsonable(importer.run(db, user, data, commit=True))


@router.post("/import/errors.xlsx")
def import_errors(data: dict, user: CurrentUser = Depends(get_current_user)):
    rows = [r for r in data.get("results") or [] if r.get("status") in ("error", "skipped")]
    rep = {"title": "Import problems", "columns": [{"key": "row", "label": "Excel row", "type": "number"}, {"key": "key", "label": "Record"}, {"key": "status", "label": "Status"}, {"key": "message", "label": "Problem"}], "rows": rows}
    return Response(exports.report_xlsx(rep, "Import"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="import-problems.xlsx"'})


@router.get("/import/template/{target}")
def import_blank_template(target: str, user: CurrentUser = Depends(get_current_user)):
    """A blank Excel with the ERP's own headings – for people starting a new sheet."""
    t = importer.targets().get(target)
    if not t:
        raise AppError("Unknown import type", 404)
    rep = {"title": t["title"], "columns": [{"key": f["key"], "label": f["label"] + (" *" if f["required"] else "")} for f in t["fields"] if not f.get("secret")], "rows": []}
    return Response(exports.report_xlsx(rep, "Import template"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="template-{target}.xlsx"'})


@router.get("/import/templates")
def get_templates(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return importer.list_templates(db)


@router.post("/import/templates")
def put_template(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    t = importer.targets().get(data.get("target"))
    if not t or not user.can(t["perm"]):
        raise AppError("Not permitted", 403)
    out = importer.save_template(db, user, data)
    db.commit()
    return out


@router.delete("/import/templates/{target}/{name}")
def del_template(target: str, name: str, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    t = importer.targets().get(target)
    if not t or not user.can(t["perm"]):
        raise AppError("Not permitted", 403)
    out = importer.delete_template(db, user, target, name)
    db.commit()
    return out


# ------------------------------------------------------------------ accounts home

@router.get("/accounts/summary")
def accounts_summary(db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    from ..models import Invoice, VendorBill, Voucher
    from ..services import accounting as acc

    today = date.today()
    groups = acc.groups_map(db)
    bal = acc.ledger_balances(db, upto=today)
    cash, banks, recv, pay = [], [], ZERO, ZERO
    taxes = {"gst_output": ZERO, "gst_input": ZERO, "rcm": ZERO, "tds_payable": ZERO, "pf_esi_pt": ZERO}
    for b in bal.values():
        led, g = b["ledger"], groups[b["ledger"].group_id]
        c = b["closing"]
        if g.name == "Cash-in-Hand":
            cash.append({"id": led.id, "name": led.name, "balance": r2(c)})
        elif g.name == "Bank Accounts":
            banks.append({"id": led.id, "name": led.name, "balance": r2(c)})
        elif g.name == "Sundry Debtors":
            recv += c
        elif g.name == "Sundry Creditors":
            pay += -c
        key = led.system_key or ""
        if key in ("CGST_OUTPUT", "SGST_OUTPUT", "IGST_OUTPUT"):
            taxes["gst_output"] += -c
        elif key in ("CGST_INPUT", "SGST_INPUT", "IGST_INPUT"):
            taxes["gst_input"] += c
        elif key == "RCM_PAYABLE":
            taxes["rcm"] += -c
        elif key == "TDS_PAYABLE":
            taxes["tds_payable"] += -c
        elif key in ("PF_PAYABLE", "ESI_PAYABLE", "PT_PAYABLE"):
            taxes["pf_esi_pt"] += -c
    ms = today.replace(day=1)
    p = acc.profit_and_loss(db, ms, today)
    overdue = db.query(Invoice).filter(Invoice.status.in_(["Issued", "Partly Paid"]), Invoice.due_date < today, Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note"])).count()
    recent = db.query(Voucher).order_by(Voucher.id.desc()).limit(12).all()
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    tb = acc.trial_balance(db, fy_start, today)
    # month-on-month figures (this month to date vs the whole of last month)
    lm_end = ms - timedelta(days=1)
    lm_start = lm_end.replace(day=1)

    def vsum(vtype, a, b):
        return r2(D(db.execute(select(func.coalesce(func.sum(Voucher.total), 0)).where(Voucher.voucher_type == vtype, Voucher.status == "Posted", Voucher.voucher_date.between(a, b))).scalar()))

    def sales(a, b):
        tot = ZERO
        for i in db.query(Invoice).filter(Invoice.status != "Cancelled", Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note", "credit_note"]), Invoice.invoice_date.between(a, b)):
            tot += D(i.total) * (-1 if i.doc_type == "credit_note" else 1)
        return r2(tot)

    def purchases(a, b):
        return r2(D(db.execute(select(func.coalesce(func.sum(VendorBill.total), 0)).where(VendorBill.status != "Cancelled", VendorBill.bill_date.between(a, b))).scalar()))

    buckets = ["Not due", "0-30", "31-60", "61-90", "90+"]

    def ageing(kind):
        tot = {b: ZERO for b in buckets}
        for r in acc.ageing(db, kind, today):
            tot[r["bucket"]] += D(r["balance"])
        return [{"bucket": b, "amount": r2(tot[b])} for b in buckets]

    import calendar

    fy_trend, m = [], fy_start
    while m <= today:
        me = date(m.year, m.month, calendar.monthrange(m.year, m.month)[1])
        mp = acc.profit_and_loss(db, m, min(me, today))
        inc = r2(mp["totals"]["Direct Incomes"] + mp["totals"]["Indirect Incomes"])
        exp = r2(mp["totals"]["Direct Expenses"] + mp["totals"]["Indirect Expenses"])
        fy_trend.append({"month": m.strftime("%b"), "income": inc, "expenses": exp, "net": mp["net_profit"]})
        m = me + timedelta(days=1)
    fyp = acc.profit_and_loss(db, fy_start, today)
    return jsonable({
        "cash": cash, "banks": banks, "cash_total": r2(sum((x["balance"] for x in cash), ZERO)), "bank_total": r2(sum((x["balance"] for x in banks), ZERO)),
        "receivables": r2(recv), "payables": r2(pay), "overdue_invoices": overdue,
        "taxes": {k: r2(v) for k, v in taxes.items()} | {"gst_net_payable": r2(taxes["gst_output"] - taxes["gst_input"])},
        "month": {"income": r2(p["totals"]["Direct Incomes"] + p["totals"]["Indirect Incomes"]), "expenses": r2(p["totals"]["Direct Expenses"] + p["totals"]["Indirect Expenses"]), "net_profit": p["net_profit"]},
        "books_balanced": tb["balanced"],
        "compare": {
            "billing": {"this": sales(ms, today), "last": sales(lm_start, lm_end)},
            "purchases": {"this": purchases(ms, today), "last": purchases(lm_start, lm_end)},
            "receipts": {"this": vsum("Receipt", ms, today), "last": vsum("Receipt", lm_start, lm_end)},
            "payments": {"this": vsum("Payment", ms, today), "last": vsum("Payment", lm_start, lm_end)},
        },
        "ar_ageing": ageing("customer"), "ap_ageing": ageing("supplier"),
        "fy": {"start": fy_start, "income": r2(fyp["totals"]["Direct Incomes"] + fyp["totals"]["Indirect Incomes"]), "expenses": r2(fyp["totals"]["Direct Expenses"] + fyp["totals"]["Indirect Expenses"]), "net_profit": fyp["net_profit"], "trend": fy_trend},
        "recent": [{"id": v.id, "date": v.voucher_date, "no": v.voucher_no, "type": v.voucher_type, "narration": v.narration, "total": v.total, "status": v.status} for v in recent],
    })
