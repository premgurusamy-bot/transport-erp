"""GST treatments, invoices, notes, e-way bills, chart of accounts, vouchers, bank reconciliation."""
from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from .base import (
    JSON, ActiveMixin, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, Money, Numeric, Qty, Rate,
    String, Text,
)


class GstTreatment(AuditMixin, ActiveMixin, Base):
    """Configurable GST classification. Defaults are seeded but MUST be verified with a GST practitioner."""

    __tablename__ = "gst_treatments"
    code = F(String(30), "Code", required=True, unique=True)
    name = F(String(160), "Name", required=True)
    service_type = F(String(30), "Service classification", options=["GTA", "Vehicle Hire (with operator)", "Warehousing", "Handling", "Other"], required=True)
    sac = F(String(8), "SAC", required=True)
    gst_rate = F(Numeric(5, 2), "GST rate (%)", default=0)
    charge_mechanism = F(String(6), "Mechanism", options=["FCM", "RCM", "EXEMPT", "NIL"], required=True)
    itc_eligible = F(Boolean, "Transporter can claim ITC", default=False)
    invoice_note = F(Text, "Note printed on invoice")
    legal_basis = F(Text, "Legal basis / notification reference")
    verified = F(Boolean, "Verified by tax consultant", default=False)


class Invoice(AuditMixin, Base):
    __tablename__ = "invoices"
    invoice_no = Column(String(40), unique=True, nullable=False)
    doc_type = Column(String(20), nullable=False)  # tax_invoice / proforma / debit_note / credit_note / bill_of_supply / advance_receipt
    invoice_date = Column(Date, nullable=False, index=True)
    branch_id = Column(Integer)
    customer_id = Column(Integer, nullable=False, index=True)
    billing_name = Column(String(200))
    billing_address = Column(Text)
    customer_gstin = Column(String(15))
    place_of_supply = Column(String(2), nullable=False)
    supplier_state_code = Column(String(2), nullable=False)
    supplier_gstin = Column(String(15))
    gst_treatment_id = Column(Integer)
    gst_treatment_code = Column(String(30))
    sac = Column(String(8))
    charge_mechanism = Column(String(6), nullable=False)
    gst_rate = Column(Numeric(5, 2), default=0)
    is_interstate = Column(Boolean, default=False, nullable=False)
    basis = Column(String(20))  # lr / trip / consolidated / monthly_contract / warehouse / manual
    period_from = Column(Date)
    period_to = Column(Date)
    reference_invoice_id = Column(Integer)  # for debit/credit notes
    reason = Column(Text)
    po_number = Column(String(60))
    taxable_value = Column(Money, default=0, nullable=False)
    cgst = Column(Money, default=0, nullable=False)
    sgst = Column(Money, default=0, nullable=False)
    igst = Column(Money, default=0, nullable=False)
    rcm_tax = Column(Money, default=0, nullable=False)
    round_off = Column(Money, default=0, nullable=False)
    total = Column(Money, default=0, nullable=False)
    amount_received = Column(Money, default=0, nullable=False)
    due_date = Column(Date)
    status = Column(String(15), default="Issued", nullable=False)  # Draft / Issued / Partly Paid / Paid / Cancelled
    voucher_id = Column(Integer)
    cancel_voucher_id = Column(Integer)
    cancelled_at = Column(DateTime(timezone=True))
    cancelled_by = Column(Integer)
    cancel_reason = Column(Text)
    einvoice_status = Column(String(20), default="Not Applicable")  # Not Applicable / Pending / Generated / Failed / Cancelled
    irn = Column(String(64))
    ack_no = Column(String(30))
    ack_date = Column(DateTime(timezone=True))
    signed_qr = Column(Text)
    einvoice_error = Column(Text)
    notes = Column(Text)
    verify_token = Column(String(40))


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, nullable=False, index=True)
    line_no = Column(Integer, default=1)
    description = Column(Text, nullable=False)
    sac = Column(String(8))
    consignment_id = Column(Integer, index=True)
    trip_id = Column(Integer, index=True)
    quantity = Column(Qty, default=1)
    uom = Column(String(10), default="NOS")
    rate = Column(Rate, default=0)
    amount = Column(Money, default=0, nullable=False)
    details = Column(JSON)


