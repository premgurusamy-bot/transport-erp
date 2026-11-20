"""Tax invoices, proforma, debit/credit notes, consolidated & monthly-contract billing, cancellation, receipts."""
from __future__ import annotations

import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log, snapshot
from ..core.deps import AppError
from ..core.money import D, ZERO, r2
from ..core.numbering import next_number
from ..core.validators import state_code_from_gstin
from ..models import BillAllocation, Branch, Consignment, Customer, GstTreatment, Invoice, InvoiceLine, RateContract, Trip, Voucher
from . import accounting as acc
from . import freight as fr
from . import gst
from . import notify
from . import settings as app_settings

DOC_SERIES = {
    "tax_invoice": "INVOICE", "proforma": "PROFORMA", "debit_note": "DEBIT_NOTE", "credit_note": "CREDIT_NOTE",
    "bill_of_supply": "BILL_OF_SUPPLY", "advance_receipt": "ADVANCE_RECEIPT",
}
POSTING_TYPES = {"tax_invoice", "bill_of_supply", "debit_note", "credit_note"}


def _treatment(db: Session, data: dict, customer: Customer, contract: RateContract | None = None) -> GstTreatment:
    tid = data.get("gst_treatment_id") or (contract.gst_treatment_id if contract else None) or customer.default_gst_treatment_id
    t = db.get(GstTreatment, int(tid)) if tid else None
    if t is None:
        code = app_settings.get(db, "gst")["default_treatment_code"]
        t = db.execute(select(GstTreatment).where(GstTreatment.code == code)).scalar_one_or_none()
    if t is None or not t.is_active:
        raise AppError("Select a GST treatment for this invoice (Settings → GST treatments)")
    return t


def _lr_line(lr: Consignment) -> dict:
    desc = f"Freight – LR {lr.lr_no} dt {lr.lr_date:%d-%m-%Y}, {lr.from_place} → {lr.to_place}"
    if lr.vehicle_no:
        desc += f", Vehicle {lr.vehicle_no}"
    if lr.customer_invoice_no:
        desc += f", Inv {lr.customer_invoice_no}"
    if D(lr.weight_kg):
        desc += f", {D(lr.weight_kg):g} kg"
    return {"description": desc, "consignment_id": lr.id, "trip_id": lr.trip_id, "quantity": 1, "rate": lr.total_freight, "amount": lr.total_freight,
            "details": {"basis": lr.freight_basis, "breakdown": (lr.freight_breakdown or {}).get("lines"), "advance": str(lr.advance_freight)}}


def _collect_lrs(db: Session, customer_id: int, lr_ids: list[int]) -> list[Consignment]:
    lrs = db.query(Consignment).filter(Consignment.id.in_(lr_ids)).order_by(Consignment.lr_date, Consignment.id).all()
    if len(lrs) != len(set(lr_ids)):
        raise AppError("Some LRs were not found")
    for lr in lrs:
        if lr.customer_id != customer_id:
            raise AppError(f"LR {lr.lr_no} belongs to another customer")
        if lr.status == "Cancelled":
            raise AppError(f"LR {lr.lr_no} is cancelled")
        if lr.invoice_id:
            inv = db.get(Invoice, lr.invoice_id)
            if inv and inv.status != "Cancelled" and inv.doc_type != "proforma":
                raise AppError(f"LR {lr.lr_no} is already billed in {inv.invoice_no}")
    return lrs


