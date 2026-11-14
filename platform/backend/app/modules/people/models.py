"""HR, attendance, leave, payroll, SOP library and checklists; AI usage; marketing."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Employee(Base, IdMixin, TimestampMixin):
    __tablename__ = "employees"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(30))  # office|operations|accounts|drivers|store|sales|management
    designation: Mapped[str | None] = mapped_column(String(80))
    employment_type: Mapped[str] = mapped_column(String(15), default="permanent")  # permanent|temporary|contract
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    joined_on: Mapped[date | None] = mapped_column(Date)
    exited_on: Mapped[date | None] = mapped_column(Date)
    emergency_contact: Mapped[dict | None] = mapped_column(JSON)
    monthly_salary: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)  # restricted (hr.view_salary)
    salary_components: Mapped[dict | None] = mapped_column(JSON)
    statutory: Mapped[dict | None] = mapped_column(JSON)  # {pf: bool, esi: bool, pt: bool}
    is_driver: Mapped[bool] = mapped_column(Boolean, default=False)  # drivers' trip pay handled separately
    backup_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    status: Mapped[str] = mapped_column(String(15), default="active")


class Attendance(Base, IdMixin, TimestampMixin):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("employee_id", "day"),)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15))  # present|absent|half_day|leave|field_duty|holiday
    in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overtime_hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    source: Mapped[str] = mapped_column(String(15), default="manual")
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    correction_reason: Mapped[str | None] = mapped_column(Text)


class LeaveRequest(Base, IdMixin, TimestampMixin):
    __tablename__ = "leave_requests"
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"))
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(15), default="casual")
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="requested")  # requested|approved|rejected
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class PayrollRun(Base, IdMixin, TimestampMixin):
    __tablename__ = "payroll_runs"
    period: Mapped[str] = mapped_column(String(7), unique=True)  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|paid
    totals: Mapped[dict] = mapped_column(JSON, default=dict)
    rules_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    prepared_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Payslip(Base, IdMixin, TimestampMixin):
    __tablename__ = "payslips"
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_runs.id"), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    days_payable: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    earnings: Mapped[dict] = mapped_column(JSON)
    deductions: Mapped[dict] = mapped_column(JSON)
    gross: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    net: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class Sop(Base, IdMixin, TimestampMixin):
    __tablename__ = "sops"
    __table_args__ = (UniqueConstraint("code", "version"),)
    code: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    owner_role: Mapped[str | None] = mapped_column(String(40))
    approver_role: Mapped[str | None] = mapped_column(String(40))
    steps: Mapped[list] = mapped_column(JSON, default=list)
    required_documents: Mapped[list] = mapped_column(JSON, default=list)
    escalation: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(15), default="draft")  # draft|approved|superseded
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    change_note: Mapped[str | None] = mapped_column(Text)


class SopAck(Base, IdMixin):
    __tablename__ = "sop_acks"
    __table_args__ = (UniqueConstraint("sop_id", "user_id"),)
    sop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sops.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChecklistTemplate(Base, IdMixin, TimestampMixin):
    __tablename__ = "checklist_templates"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    frequency: Mapped[str] = mapped_column(String(10))  # daily|weekly|monthly
    department: Mapped[str] = mapped_column(String(30))
    owner_role: Mapped[str] = mapped_column(String(40))
    backup_role: Mapped[str | None] = mapped_column(String(40))
    items: Mapped[list] = mapped_column(JSON)
    due_hour: Mapped[int] = mapped_column(Integer, default=18)


class ChecklistRun(Base, IdMixin, TimestampMixin):
    __tablename__ = "checklist_runs"
    __table_args__ = (UniqueConstraint("template_id", "period_key"),)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checklist_templates.id"))
    period_key: Mapped[str] = mapped_column(String(12))
    results: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(15), default="open")


class AiUsage(Base, IdMixin):
    __tablename__ = "ai_usage"
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    assistant: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    app: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_inr: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    status: Mapped[str] = mapped_column(String(15))  # ok|error|blocked_budget|fallback
    prompt_version: Mapped[str | None] = mapped_column(String(30))
    tools_used: Mapped[list] = mapped_column(JSON, default=list)


class AiRecommendation(Base, IdMixin, TimestampMixin):
    """Something an assistant proposes. Execution needs an authorised human (and never the AI itself)."""

    __tablename__ = "ai_recommendations"
    assistant: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(250))
    reasoning: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    data_freshness: Mapped[str | None] = mapped_column(String(120))
    entity: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    proposed_action: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(15), default="open")  # open|accepted|dismissed
    for_user: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Campaign(Base, IdMixin, TimestampMixin):
    __tablename__ = "campaigns"
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    channels: Mapped[list] = mapped_column(JSON, default=list)
    audience: Mapped[str | None] = mapped_column(Text)
    budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    spent: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|running|ended
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    leads: Mapped[int] = mapped_column(Integer, default=0)


class ContentItem(Base, IdMixin, TimestampMixin):
    __tablename__ = "content_items"
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id"))
    channel: Mapped[str] = mapped_column(String(20))  # facebook|instagram|youtube|whatsapp|gbp|linkedin|website
    kind: Mapped[str] = mapped_column(String(20), default="routine")  # routine|major|ad|brand
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(5), default="en")
    media_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    media_consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    drafted_by_agent: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|pending_approval|approved|scheduled|published|rejected
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_mode: Mapped[str | None] = mapped_column(String(15))  # MOCK|LIVE
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Opportunity(Base, IdMixin, TimestampMixin):
    """Business opportunity database. Presence here does NOT imply G ROAD LINES serves that location."""

    __tablename__ = "opportunities"
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(60))
    lat: Mapped[float | None] = mapped_column()
    lng: Mapped[float | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(120))  # lawful public/authorised source
    source_date: Mapped[date | None] = mapped_column(Date)
    confidence: Mapped[str] = mapped_column(String(10), default="low")
    data_kind: Mapped[str] = mapped_column(String(10), default="estimated")  # actual|estimated
    stage: Mapped[str] = mapped_column(String(20), default="identified")  # identified|contacted|qualified|proposal|won|lost
    estimated_monthly_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    next_follow_up: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[int] = mapped_column(Integer, default=3)
