"""Finance API: chart, vouchers, invoices, receipts, expenses, settlements, payments, bank, collections, budgets,
reports, Tally import/export."""
from __future__ import annotations

import hashlib
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.notify import queue
from app.core.services import financial_year, get_config, next_number, on_approval, raise_exception_task, request_approval
from app.integrations.adapters import REGISTRY
from app.modules.finance import bank as banksvc
from app.modules.finance import billing
from app.modules.finance import reports as rpt
from app.modules.finance.models import (
    Account, BankTransaction, Budget, CollectionNote, Expense, ImportBatch, Invoice, InvoiceLine, Payment, Receipt,
    ReceiptAllocation, Settlement, Voucher, VoucherLine,
)
from app.modules.finance.posting import post_expense, post_voucher, reverse_voucher
from app.modules.masters.models import Contact, Customer, PartyBankAccount, VehicleOwner, Vendor
from app.modules.operations.access import assert_trip_access
from app.modules.operations.models import Trip

router = APIRouter(prefix="/api/v1/finance", tags=["finance"])


# ===================================================================== chart & vouchers
@router.get("/accounts")
def accounts(p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    return [to_dict(a) for a in db.execute(select(Account).order_by(Account.code)).scalars()]


class JournalLine(BaseModel):
    account: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    party_type: str | None = None
    party_id: uuid.UUID | None = None
    cost_centre: str | None = None
    narration: str | None = None


class JournalIn(BaseModel):
    vdate: date
    narration: str = Field(min_length=3)
    lines: list[JournalLine] = Field(min_length=2)


@router.post("/journals")
def post_journal(body: JournalIn, p: Principal = Depends(require("accounts.post")), db: Session = Depends(get_db)):
    total = sum((l.debit for l in body.lines), Decimal("0"))
    thr = Decimal(str(get_config(db, "approval.thresholds")["expense"]))
    if total > thr * 10:
        # Large manual journals are maker-checker
        ar = request_approval(db, p, kind="journal", entity="journal", entity_id=uuid.uuid4(), title=f"Manual journal Rs {total}: {body.narration}",
                              required_permission="accounts.approve", amount=total, payload=body.model_dump(mode="json"), reason=body.narration)
        return {"status": "pending_approval", "approval": ar.code}
    v = post_voucher(db, p, vtype="journal", vdate=body.vdate, narration=body.narration,
                     lines=[l.model_dump() for l in body.lines], source_entity="manual")
    return to_dict(v)


@on_approval("journal")
def _journal_ok(db, actor, ar):
    if ar.status == "approved":
        post_voucher(db, actor, vtype="journal", vdate=date.fromisoformat(ar.payload["vdate"]), narration=ar.payload["narration"],
                     lines=[{**l, "debit": Decimal(str(l["debit"])), "credit": Decimal(str(l["credit"]))} for l in ar.payload["lines"]],
                     source_entity="manual", approved_by=actor.user_id)


@router.get("/vouchers")
def vouchers(frm: date | None = None, to: date | None = None, p: Principal = Depends(require_any("accounts.read", "ca.read")),
             db: Session = Depends(get_db)):
    q = select(Voucher).order_by(Voucher.vdate.desc(), Voucher.number.desc()).limit(1000)
    if frm:
        q = q.where(Voucher.vdate >= frm)
    if to:
        q = q.where(Voucher.vdate <= to)
    return [to_dict(v) for v in db.execute(q).scalars()]


@router.get("/vouchers/{vid}")
def voucher(vid: uuid.UUID, p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    v = get_or_404(db, Voucher, vid, "Voucher")
    lines = []
    for l in db.execute(select(VoucherLine).where(VoucherLine.voucher_id == v.id)).scalars():
        a = db.get(Account, l.account_id)
        lines.append({**to_dict(l), "account_code": a.code, "account_name": a.name})
    return {**to_dict(v), "lines": lines}


class ReverseIn(BaseModel):
    reason: str = Field(min_length=5)


@router.post("/vouchers/{vid}/reverse")
def reverse(vid: uuid.UUID, body: ReverseIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    return to_dict(reverse_voucher(db, p, vid, body.reason))


# ===================================================================== invoices
class InvoiceIn(BaseModel):
    customer_id: uuid.UUID
    booking_ids: list[uuid.UUID] = Field(min_length=1)
    invoice_date: date | None = None


def invoice_out(db: Session, inv: Invoice) -> dict:
    d = to_dict(inv)
    d["lines"] = [to_dict(l) for l in db.execute(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).scalars()]
    d["balance"] = str(Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received))
    c = db.get(Customer, inv.customer_id)
    d["customer_name"] = c.name if c else None
    return d


@router.post("/invoices")
def create_invoice(body: InvoiceIn, p: Principal = Depends(require("invoice.write")), db: Session = Depends(get_db)):
    inv = billing.generate_invoice(db, p, customer_id=body.customer_id, booking_ids=body.booking_ids, invoice_date=body.invoice_date)
    contact = db.execute(select(Contact).where(Contact.customer_id == inv.customer_id)).scalars().first()
    if contact and contact.email:
        queue(db, channel="email", recipient=contact.email, template="invoice_issued", number=inv.number, total=inv.total,
              due=f"{inv.due_date:%d-%m-%Y}", entity="invoice", entity_id=inv.id)
    return invoice_out(db, inv)


@router.get("/invoices")
def list_invoices(status: str | None = None, customer_id: uuid.UUID | None = None,
                  p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    q = select(Invoice).order_by(Invoice.invoice_date.desc()).limit(1000)
    if status:
        q = q.where(Invoice.status.in_(status.split(",")))
    if customer_id:
        q = q.where(Invoice.customer_id == customer_id)
    return [invoice_out(db, i) for i in db.execute(q).scalars()]


@router.get("/invoices/{iid}")
def get_invoice(iid: uuid.UUID, p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    return invoice_out(db, get_or_404(db, Invoice, iid, "Invoice"))


@router.post("/invoices/{iid}/cancel")
def cancel_invoice(iid: uuid.UUID, body: ReverseIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    inv = get_or_404(db, Invoice, iid, "Invoice", lock=True)
    billing.cancel_invoice(db, p, inv, body.reason)
    return invoice_out(db, inv)


@router.post("/invoices/{iid}/irn")
def generate_irn(iid: uuid.UUID, p: Principal = Depends(require("invoice.write")), db: Session = Depends(get_db)):
    inv = get_or_404(db, Invoice, iid, "Invoice")
    res = REGISTRY["gst"].generate_irn({"number": inv.number, "total": str(inv.total)})
    inv.irn, inv.irn_status = res.data["irn"], "generated_mock"
    return {"irn": inv.irn, "mode": res.mode, "label": "MOCK IRN - not registered on the e-invoice portal"}


@router.get("/unbilled")
def unbilled(p: Principal = Depends(require("invoice.write")), db: Session = Depends(get_db)):
    from app.modules.commercial.models import Booking
    rows = db.execute(select(Booking).where(Booking.status == "pod_verified").order_by(Booking.customer_id)).scalars()
    return [{"booking_id": str(b.id), "code": b.code, "customer_id": str(b.customer_id), "freight": str(b.freight_amount),
             "pod_verified_at": b.pod_verified_at, "gst_mode": b.gst_mode} for b in rows]


# ===================================================================== receipts
class ReceiptIn(BaseModel):
    customer_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    tds_amount: Decimal = Field(Decimal("0"), ge=0)
    mode: str = Field(pattern="^(neft|rtgs|imps|upi|cheque|cash|gateway)$")
    reference: str | None = None
    receipt_date: date
    company_bank_id: uuid.UUID | None = None
    allocations: list[dict] = []
    is_advance: bool = False
    booking_id: uuid.UUID | None = None
    remittance_note: str | None = None


@router.post("/receipts")
def post_receipt(body: ReceiptIn, p: Principal = Depends(require("accounts.post")), db: Session = Depends(get_db)):
    if not body.customer_id:
        raise AppError("customer_required", "Unidentified money stays in the bank exception queue until identified")
    r = billing.record_receipt(db, p, customer_id=body.customer_id, amount=body.amount, tds_amount=body.tds_amount, mode=body.mode,
                               reference=body.reference, receipt_date=body.receipt_date, company_bank_id=body.company_bank_id,
                               allocations=[{**a, "amount": Decimal(str(a.get("amount", 0)))} if "amount" in a else a for a in body.allocations],
                               is_advance=body.is_advance, booking_id=body.booking_id, remittance_note=body.remittance_note)
    out = to_dict(r)
    if r.status != "confirmed":
        out["note"] = "Recorded as UNCONFIRMED. It is confirmed only when matched to the bank statement."
    return out


@router.get("/receipts")
def list_receipts(p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    return [to_dict(r) for r in db.execute(select(Receipt).order_by(Receipt.receipt_date.desc()).limit(1000)).scalars()]


@router.post("/receipts/{rid}/reverse")
def reverse_receipt(rid: uuid.UUID, body: ReverseIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    """Bounced cheque / reversal: reverses the voucher and the invoice allocations."""
    r = get_or_404(db, Receipt, rid, "Receipt", lock=True)
    if r.status != "confirmed":
        raise Conflict("bad_status", "Only confirmed receipts can be reversed")
    reverse_voucher(db, p, r.voucher_id, body.reason)
    for a in db.execute(select(ReceiptAllocation).where(ReceiptAllocation.receipt_id == r.id)).scalars():
        inv = db.get(Invoice, a.invoice_id)
        inv.amount_received = money(Decimal(inv.amount_received) - Decimal(a.amount))
        inv.tds_received = money(Decimal(inv.tds_received) - Decimal(a.tds_amount))
        billing._inv_status(inv)
        db.delete(a)
    r.status = "reversed"
    write_audit(db, actor=p, action="receipt.reverse", entity="receipt", entity_id=r.id, reason=body.reason)
    return to_dict(r)


# ===================================================================== expenses
class ExpenseIn(BaseModel):
    category: str = Field(pattern="^(fuel|toll|repair|hamali|loading|crane|parking|permit|allowance|insurance|compliance|godown|overhead|tyre|marketing|other)$")
    expense_date: date
    amount: Decimal = Field(gt=0)
    tax_amount: Decimal = Field(Decimal("0"), ge=0)
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = None
    bill_number: str | None = None
    trip_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    paid_by: str = Field("company", pattern="^(company|driver_cash|driver_advance|vendor_credit)$")
    payment_mode: str | None = None
    rebillable: bool = False
    receipt_document_id: uuid.UUID | None = None
    occurred_at: datetime | None = None


def find_duplicate_expense(db: Session, e: Expense) -> Expense | None:
    q = select(Expense).where(Expense.id != e.id, Expense.amount == e.amount, Expense.status != "rejected")
    if e.bill_number:
        hit = db.execute(q.where(Expense.bill_number == e.bill_number)).scalars().first()
        if hit:
            return hit
    return db.execute(q.where(Expense.expense_date == e.expense_date, Expense.category == e.category,
                              Expense.vehicle_id == e.vehicle_id, Expense.trip_id == e.trip_id)).scalars().first()


@router.post("/expenses")
def submit_expense(body: ExpenseIn, p: Principal = Depends(require_any("accounts.post", "driver.app", "fleet.write")), db: Session = Depends(get_db)):
    if body.trip_id:
        t = get_or_404(db, Trip, body.trip_id, "Trip")
        assert_trip_access(db, p, t, write=True)
        body.vehicle_id = body.vehicle_id or t.vehicle_id
    elif not p.is_internal:
        raise Forbidden("Drivers record expenses against an assigned trip")
    e = Expense(code=next_number(db, "EXP", "EXP"), submitted_by=p.user_id, driver_id=p.driver_id or None,
                source="driver_app" if p.driver_id else "office", **body.model_dump())
    db.add(e)
    db.flush()
    dup = find_duplicate_expense(db, e)
    if dup:
        e.duplicate_of = dup.id
    if body.receipt_document_id:
        from app.modules.platform.models import Document
        d = db.get(Document, body.receipt_document_id)
        if d and d.extracted:
            e.ocr = d.extracted
    return {**to_dict(e), "possible_duplicate": dup.code if dup else None}


@router.get("/expenses")
def list_expenses(status: str | None = None, trip_id: uuid.UUID | None = None, p: Principal = Depends(require_any("accounts.read", "fleet.read")),
                  db: Session = Depends(get_db)):
    q = select(Expense).order_by(Expense.expense_date.desc()).limit(1000)
    if status:
        q = q.where(Expense.status.in_(status.split(",")))
    if trip_id:
        q = q.where(Expense.trip_id == trip_id)
    return [to_dict(e) for e in db.execute(q).scalars()]


class ExpenseDecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/expenses/{eid}/decide")
def decide_expense(eid: uuid.UUID, body: ExpenseDecisionIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    e = get_or_404(db, Expense, eid, "Expense", lock=True)
    if e.status != "submitted":
        raise Conflict("bad_status", f"Expense is {e.status}")
    if e.submitted_by == p.user_id:
        raise Forbidden("You cannot approve an expense you submitted", code="self_approval")
    if e.duplicate_of and body.approve and not body.note:
        raise AppError("duplicate_note", "Possible duplicate - explain why it is not a duplicate")
    if not body.approve:
        if not body.note:
            raise AppError("reason_required", "Give the rejection reason")
        e.status, e.reject_reason = "rejected", body.note
    else:
        thr = Decimal(str(get_config(db, "approval.thresholds")["expense"]))
        if Decimal(e.amount) > thr and "owner_director" not in p.roles and not p.can("payment.approve"):
            raise Forbidden(f"Expenses above Rs {thr} need Owner/Director or payment approver")
        e.status, e.approved_by = "approved", p.user_id
        post_expense(db, p, e)
    write_audit(db, actor=p, action="expense.approve" if body.approve else "expense.reject", entity="expense", entity_id=e.id, reason=body.note)
    return to_dict(e)


# ===================================================================== settlements
class OwnerSettleIn(BaseModel):
    owner_id: uuid.UUID
    trip_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/settlements/owner")
def settle_owner(body: OwnerSettleIn, p: Principal = Depends(require("settlement.prepare")), db: Session = Depends(get_db)):
    return to_dict(billing.owner_settlement(db, p, body.owner_id, body.trip_ids))


class DriverSettleIn(BaseModel):
    driver_id: uuid.UUID
    earning_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/settlements/driver")
def settle_driver(body: DriverSettleIn, p: Principal = Depends(require("settlement.prepare")), db: Session = Depends(get_db)):
    return to_dict(billing.driver_settlement(db, p, body.driver_id, body.earning_ids))


@router.post("/settlements/{sid}/submit")
def submit_settlement(sid: uuid.UUID, p: Principal = Depends(require("settlement.prepare")), db: Session = Depends(get_db)):
    s = get_or_404(db, Settlement, sid, "Settlement")
    if s.status != "draft":
        raise Conflict("bad_status", f"Settlement is {s.status}")
    request_approval(db, p, kind="settlement", entity="settlement", entity_id=s.id, title=f"{s.party_type} settlement {s.code}: Rs {s.net_payable}",
                     required_permission="settlement.approve", amount=s.net_payable, payload={"lines": s.lines})
    s.status = "pending_approval"
    return to_dict(s)


@on_approval("settlement")
def _settlement_decided(db, actor, ar):
    s = db.get(Settlement, uuid.UUID(ar.entity_id))
    if ar.status == "approved":
        s.status, s.approved_by = "approved", actor.user_id
        billing.post_settlement(db, actor, s)
    else:
        s.status = "draft"


@router.get("/settlements")
def list_settlements(party_type: str | None = None, p: Principal = Depends(require_any("accounts.read", "settlement.prepare")), db: Session = Depends(get_db)):
    q = select(Settlement).order_by(Settlement.created_at.desc())
    if party_type:
        q = q.where(Settlement.party_type == party_type)
    return [to_dict(s) for s in db.execute(q).scalars()]


# ===================================================================== payments
class PaymentIn(BaseModel):
    payee_type: str = Field(pattern="^(owner|vendor|driver|employee|customer|statutory)$")
    payee_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    purpose: str = Field(min_length=3)
    settlement_id: uuid.UUID | None = None
    vendor_invoice_id: uuid.UUID | None = None
    company_bank_id: uuid.UUID | None = None
    mode: str = Field("neft", pattern="^(neft|rtgs|imps|upi|cheque|cash)$")
    idempotency_key: str | None = None


def _payee_name(db: Session, t: str, pid) -> str:
    from app.modules.fleet.models import Driver
    m = {"owner": VehicleOwner, "vendor": Vendor, "driver": Driver, "customer": Customer}.get(t)
    o = db.get(m, pid) if m and pid else None
    return o.name if o else t


@router.post("/payments")
def prepare_payment(body: PaymentIn, p: Principal = Depends(require("payment.prepare")), db: Session = Depends(get_db)):
    key = body.idempotency_key or hashlib.sha256(f"{body.payee_type}{body.payee_id}{body.amount}{body.purpose}{body.settlement_id}".encode()).hexdigest()[:40]
    existing = db.execute(select(Payment).where(Payment.idempotency_key == key)).scalar_one_or_none()
    if existing:
        return to_dict(existing)
    bank = None
    if body.payee_type in ("owner", "vendor", "driver", "employee") and body.mode != "cash":
        bank = db.execute(select(PartyBankAccount).where(PartyBankAccount.party_type == body.payee_type,
                                                         PartyBankAccount.party_id == body.payee_id,
                                                         PartyBankAccount.status == "active")).scalar_one_or_none()
        if not bank:
            raise BlockedByRule("no_verified_bank", "No approved bank account for this payee (bank details need maker-checker approval)")
    if body.settlement_id:
        s = get_or_404(db, Settlement, body.settlement_id, "Settlement")
        if s.status not in ("approved", "part_paid"):
            raise BlockedByRule("settlement_not_approved", "Settlement must be approved before payment")
        if Decimal(s.paid) + body.amount > Decimal(s.net_payable):
            raise BlockedByRule("overpayment", f"Payment exceeds settlement balance Rs {Decimal(s.net_payable) - Decimal(s.paid)}")
    pay = Payment(code=next_number(db, "PAY", "PAY"), payee_name=_payee_name(db, body.payee_type, body.payee_id),
                  bank_account_id=bank.id if bank else None, prepared_by=p.user_id, idempotency_key=key, status="pending_approval",
                  **body.model_dump(exclude={"idempotency_key"}))
    db.add(pay)
    db.flush()
    request_approval(db, p, kind="payment", entity="payment", entity_id=pay.id, title=f"Pay {pay.payee_name} Rs {pay.amount}: {pay.purpose}",
                     required_permission="payment.approve", amount=pay.amount)
    return to_dict(pay)


@on_approval("payment")
def _payment_decided(db, actor, ar):
    pay = db.get(Payment, uuid.UUID(ar.entity_id))
    if ar.status == "approved":
        pay.status, pay.approved_by = "approved", actor.user_id
    else:
        pay.status = "cancelled"


class ExecuteIn(BaseModel):
    via: str = Field(pattern="^(manual_bank_portal|bank_api)$")
    bank_reference: str | None = None


@router.post("/payments/{pid}/execute")
def execute(pid: uuid.UUID, body: ExecuteIn, p: Principal = Depends(require("payment.approve")), db: Session = Depends(get_db)):
    pay = get_or_404(db, Payment, pid, "Payment", lock=True)
    if pay.status == "executed":
        return to_dict(pay)  # idempotent
    if pay.prepared_by == p.user_id:
        raise Forbidden("Preparer cannot execute the payment", code="self_approval")
    billing.execute_payment(db, p, pay, body.via, body.bank_reference)
    return {**to_dict(pay), "mode_label": "SIMULATED bank execution (MOCK) - no money moved" if pay.executed_via and "mock" in pay.executed_via else None}


@router.get("/payments")
def list_payments(p: Principal = Depends(require_any("accounts.read", "payment.prepare")), db: Session = Depends(get_db)):
    return [to_dict(x) for x in db.execute(select(Payment).order_by(Payment.created_at.desc()).limit(1000)).scalars()]


# ===================================================================== bank
@router.post("/bank/import")
async def bank_import(company_bank_id: uuid.UUID = Form(...), file: UploadFile = File(...), p: Principal = Depends(require("bank.import")),
                      db: Session = Depends(get_db)):
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise AppError("too_large", "Statement file too large")
    imp = banksvc.import_statement(db, p, company_bank_id=company_bank_id, text=raw.decode("utf-8-sig", errors="replace"),
                                   filename=file.filename or "statement.csv")
    stats = banksvc.match_all(db, p, company_bank_id)
    return {"import": to_dict(imp), "matching": stats}


@router.post("/bank/match")
def run_match(p: Principal = Depends(require("bank.reconcile")), db: Session = Depends(get_db)):
    return banksvc.match_all(db, p)


@router.get("/bank/transactions")
def bank_txns(status: str | None = None, p: Principal = Depends(require_any("bank.reconcile", "accounts.read")), db: Session = Depends(get_db)):
    q = select(BankTransaction).order_by(BankTransaction.txn_date.desc()).limit(2000)
    if status:
        q = q.where(BankTransaction.status.in_(status.split(",")))
    return [to_dict(t) for t in db.execute(q).scalars()]


class ConfirmIn(BaseModel):
    entity: str = Field(pattern="^(receipt|invoice|customer|advance|payment|charges|interest|emi)$")
    ids: list[str] = []
    customer_id: uuid.UUID | None = None
    tds_amount: Decimal = Decimal("0")


@router.post("/bank/transactions/{tid}/confirm")
def confirm_txn(tid: uuid.UUID, body: ConfirmIn, p: Principal = Depends(require("bank.reconcile")), db: Session = Depends(get_db)):
    t = get_or_404(db, BankTransaction, tid, "Bank transaction", lock=True)
    banksvc.confirm_match(db, p, t, body.entity, body.ids, customer_id=body.customer_id, tds_amount=body.tds_amount)
    return to_dict(t)


@router.post("/bank/transactions/{tid}/ignore")
def ignore_txn(tid: uuid.UUID, body: ReverseIn, p: Principal = Depends(require("bank.reconcile")), db: Session = Depends(get_db)):
    t = get_or_404(db, BankTransaction, tid, "Bank transaction")
    t.status, t.match_reason = "ignored", body.reason
    write_audit(db, actor=p, action="bank.ignore", entity="bank_txn", entity_id=t.id, reason=body.reason)
    return to_dict(t)


@router.get("/bank/summary")
def bank_summary(p: Principal = Depends(require_any("bank.reconcile", "accounts.read", "cashflow.read")), db: Session = Depends(get_db)):
    from app.modules.masters.models import CompanyBankAccount
    return [banksvc.reconciliation_summary(db, cb.id) for cb in db.execute(select(CompanyBankAccount).where(CompanyBankAccount.is_cash.is_(False))).scalars()]


# ===================================================================== collections
@router.get("/collections")
def collections(p: Principal = Depends(require_any("collections.write", "accounts.read")), db: Session = Depends(get_db)):
    from app.modules.commercial.credit import exposure
    out = []
    for c in db.execute(select(Customer)).scalars():
        ex = exposure(db, c.id)
        if ex["outstanding"] <= 0:
            continue
        notes = [to_dict(n) for n in db.execute(select(CollectionNote).where(CollectionNote.customer_id == c.id)
                                                .order_by(CollectionNote.created_at.desc()).limit(5)).scalars()]
        priority = float(ex["overdue"]) * (1 + ex["oldest_overdue_days"] / 30)
        out.append({"customer_id": str(c.id), "customer": c.name, "outstanding": str(ex["outstanding"]), "overdue": str(ex["overdue"]),
                    "oldest_overdue_days": ex["oldest_overdue_days"], "disputed": str(ex["disputed"]), "priority_score": round(priority),
                    "recent_notes": notes})
    return sorted(out, key=lambda x: -x["priority_score"])


class NoteIn(BaseModel):
    customer_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    kind: str = Field(pattern="^(call|reminder|promise|dispute|short_payment|statement)$")
    note: str = Field(min_length=2)
    promise_date: date | None = None
    promise_amount: Decimal | None = None


@router.post("/collections/notes")
def add_note(body: NoteIn, p: Principal = Depends(require("collections.write")), db: Session = Depends(get_db)):
    n = CollectionNote(**body.model_dump(), by_user=p.user_id)
    db.add(n)
    if body.kind == "dispute" and body.invoice_id:
        inv = db.get(Invoice, body.invoice_id)
        inv.status = "disputed"
    db.flush()
    return to_dict(n)


@router.post("/collections/reminders")
def send_reminders(p: Principal = Depends(require("collections.write")), db: Session = Depends(get_db)):
    """Routine polite pre-due/due/overdue reminders via approved template. Never threatens or changes terms."""
    sent = 0
    today = date.today()
    for inv in db.execute(select(Invoice).where(Invoice.status.in_(("issued", "part_paid")))).scalars():
        days = (inv.due_date - today).days
        if days in (3, 0, -7, -15, -30):
            c = db.execute(select(Contact).where(Contact.customer_id == inv.customer_id)).scalars().first()
            if c and (c.email or c.phone):
                bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
                queue(db, channel="email" if c.email else "sms", recipient=c.email or c.phone, template="payment_reminder",
                      number=inv.number, balance=bal, due=f"{inv.due_date:%d-%m-%Y}", entity="invoice", entity_id=inv.id)
                sent += 1
    return {"sent": sent}


@router.get("/customers/{cid}/statement")
def statement(cid: uuid.UUID, p: Principal = Depends(require_any("accounts.read", "collections.write")), db: Session = Depends(get_db)):
    return customer_statement(db, cid)


def customer_statement(db: Session, cid) -> dict:
    rows = []
    for inv in db.execute(select(Invoice).where(Invoice.customer_id == cid, Invoice.status != "cancelled")).scalars():
        rows.append({"date": str(inv.invoice_date), "type": "invoice", "ref": inv.number, "debit": str(inv.total), "credit": "0"})
    for r in db.execute(select(Receipt).where(Receipt.customer_id == cid, Receipt.status == "confirmed")).scalars():
        rows.append({"date": str(r.receipt_date), "type": "advance" if r.is_advance else "receipt", "ref": r.number, "debit": "0",
                     "credit": str(Decimal(r.amount) + Decimal(r.tds_amount))})
        if r.tds_amount:
            rows[-1]["note"] = f"includes TDS {r.tds_amount}"
    rows.sort(key=lambda x: x["date"])
    bal = Decimal("0")
    for x in rows:
        bal += Decimal(x["debit"]) - Decimal(x["credit"])
        x["balance"] = str(bal)
    return {"customer_id": str(cid), "rows": rows, "closing_balance": str(bal)}


# ===================================================================== budgets
class BudgetIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    area: str = Field(pattern="^(fleet|operations|marketing|administration)$")
    category: str
    amount: Decimal = Field(ge=0)


@router.post("/budgets")
def add_budget(body: BudgetIn, p: Principal = Depends(require("budget.write")), db: Session = Depends(get_db)):
    b = db.execute(select(Budget).where(Budget.period == body.period, Budget.area == body.area, Budget.category == body.category)).scalar_one_or_none()
    if b and b.status == "approved":
        raise Conflict("approved", "Approved budgets change only through a new approval")
    if not b:
        b = Budget(**body.model_dump())
        db.add(b)
    b.amount = body.amount
    db.flush()
    return to_dict(b)


@router.post("/budgets/{period}/submit")
def submit_budget(period: str, p: Principal = Depends(require("budget.write")), db: Session = Depends(get_db)):
    total = db.execute(select(func.coalesce(func.sum(Budget.amount), 0)).where(Budget.period == period)).scalar()
    ar = request_approval(db, p, kind="budget", entity="budget", entity_id=period, title=f"Budget {period}: Rs {total}",
                          required_permission="budget.approve", amount=Decimal(total))
    return {"approval": ar.code}


@on_approval("budget")
def _budget_ok(db, actor, ar):
    if ar.status == "approved":
        for b in db.execute(select(Budget).where(Budget.period == ar.entity_id)).scalars():
            b.status, b.approved_by = "approved", actor.user_id


AREA_ACCOUNTS = {"fleet": ("5010", "5020", "5030", "5040", "5080", "5090"), "operations": ("5000", "5050", "5060", "5070", "5100"),
                 "marketing": ("5400",), "administration": ("5200", "5300", "5500", "5900")}


@router.get("/budgets/{period}/vs-actual")
def budget_vs_actual(period: str, p: Principal = Depends(require("cashflow.read")), db: Session = Depends(get_db)):
    y, m = map(int, period.split("-"))
    frm = date(y, m, 1)
    to = date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)
    pl = rpt.profit_and_loss(db, frm, to)
    actual = {e["code"]: Decimal(e["amount"]) for e in pl["expenses"]}
    out = []
    for area, codes in AREA_ACCOUNTS.items():
        bud = db.execute(select(func.coalesce(func.sum(Budget.amount), 0)).where(Budget.period == period, Budget.area == area)).scalar()
        act = sum((actual.get(c, Decimal("0")) for c in codes), Decimal("0"))
        out.append({"area": area, "budget": str(bud), "actual": str(act), "variance": str(Decimal(bud) - act)})
    return {"period": period, "rows": out, "actual_basis": "ACTUAL posted vouchers"}


# ===================================================================== reports
@router.get("/reports/trial-balance")
def r_tb(as_of: date | None = None, p: Principal = Depends(require_any("reports.read", "ca.read", "accounts.read")), db: Session = Depends(get_db)):
    return rpt.trial_balance(db, as_of)


@router.get("/reports/pnl")
def r_pnl(frm: date, to: date, p: Principal = Depends(require_any("reports.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.profit_and_loss(db, frm, to)


@router.get("/reports/balance-sheet")
def r_bs(as_of: date, p: Principal = Depends(require_any("reports.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.balance_sheet(db, as_of)


@router.get("/reports/ledger/{code}")
def r_ledger(code: str, frm: date | None = None, to: date | None = None, party_id: uuid.UUID | None = None, cost_centre: str | None = None,
             p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.ledger(db, code, frm, to, party_id, cost_centre)


@router.get("/reports/day-book")
def r_daybook(day: date, p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.day_book(db, day)


@router.get("/reports/ageing")
def r_ageing(side: str = "receivable", p: Principal = Depends(require_any("accounts.read", "reports.read")), db: Session = Depends(get_db)):
    return rpt.ageing(db, side)


@router.get("/reports/gst")
def r_gst(frm: date, to: date, p: Principal = Depends(require_any("tax.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.gst_register(db, frm, to)


@router.get("/reports/tds")
def r_tds(frm: date, to: date, p: Principal = Depends(require_any("tax.read", "ca.read")), db: Session = Depends(get_db)):
    return rpt.tds_register(db, frm, to)


@router.get("/reports/trip/{tid}/profitability")
def r_trip(tid: uuid.UUID, p: Principal = Depends(require_any("reports.read", "quote.view_cost")), db: Session = Depends(get_db)):
    return rpt.trip_profitability(db, get_or_404(db, Trip, tid, "Trip"))


@router.get("/reports/profitability")
def r_profit(frm: date, to: date, p: Principal = Depends(require("reports.read")), db: Session = Depends(get_db)):
    return rpt.profitability_summary(db, frm, to)


@router.get("/reports/cashflow")
def r_cash(weeks: int = 8, p: Principal = Depends(require("cashflow.read")), db: Session = Depends(get_db)):
    return rpt.cashflow_forecast(db, min(weeks, 26))


@router.get("/reports/export/{name}")
def export(name: str, fmt: str = "csv", frm: date | None = None, to: date | None = None,
           p: Principal = Depends(require("reports.export")), db: Session = Depends(get_db)):
    from app.modules.finance.export import export_report
    content, media, fname = export_report(db, name, fmt, frm or date(date.today().year, 4, 1), to or date.today())
    write_audit(db, actor=p, action="report.export", entity="report", entity_id=name, after={"format": fmt})
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ===================================================================== Tally
def tally_xml(db: Session, frm: date, to: date) -> bytes:
    env = ET.Element("ENVELOPE")
    hdr = ET.SubElement(env, "HEADER")
    ET.SubElement(hdr, "TALLYREQUEST").text = "Import Data"
    body = ET.SubElement(ET.SubElement(env, "BODY"), "IMPORTDATA")
    rd = ET.SubElement(ET.SubElement(body, "REQUESTDESC"), "REPORTNAME")
    rd.text = "Vouchers"
    data = ET.SubElement(body, "REQUESTDATA")
    tmap = {"sales": "Sales", "receipt": "Receipt", "payment": "Payment", "journal": "Journal", "expense": "Journal", "purchase": "Purchase"}
    for v in db.execute(select(Voucher).where(Voucher.vdate.between(frm, to), Voucher.status == "posted").order_by(Voucher.vdate)).scalars():
        msg = ET.SubElement(data, "TALLYMESSAGE")
        vx = ET.SubElement(msg, "VOUCHER", VCHTYPE=tmap.get(v.vtype, "Journal"), ACTION="Create")
        ET.SubElement(vx, "DATE").text = v.vdate.strftime("%Y%m%d")
        ET.SubElement(vx, "VOUCHERTYPENAME").text = tmap.get(v.vtype, "Journal")
        ET.SubElement(vx, "VOUCHERNUMBER").text = v.number
        ET.SubElement(vx, "NARRATION").text = v.narration
        for l in db.execute(select(VoucherLine).where(VoucherLine.voucher_id == v.id)).scalars():
            a = db.get(Account, l.account_id)
            le = ET.SubElement(vx, "ALLLEDGERENTRIES.LIST")
            ET.SubElement(le, "LEDGERNAME").text = a.name
            # Tally convention: debit = negative amount with ISDEEMEDPOSITIVE Yes
            ET.SubElement(le, "ISDEEMEDPOSITIVE").text = "Yes" if l.debit > 0 else "No"
            ET.SubElement(le, "AMOUNT").text = str(-l.debit if l.debit > 0 else l.credit)
    return ET.tostring(env, encoding="utf-8", xml_declaration=True)


@router.get("/tally/export")
def tally_export(frm: date, to: date, p: Principal = Depends(require_any("accounts.read", "ca.read")), db: Session = Depends(get_db)):
    write_audit(db, actor=p, action="tally.export", entity="report", entity_id="tally", after={"from": str(frm), "to": str(to)})
    return Response(content=tally_xml(db, frm, to), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="GRL_Tally_{frm}_{to}.xml"'})


def parse_tally(db: Session, raw: bytes) -> tuple[list[dict], list[dict]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise AppError("bad_xml", f"Not a valid Tally XML file: {e}")
    names = {a.name.lower(): a.code for a in db.execute(select(Account)).scalars()}
    vouchers, exceptions = [], []
    seen = set()
    for i, vx in enumerate(root.iter("VOUCHER")):
        num = (vx.findtext("VOUCHERNUMBER") or "").strip()
        dt = vx.findtext("DATE") or ""
        try:
            vdate = datetime.strptime(dt.strip(), "%Y%m%d").date()
        except ValueError:
            exceptions.append({"row": i + 1, "voucher": num, "issue": f"Bad date '{dt}'"})
            continue
        lines, td, tc = [], Decimal("0"), Decimal("0")
        bad = False
        for le in vx.iter("ALLLEDGERENTRIES.LIST"):
            lname = (le.findtext("LEDGERNAME") or "").strip()
            amt = Decimal((le.findtext("AMOUNT") or "0").strip())
            code = names.get(lname.lower())
            if not code:
                exceptions.append({"row": i + 1, "voucher": num, "issue": f"Ledger '{lname}' not mapped"})
                bad = True
                continue
            if amt < 0:
                lines.append({"account": code, "debit": -amt, "credit": Decimal("0")})
                td += -amt
            else:
                lines.append({"account": code, "debit": Decimal("0"), "credit": amt})
                tc += amt
        ext = f"TALLY:{vx.get('VCHTYPE', '')}:{num}:{vdate}"
        if td != tc:
            exceptions.append({"row": i + 1, "voucher": num, "issue": f"Unbalanced Dr {td} / Cr {tc}"})
            bad = True
        if ext in seen or db.execute(select(Voucher.id).where(Voucher.external_ref == ext)).first():
            exceptions.append({"row": i + 1, "voucher": num, "issue": "Duplicate - already imported"})
            bad = True
        seen.add(ext)
        if not bad:
            vouchers.append({"external_ref": ext, "vdate": str(vdate), "fy": financial_year(vdate),
                             "narration": vx.findtext("NARRATION") or f"Tally {num}",
                             "lines": [{k: str(v) for k, v in l.items()} for l in lines]})
    return vouchers, exceptions


@router.post("/tally/import")
async def tally_import(file: UploadFile = File(...), p: Principal = Depends(require("accounts.post")), db: Session = Depends(get_db)):
    """Dry run: parse and validate. Nothing is posted until a different user approves the batch."""
    raw = await file.read()
    vouchers, exceptions = parse_tally(db, raw)
    b = ImportBatch(code=next_number(db, "IMP", "IMP"), kind="tally_vouchers", filename=file.filename or "tally.xml",
                    checksum=hashlib.sha256(raw).hexdigest(), preview={"vouchers": vouchers, "count": len(vouchers)},
                    exceptions=exceptions, created_by=p.user_id)
    db.add(b)
    db.flush()
    return {"batch": b.code, "id": str(b.id), "valid_vouchers": len(vouchers), "exceptions": exceptions}


@router.post("/import-batches/{bid}/commit")
def commit_batch(bid: uuid.UUID, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    b = get_or_404(db, ImportBatch, bid, "Import batch", lock=True)
    if b.status != "previewed":
        raise Conflict("bad_status", f"Batch is {b.status}")
    if b.created_by == p.user_id:
        raise Forbidden("A different user must approve the import", code="self_approval")
    ids = []
    for v in b.preview["vouchers"]:
        vo = post_voucher(db, p, vtype="journal", vdate=date.fromisoformat(v["vdate"]), narration=v["narration"],
                          lines=[{**l, "debit": Decimal(l["debit"]), "credit": Decimal(l["credit"])} for l in v["lines"]],
                          source_entity="import", source_id=b.id, external_ref=v["external_ref"], approved_by=p.user_id)
        ids.append(str(vo.id))
    b.status, b.approved_by, b.committed_ids = "committed", p.user_id, ids
    return {"committed": len(ids)}


@router.post("/import-batches/{bid}/reverse")
def reverse_batch(bid: uuid.UUID, body: ReverseIn, p: Principal = Depends(require("accounts.approve")), db: Session = Depends(get_db)):
    b = get_or_404(db, ImportBatch, bid, "Import batch", lock=True)
    if b.status != "committed":
        raise Conflict("bad_status", "Only committed batches can be reversed")
    for vid in b.committed_ids:
        reverse_voucher(db, p, uuid.UUID(vid), f"Import batch {b.code} reversed: {body.reason}")
    b.status = "reversed"
    return {"reversed": len(b.committed_ids)}


@router.get("/import-batches")
def batches(p: Principal = Depends(require("accounts.read")), db: Session = Depends(get_db)):
    return [{**to_dict(b), "preview": {"count": b.preview.get("count")}} for b in db.execute(select(ImportBatch).order_by(ImportBatch.created_at.desc())).scalars()]
