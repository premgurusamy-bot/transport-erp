"""Complaints, incidents, insurance, claims (separate financial treatment) and privileged legal cases."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.notify import queue
from app.core.resource import register_crud
from app.core.services import next_number, on_approval, raise_exception_task, request_approval
from app.modules.commercial.models import Booking
from app.modules.finance.posting import post_voucher
from app.modules.risk.models import Claim, Complaint, Incident, InsurancePolicy, LegalCase

router = APIRouter(prefix="/api/v1", tags=["risk"])

register_crud(router, "insurance-policies", InsurancePolicy, read_perm="insurance.read", write_perm="insurance.write",
              search_fields=("policy_number", "insurer"))

RESPONSE_HOURS = {"critical": 2, "high": 4, "medium": 24, "low": 48}
RESOLVE_DAYS = {"critical": 2, "high": 5, "medium": 10, "low": 15}


# ===================================================================== complaints
class ComplaintIn(BaseModel):
    customer_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    category: str = Field(pattern="^(delay|damage|shortage|billing|driver_behaviour|service_quality|other)$")
    description: str = Field(min_length=5)
    priority: str = Field("medium", pattern="^(critical|high|medium|low)$")
    channel: str = "office"


def create_complaint(db: Session, actor, body: ComplaintIn, customer_scope=None) -> Complaint:
    data = body.model_dump()
    if customer_scope:
        data["customer_id"], data["channel"] = customer_scope, "portal"
        if body.booking_id:
            b = db.get(Booking, body.booking_id)
            if not b or b.customer_id != customer_scope:
                raise Forbidden()
    if data["category"] in ("damage", "shortage") and data["priority"] in ("low", "medium"):
        data["priority"] = "high"
    now = utcnow()
    c = Complaint(code=next_number(db, "CMP", "CMP"), raised_by=actor.user_id, response_due_at=now + timedelta(hours=RESPONSE_HOURS[data["priority"]]),
                  resolve_due_at=now + timedelta(days=RESOLVE_DAYS[data["priority"]]), **data)
    db.add(c)
    db.flush()
    raise_exception_task(db, kind="followup", severity=data["priority"], title=f"Complaint {c.code}: {c.category}", entity="complaint",
                         entity_id=c.id, source="complaint", owner_role="customer_support", due_at=c.response_due_at)
    write_audit(db, actor=actor, action="complaint.create", entity="complaint", entity_id=c.id, after={"category": c.category})
    return c


@router.post("/complaints")
def post_complaint(body: ComplaintIn, p: Principal = Depends(require("complaint.write")), db: Session = Depends(get_db)):
    return to_dict(create_complaint(db, p, body))


@router.get("/complaints")
def list_complaints(status: str | None = None, p: Principal = Depends(require("complaint.read")), db: Session = Depends(get_db)):
    q = select(Complaint).order_by(Complaint.created_at.desc())
    if status:
        q = q.where(Complaint.status.in_(status.split(",")))
    out = []
    for c in db.execute(q).scalars():
        d = to_dict(c)
        d["overdue"] = c.status not in ("resolved", "closed") and c.resolve_due_at and c.resolve_due_at < utcnow()
        out.append(d)
    return out


class ComplaintUpdate(BaseModel):
    status: str | None = Field(None, pattern="^(open|investigating|awaiting_customer|resolved|closed)$")
    owner_user_id: uuid.UUID | None = None
    root_cause: str | None = None
    corrective_action: str | None = None
    resolution: str | None = None
    customer_message: str | None = None


@router.patch("/complaints/{cid}")
def update_complaint(cid: uuid.UUID, body: ComplaintUpdate, p: Principal = Depends(require("complaint.write")), db: Session = Depends(get_db)):
    c = get_or_404(db, Complaint, cid, "Complaint")
    if body.status in ("resolved", "closed") and not (body.resolution or c.resolution):
        raise AppError("resolution_required", "Record the resolution before closing")
    if body.status == "closed" and c.category in ("damage", "shortage", "delay") and not (body.root_cause or c.root_cause):
        raise AppError("root_cause_required", "Root cause and corrective action are required for service failures")
    for k, v in body.model_dump(exclude_unset=True, exclude={"customer_message"}).items():
        setattr(c, k, v)
    if body.customer_message:
        # Complaint responses are held for human approval before sending (sensitive template)
        from app.modules.masters.models import Contact
        ct = db.execute(select(Contact).where(Contact.customer_id == c.customer_id)).scalars().first()
        if ct and (ct.email or ct.phone):
            n = queue(db, channel="email" if ct.email else "sms", recipient=ct.email or ct.phone, template="complaint_response",
                      body=body.customer_message, entity="complaint", entity_id=c.id)
            c.communications = [*c.communications, {"at": utcnow().isoformat(), "by": str(p.user_id), "status": n.status, "text": body.customer_message}]
    write_audit(db, actor=p, action="complaint.update", entity="complaint", entity_id=c.id, after=body.model_dump(exclude_unset=True))
    return to_dict(c)


# ===================================================================== incidents
class IncidentIn(BaseModel):
    kind: str = Field(pattern="^(accident|injury|death|theft|cargo_damage|shortage|fire|flood|third_party|vendor_damage|fraud|cyber|environmental|legal_notice|breakdown)$")
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    occurred_at: datetime
    location_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    vehicle_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    booking_id: uuid.UUID | None = None
    description: str = Field(min_length=5)
    people: list[dict] = []
    witnesses: list[dict] = []
    emergency_actions: str | None = None
    authority_reference: str | None = None
    evidence_document_ids: list[uuid.UUID] = []


@router.post("/incidents")
def post_incident(body: IncidentIn, p: Principal = Depends(require("incident.write")), db: Session = Depends(get_db)):
    i = Incident(code=next_number(db, "INC", "INC"), reported_by=p.user_id,
                 **{**body.model_dump(), "evidence_document_ids": [str(x) for x in body.evidence_document_ids]})
    db.add(i)
    db.flush()
    if i.evidence_document_ids:
        from app.modules.platform.models import Document
        for did in i.evidence_document_ids:
            d = db.get(Document, uuid.UUID(did))
            if d:
                d.legal_hold = True
    raise_exception_task(db, severity=i.severity, title=f"Incident {i.code}: {i.kind}", entity="incident", entity_id=i.id,
                         source="incident", owner_role="operations_manager", blocking=i.severity == "critical")
    write_audit(db, actor=p, action="incident.create", entity="incident", entity_id=i.id, after={"kind": i.kind, "severity": i.severity})
    return to_dict(i)


@router.get("/incidents")
def list_incidents(p: Principal = Depends(require("incident.read")), db: Session = Depends(get_db)):
    return [to_dict(i) for i in db.execute(select(Incident).order_by(Incident.occurred_at.desc())).scalars()]


@router.get("/incidents/{iid}")
def get_incident(iid: uuid.UUID, p: Principal = Depends(require("incident.read")), db: Session = Depends(get_db)):
    i = get_or_404(db, Incident, iid, "Incident")
    out = to_dict(i)
    out["claims"] = [to_dict(c) for c in db.execute(select(Claim).where(Claim.incident_id == i.id)).scalars()]
    out["applicable_policies"] = _policies_for(db, i)
    return out


def _policies_for(db: Session, i: Incident) -> list[dict]:
    """Lists policies that MAY be relevant. Coverage is never assumed - actual wording must be checked by a person."""
    q = select(InsurancePolicy).where(InsurancePolicy.valid_from <= i.occurred_at.date(), InsurancePolicy.valid_to >= i.occurred_at.date())
    out = []
    for pol in db.execute(q).scalars():
        if pol.vehicle_id and i.vehicle_id and pol.vehicle_id != i.vehicle_id:
            continue
        out.append({"id": str(pol.id), "kind": pol.kind, "insurer": pol.insurer, "policy_number": pol.policy_number,
                    "notification_deadline_hours": pol.notification_deadline_hours, "wording_verified": pol.wording_verified,
                    "note": "Possible relevance only - coverage depends on actual policy wording, exclusions and endorsements."})
    return out


# ===================================================================== claims
class ClaimIn(BaseModel):
    incident_id: uuid.UUID
    policy_id: uuid.UUID | None = None
    direction: str = Field(pattern="^(insurer|customer_claim|recovery_from_owner|recovery_from_vendor)$")
    gross_loss: Decimal = Field(Decimal("0"), ge=0)
    claimed_amount: Decimal = Field(Decimal("0"), ge=0)


@router.post("/claims")
def post_claim(body: ClaimIn, p: Principal = Depends(require("incident.write")), db: Session = Depends(get_db)):
    i = get_or_404(db, Incident, body.incident_id, "Incident")
    c = Claim(code=next_number(db, "CLM", "CLM"), **body.model_dump())
    if body.policy_id:
        pol = get_or_404(db, InsurancePolicy, body.policy_id, "Policy")
        c.deductible = pol.deductible or Decimal("0")
        if pol.notification_deadline_hours:
            c.notify_deadline = i.occurred_at + timedelta(hours=pol.notification_deadline_hours)
            raise_exception_task(db, severity="high", title=f"Notify insurer for {c.code} by {c.notify_deadline:%d-%m %H:%M} UTC",
                                 entity="claim", entity_id=c.id, source="claim", owner_role="compliance_coordinator", due_at=c.notify_deadline)
    c.timeline = [{"at": utcnow().isoformat(), "status": "draft", "by": str(p.user_id)}]
    db.add(c)
    i.status = "claim_filed" if body.direction == "insurer" else i.status
    db.flush()
    return to_dict(c)


class ClaimUpdate(BaseModel):
    status: str = Field(pattern="^(notified|documents_submitted|survey|assessed|accepted|rejected|settled|closed)$")
    insurer_claim_number: str | None = None
    surveyor: str | None = None
    assessed_amount: Decimal | None = None
    salvage: Decimal | None = None
    note: str | None = None


@router.post("/claims/{cid}/progress")
def claim_progress(cid: uuid.UUID, body: ClaimUpdate, p: Principal = Depends(require("incident.write")), db: Session = Depends(get_db)):
    c = get_or_404(db, Claim, cid, "Claim")
    if body.status == "notified":
        c.notified_at = utcnow()
    for k in ("insurer_claim_number", "surveyor", "assessed_amount", "salvage"):
        if getattr(body, k) is not None:
            setattr(c, k, getattr(body, k))
    c.status = body.status
    c.timeline = [*c.timeline, {"at": utcnow().isoformat(), "status": body.status, "by": str(p.user_id), "note": body.note}]
    return to_dict(c)


class ClaimFinanceIn(BaseModel):
    customer_compensation: Decimal = Field(Decimal("0"), ge=0)
    recoveries: Decimal = Field(Decimal("0"), ge=0)
    insurance_receivable: Decimal = Field(Decimal("0"), ge=0)
    reason: str = Field(min_length=5)


@router.post("/claims/{cid}/financial-treatment")
def claim_finance(cid: uuid.UUID, body: ClaimFinanceIn, p: Principal = Depends(require("incident.write")), db: Session = Depends(get_db)):
    """Proposes compensation/receivable entries. Nothing is posted or paid until a claim approver approves."""
    c = get_or_404(db, Claim, cid, "Claim")
    ar = request_approval(db, p, kind="claim_finance", entity="claim", entity_id=c.id, title=f"Claim {c.code} financial treatment",
                          required_permission="claim.approve", amount=body.customer_compensation + body.insurance_receivable,
                          payload=body.model_dump(mode="json"), reason=body.reason)
    c.financial_treatment_approval_id = ar.id
    return {"approval": ar.code}


@on_approval("claim_finance")
def _claim_fin(db, actor, ar):
    if ar.status != "approved":
        return
    c = db.get(Claim, uuid.UUID(ar.entity_id))
    pl = ar.payload
    comp, rec, ins = Decimal(pl["customer_compensation"]), Decimal(pl["recoveries"]), Decimal(pl["insurance_receivable"])
    lines = []
    if comp:
        lines += [{"account": "5600", "debit": comp}, {"account": "2010", "credit": comp, "narration": "Compensation payable (via approved payment)"}]
    if ins:
        lines += [{"account": "1300", "debit": ins}, {"account": "5600", "credit": ins, "narration": "Insurance receivable (not cash)"}]
    if rec:
        party = "owner" if c.direction == "recovery_from_owner" else "vendor"
        lines += [{"account": "1150" if party == "owner" else "1170", "debit": rec}, {"account": "5600", "credit": rec}]
    if lines:
        v = post_voucher(db, actor, vtype="journal", vdate=date.today(), narration=f"Claim {c.code} approved treatment", lines=lines,
                         source_entity="claim", source_id=c.id, approved_by=actor.user_id)
        c.voucher_id = v.id
    c.customer_compensation, c.recoveries = comp, rec


class ClaimCashIn(BaseModel):
    amount: Decimal = Field(gt=0)
    reference: str


@router.post("/claims/{cid}/cash-received")
def claim_cash(cid: uuid.UUID, body: ClaimCashIn, p: Principal = Depends(require("accounts.post")), db: Session = Depends(get_db)):
    c = get_or_404(db, Claim, cid, "Claim")
    post_voucher(db, p, vtype="receipt", vdate=date.today(), narration=f"Insurance settlement {c.code} ({body.reference})",
                 lines=[{"account": "1010", "debit": body.amount}, {"account": "1300", "credit": body.amount}], source_entity="claim", source_id=c.id)
    c.cash_received = money(Decimal(c.cash_received) + body.amount)
    return to_dict(c)


@router.get("/claims")
def list_claims(p: Principal = Depends(require("incident.read")), db: Session = Depends(get_db)):
    return [to_dict(c) for c in db.execute(select(Claim).order_by(Claim.created_at.desc())).scalars()]


# ===================================================================== legal (privileged)
class LegalIn(BaseModel):
    kind: str = Field(pattern="^(notice|litigation|arbitration|consumer|labour|tax|regulatory|contract)$")
    title: str
    parties: list[dict] = []
    forum: str | None = None
    advocate: str | None = None
    served_on: date | None = None
    response_due: date | None = None
    next_hearing: date | None = None
    exposure: Decimal | None = None
    next_action: str | None = None
    incident_id: uuid.UUID | None = None


@router.post("/legal-cases")
def post_legal(body: LegalIn, p: Principal = Depends(require("legal.write")), db: Session = Depends(get_db)):
    lc = LegalCase(code=next_number(db, "LGL", "LGL"), **body.model_dump())
    db.add(lc)
    db.flush()
    if body.response_due:
        raise_exception_task(db, severity="high", title=f"Legal response due {body.response_due}: {body.title}"[:240], entity="legal_case",
                             entity_id=lc.id, source="legal", owner_role="owner_director",
                             due_at=datetime.combine(body.response_due, datetime.min.time()).replace(tzinfo=utcnow().tzinfo))
    write_audit(db, actor=p, action="legal.create", entity="legal_case", entity_id=lc.id)
    return to_dict(lc)


@router.get("/legal-cases")
def list_legal(p: Principal = Depends(require("legal.read")), db: Session = Depends(get_db)):
    rows = [to_dict(x) for x in db.execute(select(LegalCase).order_by(LegalCase.response_due)).scalars()]
    write_audit(db, actor=p, action="legal.read", entity="legal_case", entity_id="list")
    return rows


class LegalUpdate(BaseModel):
    status: str | None = None
    next_hearing: date | None = None
    next_action: str | None = None
    advocate: str | None = None
    exposure: Decimal | None = None


@router.patch("/legal-cases/{lid}")
def update_legal(lid: uuid.UUID, body: LegalUpdate, p: Principal = Depends(require("legal.write")), db: Session = Depends(get_db)):
    lc = get_or_404(db, LegalCase, lid, "Case")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(lc, k, v)
    write_audit(db, actor=p, action="legal.update", entity="legal_case", entity_id=lc.id, after=body.model_dump(exclude_unset=True, mode="json"))
    return to_dict(lc)
