"""Platform models: identity, sessions, OTP, audit, configuration, numbering, approvals, documents,
notifications, integrations, offline sync."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text, text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Role(Base, IdMixin, TimestampMixin):
    __tablename__ = "roles"
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(160), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(5), default="en")
    # Scope links for external / driver users. Exactly the records these users may see.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicle_owners.id"))
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vendors.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    # CA/auditor access is limited by purpose and period
    access_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_purpose: Mapped[str | None] = mapped_column(String(200))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_secret_sealed: Mapped[str | None] = mapped_column(Text)  # TOTP secret, AES-GCM sealed
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    roles: Mapped[list[Role]] = relationship(secondary="user_roles", lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class Session(Base, IdMixin):
    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(64))
    # Trip-scoped temporary driver access: session is only valid for this trip
    scope_trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id"))


class LoginAttempt(Base, IdMixin):
    __tablename__ = "login_attempts"
    identifier: Mapped[str] = mapped_column(String(160), index=True)
    success: Mapped[bool] = mapped_column(Boolean)
    ip: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OtpChallenge(Base, IdMixin):
    """OTP is stored only as an HMAC; the plain OTP is sent via the SMS/WhatsApp adapter."""

    __tablename__ = "otp_challenges"
    purpose: Mapped[str] = mapped_column(String(40))  # login | pod | temp_driver
    target: Mapped[str] = mapped_column(String(160))  # phone / email / consignment id
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    otp_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TempDriverAccess(Base, IdMixin, TimestampMixin):
    """Trip-scoped, OTP-verified access for attached/market drivers. Revoked on trip completion/cancellation."""

    __tablename__ = "temp_driver_access"
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id"), index=True)
    driver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drivers.id"))
    phone: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(200))
    gps_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """Hash-chained audit log: each row's hash covers its content and the previous row's hash,
    so any edit/deletion of history is detectable by verify_chain(). (Tamper-evident, not tamper-proof.)"""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_name: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class ConfigValue(Base, IdMixin):
    """Versioned business configuration with effective dates. Never updated in place: a change inserts a new version."""

    __tablename__ = "config_values"
    __table_args__ = (UniqueConstraint("key", "version"),)
    key: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    changed_by: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NumberSequence(Base):
    __tablename__ = "number_sequences"
    series: Mapped[str] = mapped_column(String(30), primary_key=True)
    fy: Mapped[str] = mapped_column(String(9), primary_key=True)  # e.g. 2026-27, or "-" when not FY-bound
    last: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalRequest(Base, IdMixin, TimestampMixin):
    """Generic maker-checker approval. The executing service re-checks status before acting."""

    __tablename__ = "approval_requests"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)  # e.g. quote_discount, payment, credit_limit
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(250))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    payload: Mapped[dict | None] = mapped_column(JSON)
    required_permission: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending|approved|rejected|cancelled
    maker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    maker_reason: Mapped[str | None] = mapped_column(Text)
    checker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    checker_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str] = mapped_column(String(20), default="human")  # human | ai


class Document(Base, IdMixin, TimestampMixin):
    """Metadata for an object in encrypted object storage. Binary content lives in the object store."""

    __tablename__ = "documents"
    doc_type: Mapped[str] = mapped_column(String(50), index=True)
    entity: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    doc_number: Mapped[str | None] = mapped_column(String(80))
    review_status: Mapped[str] = mapped_column(String(20), default="unverified")  # unverified|verified|rejected
    extracted: Mapped[dict | None] = mapped_column(JSON)  # OCR output - labelled 'extracted, not verified'
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_lat: Mapped[float | None] = mapped_column()
    captured_lng: Mapped[float | None] = mapped_column()
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    visible_to_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    visible_to_driver: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoredObject(Base):
    """Fallback object store inside PostgreSQL for development only (when no S3 is configured)."""

    __tablename__ = "stored_objects"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Notification(Base, IdMixin, TimestampMixin):
    """Outbox for every outgoing message. A worker delivers via the channel adapter and records the result."""

    __tablename__ = "notifications"
    channel: Mapped[str] = mapped_column(String(20))  # in_app|sms|whatsapp|email
    template: Mapped[str] = mapped_column(String(60))
    recipient: Mapped[str] = mapped_column(String(160))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|sent|failed|held|blocked
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommConsent(Base, IdMixin, TimestampMixin):
    __tablename__ = "comm_consents"
    __table_args__ = (UniqueConstraint("recipient", "channel"),)
    recipient: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(20))
    opted_in: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(String(100))


class IntegrationProvider(Base, IdMixin, TimestampMixin):
    """Registry of every external integration and its honest status (MOCK / SANDBOX / LIVE / DISABLED)."""

    __tablename__ = "integration_providers"
    kind: Mapped[str] = mapped_column(String(40), unique=True)  # bank, gst, eway, sms, whatsapp, ...
    adapter: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20), default="MOCK")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    verified_live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class SyncEvent(Base):
    """Offline events from Driver/Management apps. client_event_id makes submission idempotent."""

    __tablename__ = "sync_events"
    client_event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # original event time on device
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String(30), default="app_offline")  # app_offline|paper_form|app_online
    status: Mapped[str] = mapped_column(String(20))  # applied|rejected|needs_review
    result: Mapped[dict | None] = mapped_column(JSON)


class Task(Base, IdMixin, TimestampMixin):
    """Exception / task register used by the Control Tower and SOP checklists."""

    __tablename__ = "tasks"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # exception|checklist|followup|alert
    severity: Mapped[str] = mapped_column(String(10), default="medium")  # critical|high|medium|low
    title: Mapped[str] = mapped_column(String(250))
    detail: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(80))
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    owner_role: Mapped[str | None] = mapped_column(String(40))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open|in_progress|closed
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closure_reason: Mapped[str | None] = mapped_column(Text)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)


Index("ix_tasks_open_entity", Task.entity, Task.entity_id, Task.status)