def create_invoice(db: Session, user, data: dict) -> Invoice:
    doc_type = data.get("doc_type") or "tax_invoice"
    if doc_type not in DOC_SERIES:
        raise AppError("Unknown document type")
    customer = db.get(Customer, int(data.get("customer_id") or 0))
    if not customer:
        raise AppError("Select a customer")
    inv_date = date.fromisoformat(str(data.get("invoice_date") or date.today())[:10])
    comp = app_settings.company(db)
    supplier_state, supplier_gstin = comp.state_code or "33", comp.gstin
    if data.get("branch_id"):
        br = db.get(Branch, int(data["branch_id"]))
        if br and br.gstin:
            supplier_state, supplier_gstin = br.state_code or state_code_from_gstin(br.gstin) or supplier_state, br.gstin
    basis = data.get("basis") or ("manual" if data.get("lines") else "lr")
    lines: list[dict] = []
    lrs: list[Consignment] = []
    contract = None
    ref = None
    loading_state = None
    if doc_type in ("debit_note", "credit_note"):
        ref = db.get(Invoice, int(data.get("reference_invoice_id") or 0))
        if not ref or ref.customer_id != customer.id or ref.doc_type not in ("tax_invoice", "bill_of_supply") or ref.status == "Cancelled":
            raise AppError("Select the original (issued) invoice of this customer")
        if not (data.get("reason") or "").strip():
            raise AppError("Reason is required for debit / credit notes")
        basis = "manual"
    if basis in ("lr", "consolidated", "trip"):
        lr_ids = [int(x) for x in data.get("lr_ids") or []]
        if basis == "trip":
            trip_ids = [int(x) for x in data.get("trip_ids") or []]
            if not trip_ids:
                raise AppError("Select at least one trip")
            lr_ids = [l.id for l in db.query(Consignment).filter(Consignment.trip_id.in_(trip_ids), Consignment.status != "Cancelled", Consignment.customer_id == customer.id)]
        if not lr_ids:
            raise AppError("Select at least one LR to bill")
        lrs = _collect_lrs(db, customer.id, lr_ids)
        if basis == "trip":
            by_trip: dict[int, list[Consignment]] = {}
            for l in lrs:
                by_trip.setdefault(l.trip_id or 0, []).append(l)
            for tid, group in by_trip.items():
                t = db.get(Trip, tid) if tid else None
                amt = sum((D(l.total_freight) for l in group), ZERO)
                desc = f"Freight – Trip {t.trip_no if t else ''} {t.from_place if t else ''} → {t.to_place if t else ''}; LR {', '.join(l.lr_no for l in group)}"
                lines.append({"description": desc, "trip_id": tid or None, "quantity": 1, "rate": amt, "amount": amt})
        else:
            lines = [_lr_line(l) for l in lrs]
        contract = db.get(RateContract, lrs[0].rate_contract_id) if lrs[0].rate_contract_id else None
        loading_state = None
    elif basis == "monthly_contract":
        contract = db.get(RateContract, int(data.get("contract_id") or 0))
        if not contract or contract.customer_id != customer.id or contract.basis != "monthly_fixed":
            raise AppError("Select a monthly fixed contract of this customer")
        p_from = date.fromisoformat(str(data["period_from"])[:10])
        p_to = date.fromisoformat(str(data["period_to"])[:10])
        dup = db.execute(select(Invoice).where(Invoice.customer_id == customer.id, Invoice.basis == "monthly_contract", Invoice.status != "Cancelled", Invoice.period_from <= p_to, Invoice.period_to >= p_from, Invoice.doc_type == doc_type)).scalars().first()
        if dup and doc_type != "proforma":
            raise AppError(f"Period already billed in {dup.invoice_no}")
        trips_in = db.execute(select(func.count(Trip.id)).where(Trip.customer_id == customer.id, Trip.trip_date.between(p_from, p_to), Trip.stage != "Cancelled")).scalar()
        months = D(data.get("months") or 1)
        res = fr.calculate(contract, fr.FreightInputs(months=months, trips_in_period=D(trips_in), include_loading=False, include_unloading=False))
        lines.append({"description": f"{contract.name} – fixed monthly contract {contract.contract_no} v{contract.version}, period {p_from:%d-%m-%Y} to {p_to:%d-%m-%Y} ({trips_in} trips)", "quantity": months, "rate": contract.rate, "amount": res["total"], "details": {"lines": res["lines"]}})
        lrs = db.query(Consignment).filter(Consignment.customer_id == customer.id, Consignment.rate_contract_id == contract.id, Consignment.lr_date.between(p_from, p_to), Consignment.status != "Cancelled", Consignment.invoice_id.is_(None)).all()
        data = {**data, "period_from": p_from, "period_to": p_to}
    elif basis in ("manual", "warehouse"):
        if basis == "warehouse":
            data = {**data, "period_from": date.fromisoformat(str(data["period_from"])[:10]), "period_to": date.fromisoformat(str(data["period_to"])[:10])}
        for ln in data.get("lines") or []:
            amt = r2(ln.get("amount")) if ln.get("amount") not in (None, "") else r2(D(ln.get("quantity") or 1) * D(ln.get("rate")))
            if not (ln.get("description") or "").strip() or amt <= 0:
                raise AppError("Each line needs a description and an amount greater than zero")
            lines.append({"description": ln["description"].strip(), "quantity": D(ln.get("quantity") or 1), "rate": D(ln.get("rate") or amt), "amount": amt, "sac": ln.get("sac"), "uom": ln.get("uom") or "NOS"})
    else:
        raise AppError("Unknown billing basis")
    if not lines:
        raise AppError("Invoice has no lines")

    treatment = _treatment(db, data, customer, contract) if not ref else db.get(GstTreatment, ref.gst_treatment_id) or _treatment(db, data, customer)
    if doc_type == "bill_of_supply" and treatment.charge_mechanism not in ("EXEMPT", "NIL"):
        raise AppError("Bill of supply is only for exempt / nil-rated supplies")
    if doc_type == "tax_invoice" and treatment.charge_mechanism in ("EXEMPT", "NIL"):
        doc_type = "bill_of_supply"
    pos = data.get("place_of_supply") or (ref.place_of_supply if ref else gst.place_of_supply(customer.gstin, customer.billing_state_code, loading_state)) or supplier_state
    taxable = r2(sum((D(l["amount"]) for l in lines), ZERO))
    if ref and doc_type == "credit_note":
        prior = D(db.execute(select(func.coalesce(func.sum(Invoice.taxable_value), 0)).where(Invoice.reference_invoice_id == ref.id, Invoice.doc_type == "credit_note", Invoice.status != "Cancelled")).scalar())
        if taxable + prior > D(ref.taxable_value):
            raise AppError(f"Credit notes cannot exceed the original taxable value ₹{ref.taxable_value} (already credited ₹{r2(prior)})")
    tax = gst.compute(taxable, treatment.gst_rate, treatment.charge_mechanism, supplier_state, pos)
    gross = taxable + tax["cgst"] + tax["sgst"] + tax["igst"]
    if app_settings.get(db, "invoice")["round_off"]:
        total, round_off = gst.round_total(gross)
    else:
        total, round_off = r2(gross), ZERO
    due_days = customer.credit_days if customer.credit_days is not None else app_settings.get(db, "invoice")["default_due_days"]
    inv = Invoice(
        invoice_no=next_number(db, DOC_SERIES[doc_type], inv_date), doc_type=doc_type, invoice_date=inv_date,
        branch_id=int(data["branch_id"]) if data.get("branch_id") else None, customer_id=customer.id,
        billing_name=customer.legal_name or customer.name, billing_address=customer.billing_address, customer_gstin=customer.gstin,
        place_of_supply=pos, supplier_state_code=supplier_state, supplier_gstin=supplier_gstin, gst_treatment_id=treatment.id,
        gst_treatment_code=treatment.code, sac=treatment.sac, charge_mechanism=treatment.charge_mechanism, gst_rate=treatment.gst_rate,
        is_interstate=tax["interstate"], basis=basis,
        period_from=data.get("period_from") if basis in ("monthly_contract", "warehouse") else None, period_to=data.get("period_to") if basis in ("monthly_contract", "warehouse") else None,
        reference_invoice_id=ref.id if ref else None, reason=data.get("reason"), po_number=data.get("po_number") or customer.po_number,
        taxable_value=taxable, cgst=tax["cgst"], sgst=tax["sgst"], igst=tax["igst"], rcm_tax=tax["rcm_tax"], round_off=round_off, total=total,
        due_date=inv_date + timedelta(days=int(due_days or 0)), status="Issued", notes=data.get("notes"), created_by=user.id,
        verify_token=secrets.token_urlsafe(12),
        einvoice_status="Pending" if (app_settings.get(db, "gst")["einvoice_enabled"] and doc_type in ("tax_invoice", "debit_note", "credit_note") and customer.gstin) else "Not Applicable",
    )
    db.add(inv)
    db.flush()
    for i, l in enumerate(lines, 1):
        db.add(InvoiceLine(invoice_id=inv.id, line_no=i, description=l["description"], sac=l.get("sac") or treatment.sac, consignment_id=l.get("consignment_id"), trip_id=l.get("trip_id"), quantity=D(l.get("quantity") or 1), uom=l.get("uom") or "NOS", rate=D(l.get("rate")), amount=r2(l["amount"]), details=jsonable(l.get("details"))))
    if doc_type not in ("proforma", "advance_receipt"):
        for lr in lrs:
            lr.invoice_id = inv.id
            lr.status = "Billed"
        db.flush()
        _mark_trips_billed(db, user, {l.trip_id for l in lrs if l.trip_id})
    if doc_type in POSTING_TYPES:
        _post_invoice(db, user, inv, customer, lines)
        if doc_type == "credit_note" and ref:
            adj = min(D(total), D(ref.total) - D(ref.amount_received))
            if adj > 0:
                db.add(BillAllocation(voucher_id=inv.voucher_id, invoice_id=ref.id, amount=r2(adj)))
                ref.amount_received = r2(D(ref.amount_received) + adj)
                acc.refresh_invoice_status(ref)
                inv.amount_received = r2(adj)
            inv.status = "Adjusted" if D(inv.amount_received) >= D(total) else "Issued"
    log(db, user, "create", "invoices", inv.id, None, snapshot(inv))
    if doc_type in ("tax_invoice", "bill_of_supply"):
        notify.event(db, "invoice_generated", {"invoice_no": inv.invoice_no, "customer": customer.name, "amount": str(total), "date": inv_date.strftime("%d-%m-%Y")}, customer=customer, entity=("invoices", inv.id))
    return inv


