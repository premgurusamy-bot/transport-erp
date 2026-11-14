"""Invoicing (GST configurable), receipts & allocation, expenses, settlements, payments."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import money, utcnow
from app.core.errors import AppError, BlockedByRule, Conflict
from app.core.services import get_config, next_number, raise_exception_task
from app.modules.commercial import credit as creditsvc
from app.modules.commercial.models import Booking
from app.modules.finance.models import (
    Expense, Invoice, InvoiceLine, Payment, Receipt, ReceiptAllocation, Settlement,
)
from app.modules.finance.posting import bank_ledger, post_voucher
from app.modules.masters.models import Customer
from app.modules.operations.models import LorryReceipt, Trip, TripLoad


def income_account(db: Session, b: Booking) -> str:
    if b.service_type == "PTL":
        return "4020"
    tl = db.execute(select(TripLoad).where(TripLoad.booking_id == b.id, TripLoad.status != "removed")).scalars().first()
    t = db.get(Trip, tl.trip_id) if tl else None
    return "4010" if t and t.fleet_type == "attached" else "4000"


def tax_rule(db: Session, gst_mode: str, customer: Customer) -> dict:
    rates = get_config(db, "tax.gst_rates")
    company = get_config(db, "company.profile")
    if gst_mode == "RCM":
        return {"mode": "RCM", "rate": 0.0, "intra_state": None,
                "note": "GST payable by recipient under reverse charge (GTA). Configurable - verify with CA."}
    rate = float(rates.get("freight_gta_fcm", 12.0))
    intra = (customer.state_code or company.get("state_code")) == company.get("state_code")
    return {"mode": "FCM", "rate": rate, "intra_state": intra, "note": "Forward charge rate from configuration - verify with CA."}


def generate_invoice(db: Session, actor, *, customer_id, booking_ids: list[uuid.UUID], invoice_date: date | None = None) -> Invoice:
    cust = db.get(Customer, customer_id)
    if not cust:
        raise AppError("customer_missing", "Customer not found")
    bookings = [db.execute(select(Booking).where(Booking.id == i).with_for_update()).scalar_one_or_none() for i in booking_ids]
    if not bookings or any(b is None for b in bookings):
        raise AppError("booking_missing", "Booking not found")
    problems = []
    gst_modes = {b.gst_mode for b in bookings}
    if len(gst_modes) > 1:
        problems.append("Bookings have different GST modes - invoice separately")
    for b in bookings:
        if b.customer_id != customer_id:
            problems.append(f"{b.code} belongs to another customer")
        if b.status not in ("pod_verified",) and not (b.status == "cancelled" and b.extra_charges):
            problems.append(f"{b.code}: billing milestone not reached (POD must be verified; status {b.status})")
        if db.execute(select(InvoiceLine).where(InvoiceLine.booking_id == b.id, InvoiceLine.active.is_(True))).first():
            problems.append(f"{b.code} already invoiced")
    if problems:
        raise BlockedByRule("invoice_blocked", "Invoice cannot be generated", details=[{"check": "billing", "ok": False, "message": m} for m in problems])
    prof = creditsvc.active_profile(db, customer_id)
    inv_date = invoice_date or date.today()
    rule = tax_rule(db, bookings[0].gst_mode, cust)
    inv = Invoice(number=next_number(db, "INV", "GRL/INV", when=inv_date), customer_id=customer_id, invoice_date=inv_date,
                  due_date=inv_date + timedelta(days=prof.credit_days if prof else 0), gst_mode=rule["mode"],
                  place_of_supply=cust.state_code, taxable_value=Decimal("0"), total=Decimal("0"), tax_rule_snapshot=rule,
                  created_by=actor.user_id)
    db.add(inv)
    db.flush()
    taxable = Decimal("0")
    passthrough = Decimal("0")
    income_lines: dict[str, Decimal] = {}
    for b in bookings:
        lr = db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id, LorryReceipt.status != "cancelled")).scalar_one_or_none()
        if b.status != "cancelled":
            db.add(InvoiceLine(invoice_id=inv.id, booking_id=b.id, lr_number=lr.number if lr else None, charge_code="freight",
                               description=f"Freight {b.code} ({b.service_type})", amount=money(b.freight_amount)))
            taxable += money(b.freight_amount)
            acc = income_account(db, b)
            income_lines[acc] = income_lines.get(acc, Decimal("0")) + money(b.freight_amount)
        for x in b.extra_charges or []:
            amt = money(x.get("amount", 0))
            if amt <= 0:
                continue
            pt = bool(x.get("pass_through"))
            db.add(InvoiceLine(invoice_id=inv.id, booking_id=b.id, lr_number=lr.number if lr else None,
                               charge_code=x.get("code", "extra"), description=x.get("label", "Charge"), amount=amt, is_pass_through=pt))
            if pt:
                passthrough += amt
            else:
                taxable += amt
                acc = "4050" if x.get("code") in ("detention", "cancellation") else "4030"
                income_lines[acc] = income_lines.get(acc, Decimal("0")) + amt
        b.status = "invoiced" if b.status != "cancelled" else b.status
    gst = money(taxable * Decimal(str(rule["rate"])) / 100)
    if rule["mode"] == "FCM":
        if rule["intra_state"]:
            inv.cgst = money(gst / 2)
            inv.sgst = gst - inv.cgst
        else:
            inv.igst = gst
    inv.taxable_value, inv.pass_through = taxable, passthrough
    inv.total = money(taxable + gst + passthrough)
    db.flush()
    lines = [{"account": "1100", "debit": inv.total, "party_type": "customer", "party_id": customer_id}]
    for acc, amt in income_lines.items():
        lines.append({"account": acc, "credit": amt})
    if inv.cgst:
        lines += [{"account": "2101", "credit": inv.cgst}, {"account": "2102", "credit": inv.sgst}]
    if inv.igst:
        lines.append({"account": "2103", "credit": inv.igst})
    if passthrough:
        lines.append({"account": "1250", "credit": passthrough, "narration": "Pass-through reimbursements (not income)"})
    v = post_voucher(db, actor, vtype="sales", vdate=inv_date, narration=f"Invoice {inv.number} to {cust.name}", lines=lines,
                     source_entity="invoice", source_id=inv.id)
    inv.voucher_id = v.id
    # Apply customer advances received against these bookings
    for b in bookings:
        for r in db.execute(select(Receipt).where(Receipt.booking_id == b.id, Receipt.is_advance.is_(True), Receipt.status == "confirmed",
                                                  Receipt.unallocated > 0)).scalars():
            apply_advance(db, actor, r, inv)
    write_audit(db, actor=actor, action="invoice.issue", entity="invoice", entity_id=inv.id,
                after={"number": inv.number, "total": inv.total, "bookings": [b.code for b in bookings]})
    return inv


def apply_advance(db: Session, actor, r: Receipt, inv: Invoice):
    bal = money(Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received))
    amt = min(bal, Decimal(r.unallocated))
    if amt <= 0:
        return
    db.add(ReceiptAllocation(receipt_id=r.id, invoice_id=inv.id, amount=amt))
    r.unallocated = money(Decimal(r.unallocated) - amt)
    inv.amount_received = money(Decimal(inv.amount_received) + amt)
    _inv_status(inv)
    post_voucher(db, actor, vtype="journal", vdate=date.today(), narration=f"Advance {r.number} adjusted to {inv.number}",
                 lines=[{"account": "2200", "debit": amt, "party_type": "customer", "party_id": r.customer_id},
                        {"account": "1100", "credit": amt, "party_type": "customer", "party_id": r.customer_id}],
                 source_entity="receipt_allocation", source_id=r.id)


def _inv_status(inv: Invoice):
    bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
    if inv.status in ("cancelled", "disputed"):
        return
    inv.status = "paid" if bal <= 0 else ("part_paid" if inv.amount_received or inv.tds_received else "issued")


def cancel_invoice(db: Session, actor, inv: Invoice, reason: str):
    from app.modules.finance.posting import reverse_voucher
    if inv.amount_received or inv.tds_received:
        raise BlockedByRule("has_receipts", "Invoice has receipts allocated - issue a credit note instead")
    if inv.status == "cancelled":
        raise Conflict("cancelled", "Already cancelled")
    reverse_voucher(db, actor, inv.voucher_id, f"Invoice {inv.number} cancelled: {reason}")
    for l in db.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).scalars():
        l.active = False
        if l.booking_id:
            b = db.get(Booking, l.booking_id)
            if b.status == "invoiced":
                b.status = "pod_verified"
    inv.status, inv.cancel_reason = "cancelled", reason
    write_audit(db, actor=actor, action="invoice.cancel", entity="invoice", entity_id=inv.id, reason=reason)


def record_receipt(db: Session, actor, *, customer_id, amount: Decimal, tds_amount: Decimal, mode: str, reference: str | None,
                   receipt_date: date, company_bank_id=None, allocations: list[dict] | None = None, is_advance: bool = False,
                   booking_id=None, confirmed: bool = False, bank_txn_id=None, remittance_note: str | None = None) -> Receipt:
    if amount <= 0:
        raise AppError("amount", "Amount must be positive")
    if reference:
        dup = db.execute(select(Receipt).where(Receipt.reference == reference, Receipt.amount == amount,
                                               Receipt.status != "reversed")).first()
        if dup:
            raise Conflict("duplicate_receipt", f"A receipt with reference {reference} and the same amount exists")
    r = Receipt(number=next_number(db, "RCT", "RCT", when=receipt_date), customer_id=customer_id, receipt_date=receipt_date,
                amount=money(amount), tds_amount=money(tds_amount), mode=mode, reference=reference, company_bank_id=company_bank_id,
                status="unconfirmed", is_advance=is_advance, booking_id=booking_id, unallocated=money(amount),
                bank_txn_id=bank_txn_id, remittance_note=remittance_note)
    db.add(r)
    db.flush()
    r.planned_allocations = [{k: str(v) for k, v in a.items()} for a in (allocations or [])]
    if confirmed or mode == "cash":
        confirm_receipt(db, actor, r, allocations or [])
    write_audit(db, actor=actor, action="receipt.record", entity="receipt", entity_id=r.id,
                after={"number": r.number, "amount": amount, "status": r.status, "mode": mode})
    return r


def confirm_receipt(db: Session, actor, r: Receipt, allocations: list[dict]) -> Receipt:
    """Confirmation = money is verified in bank (matched) or cash counted. Only then is it posted and allocated."""
    if r.status == "confirmed":
        return r
    if r.customer_id is None:
        raise AppError("unidentified", "Identify the customer before confirming")
    tds = Decimal(r.tds_amount)
    if r.is_advance:
        lines = [{"account": "1000" if r.mode == "cash" else bank_ledger(db, r.company_bank_id), "debit": r.amount},
                 {"account": "2200", "credit": r.amount, "party_type": "customer", "party_id": r.customer_id}]
        if r.booking_id:
            b = db.get(Booking, r.booking_id)
            b.advance_received = money(Decimal(b.advance_received) + Decimal(r.amount))
    else:
        lines = [{"account": "1000" if r.mode == "cash" else bank_ledger(db, r.company_bank_id), "debit": r.amount}]
        if tds:
            lines.append({"account": "1200", "debit": tds})
        lines.append({"account": "1100", "credit": money(Decimal(r.amount) + tds), "party_type": "customer", "party_id": r.customer_id})
    v = post_voucher(db, actor, vtype="receipt", vdate=r.receipt_date, narration=f"Receipt {r.number} ({r.mode} {r.reference or ''})",
                     lines=lines, source_entity="receipt", source_id=r.id)
    r.voucher_id, r.status = v.id, "confirmed"
    if not r.is_advance:
        remaining = Decimal(r.amount)
        tds_left = tds
        allocs = allocations or _auto_allocations(db, r)
        for a in allocs:
            inv = db.execute(select(Invoice).where(Invoice.id == uuid.UUID(str(a["invoice_id"]))).with_for_update()).scalar_one()
            if inv.customer_id != r.customer_id:
                raise AppError("wrong_customer", f"Invoice {inv.number} belongs to another customer")
            bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
            amt = min(money(a.get("amount", bal)), remaining, bal)
            t = min(money(a.get("tds_amount", 0)), tds_left)
            if amt <= 0 and t <= 0:
                continue
            db.add(ReceiptAllocation(receipt_id=r.id, invoice_id=inv.id, amount=amt, tds_amount=t))
            inv.amount_received = money(Decimal(inv.amount_received) + amt)
            inv.tds_received = money(Decimal(inv.tds_received) + t)
            remaining -= amt
            tds_left -= t
            _inv_status(inv)
        r.unallocated = money(remaining)
    return r


def _auto_allocations(db: Session, r: Receipt) -> list[dict]:
    """Oldest-first allocation when the remittance does not specify invoices."""
    out = []
    remaining = Decimal(r.amount)
    tds = Decimal(r.tds_amount)
    for inv in db.execute(select(Invoice).where(Invoice.customer_id == r.customer_id, Invoice.status.in_(("issued", "part_paid")))
                          .order_by(Invoice.due_date)).scalars():
        if remaining <= 0 and tds <= 0:
            break
        bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
        t = min(tds, bal)
        a = min(remaining, bal - t)
        out.append({"invoice_id": inv.id, "amount": a, "tds_amount": t})
        remaining -= a
        tds -= t
    return out


# ------------------------------------------------------------------ settlements
def owner_settlement(db: Session, actor, owner_id, trip_ids: list[uuid.UUID]) -> Settlement:
    from app.modules.masters.models import VehicleOwner
    owner = db.get(VehicleOwner, owner_id)
    lines, gross, adv = [], Decimal("0"), Decimal("0")
    for tid in trip_ids:
        t = db.get(Trip, tid)
        if not t or t.owner_id != owner_id:
            raise AppError("trip_owner", "Trip does not belong to this owner")
        if t.status != "closed":
            raise BlockedByRule("trip_open", f"Trip {t.code} must be closed (POD verified) before owner settlement")
        settled_refs = {l.get("ref") for st in db.execute(select(Settlement).where(
            Settlement.party_type == "owner", Settlement.party_id == owner_id, Settlement.status != "cancelled")).scalars()
            for l in st.lines}
        if str(t.id) in settled_refs:
            raise Conflict("already_settled", f"Trip {t.code} already in a settlement")
        lines.append({"kind": "hire", "ref": str(t.id), "description": f"Hire {t.code}", "amount": str(t.owner_hire_amount)})
        gross += Decimal(t.owner_hire_amount)
        if t.owner_advance:
            lines.append({"kind": "advance", "ref": str(t.id), "description": f"Advance paid {t.code}", "amount": str(-Decimal(t.owner_advance))})
            adv += Decimal(t.owner_advance)
        # Approved recoveries (e.g. damage) appear only if an approved claim recovery exists - never arbitrary deductions
    tds = Decimal("0")
    tds_rates = get_config(db, "tax.tds_rates")
    if owner and not owner.tds_declaration_received:
        rate = Decimal(str(tds_rates.get("194C_individual", 1.0)))
        tds = money(gross * rate / 100)
    s = Settlement(code=next_number(db, "STL", "STL"), party_type="owner", party_id=owner_id, lines=lines, gross=money(gross),
                   advances=money(adv), tds=tds, net_payable=money(gross - adv - tds), prepared_by=actor.user_id, status="draft")
    db.add(s)
    db.flush()
    return s


def driver_settlement(db: Session, actor, driver_id, earning_ids: list[uuid.UUID]) -> Settlement:
    from app.modules.fleet.models import DriverAdvance, DriverEarning
    lines, gross = [], Decimal("0")
    for eid in earning_ids:
        e = db.get(DriverEarning, eid)
        if not e or e.driver_id != driver_id:
            raise AppError("earning", "Earning not found for this driver")
        if e.status != "approved":
            raise BlockedByRule("not_approved", "Only approved earnings can be settled")
        if e.settlement_id:
            raise Conflict("settled", "Earning already in a settlement")
        lines.append({"kind": "earning", "ref": str(e.id), "description": "Trip earning", "amount": str(e.gross)})
        gross += Decimal(e.gross)
    adv = Decimal("0")
    for a in db.execute(select(DriverAdvance).where(DriverAdvance.driver_id == driver_id, DriverAdvance.status == "paid")).scalars():
        take = min(Decimal(a.amount), gross - adv)
        if take <= 0:
            break
        lines.append({"kind": "advance", "ref": str(a.id), "description": f"Advance: {a.purpose}", "amount": str(-take)})
        adv += take
    # driver cash expenses reimbursable
    reimb = Decimal("0")
    for x in db.execute(select(Expense).where(Expense.driver_id == driver_id, Expense.paid_by == "driver_cash",
                                              Expense.status == "posted")).scalars():
        if any(l.get("ref") == str(x.id) for s in db.execute(select(Settlement).where(Settlement.party_type == "driver",
                                                                                     Settlement.party_id == driver_id,
                                                                                     Settlement.status != "cancelled")).scalars() for l in s.lines):
            continue
        lines.append({"kind": "reimbursement", "ref": str(x.id), "description": f"Expense {x.code}", "amount": str(x.amount)})
        reimb += Decimal(x.amount)
    s = Settlement(code=next_number(db, "STL", "STL"), party_type="driver", party_id=driver_id, lines=lines,
                   gross=money(gross + reimb), advances=money(adv), net_payable=money(gross + reimb - adv),
                   prepared_by=actor.user_id, status="draft")
    db.add(s)
    db.flush()
    for eid in earning_ids:
        db.get(DriverEarning, eid).settlement_id = s.id
    return s


def post_settlement(db: Session, actor, s: Settlement):
    if s.party_type == "owner":
        lines = []
        for l in s.lines:
            if l["kind"] == "hire":
                t = db.get(Trip, uuid.UUID(l["ref"]))
                lines.append({"account": "5000", "debit": Decimal(l["amount"]), "trip_id": t.id, "vehicle_id": t.vehicle_id,
                              "party_type": "owner", "party_id": s.party_id})
        if s.advances:
            lines.append({"account": "1150", "credit": s.advances, "party_type": "owner", "party_id": s.party_id})
        if s.tds:
            lines.append({"account": "2110", "credit": s.tds})
        lines.append({"account": "2000", "credit": s.net_payable, "party_type": "owner", "party_id": s.party_id})
    elif s.party_type == "driver":
        earn = sum((Decimal(l["amount"]) for l in s.lines if l["kind"] == "earning"), Decimal("0"))
        reimb = sum((Decimal(l["amount"]) for l in s.lines if l["kind"] == "reimbursement"), Decimal("0"))
        lines = []
        if earn:
            lines.append({"account": "5050", "debit": earn, "party_type": "driver", "party_id": s.party_id})
        if reimb:
            lines.append({"account": "2020", "debit": reimb, "party_type": "driver", "party_id": s.party_id,
                          "narration": "Clear expense reimbursement payable (already expensed)"})
        if s.advances:
            lines.append({"account": "1160", "credit": s.advances, "party_type": "driver", "party_id": s.party_id})
        lines.append({"account": "2020", "credit": s.net_payable, "party_type": "driver", "party_id": s.party_id})
    else:
        raise AppError("unsupported", "Vendor settlements are posted from vendor invoices")
    v = post_voucher(db, actor, vtype="journal", vdate=date.today(), narration=f"Settlement {s.code}", lines=lines,
                     source_entity="settlement", source_id=s.id, approved_by=s.approved_by)
    s.voucher_id = v.id


def party_payable_account(payee_type: str) -> str:
    return {"owner": "2000", "vendor": "2010", "driver": "2020", "employee": "2030", "customer": "2200"}.get(payee_type, "2010")


def execute_payment(db: Session, actor, pay: Payment, via: str, bank_reference: str | None):
    from app.integrations.adapters import get_adapter
    if pay.status != "approved":
        raise BlockedByRule("not_approved", "Payment must be approved by an authorised checker before execution")
    if via == "bank_api":
        res = get_adapter("bank").execute_payment({"idempotency_key": pay.idempotency_key, "amount": str(pay.amount)})
        bank_reference, via = res.data["bank_reference"], f"bank_api_{res.mode.lower()}"
    elif not bank_reference:
        raise AppError("reference_required", "Enter the bank UTR/reference of the payment made in the bank portal")
    pay.status, pay.executed_by, pay.executed_at, pay.executed_via, pay.bank_reference = "executed", actor.user_id, utcnow(), via, bank_reference
    advance = pay.purpose.lower().startswith("advance")
    dr = {"owner": "1150", "driver": "1160", "vendor": "1170"}.get(pay.payee_type, "2010") if advance else party_payable_account(pay.payee_type)
    v = post_voucher(db, actor, vtype="payment", vdate=date.today(), narration=f"Payment {pay.code}: {pay.purpose} ({bank_reference})",
                     lines=[{"account": dr, "debit": pay.amount, "party_type": pay.payee_type, "party_id": pay.payee_id},
                            {"account": bank_ledger(db, pay.company_bank_id), "credit": pay.amount}],
                     source_entity="payment", source_id=pay.id, approved_by=pay.approved_by)
    pay.voucher_id = v.id
    if pay.settlement_id:
        s = db.get(Settlement, pay.settlement_id)
        s.paid = money(Decimal(s.paid) + Decimal(pay.amount))
        s.status = "paid" if s.paid >= s.net_payable else "part_paid"
        if s.status == "paid" and s.party_type == "driver":
            from app.modules.fleet.models import DriverAdvance, DriverEarning
            for l in s.lines:
                if l["kind"] == "earning":
                    e = db.get(DriverEarning, uuid.UUID(l["ref"]))
                    e.status = "paid"
                if l["kind"] == "advance":
                    a = db.get(DriverAdvance, uuid.UUID(l["ref"]))
                    a.status = "adjusted"
    write_audit(db, actor=actor, action="payment.execute", entity="payment", entity_id=pay.id,
                after={"via": via, "reference": bank_reference, "amount": pay.amount})
