"""Trips, loads, owner offers, events, GPS, custody, scans, POD, LR and e-way bills."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Trip(Base, IdMixin, TimestampMixin):
    __tablename__ = "trips"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    trip_mode: Mapped[str] = mapped_column(String(3))  # FTL|PTL
    fleet_type: Mapped[str] = mapped_column(String(10))  # own|attached
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"), index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_owners.id"), index=True)
    exclusive_booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"), unique=True)  # FTL only
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    # planned|ready|dispatched|in_transit|delivered|closed|cancelled
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eta_source: Mapped[str | None] = mapped_column(String(30))  # planned|gps_estimate|manual
    planned_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    start_odometer: Mapped[int | None] = mapped_column(Integer)
    end_odometer: Mapped[int | None] = mapped_column(Integer)
    loaded_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    empty_km: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    owner_hire_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # attached: agreed hire
    owner_advance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    load_plan: Mapped[dict | None] = mapped_column(JSON)
    allocation_checks: Mapped[list | None] = mapped_column(JSON)  # result of last allocation check
    override: Mapped[dict | None] = mapped_column(JSON)  # {by, reason, checks}
    dispatch_authorized_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    dispatch_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    driver_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gps_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_lat: Mapped[float | None] = mapped_column()
    last_lng: Mapped[float | None] = mapped_column()
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ping_source: Mapped[str | None] = mapped_column(String(20))
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class TripLoad(Base, IdMixin, TimestampMixin):
    """A booking (consignment) carried on a trip. PTL trips have several; FTL exactly one."""

    __tablename__ = "trip_loads"
    __table_args__ = (UniqueConstraint("trip_id", "booking_id"),)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"), index=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    pickup_seq: Mapped[int] = mapped_column(Integer, default=1)
    drop_seq: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|loaded|delivered|partial|failed|returned|removed
    loaded_count: Mapped[int] = mapped_column(Integer, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, default=0)
    allocated_cost_est: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    allocated_cost_actual: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    allocation_basis: Mapped[dict | None] = mapped_column(JSON)


class OwnerOffer(Base, IdMixin, TimestampMixin):
    """Attached vehicle: request to an owner → owner quote → negotiation → owner acceptance with actual vehicle/driver."""

    __tablename__ = "owner_offers"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicle_owners.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    lane: Mapped[str] = mapped_column(String(200))
    vehicle_requirement: Mapped[str | None] = mapped_column(String(160))
    required_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_quote: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    negotiated_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    advance_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    status: Mapped[str] = mapped_column(String(20), default="requested")
    # requested|quoted|negotiated|accepted|declined|expired|cancelled
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms: Mapped[str | None] = mapped_column(Text)


class TripEvent(Base, IdMixin):
    __tablename__ = "trip_events"
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"), index=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    event: Mapped[str] = mapped_column(String(30))
    # dispatched|arrived_pickup|loading_started|loaded|departed|checkpoint|delay|breakdown|accident|sos|arrived_drop|unloading|delivered|waiting|note
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # device time
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(20), default="app")  # app|office|gps|paper_form
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSON)
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    customer_visible: Mapped[bool] = mapped_column(Boolean, default=False)


class GpsPing(Base):
    __tablename__ = "gps_pings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id"))
    source: Mapped[str] = mapped_column(String(20))  # phone|tracker|manual
    lat: Mapped[float] = mapped_column()
    lng: Mapped[float] = mapped_column()
    speed_kmph: Mapped[float | None] = mapped_column()
    accuracy_m: Mapped[float | None] = mapped_column()
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # device time
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_gps_trip_time", GpsPing.trip_id, GpsPing.recorded_at)
Index("ix_gps_vehicle_time", GpsPing.vehicle_id, GpsPing.recorded_at)


class CustodyEvent(Base, IdMixin):
    """Chain of custody from pickup inspection to POD. Each transfer names who handed over and who received."""

    __tablename__ = "custody_events"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    event: Mapped[str] = mapped_column(String(30))  # pickup_inspection|loaded|seal_applied|seal_checked|handover|godown_in|godown_out|unloaded|delivered|exception
    package_count: Mapped[int | None] = mapped_column(Integer)
    expected_count: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(20))  # good|damaged|wet|open
    seal_number: Mapped[str | None] = mapped_column(String(40))
    from_party: Mapped[str | None] = mapped_column(String(160))
    to_party: Mapped[str | None] = mapped_column(String(160))
    handler_vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    facility_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("facilities.id"))
    photo_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
    exception_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id"))


class PackageScan(Base, IdMixin):
    __tablename__ = "package_scans"
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packages.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    stage: Mapped[str] = mapped_column(String(20))  # picked|godown_in|godown_out|loaded|unloaded|delivered
    result: Mapped[str] = mapped_column(String(20))  # ok|wrong_trip|duplicate|damaged|unknown
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    by_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    client_event_id: Mapped[str | None] = mapped_column(String(80), unique=True)


class ProofOfDelivery(Base, IdMixin, TimestampMixin):
    __tablename__ = "pods"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), unique=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"), index=True)
    delivered_count: Mapped[int] = mapped_column(Integer)
    expected_count: Mapped[int] = mapped_column(Integer)
    receiver_name: Mapped[str] = mapped_column(String(160))
    receiver_phone: Mapped[str | None] = mapped_column(String(20))
    otp_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    signature_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    photo_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    condition: Mapped[str] = mapped_column(String(20), default="good")
    remarks: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted|verified|rejected
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LorryReceipt(Base, IdMixin, TimestampMixin):
    __tablename__ = "lorry_receipts"
    number: Mapped[str] = mapped_column(String(40), unique=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="issued")  # issued|amended|cancelled
    content: Mapped[dict] = mapped_column(JSON)
    verify_token: Mapped[str] = mapped_column(String(40), unique=True)  # used in QR for verification
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    amendments: Mapped[list] = mapped_column(JSON, default=list)


class EwayBill(Base, IdMixin, TimestampMixin):
    __tablename__ = "eway_bills"
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    number: Mapped[str | None] = mapped_column(String(20))
    applicable: Mapped[bool] = mapped_column(Boolean)
    applicability_reason: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vehicle_registration: Mapped[str | None] = mapped_column(String(15))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual|provider_mock|provider_live
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|expired|cancelled|not_required
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
