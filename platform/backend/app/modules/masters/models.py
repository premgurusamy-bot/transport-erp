"""Central business master data."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Customer(Base, IdMixin, TimestampMixin):
    """A customer organisation = a tenant. Customer users only ever see records with their customer_id."""

    __tablename__ = "customers"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    name_normalized: Mapped[str] = mapped_column(String(200), index=True)  # for de-duplication
    group_name: Mapped[str | None] = mapped_column(String(120))
    gstin: Mapped[str | None] = mapped_column(String(15), index=True)
    pan: Mapped[str | None] = mapped_column(String(10))
    billing_address: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default="active")  # prospect|active|on_hold|inactive
    billing_cycle: Mapped[str] = mapped_column(String(20), default="per_lr")  # per_lr|per_trip|weekly|monthly
    gst_mode: Mapped[str] = mapped_column(String(10), default="RCM")  # RCM|FCM (GTA) - verify with CA
    source: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)


class CustomerBranch(Base, IdMixin, TimestampMixin):
    __tablename__ = "customer_branches"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(80))
    pincode: Mapped[str | None] = mapped_column(String(6))
    gstin: Mapped[str | None] = mapped_column(String(15))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()


class Contact(Base, IdMixin, TimestampMixin):
    __tablename__ = "contacts"
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_owners.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    name: Mapped[str] = mapped_column(String(120))
    designation: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    whatsapp_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)


class CreditProfile(Base, IdMixin, TimestampMixin):
    """Approved credit terms. Changes go through approval and create a new effective-dated row."""

    __tablename__ = "credit_profiles"
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    credit_days: Mapped[int] = mapped_column(Integer, default=0)
    advance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)  # required advance for bookings
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    risk_category: Mapped[str] = mapped_column(String(10), default="medium")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|superseded|rejected
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)


class VehicleOwner(Base, IdMixin, TimestampMixin):
    __tablename__ = "vehicle_owners"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    pan: Mapped[str | None] = mapped_column(String(10))
    gstin: Mapped[str | None] = mapped_column(String(15))
    address: Mapped[str | None] = mapped_column(Text)
    kyc_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|verified|rejected
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|suspended|blacklisted (only after review)
    routes: Mapped[list | None] = mapped_column(JSON)  # route-wise availability notes
    tds_section: Mapped[str | None] = mapped_column(String(20), default="194C")
    tds_declaration_received: Mapped[bool] = mapped_column(Boolean, default=False)  # 194C(6) declaration - verify with CA
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))


class Vendor(Base, IdMixin, TimestampMixin):
    __tablename__ = "vendors"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    categories: Mapped[list] = mapped_column(JSON, default=list)  # hamali, crane, repair, tyres, diesel ...
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    gstin: Mapped[str | None] = mapped_column(String(15))
    pan: Mapped[str | None] = mapped_column(String(10))
    address: Mapped[str | None] = mapped_column(Text)
    service_areas: Mapped[list] = mapped_column(JSON, default=list)
    rate_card: Mapped[dict | None] = mapped_column(JSON)
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|suspended
    score: Mapped[dict | None] = mapped_column(JSON)


class PartyBankAccount(Base, IdMixin, TimestampMixin):
    """Bank details of owners/vendors/drivers/employees. A change creates a new pending row that
    must be approved (maker-checker) before payments can use it. Old rows are kept."""

    __tablename__ = "party_bank_accounts"
    party_type: Mapped[str] = mapped_column(String(20))  # owner|vendor|driver|employee|customer
    party_id: Mapped[uuid.UUID] = mapped_column(index=True)
    account_name: Mapped[str] = mapped_column(String(160))
    account_number: Mapped[str] = mapped_column(String(30))
    ifsc: Mapped[str] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|superseded|rejected
    verified_method: Mapped[str | None] = mapped_column(String(40))  # penny_drop_mock|cancelled_cheque|...


class Location(Base, IdMixin):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("city", "district", "state"),)
    city: Mapped[str] = mapped_column(String(80), index=True)
    district: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(60))
    state_code: Mapped[str | None] = mapped_column(String(2))
    pincode: Mapped[str | None] = mapped_column(String(6))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    industrial_area: Mapped[str | None] = mapped_column(String(120))
    # Verified service coverage only. Database presence does NOT imply coverage.
    service_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    service_notes: Mapped[str | None] = mapped_column(Text)


class RouteDistance(Base, IdMixin):
    """Known lane distances (manual or from maps adapter, source recorded)."""

    __tablename__ = "route_distances"
    __table_args__ = (UniqueConstraint("origin_id", "destination_id"),)
    origin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    destination_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    km: Mapped[Decimal] = mapped_column(Numeric(8, 1))
    toll_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(30), default="manual")
    restrictions: Mapped[str | None] = mapped_column(Text)


class GoodsCategory(Base, IdMixin):
    __tablename__ = "goods_categories"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    hazard_class: Mapped[str | None] = mapped_column(String(30))  # None = non-hazardous
    # Compatibility group tags used by the PTL consolidation engine (e.g. food, chemical, odorous, fragile)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    incompatible_tags: Mapped[list] = mapped_column(JSON, default=list)
    ptl_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_special_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    handling_notes: Mapped[str | None] = mapped_column(Text)


class ChargeType(Base, IdMixin):
    __tablename__ = "charge_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # freight|accessorial|pass_through|tax
    gst_applicable: Mapped[bool] = mapped_column(Boolean, default=True)
    ledger_code: Mapped[str | None] = mapped_column(String(20))


class ReasonCode(Base, IdMixin):
    __tablename__ = "reason_codes"
    __table_args__ = (UniqueConstraint("category", "code"),)
    category: Mapped[str] = mapped_column(String(30))  # cancellation|delay|claim|exception|override
    code: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(160))
    label_ta: Mapped[str | None] = mapped_column(String(200))


class VehicleType(Base, IdMixin):
    __tablename__ = "vehicle_types"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    body_type: Mapped[str] = mapped_column(String(30))  # open|closed|container|flatbed|trailer
    nominal_tons: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class Facility(Base, IdMixin, TimestampMixin):
    """Office, godown or partner facility. Only `verified` facilities may be offered/used for custody."""

    __tablename__ = "facilities"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(30))  # office|godown|partner_warehouse|cross_dock
    address: Mapped[str | None] = mapped_column(Text)
    area_sqft: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    width_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    ceiling_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    max_vehicle_type: Mapped[str | None] = mapped_column(String(60))  # e.g. "small vehicles only - lorries not assumed"
    operating_hours: Mapped[str | None] = mapped_column(String(80))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_notes: Mapped[str | None] = mapped_column(Text)
    safety_checklist: Mapped[dict | None] = mapped_column(JSON)
    partner_vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))


class CompanyBankAccount(Base, IdMixin, TimestampMixin):
    __tablename__ = "company_bank_accounts"
    name: Mapped[str] = mapped_column(String(120))
    bank_name: Mapped[str] = mapped_column(String(100))
    account_number_masked: Mapped[str] = mapped_column(String(30))
    ifsc: Mapped[str | None] = mapped_column(String(11))
    ledger_code: Mapped[str] = mapped_column(String(20))
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    opening_date: Mapped[date | None] = mapped_column(Date)