def _mark_trips_billed(db: Session, user, trip_ids: set[int]) -> None:
    from .operations import _move

    for tid in trip_ids:
        t = db.get(Trip, tid)
        if not t:
            continue
        unbilled = db.query(Consignment).filter(Consignment.trip_id == tid, Consignment.status != "Cancelled", Consignment.invoice_id.is_(None)).count()
        if unbilled == 0:
            t.billed = True
            if t.stage == "Closed":
                _move(db, user, t, "Billed", "All LRs invoiced")
                if t.driver_settlement_id:
                    _move(db, user, t, "Settled", "Driver already settled")


def _post_invoice(db: Session, user, inv: Invoice, customer: Customer, lines: list[dict]) -> None:
    cust_ledger = acc.party_ledger(db, "customer", customer.id, customer.name, customer.gstin)
    customer.ledger_id = cust_ledger
    income_key = "WAREHOUSE_INCOME" if inv.basis == "warehouse" else "FREIGHT_INCOME"
    income = acc.sys_ledger(db, income_key)
    sign = -1 if inv.doc_type == "credit_note" else 1

    def side(amount, dr: bool) -> dict:
        amount = D(amount)
        if sign < 0:
            dr = not dr
        return {"debit": amount, "credit": ZERO} if dr else {"debit": ZERO, "credit": amount}

    entries = [{"ledger_id": cust_ledger, **side(inv.total, True), "narration": inv.invoice_no}]
    vehicle_by_lr = {}
    for l in lines:
        vid = None
        if l.get("consignment_id"):
            lr = db.get(Consignment, l["consignment_id"])
            vid = lr.vehicle_id if lr else None
        elif l.get("trip_id"):
            t = db.get(Trip, l["trip_id"])
            vid = t.vehicle_id if t else None
        entries.append({"ledger_id": income, **side(l["amount"], False), "vehicle_id": vid, "trip_id": l.get("trip_id")})
    for key, amt in (("CGST_OUTPUT", inv.cgst), ("SGST_OUTPUT", inv.sgst), ("IGST_OUTPUT", inv.igst)):
        if D(amt):
            entries.append({"ledger_id": acc.sys_ledger(db, key), **side(amt, False)})
    if D(inv.round_off):
        ro = D(inv.round_off)
        entries.append({"ledger_id": acc.sys_ledger(db, "ROUND_OFF"), **side(abs(ro), ro < 0)})
    vtype = {"credit_note": "Credit Note", "debit_note": "Debit Note"}.get(inv.doc_type, "Sales")
    v = acc.post(db, user, vtype, inv.invoice_date, entries, f"{inv.doc_type.replace('_', ' ').title()} {inv.invoice_no} – {customer.name}", "invoice", inv.id, inv.invoice_no)
    inv.voucher_id = v.id


