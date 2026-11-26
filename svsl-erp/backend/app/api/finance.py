"""Invoices & GST, receipts, vouchers, bank reconciliation, Tally export/import, purchase & vendor bills."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log
from ..core.deps import AppError, CurrentUser, require
from ..core.money import D, ZERO, r2
from ..db import get_db
from ..integrations import channels, gst_portals
from ..models import (
    AccountGroup, BankAccount, BankStatementLine, BillAllocation, Customer, GoodsReceipt, GstTreatment, Invoice, InvoiceLine,
    Ledger, PurchaseOrder, Vendor, VendorBill, Voucher, VoucherEntry,
)
from ..services import accounting as acc
from ..services import billing, business, exports, pdf
from ..services import settings as app_settings

router = APIRouter(prefix="/api", tags=["finance"])


def _inv_out(db: Session, inv: Invoice, full: bool = False) -> dict:
    out = {c.name: jsonable(getattr(inv, c.name)) for c in Invoice.__table__.columns}
    out["balance"] = jsonable(r2(D(inv.total) - D(inv.amount_received))) if inv.doc_type not in ("proforma", "advance_receipt") else None
    if full:
        out["lines"] = [jsonable({c.name: getattr(l, c.name) for c in InvoiceLine.__table__.columns}) for l in db.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.line_no)]
        out["receipts"] = [jsonable({"voucher_id": a.voucher_id, "voucher_no": db.get(Voucher, a.voucher_id).voucher_no, "amount": a.amount, "tds": a.tds_amount, "reversed": a.reversed}) for a in db.query(BillAllocation).filter_by(invoice_id=inv.id)]
        out["notes"] = [{"id": n.id, "invoice_no": n.invoice_no, "doc_type": n.doc_type, "total": jsonable(n.total), "status": n.status} for n in db.query(Invoice).filter_by(reference_invoice_id=inv.id)]
    return out


# ------------------------------------------------------------------ invoices

@router.get("/invoices")
def list_invoices(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    p = request.query_params
    q = db.query(Invoice)
    if p.get("customer_id"):
        q = q.filter(Invoice.customer_id == int(p["customer_id"]))
    if p.get("doc_type"):
        q = q.filter(Invoice.doc_type == p["doc_type"])
    if p.get("status"):
        q = q.filter(Invoice.status.in_(p["status"].split(",")))
    if p.get("q"):
        q = q.filter(or_(Invoice.invoice_no.ilike(f"%{p['q']}%"), Invoice.billing_name.ilike(f"%{p['q']}%")))
    if p.get("from"):
        q = q.filter(Invoice.invoice_date >= date.fromisoformat(p["from"]))
    if p.get("to"):
        q = q.filter(Invoice.invoice_date <= date.fromisoformat(p["to"]))
    total = q.count()
    rows = q.order_by(Invoice.id.desc()).limit(min(int(p.get("limit") or 100), 1000)).offset(int(p.get("offset") or 0)).all()
    return {"total": total, "items": [_inv_out(db, i) for i in rows]}


@router.post("/invoices")
def create_invoice(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:write"))):
    if data.get("doc_type") == "credit_note" and not user.can("invoices:cancel"):
        raise AppError("Credit notes need the 'invoices:cancel' permission", 403)
    if data.get("basis") == "warehouse" and not data.get("lines"):
        start, end = date.fromisoformat(data["period_from"]), date.fromisoformat(data["period_to"])
        data = {**data, "lines": business.warehouse_bill_lines(db, int(data["customer_id"]), start, end)}
    inv = billing.create_invoice(db, user, data)
    db.commit()
    return _inv_out(db, inv, True)


@router.post("/invoices/preview-warehouse")
def preview_warehouse(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    return jsonable(business.warehouse_bill_lines(db, int(data["customer_id"]), date.fromisoformat(data["period_from"]), date.fromisoformat(data["period_to"])))


@router.get("/invoices/{iid}")
def get_invoice(iid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    inv = db.get(Invoice, iid)
    if not inv:
        raise AppError("Invoice not found", 404)
    return _inv_out(db, inv, True)


def invoice_pdf_bytes(db: Session, inv: Invoice) -> bytes:
    company = app_settings.company(db)
    cust = db.get(Customer, inv.customer_id)
    lines = db.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.line_no).all()
    bank = db.query(BankAccount).filter_by(is_active=True, print_on_invoice=True).order_by(BankAccount.id).first() if app_settings.get(db, "invoice")["show_bank_details"] else None
    ref = db.get(Invoice, inv.reference_invoice_id) if inv.reference_invoice_id else None
    from ..services import layouts

    return pdf.invoice_pdf(inv, company, cust, lines, bank, db.get(GstTreatment, inv.gst_treatment_id) if inv.gst_treatment_id else None, ref, layouts.get(db, "invoice"))


@router.get("/invoices/{iid}/pdf")
def invoice_pdf(iid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    inv = db.get(Invoice, iid)
    if not inv:
        raise AppError("Not found", 404)
    return Response(invoice_pdf_bytes(db, inv), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{inv.invoice_no.replace("/", "-")}.pdf"'})


@router.post("/invoices/{iid}/cancel")
def cancel_invoice(iid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:cancel"))):
    inv = billing.cancel_invoice(db, user, iid, data.get("reason") or "")
    db.commit()
    return _inv_out(db, inv)


@router.post("/invoices/{iid}/share")
def share_invoice(iid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    inv = db.get(Invoice, iid)
    cust = db.get(Customer, inv.customer_id)
    text = f"Invoice {inv.invoice_no} dt {inv.invoice_date:%d-%m-%Y} for ₹{inv.total}. Verify: {pdf.verify_url('inv', inv.invoice_no, inv.verify_token)}"
    if data.get("channel") == "email":
        to = data.get("to") or cust.email
        if not to:
            raise AppError("Customer has no email address")
        status, err = channels.send_email(to, f"Invoice {inv.invoice_no}", text, [(f"{inv.invoice_no.replace('/', '-')}.pdf", invoice_pdf_bytes(db, inv), "application/pdf")])
        return {"status": status, "error": err}
    return {"status": "link", "url": channels.whatsapp_share_link(data.get("to") or cust.whatsapp or cust.mobile, text)}


@router.get("/invoices/{iid}/einvoice-json")
def einvoice_json(iid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:read"))):
    inv = db.get(Invoice, iid)
    lines = db.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.line_no).all()
    return gst_portals.build_einvoice_json(inv, app_settings.company(db), db.get(Customer, inv.customer_id), lines)


@router.post("/invoices/{iid}/einvoice")
def einvoice_generate(iid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:write"))):
    inv = db.get(Invoice, iid)
    if not inv or inv.status == "Cancelled":
        raise AppError("Invoice not found or cancelled")
    if inv.irn:
        raise AppError("IRN already generated")
    lines = db.query(InvoiceLine).filter_by(invoice_id=inv.id).order_by(InvoiceLine.line_no).all()
    payload = gst_portals.build_einvoice_json(inv, app_settings.company(db), db.get(Customer, inv.customer_id), lines)
    try:
        res = gst_portals.generate_irn(payload)
    except gst_portals.NotConfigured as exc:
        raise AppError(str(exc), 409)
    except gst_portals.PortalError as exc:
        inv.einvoice_status, inv.einvoice_error = "Failed", str(exc)[:1000]
        db.commit()
        raise AppError(str(exc), 502)
    inv.irn, inv.ack_no, inv.signed_qr, inv.einvoice_status, inv.einvoice_error = res["irn"], res["ack_no"], res["signed_qr"], "Generated", None
    inv.ack_date = datetime.now(timezone.utc)
    log(db, user, "einvoice", "invoices", inv.id, None, {"irn": inv.irn, "ack_no": inv.ack_no})
    db.commit()
    return _inv_out(db, inv)


@router.post("/invoices/{iid}/einvoice/record")
def einvoice_record(iid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:write"))):
    """Record an IRN obtained on the IRP portal (offline/bulk tool). The user attests that the IRP issued it."""
    inv = db.get(Invoice, iid)
    if not inv or inv.status == "Cancelled":
        raise AppError("Invoice not found or cancelled")
    irn = (data.get("irn") or "").strip()
    if len(irn) != 64 or not all(c in "0123456789abcdefABCDEF" for c in irn):
        raise AppError("IRN must be the 64-character hash shown by the IRP")
    if not data.get("ack_no"):
        raise AppError("Acknowledgement number is required")
    inv.irn, inv.ack_no, inv.signed_qr = irn.lower(), str(data["ack_no"]), data.get("signed_qr") or None
    inv.ack_date = datetime.fromisoformat(data["ack_date"]).replace(tzinfo=timezone.utc) if data.get("ack_date") else datetime.now(timezone.utc)
    inv.einvoice_status = "Generated"
    log(db, user, "einvoice_record", "invoices", inv.id, None, {"irn": inv.irn, "ack_no": inv.ack_no}, "IRN recorded from IRP portal")
    db.commit()
    return _inv_out(db, inv)


@router.post("/invoices/{iid}/einvoice/cancelled")
def einvoice_cancelled(iid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("invoices:cancel"))):
    inv = db.get(Invoice, iid)
    if not inv or inv.einvoice_status != "Generated":
        raise AppError("No active IRN on this invoice")
    if inv.ack_date and datetime.now(timezone.utc) - inv.ack_date > timedelta(hours=24):
        raise AppError("IRN is older than 24 hours – the IRP does not allow cancellation; issue a credit note")
    if not data.get("confirmation"):
        raise AppError("Enter the IRP cancellation confirmation / date shown on the portal")
    if gst_portals.irp_configured():
        try:
            gst_portals.cancel_irn(inv.irn, data.get("reason_code") or "2", data.get("remarks") or "")
        except (gst_portals.PortalError, gst_portals.NotConfigured) as exc:
            raise AppError(str(exc))
    inv.einvoice_status = "Cancelled"
    log(db, user, "einvoice_cancel", "invoices", inv.id, None, {"irn": inv.irn, "confirmation": data["confirmation"]})
    db.commit()
    return _inv_out(db, inv)


@router.post("/receipts")
def receipt(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    v = billing.record_receipt(db, user, data)
    db.commit()
    return {"voucher_id": v.id, "voucher_no": v.voucher_no}


@router.get("/customers/{cid}/summary")
def customer_summary(cid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("customers:read"))):
    from ..models import Consignment, Trip
    from ..services.operations import credit_warning, trip_pnl

    c = db.get(Customer, cid)
    if not c:
        raise AppError("Not found", 404)
    bal = acc.ledger_balance(db, c.ledger_id) if c.ledger_id else ZERO
    trips = db.query(Trip).filter(Trip.customer_id == cid, Trip.stage != "Cancelled").order_by(Trip.id.desc()).limit(50).all()
    rev = exp = ZERO
    for t in db.query(Trip).filter(Trip.customer_id == cid, Trip.stage != "Cancelled"):
        p = trip_pnl(db, t)
        rev += p["revenue"]
        exp += p["expenses"]
    unbilled = db.query(Consignment).filter(Consignment.customer_id == cid, Consignment.invoice_id.is_(None), Consignment.status != "Cancelled").count()
    return jsonable({"outstanding": bal, "credit_limit": c.credit_limit, "credit_warning": credit_warning(db, c, ZERO), "revenue": rev, "trip_expenses": exp, "profit": rev - exp, "unbilled_lrs": unbilled,
                     "contract_end": c.contract_end, "recent_trips": [{"id": t.id, "trip_no": t.trip_no, "date": t.trip_date, "route": f"{t.from_place} → {t.to_place}", "stage": t.stage} for t in trips]})


# ------------------------------------------------------------------ vouchers & ledgers

@router.get("/vouchers")
def list_vouchers(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    p = request.query_params
    q = db.query(Voucher)
    if p.get("type"):
        q = q.filter(Voucher.voucher_type == p["type"])
    if p.get("from"):
        q = q.filter(Voucher.voucher_date >= date.fromisoformat(p["from"]))
    if p.get("to"):
        q = q.filter(Voucher.voucher_date <= date.fromisoformat(p["to"]))
    if p.get("q"):
        q = q.filter(or_(Voucher.voucher_no.ilike(f"%{p['q']}%"), Voucher.narration.ilike(f"%{p['q']}%"), Voucher.reference.ilike(f"%{p['q']}%")))
    for key, col in (("vehicle_id", VoucherEntry.cost_vehicle_id), ("trip_id", VoucherEntry.cost_trip_id), ("ledger_id", VoucherEntry.ledger_id)):
        if p.get(key):  # vouchers with at least one line for this vehicle / trip / ledger
            q = q.filter(Voucher.id.in_(select(VoucherEntry.voucher_id).where(col == int(p[key]))))
    total = q.count()
    rows = q.order_by(Voucher.voucher_date.desc(), Voucher.id.desc()).limit(min(int(p.get("limit") or 100), 1000)).offset(int(p.get("offset") or 0)).all()
    return {"total": total, "items": [jsonable({c.name: getattr(v, c.name) for c in Voucher.__table__.columns}) for v in rows]}


@router.get("/vouchers/{vid}")
def get_voucher(vid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    v = db.get(Voucher, vid)
    if not v:
        raise AppError("Not found", 404)
    names = {l.id: l.name for l in db.query(Ledger)}
    out = jsonable({c.name: getattr(v, c.name) for c in Voucher.__table__.columns})
    out["entries"] = [jsonable({"ledger_id": e.ledger_id, "ledger": names.get(e.ledger_id), "debit": e.debit, "credit": e.credit, "narration": e.narration, "reconciled_on": e.bank_reconciled_on}) for e in db.query(VoucherEntry).filter_by(voucher_id=v.id).order_by(VoucherEntry.id)]
    return out


@router.post("/vouchers")
def create_voucher(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    vtype = data.get("voucher_type")
    if vtype not in ("Journal", "Payment", "Receipt", "Contra"):
        raise AppError("Manual vouchers: Journal, Payment, Receipt or Contra. Sales/purchase come from invoices and vendor bills.")
    lines = data.get("lines") or []
    groups = acc.groups_map(db)
    ledgers = {l.id: l for l in db.query(Ledger)}
    cashbank = lambda lid: lid in ledgers and groups[ledgers[lid].group_id].cash_flow == "cash"  # noqa: E731
    if vtype == "Contra" and not all(cashbank(int(l["ledger_id"])) for l in lines if l.get("ledger_id")):
        raise AppError("Contra entries can only use cash and bank ledgers")
    if vtype in ("Payment", "Receipt") and not any(cashbank(int(l["ledger_id"])) for l in lines if l.get("ledger_id")):
        raise AppError(f"A {vtype.lower()} voucher must include a cash or bank ledger")
    clean = [{"ledger_id": int(l["ledger_id"]), "debit": D(l.get("debit")), "credit": D(l.get("credit")), "narration": l.get("narration"), "instrument_no": l.get("instrument_no")} for l in lines if l.get("ledger_id")]
    v = acc.post(db, user, vtype, date.fromisoformat(str(data.get("voucher_date") or date.today())[:10]), clean, data.get("narration") or "", "manual", None, data.get("reference"))
    db.commit()
    return {"id": v.id, "voucher_no": v.voucher_no}


@router.post("/vouchers/{vid}/cancel")
def cancel_voucher(vid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:cancel"))):
    v = db.get(Voucher, vid)
    if not v:
        raise AppError("Not found", 404)
    if v.source_type in ("invoice",):
        raise AppError("This voucher belongs to an invoice – cancel the invoice instead")
    if v.source_type in ("vendor_bill",):
        raise AppError("This voucher belongs to a vendor bill – cancel the bill instead")
    rev = acc.reverse(db, user, vid, data.get("reason") or "")
    db.commit()
    return {"reversal_id": rev.id, "reversal_no": rev.voucher_no}


@router.get("/ledgers/balances")
def ledger_balances(on: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    d = date.fromisoformat(on) if on else date.today()
    groups = acc.groups_map(db)
    out = []
    for lid, b in acc.ledger_balances(db, upto=d).items():
        led = b["ledger"]
        out.append({"id": lid, "name": led.name, "group": groups[led.group_id].name, "nature": acc.top_group(groups, led.group_id).nature, "balance": jsonable(r2(b["closing"])), "party_type": led.party_type, "is_active": led.is_active})
    return sorted(out, key=lambda r: (r["group"], r["name"]))


@router.get("/account-groups")
def account_groups(db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    return [{"id": g.id, "label": g.name, "name": g.name, "parent_id": g.parent_id, "nature": g.nature} for g in db.query(AccountGroup).order_by(AccountGroup.name)]


# ------------------------------------------------------------------ bank reconciliation

@router.post("/bank/{ledger_id}/statement")
async def import_statement(ledger_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    led = db.get(Ledger, ledger_id)
    if not led or not led.is_bank:
        raise AppError("Select a bank ledger")
    rows = exports.read_table(file.filename or "", await file.read())
    batch, added, errors = uuid.uuid4().hex[:10], 0, []
    for i, r in enumerate(rows, 2):
        d = exports.pick(r, "date", "txn date", "transaction date", "value date", "tran date")
        desc = exports.pick(r, "description", "narration", "particulars", "remarks")
        ref = exports.pick(r, "reference", "ref no", "cheque no", "chq/ref no", "utr", "ref no./cheque no.")
        wd = exports.pick(r, "withdrawal", "debit", "withdrawal amt", "dr", "withdrawal amount")
        dep = exports.pick(r, "deposit", "credit", "deposit amt", "cr", "deposit amount")
        if not d:
            continue
        try:
            if isinstance(d, datetime):
                dd = d.date()
            elif isinstance(d, date):
                dd = d
            else:
                s = str(d).strip()
                dd = None
                for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%y"):
                    try:
                        dd = datetime.strptime(s, fmt).date()
                        break
                    except ValueError:
                        continue
                if not dd:
                    raise ValueError(f"date '{s}'")
            line = BankStatementLine(ledger_id=ledger_id, txn_date=dd, description=str(desc or "")[:300], reference=str(ref or "")[:80], debit=abs(D(str(wd or 0).replace(",", ""))), credit=abs(D(str(dep or 0).replace(",", ""))), import_batch=batch)
        except (ValueError, ArithmeticError) as exc:
            errors.append(f"Row {i}: invalid {exc}")
            continue
        exists = db.query(BankStatementLine).filter_by(ledger_id=ledger_id, txn_date=line.txn_date, reference=line.reference, debit=line.debit, credit=line.credit).first()
        if exists:
            continue
        db.add(line)
        added += 1
    db.flush()
    matched = auto_reconcile(db, ledger_id)
    db.commit()
    return {"added": added, "auto_matched": matched, "errors": errors[:50]}


def auto_reconcile(db: Session, ledger_id: int) -> int:
    n = 0
    for line in db.query(BankStatementLine).filter(BankStatementLine.ledger_id == ledger_id, BankStatementLine.matched_entry_id.is_(None)):
        amt_dr, amt_cr = D(line.credit), D(line.debit)  # deposit = book debit on bank ledger
        q = (db.query(VoucherEntry).join(Voucher, Voucher.id == VoucherEntry.voucher_id)
             .filter(VoucherEntry.ledger_id == ledger_id, VoucherEntry.bank_reconciled_on.is_(None), Voucher.status == "Posted",
                     Voucher.voucher_date.between(line.txn_date - timedelta(days=7), line.txn_date + timedelta(days=3))))
        q = q.filter(VoucherEntry.debit == amt_dr) if amt_dr > 0 else q.filter(VoucherEntry.credit == amt_cr)
        cands = q.all()
        if line.reference:
            exact = [c for c in cands if c.instrument_no and c.instrument_no in line.reference]
            cands = exact or cands
        if len(cands) == 1:
            cands[0].bank_reconciled_on, cands[0].bank_statement_line_id = line.txn_date, line.id
            line.matched_entry_id = cands[0].id
            n += 1
    return n


@router.get("/bank/{ledger_id}/reconciliation")
def reconciliation(ledger_id: int, on: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    d = date.fromisoformat(on) if on else date.today()
    book = acc.ledger_balance(db, ledger_id, d)
    unrec = (db.query(VoucherEntry, Voucher).join(Voucher, Voucher.id == VoucherEntry.voucher_id)
             .filter(VoucherEntry.ledger_id == ledger_id, VoucherEntry.bank_reconciled_on.is_(None), Voucher.voucher_date <= d).order_by(Voucher.voucher_date).all())
    deposits_not_credited = sum((D(e.debit) for e, v in unrec), ZERO)
    cheques_not_presented = sum((D(e.credit) for e, v in unrec), ZERO)
    lines = db.query(BankStatementLine).filter(BankStatementLine.ledger_id == ledger_id, BankStatementLine.matched_entry_id.is_(None)).order_by(BankStatementLine.txn_date).all()
    return jsonable({
        "book_balance": r2(book), "deposits_not_credited": r2(deposits_not_credited), "cheques_not_presented": r2(cheques_not_presented),
        "balance_as_per_bank": r2(book - deposits_not_credited + cheques_not_presented),
        "unreconciled_entries": [{"entry_id": e.id, "date": v.voucher_date, "voucher_no": v.voucher_no, "narration": v.narration, "debit": e.debit, "credit": e.credit, "instrument_no": e.instrument_no} for e, v in unrec],
        "unmatched_statement_lines": [{"id": l.id, "date": l.txn_date, "description": l.description, "reference": l.reference, "withdrawal": l.debit, "deposit": l.credit} for l in lines],
    })


@router.post("/bank/reconcile")
def reconcile_manual(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    e = db.get(VoucherEntry, int(data["entry_id"]))
    if not e:
        raise AppError("Entry not found", 404)
    if data.get("unreconcile"):
        if e.bank_statement_line_id:
            line = db.get(BankStatementLine, e.bank_statement_line_id)
            if line:
                line.matched_entry_id = None
        e.bank_reconciled_on, e.bank_statement_line_id = None, None
    else:
        e.bank_reconciled_on = date.fromisoformat(data.get("date") or str(date.today()))
        if data.get("statement_line_id"):
            line = db.get(BankStatementLine, int(data["statement_line_id"]))
            line.matched_entry_id = e.id
            e.bank_statement_line_id = line.id
    log(db, user, "reconcile", "voucher_entries", e.id, None, {"reconciled_on": jsonable(e.bank_reconciled_on)})
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ Tally

@router.get("/tally/vouchers")
def tally_vouchers(start: str, end: str, fmt: str = "xlsx", db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    names = {l.id: l.name for l in db.query(Ledger)}
    rows = []
    q = db.query(Voucher).filter(Voucher.voucher_date.between(date.fromisoformat(start), date.fromisoformat(end)), Voucher.status != "Cancelled", Voucher.status != "Reversal").order_by(Voucher.voucher_date, Voucher.id)
    from ..models import Vehicle

    veh = {v.id: v.registration_no for v in db.query(Vehicle)}
    for v in q:
        for e in db.query(VoucherEntry).filter_by(voucher_id=v.id).order_by(VoucherEntry.id):
            rows.append({"Date": v.voucher_date, "Voucher Type": v.voucher_type, "Voucher Number": v.voucher_no, "Ledger Name": names.get(e.ledger_id), "Dr/Cr": "Dr" if D(e.debit) > 0 else "Cr",
                         "Amount": D(e.debit) if D(e.debit) > 0 else D(e.credit), "Narration": v.narration, "Reference": v.reference, "Cost Centre": veh.get(e.cost_vehicle_id)})
    rep = exports.tally_vouchers(rows)
    company = app_settings.company(db)
    if fmt == "csv":
        return Response(exports.report_csv(rep), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="tally_vouchers_{start}_{end}.csv"'})
    return Response(exports.report_xlsx(rep, company.legal_name), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="tally_vouchers_{start}_{end}.xlsx"'})


@router.get("/tally/ledgers")
def tally_ledgers(fmt: str = "xlsx", db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:read"))):
    groups = acc.groups_map(db)
    rows = [{"Name": l.name, "Under": groups[l.group_id].name, "Opening Balance": D(l.opening_balance), "Dr/Cr": l.opening_type, "GSTIN": l.gstin} for l in db.query(Ledger).order_by(Ledger.name)]
    rep = {"title": "Tally ledger masters", "columns": [{"key": k, "label": k, "type": "money" if k == "Opening Balance" else None} for k in ("Name", "Under", "Opening Balance", "Dr/Cr", "GSTIN")], "rows": rows}
    if fmt == "csv":
        return Response(exports.report_csv(rep), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="tally_ledgers.csv"'})
    return Response(exports.report_xlsx(rep, app_settings.company(db).legal_name), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="tally_ledgers.xlsx"'})


@router.post("/tally/import")
async def tally_import(file: UploadFile = File(...), dry_run: bool = True, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    """Import journal vouchers in the same layout as the Tally export (one row per ledger line, grouped by Voucher Number)."""
    rows = exports.read_table(file.filename or "", await file.read())
    by_no: dict[str, list] = {}
    for r in rows:
        no = exports.pick(r, "Voucher Number", "Voucher No")
        if no:
            by_no.setdefault(str(no), []).append(r)
    names = {l.name.lower(): l.id for l in db.query(Ledger)}
    errors, ok = [], 0
    for no, lines in by_no.items():
        try:
            d = exports.pick(lines[0], "Date")
            d = d.date() if isinstance(d, datetime) else (d if isinstance(d, date) else datetime.strptime(str(d)[:10], "%d-%m-%Y").date() if "-" in str(d)[:3] else date.fromisoformat(str(d)[:10]))
            entries = []
            for ln in lines:
                lid = names.get(str(exports.pick(ln, "Ledger Name", "Ledger") or "").lower())
                if not lid:
                    raise AppError(f"unknown ledger '{exports.pick(ln, 'Ledger Name')}'")
                amt = D(exports.pick(ln, "Amount"))
                drcr = str(exports.pick(ln, "Dr/Cr") or "Dr").strip().lower()
                entries.append({"ledger_id": lid, "debit": amt if drcr.startswith("d") else 0, "credit": amt if drcr.startswith("c") else 0})
            if not dry_run:
                with db.begin_nested():
                    acc.post(db, user, "Journal", d, entries, str(exports.pick(lines[0], "Narration") or f"Imported {no}"), "import", None, no)
            else:
                tdr = sum((D(e["debit"]) for e in entries), ZERO)
                tcr = sum((D(e["credit"]) for e in entries), ZERO)
                if tdr != tcr:
                    raise AppError(f"debit {tdr} ≠ credit {tcr}")
            ok += 1
        except (AppError, ValueError) as exc:
            errors.append(f"{no}: {getattr(exc, 'detail', exc)}")
    if not dry_run:
        if errors:
            db.rollback()
            raise AppError("Import stopped – nothing was posted. " + "; ".join(errors[:10]))
        db.commit()
    return {"vouchers": len(by_no), "valid": ok, "errors": errors[:100], "posted": 0 if dry_run else ok}


# ------------------------------------------------------------------ purchase

def _row(obj) -> dict:
    return jsonable({c.name: getattr(obj, c.name) for c in obj.__table__.columns})


@router.get("/purchase-orders")
def list_po(db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:read"))):
    names = {v.id: v.name for v in db.query(Vendor)}
    return [_row(p) | {"vendor": names.get(p.vendor_id)} for p in db.query(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(500)]


@router.post("/purchase-orders")
def new_po(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:write"))):
    po = business.create_po(db, user, data)
    db.commit()
    return _row(po)


@router.post("/purchase-orders/{pid}/receive")
def po_receive(pid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:write"))):
    grn = business.receive_po(db, user, pid, data)
    db.commit()
    return _row(grn)


@router.post("/purchase-orders/{pid}/cancel")
def po_cancel(pid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:write"))):
    po = db.get(PurchaseOrder, pid)
    if not po or po.status not in ("Open",):
        raise AppError("Only open purchase orders can be cancelled")
    po.status = "Cancelled"
    log(db, user, "cancel", "purchase_orders", po.id, None, None, data.get("reason"))
    db.commit()
    return {"ok": True}


@router.get("/goods-receipts")
def list_grn(db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:read"))):
    return [_row(g) for g in db.query(GoodsReceipt).order_by(GoodsReceipt.id.desc()).limit(500)]


@router.get("/vendor-bills")
def list_bills(vendor_id: int | None = None, status: str | None = None, vehicle_id: int | None = None, start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"),
               db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:read"))):
    q = db.query(VendorBill)
    if vendor_id:
        q = q.filter_by(vendor_id=vendor_id)
    if vehicle_id:
        q = q.filter_by(vehicle_id=vehicle_id)
    if start:
        q = q.filter(VendorBill.bill_date >= date.fromisoformat(start))
    if end:
        q = q.filter(VendorBill.bill_date <= date.fromisoformat(end))
    if status:
        q = q.filter(VendorBill.status.in_(status.split(",")))
    names = {v.id: v.name for v in db.query(Vendor)}
    return [_row(b) | {"vendor": names.get(b.vendor_id), "balance": jsonable(r2(D(b.total) - D(b.tds_amount) - D(b.amount_paid)))} for b in q.order_by(VendorBill.id.desc()).limit(1000)]


@router.post("/vendor-bills")
def new_bill(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:write"))):
    b = business.create_vendor_bill(db, user, data)
    db.commit()
    return _row(b)


@router.post("/vendor-bills/{bid}/cancel")
def cancel_bill(bid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("purchase:write", "accounts:cancel"))):
    b = business.cancel_vendor_bill(db, user, bid, data.get("reason") or "")
    db.commit()
    return _row(b)


@router.post("/vendor-payments")
def vendor_payment(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("accounts:write"))):
    v = business.pay_vendor(db, user, data)
    db.commit()
    return {"voucher_id": v.id, "voucher_no": v.voucher_no}
