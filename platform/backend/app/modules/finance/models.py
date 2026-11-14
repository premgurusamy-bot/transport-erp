"""Double-entry accounting, invoices, receipts, expenses, settlements, payments, bank reconciliation, collections, budgets."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Account(Base, IdMixin, TimestampMixin):
    __tablename__ = "accounts"
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    nature: Mapped[str] = mapped_column(String(10))  # asset|liability|equity|income|expense
    group: Mapped[str] = mapped_column(String(60))  # Sundry Debtors, Bank Accounts, Direct Expenses ...
    parent_code: Mapped[str | None] = mapped_column(String(20))
    is_control: Mapped[bool] = mapped_column(Boolean, default=False)  # debtors/creditors control (party sub-ledger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Voucher(Base, IdMixin, TimestampMixin):
    """Posted vouchers are never edited or deleted - corrections are made by reversal."""

    __tablename__ = "vouchers"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    vtype: Mapped[str] = mapped_column(String(20))  # journal|sales|purchase|receipt|payment|contra|credit_note|debit_note|expense
    vdate: Mapped[date] = mapped_column(Date, index=True)
    fy: Mapped[str] = mapped_column(String(9), index=True)
    narration: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="posted")  # posted|reversed
    source_entity: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    external_ref: Mapped[str | None] = mapped_column(String(80))  # e.g. Tally voucher no. on import


class VoucherLine(Base, IdMixin):
    __tablename__ = "voucher_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0) AND (debit + credit) > 0", name="one_side"),
    )
    voucher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vouchers.id", ondelete="RESTRICT"), index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    party_type: Mapped[str | None] = mapped_column(String(15))  # customer|owner|vendor|driver|employee
    party_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    cost_centre: Mapped[str | None] = mapped_column(String(40), index=True)  # e.g. VEH:TN37AB1234, GODOWN, OFFICE
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    line_narration: Mapped[str | None] = mapped_column(String(250))


class Invoice(Base, IdMixin, TimestampMixin):
    __tablename__ = "invoices"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    gst_mode: Mapped[str] = mapped_column(String(10))  # RCM|FCM
    place_of_supply: Mapped[str | None] = mapped_column(String(2))
    taxable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    sgst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    igst: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    pass_through: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # reimbursements not income
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    amount_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tds_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(15), default="issued")  # issued|part_paid|paid|cancelled|disputed
    tax_rule_snapshot: Mapped[dict] = mapped_column(JSON)
    irn: Mapped[str | None] = mapped_column(String(80))
    irn_status: Mapped[str] = mapped_column(String(25), default="not_applicable")  # not_applicable|pending|generated_mock|generated
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class InvoiceLine(Base, IdMixin):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    lr_number: Mapped[str | None] = mapped_column(String(40))
    charge_code: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(250))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    is_pass_through: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # false once invoice cancelled


# The same booking + charge cannot be billed twice on active invoices
Index("uq_invoice_line_booking_charge", InvoiceLine.booking_id, InvoiceLine.charge_code, unique=True,
      postgresql_where=text("active = true AND booking_id IS NOT NULL"))


class Receipt(Base, IdMixin, TimestampMixin):
    __tablename__ = "receipts"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)  # None = unidentified
    receipt_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    mode: Mapped[str] = mapped_column(String(15))  # neft|rtgs|imps|upi|cheque|cash|gateway
    reference: Mapped[str | None] = mapped_column(String(80))
    company_bank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("company_bank_accounts.id"))
    bank_txn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_transactions.id"))
    # A receipt is only `confirmed` after it matches a bank credit (or cash is counted) - never assumed.
    status: Mapped[str] = mapped_column(String(15), default="unconfirmed")  # unconfirmed|confirmed|reversed
    is_advance: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"))
    unallocated: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    remittance_note: Mapped[str | None] = mapped_column(Text)
    planned_allocations: Mapped[list | None] = mapped_column(JSON)  # remittance advice, applied on confirmation


class ReceiptAllocation(Base, IdMixin):
    __tablename__ = "receipt_allocations"
    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receipts.id"), index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class Expense(Base, IdMixin, TimestampMixin):
    __tablename__ = "expenses"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    category: Mapped[str] = mapped_column(String(30))  # fuel|toll|repair|hamali|loading|crane|parking|permit|allowance|insurance|compliance|godown|overhead|tyre|other
    expense_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    vendor_name: Mapped[str | None] = mapped_column(String(160))
    bill_number: Mapped[str | None] = mapped_column(String(60))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"))
    paid_by: Mapped[str] = mapped_column(String(20), default="company")  # company|driver_cash|driver_advance|vendor_credit
    payment_mode: Mapped[str | None] = mapped_column(String(15))
    rebillable: Mapped[bool] = mapped_column(Boolean, default=False)  # pass-through to customer
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    ocr: Mapped[dict | None] = mapped_column(JSON)  # suggestions only - "extracted, not verified"
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted|approved|rejected|posted|disputed
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), default="office")


class Settlement(Base, IdMixin, TimestampMixin):
    __tablename__ = "settlements"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    party_type: Mapped[str] = mapped_column(String(10))  # driver|owner|vendor
    party_id: Mapped[uuid.UUID] = mapped_column(index=True)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    lines: Mapped[list] = mapped_column(JSON)  # [{kind, ref, description, amount}] amount + earned / - adjustment
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    advances: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    adjustments: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tds: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    net_payable: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|part_paid|paid|cancelled
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))


class Payment(Base, IdMixin, TimestampMixin):
    """Outgoing payment. Prepared by one user, approved by another; executed only after approval.
    The system never pays autonomously."""

    __tablename__ = "payments"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    payee_type: Mapped[str] = mapped_column(String(10))  # owner|vendor|driver|employee|customer|statutory
    payee_id: Mapped[uuid.UUID | None] = mapped_column()
    payee_name: Mapped[str] = mapped_column(String(160))
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party_bank_accounts.id"))
    company_bank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("company_bank_accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purpose: Mapped[str] = mapped_column(String(250))
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("settlements.id"))
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))
    vendor_invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendor_invoices.id"))
    mode: Mapped[str] = mapped_column(String(15), default="neft")
    status: Mapped[str] = mapped_column(String(20), default="prepared")  # prepared|pending_approval|approved|executed|confirmed|failed|cancelled
    prepared_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    executed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    executed_via: Mapped[str | None] = mapped_column(String(30))  # manual_bank_portal|bank_api_mock|bank_api_live
    bank_reference: Mapped[str | None] = mapped_column(String(80))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))
    bank_txn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_transactions.id"))


class BankStatementImport(Base, IdMixin, TimestampMixin):
    __tablename__ = "bank_statement_imports"
    company_bank_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("company_bank_accounts.id"))
    source: Mapped[str] = mapped_column(String(20))  # csv_upload|email|api_mock|api_live
    filename: Mapped[str | None] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    statement_from: Mapped[date | None] = mapped_column(Date)
    statement_to: Mapped[date | None] = mapped_column(Date)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    imported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class BankTransaction(Base, IdMixin, TimestampMixin):
    __tablename__ = "bank_transactions"
    company_bank_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("company_bank_accounts.id"), index=True)
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bank_statement_imports.id"))
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(String(80), index=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    mode: Mapped[str | None] = mapped_column(String(15))  # upi|neft|rtgs|imps|cheque|charges|interest|emi|transfer|other
    counterparty: Mapped[str | None] = mapped_column(String(160))
    dedupe_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(15), default="unmatched", index=True)  # unmatched|suggested|matched|ignored
    match_entity: Mapped[str | None] = mapped_column(String(30))
    match_ids: Mapped[list | None] = mapped_column(JSON)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    match_reason: Mapped[str | None] = mapped_column(Text)
    matched_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    auto_matched: Mapped[bool] = mapped_column(Boolean, default=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class CollectionNote(Base, IdMixin, TimestampMixin):
    __tablename__ = "collection_notes"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    kind: Mapped[str] = mapped_column(String(20))  # call|reminder|promise|dispute|short_payment|statement
    note: Mapped[str] = mapped_column(Text)
    promise_date: Mapped[date | None] = mapped_column(Date)
    promise_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(15), default="open")  # open|kept|broken|resolved
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Budget(Base, IdMixin, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("period", "area", "category"),)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    area: Mapped[str] = mapped_column(String(20))  # fleet|operations|marketing|administration
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(15), default="draft")  # draft|approved
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class ImportBatch(Base, IdMixin, TimestampMixin):
    """Data migration batch (Excel / Tally XML / CSV): dry run → preview → approval → commit → reversal."""

    __tablename__ = "import_batches"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    kind: Mapped[str] = mapped_column(String(30))  # tally_vouchers|tally_ledgers|customers|vehicles|opening_balances
    filename: Mapped[str] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="previewed")  # previewed|approved|committed|reversed|failed
    preview: Mapped[dict] = mapped_column(JSON)
    exceptions: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    committed_ids: Mapped[list] = mapped_column(JSON, default=list)