def cancel_invoice(db: Session, user, inv_id: int, reason: str) -> Invoice:
    inv = db.get(Invoice, inv_id)
    if not inv:
        raise AppError("Invoice not found", 404)
    if inv.status == "Cancelled":
        raise AppError("Invoice already cancelled")
    if not reason or len(reason.strip()) < 5:
        raise AppError("Cancellation reason is required")
    live_receipts = db.execute(select(BillAllocation).join(Voucher, Voucher.id == BillAllocation.voucher_id).where(BillAllocation.invoice_id == inv.id, BillAllocation.reversed.is_(False), Voucher.source_type != "invoice")).scalars().first()
    if live_receipts:
        raise AppError("Receipts are allocated to this invoice. Cancel those receipts first, or issue a credit note.")
    notes = db.execute(select(Invoice).where(Invoice.reference_invoice_id == inv.id, Invoice.status != "Cancelled")).scalars().first()
    if notes:
        raise AppError(f"Cancel the linked {notes.doc_type.replace('_', ' ')} {notes.invoice_no} first")
    if inv.einvoice_status == "Generated":
        if inv.ack_date and datetime.now(timezone.utc) - inv.ack_date > timedelta(hours=24):
            raise AppError("IRN is older than 24 hours and cannot be cancelled on the IRP. Issue a credit note instead.")
        raise AppError("Cancel the IRN on the IRP first, then record the IRN cancellation on this invoice.")
    before = snapshot(inv)
    if inv.voucher_id:
        rev = acc.reverse(db, user, inv.voucher_id, f"Invoice {inv.invoice_no} cancelled: {reason}")
        inv.cancel_voucher_id = rev.id
    # credit note adjustments are released by the reversal above
    for lr in db.query(Consignment).filter(Consignment.invoice_id == inv.id):
        lr.invoice_id = None
        lr.status = "POD Received" if lr.pod_received_at else ("Delivered" if lr.delivered_at else "In Transit" if lr.trip_id else "Booked")
        t = db.get(Trip, lr.trip_id) if lr.trip_id else None
        if t and t.stage in ("Billed", "Settled"):
            t.stage, t.billed = "Closed", False
    inv.status = "Cancelled"
    inv.cancelled_at = datetime.now(timezone.utc)
    inv.cancelled_by = user.id
    inv.cancel_reason = reason
    log(db, user, "cancel", "invoices", inv.id, before, snapshot(inv), reason)
    return inv


