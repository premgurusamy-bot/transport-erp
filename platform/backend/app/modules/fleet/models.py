"""Vehicles, compliance, inspections, safety defects, fuel, maintenance, tyres, GPS/camera devices; drivers and remuneration."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Vehicle(Base, IdMixin, TimestampMixin):
    """Own or attached vehicle. Capacity checks use legal payload and actual body dimensions, not nominal tons."""

    __tablename__ = "vehicles"
    registration: Mapped[str] = mapped_column(String(15), unique=True)
    ownership: Mapped[str] = mapped_column(String(10))  # own|attached
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_owners.id"), index=True)
    vehicle_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_types.id"))
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    body_type: Mapped[str] = mapped_column(String(30), default="open")
    vehicle_class: Mapped[str | None] = mapped_column(String(30))  # e.g. HGV/MGV for licence matching
    gvw_kg: Mapped[int | None] = mapped_column(Integer)
    unladen_kg: Mapped[int | None] = mapped_column(Integer)
    payload_kg: Mapped[int] = mapped_column(Integer)  # legal payload (registered) - the hard limit
    axle_count: Mapped[int | None] = mapped_column(Integer)
    axle_limits_kg: Mapped[list | None] = mapped_column(JSON)  # per-axle legal limits if known
    length_ft: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    width_ft: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    height_ft: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # usable cargo height (None for open body unless set)
    fuel_type: Mapped[str] = mapped_column(String(15), default="diesel")
    tank_litres: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    baseline_kmpl: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    odometer_km: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(15), default="available")  # available|reserved|loading|transit|unloading|maintenance|unavailable
    home_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    current_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finance: Mapped[dict | None] = mapped_column(JSON)  # lender, emi, due day, tenure
    can_enter_godown: Mapped[bool] = mapped_column(Boolean, default=False)
    gps_device_id: Mapped[str | None] = mapped_column(String(60))
    dvr_device_id: Mapped[str | None] = mapped_column(String(60))
    camera_permission: Mapped[bool] = mapped_column(Boolean, default=False)  # attached: owner permission
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ComplianceItem(Base, IdMixin, TimestampMixin):
    """Insurance, road tax, permit, FC, PUC, licence etc. with validity for vehicle or driver."""

    __tablename__ = "compliance_items"
    subject_type: Mapped[str] = mapped_column(String(10))  # vehicle|driver|owner|vendor
    subject_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(30))  # insurance|road_tax|national_permit|state_permit|fitness|puc|rc|licence|hazmat_licence|medical
    number: Mapped[str | None] = mapped_column(String(60))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, index=True)
    mandatory_for_dispatch: Mapped[bool] = mapped_column(Boolean, default=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    verification: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified|verified|rejected
    status: Mapped[str] = mapped_column(String(20), default="current")  # current|superseded
    meta: Mapped[dict | None] = mapped_column(JSON)  # e.g. licence class, permit states


class ComplianceRenewal(Base, IdMixin, TimestampMixin):
    """Renewal workflow: reminder → quote → Owner/Director approval → payment evidence → updated compliance."""

    __tablename__ = "compliance_renewals"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    compliance_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("compliance_items.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    quote_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    quote_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String(25), default="initiated")  # initiated|quoted|pending_approval|approved|paid|completed|rejected
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_requests.id"))
    payment_reference: Mapped[str | None] = mapped_column(String(80))
    payment_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))
    new_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("compliance_items.id"))


class Inspection(Base, IdMixin, TimestampMixin):
    __tablename__ = "inspections"
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    kind: Mapped[str] = mapped_column(String(20), default="pre_trip")  # pre_trip|post_trip|periodic
    checklist: Mapped[dict] = mapped_column(JSON)  # {item: "ok"|"defect"|"na"}
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    fuel_level_pct: Mapped[int | None] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SafetyDefect(Base, IdMixin, TimestampMixin):
    """A critical open defect blocks dispatch until inspected and released by an authorised person."""

    __tablename__ = "safety_defects"
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), index=True)
    item: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(10))  # critical|major|minor
    description: Mapped[str | None] = mapped_column(Text)
    reported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inspections.id"))
    status: Mapped[str] = mapped_column(String(15), default="open")  # open|released
    released_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    release_note: Mapped[str | None] = mapped_column(Text)
    job_card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job_cards.id"))


class JobCard(Base, IdMixin, TimestampMixin):
    __tablename__ = "job_cards"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # preventive|breakdown|repair|accident
    description: Mapped[str] = mapped_column(Text)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    estimate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    parts_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    labour_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|pending_approval|approved|in_progress|completed|cancelled
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warranty_until: Mapped[date | None] = mapped_column(Date)
    next_due_km: Mapped[int | None] = mapped_column(Integer)
    next_due_date: Mapped[date | None] = mapped_column(Date)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))


class FuelEntry(Base, IdMixin, TimestampMixin):
    __tablename__ = "fuel_entries"
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    odometer_km: Mapped[int] = mapped_column(Integer)
    litres: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    station: Mapped[str | None] = mapped_column(String(120))
    bill_number: Mapped[str | None] = mapped_column(String(60))
    payment_mode: Mapped[str] = mapped_column(String(20), default="cash")  # cash|card|fleet_card|credit|upi
    full_tank: Mapped[bool] = mapped_column(Boolean, default=True)
    is_adblue: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    computed_kmpl: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    anomaly_flags: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|needs_review|reviewed
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id"))


class Tyre(Base, IdMixin, TimestampMixin):
    __tablename__ = "tyres"
    serial: Mapped[str] = mapped_column(String(40), unique=True)
    brand: Mapped[str | None] = mapped_column(String(60))
    size: Mapped[str | None] = mapped_column(String(30))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    position: Mapped[str | None] = mapped_column(String(20))  # FL, FR, RLO, RLI, ...
    fitted_odometer: Mapped[int | None] = mapped_column(Integer)
    km_run: Mapped[int] = mapped_column(Integer, default=0)
    tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    retread_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="in_stock")  # in_stock|fitted|retread|scrapped
    component: Mapped[str] = mapped_column(String(20), default="tyre")  # tyre|battery


class TyreEvent(Base, IdMixin):
    __tablename__ = "tyre_events"
    tyre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tyres.id"), index=True)
    event: Mapped[str] = mapped_column(String(20))  # fit|remove|rotate|retread|repair|inspect|scrap
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    position: Mapped[str | None] = mapped_column(String(20))
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class Driver(Base, IdMixin, TimestampMixin):
    __tablename__ = "drivers"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    category: Mapped[str] = mapped_column(String(15))  # company|attached|temporary
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_owners.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    licence_number: Mapped[str | None] = mapped_column(String(30))
    licence_classes: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["HGV", "MGV", "TRANS"]
    licence_valid_to: Mapped[date | None] = mapped_column(Date)
    hazmat_endorsement: Mapped[bool] = mapped_column(Boolean, default=False)
    experience_years: Mapped[int | None] = mapped_column(Integer)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    emergency_contact: Mapped[dict | None] = mapped_column(JSON)
    id_number_masked: Mapped[str | None] = mapped_column(String(30))  # never store full Aadhaar
    status: Mapped[str] = mapped_column(String(15), default="available")  # available|on_trip|off_duty|leave|inactive
    duty_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_rest_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    driving_minutes_today: Mapped[int] = mapped_column(Integer, default=0)
    training: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RemunerationRule(Base, IdMixin, TimestampMixin):
    """One component of a driver's pay. Versioned: changes create a new rule effective prospectively.
    Only `active` (approved) rules are used in calculations."""

    __tablename__ = "remuneration_rules"
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"), index=True)
    component: Mapped[str] = mapped_column(String(30))  # fixed_monthly|per_trip|per_km|duty_day|night|waiting_hour|incentive_on_time
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    conditions: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"min_km": 100}
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending|active|superseded|rejected
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str | None] = mapped_column(Text)


class DriverEarning(Base, IdMixin, TimestampMixin):
    """Calculated earning per trip (or period). Calculation breakdown is stored for transparency."""

    __tablename__ = "driver_earnings"
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    period: Mapped[str | None] = mapped_column(String(20))
    breakdown: Mapped[list] = mapped_column(JSON)
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    advances_adjusted: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    adjustments: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    net: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(20), default="calculated")  # calculated|pending_approval|approved|paid|disputed
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("settlements.id"))


class DriverAdvance(Base, IdMixin, TimestampMixin):
    __tablename__ = "driver_advances"
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purpose: Mapped[str] = mapped_column(String(120))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")  # pending_approval|paid|adjusted|rejected
    adjusted_in_earning_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("driver_earnings.id"))


class Grievance(Base, IdMixin, TimestampMixin):
    """Disputes on attendance, fuel, expenses, damage or remuneration - always human review."""

    __tablename__ = "grievances"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    raised_by_user: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    topic: Mapped[str] = mapped_column(String(20))  # attendance|fuel|expense|damage|remuneration|safety|other
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|under_review|resolved
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
