"""Company, branches, settings, numbering, users, roles, sessions, audit, notifications."""
from __future__ import annotations

from sqlalchemy import UniqueConstraint

from .base import JSON, ActiveMixin, AuditMixin, Base, Boolean, Column, Date, DateTime, F, Integer, String, Text, utcnow

STATES = None  # state list lives in core.validators.STATE_CODES


class Company(AuditMixin, Base):
    __tablename__ = "company"
    legal_name = F(String(200), "Company legal name", required=True)
    trade_name = F(String(200), "Trade name")
    gstin = F(String(15), "GSTIN", validator="gstin")
    pan = F(String(10), "PAN", validator="pan")
    cin = F(String(21), "CIN (if applicable)")
    address = F(Text, "Registered office address")
    city = F(String(80), "City")
    state = F(String(60), "State")
    state_code = F(String(2), "State code", help="Two-digit GST state code, e.g. 33 for Tamil Nadu")
    pincode = F(String(6), "Pincode", validator="pincode")
    email = F(String(120), "Official email", validator="email")
    phone = F(String(60), "Contact numbers")
    website = F(String(120), "Website")
    logo_path = F(String(300), "Logo", hidden=True)
    authorized_signatory = F(String(120), "Authorized signatory")
    signatory_designation = F(String(80), "Signatory designation")
    gst_registration_type = F(String(40), "GST registration type", options=["Regular", "Composition", "Unregistered"])
    gst_registration_date = F(Date, "GST registration date")
    terms_lr = F(Text, "LR terms and conditions")
    terms_invoice = F(Text, "Invoice terms and conditions")
    fy_start_month = F(Integer, "Financial year start month", default=4)
    lr_print_declaration = F(Text, "LR declaration")


class Branch(AuditMixin, ActiveMixin, Base):
    __tablename__ = "branches"
    code = F(String(20), "Code", required=True, unique=True)
    name = F(String(120), "Name", required=True)
    kind = F(String(20), "Type", required=True, options=["Head Office", "Branch", "Warehouse", "Operational Location"], default="Branch")
    gstin = F(String(15), "GSTIN (if separately registered)", validator="gstin")
    address = F(Text, "Address")
    city = F(String(80), "City")
    state = F(String(60), "State")
    state_code = F(String(2), "State code")
    pincode = F(String(6), "Pincode", validator="pincode")
    phone = F(String(40), "Phone")
    email = F(String(120), "Email", validator="email")
    manager = F(String(120), "In-charge")


class BankAccount(AuditMixin, ActiveMixin, Base):
    __tablename__ = "bank_accounts"
    bank_name = F(String(120), "Bank name", required=True)
    branch_name = F(String(120), "Bank branch")
    account_name = F(String(160), "Account holder name")
    account_no = F(String(30), "Account number", required=True)
    ifsc = F(String(11), "IFSC", validator="ifsc")
    upi_id = F(String(80), "UPI ID")
    print_on_invoice = F(Boolean, "Print on invoice", default=True)
    ledger_id = F(Integer, "Ledger", fk="ledgers.id", ref="ledgers", readonly=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(80), primary_key=True)
    value = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    updated_by = Column(Integer, nullable=True)


class NumberSeries(AuditMixin, Base):
    """Gap-safe, duplicate-proof document numbering (row is locked FOR UPDATE)."""

    __tablename__ = "number_series"
    __table_args__ = (UniqueConstraint("doc_type", "fy", "branch_code", name="uq_series_doc_fy_branch"),)
    doc_type = F(String(30), "Document", required=True)
    fy = F(String(9), "Financial year", required=True)
    branch_code = F(String(20), "Branch", default="", required=False)
    prefix = F(String(40), "Prefix", default="")
    next_no = F(Integer, "Next number", default=1)
    padding = F(Integer, "Digits", default=5)
    pattern = F(String(80), "Pattern", default="{prefix}{fy}/{no}", help="Tokens: {prefix} {fy} {branch} {no}")


class Role(AuditMixin, Base):
    __tablename__ = "roles"
    name = F(String(60), "Role", required=True, unique=True)
    description = F(String(200), "Description")
    permissions = Column(JSON, default=list, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)


class User(AuditMixin, ActiveMixin, Base):
    __tablename__ = "users"
    username = F(String(60), "Username", required=True, unique=True)
    full_name = F(String(120), "Full name", required=True)
    email = F(String(120), "Email", validator="email")
    mobile = F(String(15), "Mobile", validator="mobile")
    password_hash = Column(String(200), nullable=False)
    role_id = F(Integer, "Role", fk="roles.id", ref="roles", required=True)
    branch_id = F(Integer, "Branch", fk="branches.id", ref="branches")
    customer_id = F(Integer, "Customer (portal users)", fk="customers.id", ref="customers")
    driver_id = F(Integer, "Driver (driver app users)", fk="drivers.id", ref="drivers")
    language = F(String(5), "Language", options=["en", "ta"], default="en")
    totp_secret = Column(String(64), nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    failed_logins = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    ip = Column(String(64))
    user_agent = Column(String(300))
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class LoginHistory(Base):
    __tablename__ = "login_history"
    id = Column(Integer, primary_key=True)
    username = Column(String(60), nullable=False)
    user_id = Column(Integer, nullable=True)
    at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    ip = Column(String(64))
    user_agent = Column(String(300))
    success = Column(Boolean, nullable=False)
    reason = Column(String(120))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(60))
    action = Column(String(40), nullable=False)
    entity = Column(String(60), nullable=False, index=True)
    entity_id = Column(String(40), index=True)
    before = Column(JSON)
    after = Column(JSON)
    reason = Column(Text)
    ip = Column(String(64))


class NotificationTemplate(AuditMixin, ActiveMixin, Base):
    __tablename__ = "notification_templates"
    __table_args__ = (UniqueConstraint("event", "channel", name="uq_tmpl_event_channel"),)
    event = F(String(40), "Event", required=True)
    channel = F(String(20), "Channel", required=True, options=["in_app", "email", "whatsapp", "sms"])
    subject = F(String(200), "Subject")
    body = F(Text, "Body", required=True, help="Placeholders in {braces}, e.g. {lr_no}, {customer}")
    recipients = F(String(40), "Send to", options=["customer", "driver", "staff", "all"], default="staff")


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    event = Column(String(40), nullable=False)
    channel = Column(String(20), nullable=False)
    recipient = Column(String(160))
    subject = Column(String(200))
    body = Column(Text)
    status = Column(String(20), nullable=False)  # sent / failed / not_configured / skipped
    error = Column(Text)
    entity = Column(String(60))
    entity_id = Column(String(40))


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True, index=True)  # null = all staff
    role_scope = Column(String(60), nullable=True)
    at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text)
    link = Column(String(200))
    severity = Column(String(10), default="info")
    read_by = Column(JSON, default=list, nullable=False)
    dedupe_key = Column(String(160), nullable=True, unique=True)


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    kind = Column(String(20), nullable=False)  # manual / scheduled / pre_restore
    file_name = Column(String(260), nullable=False)
    size_bytes = Column(Integer)
    sha256 = Column(String(64))
    status = Column(String(20), nullable=False)
    tables = Column(Integer)
    rows = Column(Integer)
    pg_dump_file = Column(String(260))
    note = Column(Text)
    created_by = Column(Integer)