def record_receipt(db: Session, user, data: dict) -> Voucher:
    """Customer receipt: Dr Cash/Bank (+TDS receivable), Cr customer; bill-wise allocation optional."""
    customer = db.get(Customer, int(data.get("customer_id") or 0))
    if not customer:
        raise AppError("Select a customer")
    amount = r2(data.get("amount"))
    tds = r2(data.get("tds_amount"))
    if amount <= 0:
        raise AppError("Amount must be greater than zero")
    on = date.fromisoformat(str(data.get("date") or date.today())[:10])
    cust_ledger = acc.party_ledger(db, "customer", customer.id, customer.name, customer.gstin)
    customer.ledger_id = cust_ledger
    if data.get("mode") == "Bank":
        bank = int(data.get("bank_ledger_id") or 0) or None
        from .operations import _credit_ledger_for

        bank = _credit_ledger_for(db, "Bank", None, None, bank)
    else:
        bank = acc.sys_ledger(db, "CASH")
    lines = [{"ledger_id": bank, "debit": amount, "instrument_no": data.get("instrument_no")}]
    if tds > 0:
        lines.append({"ledger_id": acc.sys_ledger(db, "TDS_RECEIVABLE"), "debit": tds})
    lines.append({"ledger_id": cust_ledger, "credit": amount + tds})
    v = acc.post(db, user, "Receipt", on, lines, data.get("narration") or f"Receipt from {customer.name}", "receipt", customer.id, data.get("instrument_no"))
    allocations = data.get("allocations") or []
    if allocations:
        acc.allocate_receipt(db, v, allocations)
    elif data.get("auto_allocate", True):
        remaining = amount + tds
        open_invs = db.query(Invoice).filter(Invoice.customer_id == customer.id, Invoice.status.in_(["Issued", "Partly Paid"]), Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note"])).order_by(Invoice.invoice_date, Invoice.id).all()
        auto = []
        for inv in open_invs:
            if remaining <= 0:
                break
            bal = D(inv.total) - D(inv.amount_received)
            take = min(bal, remaining)
            if take > 0:
                auto.append({"invoice_id": inv.id, "amount": take, "tds_amount": 0})
                remaining -= take
        if auto:
            acc.allocate_receipt(db, v, auto)
    notify.event(db, "payment_received", {"customer": customer.name, "amount": str(amount), "voucher_no": v.voucher_no}, customer=customer, entity=("vouchers", v.id))
    return v


def customer_outstanding(db: Session, customer_id: int) -> Decimal:
    c = db.get(Customer, customer_id)
    return acc.ledger_balance(db, c.ledger_id) if c and c.ledger_id else ZERO