class EwayBill(AuditMixin, Base):
    __tablename__ = "eway_bills"
    ewb_no = F(String(12), "E-way bill no.", required=True, unique=True)
    ewb_date = F(DateTime(timezone=True), "Generated on", required=True)
    valid_until = F(DateTime(timezone=True), "Valid until", required=True)
    consignment_id = F(Integer, "LR", fk="consignments.id", ref="consignments")
    vehicle_no = F(String(15), "Vehicle no.")
    from_place = F(String(120), "From")
    to_place = F(String(120), "To")
    distance_km = F(Numeric(8, 1), "Distance (km)")
    goods_value = F(Money, "Goods value (₹)")
    source = F(String(20), "Source", options=["Manual (portal)", "API"], default="Manual (portal)")
    status = F(String(15), "Status", options=["Active", "Extended", "Cancelled", "Expired", "Closed"], default="Active")
    part_b_history = Column(JSON, default=list)
    remarks = F(Text, "Remarks")


class AccountGroup(Base):
    __tablename__ = "account_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    parent_id = Column(Integer, nullable=True)
    nature = Column(String(10), nullable=False)  # Asset / Liability / Income / Expense / Equity
    cash_flow = Column(String(12), default="operating")  # operating / investing / financing / cash
    is_system = Column(Boolean, default=True)


class Ledger(AuditMixin, ActiveMixin, Base):
    __tablename__ = "ledgers"
    name = F(String(200), "Ledger name", required=True, unique=True)
    code = F(String(30), "Code", unique=True)
    group_id = F(Integer, "Group", fk="account_groups.id", ref="account_groups", required=True)
    opening_balance = F(Money, "Opening balance (₹)", default=0)
    opening_type = F(String(2), "Opening Dr/Cr", options=["Dr", "Cr"], default="Dr")
    party_type = F(String(12), "Linked to", options=["", "customer", "vendor", "driver", "employee", "bank", "cash", "vehicle"], readonly=True)
    party_id = F(Integer, "Party id", readonly=True)
    system_key = Column(String(40), unique=True, nullable=True)  # e.g. FREIGHT_INCOME, CGST_OUTPUT
    gstin = F(String(15), "GSTIN", validator="gstin")
    is_bank = F(Boolean, "Bank account", default=False)


class Voucher(AuditMixin, Base):
    __tablename__ = "vouchers"
    voucher_no = Column(String(40), unique=True, nullable=False)
    voucher_type = Column(String(15), nullable=False)  # Journal/Payment/Receipt/Contra/Purchase/Sales/Debit Note/Credit Note
    voucher_date = Column(Date, nullable=False, index=True)
    narration = Column(Text)
    reference = Column(String(80))
    source_type = Column(String(30))
    source_id = Column(Integer)
    status = Column(String(12), default="Posted", nullable=False)  # Posted / Cancelled / Reversal
    reversal_of_id = Column(Integer)
    reversed_by_id = Column(Integer)
    cancel_reason = Column(Text)
    total = Column(Money, default=0, nullable=False)
    branch_id = Column(Integer)


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="non_negative"),
        CheckConstraint("NOT (debit > 0 AND credit > 0)", name="one_side"),
    )
    id = Column(Integer, primary_key=True)
    voucher_id = Column(Integer, nullable=False, index=True)
    ledger_id = Column(Integer, nullable=False, index=True)
    debit = Column(Money, default=0, nullable=False)
    credit = Column(Money, default=0, nullable=False)
    narration = Column(String(300))
    cost_vehicle_id = Column(Integer, index=True)
    cost_trip_id = Column(Integer, index=True)
    bank_reconciled_on = Column(Date)
    bank_statement_line_id = Column(Integer)
    instrument_no = Column(String(40))


class BillAllocation(Base):
    """Bill-wise settlement: receipts against invoices, payments against vendor bills."""

    __tablename__ = "bill_allocations"
    id = Column(Integer, primary_key=True)
    voucher_id = Column(Integer, nullable=False, index=True)
    invoice_id = Column(Integer, index=True)
    vendor_bill_id = Column(Integer, index=True)
    amount = Column(Money, nullable=False)
    tds_amount = Column(Money, default=0)
    at = Column(DateTime(timezone=True))
    reversed = Column(Boolean, default=False, nullable=False)


class BankStatementLine(Base):
    __tablename__ = "bank_statement_lines"
    id = Column(Integer, primary_key=True)
    ledger_id = Column(Integer, nullable=False, index=True)
    txn_date = Column(Date, nullable=False)
    description = Column(String(300))
    reference = Column(String(80))
    debit = Column(Money, default=0)  # money out (bank perspective: withdrawal)
    credit = Column(Money, default=0)  # money in (deposit)
    balance = Column(Money)
    matched_entry_id = Column(Integer)
    import_batch = Column(String(40))
    __table_args__ = (UniqueConstraint("ledger_id", "txn_date", "reference", "debit", "credit", name="uq_bank_line"),)
