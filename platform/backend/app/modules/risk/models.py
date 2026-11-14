"""Complaints, incidents, insurance policies, claims and legal cases."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class Complaint(Base, IdMixin, TimestampMixin):
    __tablename__ = "complaints"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    category: Mapped[str] = mapped_column(String(20))  # delay|damage|shortage|billing|driver_behaviour|service_quality|other
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    channel: Mapped[str] = mapped_column(String(15), default="portal")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    response_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolve_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|investigating|awaiting_customer|resolved|closed
    root_cause: Mapped[str | None] = mapped_column(Text)
    corrective_action: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"))
    communications: Mapped[list] = mapped_column(JSON, default=list)
    raised_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Incident(Base, IdMixin, TimestampMixin):
    __tablename__ = "incidents"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    kind: Mapped[str] = mapped_column(String(30))  # accident|injury|death|theft|cargo_damage|shortage|fire|flood|third_party|vendor_damage|fraud|cyber|environmental|legal_notice|breakdown
    severity: Mapped[str] = mapped_column(String(10))  # critical|high|medium|low
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location_text: Mapped[str | None] = mapped_column(String(250))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"))
    description: Mapped[str] = mapped_column(Text)
    people: Mapped[list] = mapped_column(JSON, default=list)
    witnesses: Mapped[list] = mapped_column(JSON, default=list)
    emergency_actions: Mapped[str | None] = mapped_column(Text)
    authority_reference: Mapped[str | None] = mapped_column(String(80))  # FIR / police ref
    evidence_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|investigating|claim_filed|closed
    reported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(15), default="office")  # office|driver_app|sos


class InsurancePolicy(Base, IdMixin, TimestampMixin):
    __tablename__ = "insurance_policies"
    kind: Mapped[str] = mapped_column(String(30))  # motor_tp|motor_comprehensive|git_cargo|liability|employee|attached_vehicle|special_cargo
    insurer: Mapped[str] = mapped_column(String(120))
    policy_number: Mapped[str] = mapped_column(String(60))
    insured_parties: Mapped[str | None] = mapped_column(Text)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    coverage: Mapped[str | None] = mapped_column(Text)
    sum_insured: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    premium: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deductible: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    exclusions: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[str | None] = mapped_column(Text)
    limits: Mapped[dict | None] = mapped_column(JSON)  # route/cargo/value limits
    endorsements: Mapped[list] = mapped_column(JSON, default=list)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    claim_contact: Mapped[str | None] = mapped_column(String(200))
    notification_deadline_hours: Mapped[int | None] = mapped_column()
    wording_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # actual policy wording checked by a human
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))


class Claim(Base, IdMixin, TimestampMixin):
    """Financially separates gross loss, insurance receivable, deductible, compensation, recoveries and cash received."""

    __tablename__ = "claims"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("insurance_policies.id"))
    direction: Mapped[str] = mapped_column(String(15))  # insurer|customer_claim|recovery_from_owner|recovery_from_vendor
    insurer_claim_number: Mapped[str | None] = mapped_column(String(60))
    surveyor: Mapped[str | None] = mapped_column(String(160))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gross_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    claimed_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deductible: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    assessed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    customer_compensation: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    recoveries: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    salvage: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    cash_received: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    # draft|notified|documents_submitted|survey|assessed|accepted|rejected|settled|closed
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    financial_treatment_approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approval_requests.id"))
    voucher_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vouchers.id"))


class LegalCase(Base, IdMixin, TimestampMixin):
    __tablename__ = "legal_cases"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # notice|litigation|arbitration|consumer|labour|tax|regulatory|contract
    title: Mapped[str] = mapped_column(String(250))
    parties: Mapped[list] = mapped_column(JSON, default=list)
    forum: Mapped[str | None] = mapped_column(String(160))
    advocate: Mapped[str | None] = mapped_column(String(160))
    served_on: Mapped[date | None] = mapped_column(Date)
    response_due: Mapped[date | None] = mapped_column(Date)
    next_hearing: Mapped[date | None] = mapped_column(Date)
    exposure: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    next_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"))
    evidence_document_ids: Mapped[list] = mapped_column(JSON, default=list)
