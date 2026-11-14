"""CRM enquiries, versioned quotations, bookings (one booking = one customer consignment = one LR) and packages."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Enquiry(Base, IdMixin, TimestampMixin):
    __tablename__ = "enquiries"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    source: Mapped[str] = mapped_column(String(20))  # office|phone|whatsapp|email|website|referral|portal
    campaign: Mapped[str | None] = mapped_column(String(80))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    prospect_name: Mapped[str | None] = mapped_column(String(200))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(160))
    service_type: Mapped[str] = mapped_column(String(3))  # FTL|PTL
    service_level: Mapped[str] = mapped_column(String(20), default="standard")  # standard|priority|time_critical
    origin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    destination_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    origin_text: Mapped[str | None] = mapped_column(String(200))
    destination_text: Mapped[str | None] = mapped_column(String(200))
    pickup_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deliver_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    goods_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goods_categories.id"))
    goods_description: Mapped[str | None] = mapped_column(Text)
    package_count: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    volume_cft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    dimensions: Mapped[list | None] = mapped_column(JSON)  # [{l_ft,w_ft,h_ft,qty,stackable,fragile,weight_kg}]
    declared_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    handling: Mapped[list] = mapped_column(JSON, default=list)  # fragile, keep_dry, crane_required ...
    vehicle_requirement: Mapped[str | None] = mapped_column(String(120))
    required_documents: Mapped[list] = mapped_column(JSON, default=list)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    next_action: Mapped[str | None] = mapped_column(String(200))
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="new")  # new|qualifying|quoted|won|lost|duplicate|on_hold
    lead_class: Mapped[str | None] = mapped_column(String(20))  # hot|warm|cold (AI suggestion or human)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enquiries.id"))
    lost_reason: Mapped[str | None] = mapped_column(String(160))
    raw_text: Mapped[str | None] = mapped_column(Text)


class Quotation(Base, IdMixin, TimestampMixin):
    """Each version is its own row. INTERNAL fields (cost, owner quote, margin) are never sent to customers."""

    __tablename__ = "quotations"
    __table_args__ = (UniqueConstraint("number", "version"),)
    number: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enquiry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("enquiries.id"), index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    service_type: Mapped[str] = mapped_column(String(3))
    service_level: Mapped[str] = mapped_column(String(20), default="standard")
    vehicle_option: Mapped[str] = mapped_column(String(10), default="own")  # own|attached
    vehicle_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_types.id"))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    # ---- internal ----
    cost_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    internal_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    market_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    owner_quote: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    negotiated_owner_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    direct_expenses: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    floor_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    list_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    expected_contribution: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2), default=0)
    ptl_allocation: Mapped[dict | None] = mapped_column(JSON)  # formula version + basis used
    # ---- customer-facing ----
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # freight excluding GST
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0)
    extra_charges: Mapped[list] = mapped_column(JSON, default=list)  # [{code,label,amount}]
    gst_mode: Mapped[str] = mapped_column(String(10), default="RCM")
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_window: Mapped[str | None] = mapped_column(String(120))
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    assumptions: Mapped[str | None] = mapped_column(Text)
    exclusions: Mapped[str | None] = mapped_column(Text)
    customer_responsibilities: Mapped[str | None] = mapped_column(Text)
    ptl_disclosure: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|sent|accepted|rejected|expired|superseded
    below_floor: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_requests.id"))
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[str | None] = mapped_column(String(160))
    acceptance_channel: Mapped[str | None] = mapped_column(String(20))


class Booking(Base, IdMixin, TimestampMixin):
    """A customer consignment. FTL bookings get an exclusive trip; PTL bookings may share a trip."""

    __tablename__ = "bookings"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_branches.id"))
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotations.id"))
    service_type: Mapped[str] = mapped_column(String(3))
    service_level: Mapped[str] = mapped_column(String(20), default="standard")
    ptl_consent: Mapped[bool] = mapped_column(Boolean, default=False)  # customer told transport is shared
    consignor_name: Mapped[str] = mapped_column(String(200))
    consignor_address: Mapped[str | None] = mapped_column(Text)
    consignor_gstin: Mapped[str | None] = mapped_column(String(15))
    consignee_name: Mapped[str] = mapped_column(String(200))
    consignee_address: Mapped[str | None] = mapped_column(Text)
    consignee_phone: Mapped[str | None] = mapped_column(String(20))
    consignee_gstin: Mapped[str | None] = mapped_column(String(15))
    origin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    destination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    pickup_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deliver_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    goods_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("goods_categories.id"))
    goods_description: Mapped[str] = mapped_column(Text)
    package_count: Mapped[int] = mapped_column(Integer, default=1)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    volume_cft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    floor_sqft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    max_package_length_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)
    fragile: Mapped[bool] = mapped_column(Boolean, default=False)
    declared_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    handling: Mapped[list] = mapped_column(JSON, default=list)
    required_body_type: Mapped[str | None] = mapped_column(String(30))
    instructions: Mapped[str | None] = mapped_column(Text)
    loading_by: Mapped[str] = mapped_column(String(20), default="customer")  # customer|company|vendor
    unloading_by: Mapped[str] = mapped_column(String(20), default="customer")
    freight_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    extra_charges: Mapped[list] = mapped_column(JSON, default=list)
    gst_mode: Mapped[str] = mapped_column(String(10), default="RCM")
    payment_terms: Mapped[str | None] = mapped_column(String(200))
    advance_required: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    advance_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit_status: Mapped[str] = mapped_column(String(20), default="unchecked")  # unchecked|ok|warning|blocked|exception_approved
    credit_snapshot: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # draft|confirmed|planned|dispatched|in_transit|delivered|pod_verified|invoiced|closed|cancelled|on_hold
    cancellation_terms: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(String(200))
    created_via: Mapped[str] = mapped_column(String(20), default="office")  # office|portal|quote|paper_form
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pod_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str | None] = mapped_column(String(20))  # full|partial|failed|returned


class BookingVersion(Base, IdMixin):
    """Snapshot of a booking before each authorised modification."""

    __tablename__ = "booking_versions"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModificationRequest(Base, IdMixin, TimestampMixin):
    """Customer-requested change: a request until authorised and feasible."""

    __tablename__ = "modification_requests"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))  # modify|cancel|convert_ptl
    changes: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="requested")  # requested|approved|rejected
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_note: Mapped[str | None] = mapped_column(Text)
    charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class Package(Base, IdMixin, TimestampMixin):
    """Package-level identity for PTL (QR label) and custody scans."""

    __tablename__ = "packages"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    label: Mapped[str] = mapped_column(String(40), unique=True)  # printed as QR
    seq: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(200))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    width_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    height_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)
    fragile: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="created")
    # created|picked|in_godown|loaded|in_transit|delivered|short|damaged|returned
    last_location: Mapped[str | None] = mapped_column(String(120))
    godown_location: Mapped[str | None] = mapped_column(String(40))
