"""Procurement (request → RFQ → PO → receipt → invoice 3-way match), inventory and godown handling."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class PurchaseRequest(Base, IdMixin, TimestampMixin):
    __tablename__ = "purchase_requests"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    category: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    items: Mapped[list] = mapped_column(JSON, default=list)  # [{item_id?, name, qty, uom}]
    estimated_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    job_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_cards.id"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    emergency_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    # requested|rfq|quotes_received|pending_approval|approved|ordered|received|invoiced|closed|rejected|retro_review
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    shortlist: Mapped[list] = mapped_column(JSON, default=list)  # vendor ids (approved vendors only)


class RfqQuote(Base, IdMixin, TimestampMixin):
    __tablename__ = "rfq_quotes"
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_requests.id"), index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    submitted_via: Mapped[str] = mapped_column(String(15), default="office")  # office|vendor_portal
    selected: Mapped[bool] = mapped_column(Boolean, default=False)


class PurchaseOrder(Base, IdMixin, TimestampMixin):
    __tablename__ = "purchase_orders"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_requests.id"))
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id"), index=True)
    kind: Mapped[str] = mapped_column(String(15), default="po")  # po|work_order
    lines: Mapped[list] = mapped_column(JSON)  # [{item_id?, name, qty, rate, amount}]
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="issued")  # issued|accepted|in_progress|completed|invoiced|closed|cancelled
    vendor_status_note: Mapped[str | None] = mapped_column(Text)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class GoodsReceipt(Base, IdMixin, TimestampMixin):
    """Receipt of goods or proof of service completion against a PO."""

    __tablename__ = "goods_receipts"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    lines: Mapped[list] = mapped_column(JSON)  # [{name, qty_received, qty_accepted, note}]
    accepted_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    evidence_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    inspected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VendorInvoice(Base, IdMixin, TimestampMixin):
    __tablename__ = "vendor_invoices"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vendors.id"), index=True)
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"))
    invoice_number: Mapped[str] = mapped_column(String(60))
    invoice_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tds_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    match_result: Mapped[dict | None] = mapped_column(JSON)  # three-way match detail
    status: Mapped[str] = mapped_column(String(20), default="received")  # received|matched|mismatch|approved|paid|rejected
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    submitted_via: Mapped[str] = mapped_column(String(15), default="office")
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))


class InventoryItem(Base, IdMixin, TimestampMixin):
    __tablename__ = "inventory_items"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(30))  # spare|tyre|battery|lubricant|packing|other
    uom: Mapped[str] = mapped_column(String(10), default="nos")
    facility_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facilities.id"))
    min_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    max_qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # weighted average valuation
    serial_tracked: Mapped[bool] = mapped_column(Boolean, default=False)


class StockMovement(Base, IdMixin):
    __tablename__ = "stock_movements"
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    kind: Mapped[str] = mapped_column(String(15))  # receipt|issue|return|adjust|damaged|stocktake
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3))  # +in / -out
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    job_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_cards.id"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    grn_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goods_receipts.id"))
    serial: Mapped[str | None] = mapped_column(String(60))
    reason: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class GodownEntry(Base, IdMixin, TimestampMixin):
    """Consignment held at a verified facility (inward GRN → location → outward)."""

    __tablename__ = "godown_entries"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("facilities.id"), index=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    package_count: Mapped[int] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(20), default="good")
    location: Mapped[str | None] = mapped_column(String(40))  # rack/bay
    inward_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outward_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outward_trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    outward_count: Mapped[int | None] = mapped_column(Integer)
    storage_rate_per_day: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    handling_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    photo_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(15), default="in_stock")  # in_stock|dispatched|discrepancy
