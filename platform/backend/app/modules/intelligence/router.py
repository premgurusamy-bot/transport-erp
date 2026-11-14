"""Operations Control Tower, management dashboards, AI gateway, marketing & sales automation, offline sync, jobs."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.resource import register_crud
from app.core.services import get_config, next_number, on_approval, request_approval
from app.modules.commercial.models import Booking, Enquiry, Quotation
from app.modules.finance.models import BankTransaction, Expense, Invoice, Payment
from app.modules.fleet.models import ComplianceItem, Driver, SafetyDefect, Vehicle
from app.modules.intelligence import ai
from app.modules.operations.models import ProofOfDelivery, Trip
from app.modules.operations.service import position
from app.modules.people.models import AiRecommendation, AiUsage, Campaign, ContentItem, Opportunity
from app.modules.platform.models import ApprovalRequest, SyncEvent, Task
from app.modules.risk.models import Complaint, Incident

router = APIRouter(prefix="/api/v1", tags=["intelligence"])

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ===================================================================== control tower
@router.get("/control-tower")
def control_tower(view: str = "owner", p: Principal = Depends(require("controltower.read")), db: Session = Depends(get_db)):
    now = utcnow()
    today = now.date()
    vehicles = list(db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars())
    trips = list(db.execute(select(Trip).where(Trip.status.in_(("planned", "ready", "dispatched", "in_transit", "delivered")))).scalars())
    live = []
    for t in trips:
        if t.status in ("dispatched", "in_transit"):
            pos = position(db, t.vehicle_id, t.id)
            v = db.get(Vehicle, t.vehicle_id)
            live.append({"trip": t.code, "trip_id": str(t.id), "vehicle": v.registration, "fleet": t.fleet_type, "mode": t.trip_mode,
                         "gps_state": pos["state"], "gps_source": pos["source"], "last_seen": pos["recorded_at"], "lat": pos["lat"],
                         "lng": pos["lng"], "eta": t.eta, "eta_source": t.eta_source, "delay_minutes": t.delay_minutes})
    tasks = sorted(db.execute(select(Task).where(Task.status != "closed")).scalars(), key=lambda t: (SEV_ORDER.get(t.severity, 9), t.created_at))
    if view != "owner":
        role_map = {"operations": ("operations_manager", "dispatcher", "fleet_maintenance", "compliance_coordinator"),
                    "dispatcher": ("dispatcher", "operations_manager"), "accounts": ("accounts",), "support": ("customer_support",)}
        tasks = [t for t in tasks if t.owner_role in role_map.get(view, ()) or t.severity == "critical"]
    exp_compliance = db.execute(select(func.count()).select_from(ComplianceItem).where(
        ComplianceItem.status == "current", ComplianceItem.valid_to < today)).scalar()
    due_compliance = db.execute(select(func.count()).select_from(ComplianceItem).where(
        ComplianceItem.status == "current", ComplianceItem.valid_to.between(today, today + timedelta(days=15)))).scalar()
    drivers = list(db.execute(select(Driver).where(Driver.is_active.is_(True))).scalars())
    return {
        "generated_at": now, "view": view,
        "priority_rule": "Safety/legal/custody first; customer commitments next; financial/efficiency after.",
        "availability": {
            "vehicles": [{"registration": v.registration, "ownership": v.ownership, "status": v.status, "payload_kg": v.payload_kg} for v in vehicles],
            "drivers": {s: sum(1 for d in drivers if d.status == s) for s in ("available", "on_trip", "off_duty", "leave")},
            "source": "ERP master data (actual)",
        },
        "commercial": {
            "open_enquiries": db.execute(select(func.count()).select_from(Enquiry).where(Enquiry.status.in_(("new", "qualifying")))).scalar(),
            "quotes_pending_approval": db.execute(select(func.count()).select_from(Quotation).where(Quotation.status == "pending_approval")).scalar(),
            "bookings_to_plan": db.execute(select(func.count()).select_from(Booking).where(Booking.status == "confirmed")).scalar(),
            "bookings_on_credit_hold": db.execute(select(func.count()).select_from(Booking).where(Booking.status == "on_hold")).scalar(),
        },
        "operations": {
            "planned_trips": sum(1 for t in trips if t.status in ("planned", "ready")),
            "active_trips": live,
            "pod_pending_verification": db.execute(select(func.count()).select_from(ProofOfDelivery).where(ProofOfDelivery.status == "submitted")).scalar(),
            "delivered_not_closed": sum(1 for t in trips if t.status == "delivered"),
            "open_critical_defects": db.execute(select(func.count()).select_from(SafetyDefect).where(SafetyDefect.status == "open", SafetyDefect.severity == "critical")).scalar(),
            "compliance_expired": exp_compliance, "compliance_due_15d": due_compliance,
            "gps_note": "Positions show source and age. Stale/unavailable is shown as such - never estimated.",
        },
        "finance": {
            "expenses_to_review": db.execute(select(func.count()).select_from(Expense).where(Expense.status == "submitted")).scalar(),
            "payments_awaiting_approval": db.execute(select(func.count()).select_from(Payment).where(Payment.status == "pending_approval")).scalar(),
            "bank_unreconciled": db.execute(select(func.count()).select_from(BankTransaction).where(BankTransaction.status.in_(("unmatched", "suggested")))).scalar(),
            "invoices_overdue": db.execute(select(func.count()).select_from(Invoice).where(Invoice.status.in_(("issued", "part_paid")), Invoice.due_date < today)).scalar(),
        },
        "customer": {
            "open_complaints": db.execute(select(func.count()).select_from(Complaint).where(Complaint.status.notin_(("resolved", "closed")))).scalar(),
            "open_incidents": db.execute(select(func.count()).select_from(Incident).where(Incident.status != "closed")).scalar(),
        },
        "approvals_pending": db.execute(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending")).scalar(),
        "exceptions": [{"id": str(t.id), "code": t.code, "severity": t.severity, "title": t.title, "source": t.source, "entity": t.entity,
                        "entity_id": t.entity_id, "owner_role": t.owner_role, "due_at": t.due_at, "blocking": t.blocking,
                        "age_hours": int((now - t.created_at).total_seconds() // 3600)} for t in tasks[:200]],
        "recommendations": [to_dict(r) for r in db.execute(select(AiRecommendation).where(AiRecommendation.status == "open")
                                                            .order_by(AiRecommendation.created_at.desc()).limit(20)).scalars()],
    }


@router.get("/control-tower/daily-plan")
def daily_plan(p: Principal = Depends(require("controltower.read")), db: Session = Depends(get_db)):
    from app.modules.operations.service import allocation_checks, blocking_failures
    today = date.today()
    carry = [{"trip": t.code, "status": t.status} for t in db.execute(select(Trip).where(Trip.status.in_(("dispatched", "in_transit", "delivered")))).scalars()]
    morning = []
    for v in db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars():
        fails = blocking_failures(allocation_checks(db, vehicle=v, driver=None, bookings=[], planned_start=None), None)
        legal = [f["message"] for f in fails if f["severity"] in ("legal", "safety") and f["check"] != "driver_assigned"]
        morning.append({"vehicle": v.registration, "status": v.status, "ready": not legal, "blocks": legal})
    priorities = [{"booking": b.code, "service": b.service_type, "level": b.service_level, "deliver_by": b.deliver_by, "credit": b.credit_status}
                  for b in db.execute(select(Booking).where(Booking.status.in_(("confirmed", "on_hold"))).order_by(Booking.deliver_by.nulls_last())).scalars()]
    return {"date": str(today), "1_overnight_carryover": carry, "2_vehicle_driver_compliance": morning, "3_booking_priorities": priorities,
            "4_dispatch_and_loading": "Use trip readiness for each planned trip", "5_documents_credit": [x for x in priorities if x["credit"] not in ("ok", "warning", "exception_approved")],
            "6_live_monitoring": "See control tower active trips", "7_pod": db.execute(select(func.count()).select_from(ProofOfDelivery).where(ProofOfDelivery.status == "submitted")).scalar(),
            "8_close": "Expense review, collection follow-up, bank reconciliation", "9_next_day": "Plan bookings with pickup tomorrow"}


@router.get("/dashboard/owner")
def owner_dashboard(p: Principal = Depends(require("reports.read")), db: Session = Depends(get_db)):
    from app.modules.finance.reports import profit_and_loss
    from app.modules.finance.bank import reconciliation_summary
    from app.modules.masters.models import CompanyBankAccount
    today = date.today()
    mstart = today.replace(day=1)
    pl = profit_and_loss(db, mstart, today)
    outstanding = db.execute(select(func.coalesce(func.sum(Invoice.total - Invoice.amount_received - Invoice.tds_received), 0)).where(
        Invoice.status.in_(("issued", "part_paid", "disputed")))).scalar()
    overdue = db.execute(select(func.coalesce(func.sum(Invoice.total - Invoice.amount_received - Invoice.tds_received), 0)).where(
        Invoice.status.in_(("issued", "part_paid")), Invoice.due_date < today)).scalar()
    closed = list(db.execute(select(Trip).where(Trip.status.in_(("delivered", "closed")), Trip.actual_end >= datetime.combine(mstart, datetime.min.time()).replace(tzinfo=utcnow().tzinfo))).scalars())
    on_time = 0
    for t in closed:
        late = False
        from app.modules.operations.models import TripLoad
        for tl in db.execute(select(TripLoad).where(TripLoad.trip_id == t.id)).scalars():
            b = db.get(Booking, tl.booking_id)
            if b.deliver_by and b.delivered_at and b.delivered_at > b.deliver_by:
                late = True
        on_time += 0 if late else 1
    pods = list(db.execute(select(ProofOfDelivery).where(ProofOfDelivery.status == "verified", ProofOfDelivery.verified_at.isnot(None))).scalars())
    pod_tat = round(sum((x.verified_at - x.delivered_at).total_seconds() for x in pods) / 3600 / len(pods), 1) if pods else None
    banks = [reconciliation_summary(db, cb.id) for cb in db.execute(select(CompanyBankAccount).where(CompanyBankAccount.is_cash.is_(False))).scalars()]
    def kpi(label, value, source, basis="ACTUAL"):
        return {"label": label, "value": value, "source": source, "basis": basis, "as_of": utcnow().isoformat()}
    return {"kpis": [
        kpi("Revenue (month to date)", pl["total_income"], "Posted sales vouchers"),
        kpi("Gross contribution (MTD)", pl["gross_contribution"], "Direct income − direct expenses (posted)"),
        kpi("Net profit (MTD)", pl["net_profit"], "Posted vouchers"),
        kpi("Receivables outstanding", str(outstanding), "Issued invoices less receipts/TDS"),
        kpi("Overdue receivables", str(overdue), "Invoices past due date"),
        kpi("Trips delivered (MTD)", len(closed), "Trip records"),
        kpi("On-time delivery %", round(on_time / len(closed) * 100, 1) if closed else None, "POD time vs promised delivery"),
        kpi("POD verification turnaround (h)", pod_tat, "POD delivered → verified"),
        *[kpi(f"Bank book balance - {b['bank']}", b["book_balance"], "Ledger", "ACTUAL (book)") for b in banks],
        *[kpi(f"Unreconciled bank items - {b['bank']}", b["unreconciled_count"], b["sync_status"], "UNRECONCILED") for b in banks],
    ]}


# ===================================================================== AI gateway
class AskIn(BaseModel):
    assistant: str
    question: str = Field(min_length=2, max_length=2000)


@router.post("/ai/ask")
def ai_ask(body: AskIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return ai.ask(db, p, body.assistant, body.question)


@router.get("/ai/assistants")
def ai_assistants(p: Principal = Depends(current_principal)):
    return [{"code": a.code, "title": a.title, "essential": a.essential} for a in ai.ASSISTANTS.values() if p.can(a.permission)]


@router.get("/ai/usage")
def ai_usage(p: Principal = Depends(require("ai.admin")), db: Session = Depends(get_db)):
    rows = db.execute(select(AiUsage.assistant, AiUsage.provider, func.count(), func.sum(AiUsage.input_tokens + AiUsage.output_tokens),
                             func.sum(AiUsage.cost_inr)).group_by(AiUsage.assistant, AiUsage.provider)).all()
    providers = {k: {"mode": v.mode, "available": getattr(v, "available", True) if k != "mock" else True} for k, v in ai.PROVIDERS.items()}
    return {"budget": ai.spend(db), "providers": providers, "prompt_version": ai.PROMPT_VERSION,
            "by_assistant": [{"assistant": a, "provider": pr, "calls": c, "tokens": int(t or 0), "cost_inr": str(cost or 0)} for a, pr, c, t, cost in rows]}


@router.get("/ai/recommendations")
def recs(p: Principal = Depends(require("controltower.read")), db: Session = Depends(get_db)):
    return [to_dict(r) for r in db.execute(select(AiRecommendation).order_by(AiRecommendation.created_at.desc()).limit(200)).scalars()]


class RecDecisionIn(BaseModel):
    accept: bool


@router.post("/ai/recommendations/{rid}/decide")
def rec_decide(rid: uuid.UUID, body: RecDecisionIn, p: Principal = Depends(require("controltower.read")), db: Session = Depends(get_db)):
    r = get_or_404(db, AiRecommendation, rid, "Recommendation")
    r.status, r.decided_by = ("accepted" if body.accept else "dismissed"), p.user_id
    write_audit(db, actor=p, action="ai_recommendation.decide", entity="ai_recommendation", entity_id=r.id, after={"status": r.status})
    # Accepting does NOT execute anything: the UI opens the normal screen/API for the human to act with their own permissions.
    return {**to_dict(r), "next_step": r.proposed_action}


# ===================================================================== marketing & sales
register_crud(router, "opportunities", Opportunity, read_perm="marketing.read", write_perm="marketing.write", order_by="priority")

AGENTS = ["marketing_manager", "market_research", "lead_generation", "content_creator", "social_media", "business_development",
          "marketing_analyst", "website_seo"]


class DraftIn(BaseModel):
    agent: str
    channel: str = Field(pattern="^(facebook|instagram|youtube|whatsapp|gbp|linkedin|website)$")
    topic: str
    language: str = Field("en", pattern="^(en|ta)$")
    kind: str = Field("routine", pattern="^(routine|major|ad|brand)$")
    campaign_id: uuid.UUID | None = None


@router.post("/marketing/drafts")
def draft_content(body: DraftIn, p: Principal = Depends(require("marketing.write")), db: Session = Depends(get_db)):
    if body.agent not in AGENTS:
        raise AppError("unknown_agent", f"Agent must be one of {AGENTS}")
    from app.modules.masters.models import Location
    verified = [l.city for l in db.execute(select(Location).where(Location.service_verified.is_(True))).scalars()]
    txt = {"en": f"G ROAD LINES - {body.topic}. Full truck (FTL) and shared part-load (PTL) transport"
                 + (f" on verified routes: {', '.join(verified[:6])}." if verified else ".") + " Enquire for a quotation.",
           "ta": f"ஜி ரோடு லைன்ஸ் - {body.topic}. முழு லாரி (FTL) மற்றும் பகிர்வு சரக்கு (PTL) போக்குவரத்து. விலைப்பட்டியலுக்கு தொடர்பு கொள்ளவும்."}[body.language]
    c = ContentItem(campaign_id=body.campaign_id, channel=body.channel, kind=body.kind, title=body.topic[:200], body=txt, language=body.language,
                    drafted_by_agent=f"{body.agent} (MOCK template)", status="draft")
    db.add(c)
    db.flush()
    return {**to_dict(c), "note": "Draft only. No unsupported claims; coverage lists only verified service locations."}


class PublishIn(BaseModel):
    media_consent_confirmed: bool = False


@router.post("/marketing/content/{cid}/publish")
def publish(cid: uuid.UUID, body: PublishIn, p: Principal = Depends(require("marketing.write")), db: Session = Depends(get_db)):
    c = get_or_404(db, ContentItem, cid, "Content", lock=True)
    if c.media_document_ids and not (body.media_consent_confirmed or c.media_consent_confirmed):
        raise BlockedByRule("media_consent", "Media needs explicit consent (faces, plates, cargo, locations). Camera footage is not marketing consent.")
    if c.kind != "routine" and c.status != "approved":
        if c.status == "draft":
            request_approval(db, p, kind="marketing_content", entity="content", entity_id=c.id, title=f"{c.kind} content: {c.title}",
                             required_permission="marketing.approve")
            c.status = "pending_approval"
        return {**to_dict(c), "note": "Major/ad/brand content needs management approval before publishing"}
    cap = int(get_config(db, "marketing.daily_autopublish_cap"))
    today_n = db.execute(select(func.count()).select_from(ContentItem).where(ContentItem.status == "published",
                                                                             func.date(ContentItem.published_at) == utcnow().date())).scalar()
    if c.kind == "routine" and today_n >= cap:
        raise BlockedByRule("daily_cap", f"Daily auto-publish cap of {cap} reached")
    c.status, c.published_at, c.publish_mode = "published", utcnow(), "MOCK"
    c.media_consent_confirmed = c.media_consent_confirmed or body.media_consent_confirmed
    write_audit(db, actor=p, action="content.publish", entity="content", entity_id=c.id, after={"channel": c.channel, "mode": "MOCK"})
    return {**to_dict(c), "note": "Published to MOCK channel - social platform APIs not connected"}


@on_approval("marketing_content")
def _content_ok(db, actor, ar):
    c = db.get(ContentItem, uuid.UUID(ar.entity_id))
    c.status, c.approved_by = ("approved" if ar.status == "approved" else "rejected"), actor.user_id


@router.get("/marketing/content")
def list_content(p: Principal = Depends(require("marketing.read")), db: Session = Depends(get_db)):
    return [to_dict(c) for c in db.execute(select(ContentItem).order_by(ContentItem.created_at.desc())).scalars()]


class CampaignIn(BaseModel):
    name: str
    channels: list[str]
    audience: str | None = None
    budget: Decimal = Field(Decimal("0"), ge=0)
    starts_on: date | None = None
    ends_on: date | None = None


@router.post("/marketing/campaigns")
def create_campaign(body: CampaignIn, p: Principal = Depends(require("marketing.write")), db: Session = Depends(get_db)):
    c = Campaign(code=next_number(db, "CMPG", "CMPG"), status="pending_approval", **body.model_dump())
    db.add(c)
    db.flush()
    request_approval(db, p, kind="campaign", entity="campaign", entity_id=c.id, title=f"Campaign {c.name}: budget Rs {c.budget}",
                     required_permission="marketing.approve", amount=c.budget)
    return to_dict(c)


@on_approval("campaign")
def _campaign_ok(db, actor, ar):
    c = db.get(Campaign, uuid.UUID(ar.entity_id))
    c.status, c.approved_by = ("approved" if ar.status == "approved" else "draft"), actor.user_id


@router.get("/marketing/campaigns")
def list_campaigns(p: Principal = Depends(require("marketing.read")), db: Session = Depends(get_db)):
    return [to_dict(c) for c in db.execute(select(Campaign).order_by(Campaign.created_at.desc())).scalars()]


@router.get("/marketing/funnel")
def funnel(p: Principal = Depends(require("marketing.read")), db: Session = Depends(get_db)):
    by_src = db.execute(select(Enquiry.source, Enquiry.status, func.count()).group_by(Enquiry.source, Enquiry.status)).all()
    out: dict = {}
    for src, st, n in by_src:
        out.setdefault(src, {})[st] = n
    return {"by_source": out, "opportunity_map": [{"name": o.name, "lat": o.lat, "lng": o.lng, "stage": o.stage, "data_kind": o.data_kind,
                                                   "confidence": o.confidence} for o in db.execute(select(Opportunity)).scalars()],
            "note": "Opportunity locations do not imply service coverage."}


# ===================================================================== offline sync (idempotent)
class SyncItem(BaseModel):
    client_event_id: str = Field(min_length=8, max_length=80)
    device_id: str
    event_type: str = Field(pattern="^(trip_event|gps_ping|custody|scan|expense|fuel|inspection|pod|paper_form)$")
    payload: dict
    occurred_at: datetime
    source: str = Field("app_offline", pattern="^(app_offline|app_online|paper_form)$")


class SyncIn(BaseModel):
    events: list[SyncItem] = Field(max_length=500)


@router.post("/sync/events")
def sync_events(body: SyncIn, p: Principal = Depends(require("sync.write")), db: Session = Depends(get_db)):
    """Replays offline events in original-time order. Re-sending the same client_event_id returns the stored result
    (idempotent). Payments, statutory and credit approvals are never accepted offline."""
    from fastapi.encoders import jsonable_encoder
    results = []
    for ev in sorted(body.events, key=lambda e: e.occurred_at):
        prior = db.get(SyncEvent, ev.client_event_id)
        if prior:
            results.append({"client_event_id": ev.client_event_id, "status": prior.status, "result": prior.result, "replay": True})
            continue
        sp = db.begin_nested()
        try:
            res = _apply_sync(db, p, ev)
            status = "needs_review" if ev.source == "paper_form" else "applied"
            sp.commit()
        except Exception as e:  # noqa: BLE001 - every failure is recorded per event
            sp.rollback()
            res, status = {"error": getattr(e, "message", str(e))[:300]}, "rejected"
        res = jsonable_encoder(res)
        db.add(SyncEvent(client_event_id=ev.client_event_id, device_id=ev.device_id, user_id=p.user_id, event_type=ev.event_type,
                         payload=jsonable_encoder(ev.payload), occurred_at=ev.occurred_at, source=ev.source, status=status, result=res))
        db.flush()
        results.append({"client_event_id": ev.client_event_id, "status": status, "result": res, "replay": False})
    return {"results": results}


def _apply_sync(db: Session, p: Principal, ev: SyncItem) -> dict:
    from app.modules.operations import router as ops_router
    from app.modules.operations import service as ops
    from app.modules.operations.access import assert_trip_access
    pl = dict(ev.payload)
    if ev.event_type == "paper_form":
        if not p.is_internal:
            raise Forbidden("Paper forms are entered by office staff")
        return {"recorded": True, "form": pl.get("form_number"), "note": "Queued for supervisor review and reconciliation"}
    trip = None
    if pl.get("trip_id"):
        trip = get_or_404(db, Trip, pl["trip_id"], "Trip")
        assert_trip_access(db, p, trip, write=True)
    if ev.event_type == "trip_event":
        e = ops_router.record_event(db, p, trip, ops_router.EventIn(**{**pl, "occurred_at": ev.occurred_at, "source": ev.source}))
        return {"event_id": str(e.id)}
    if ev.event_type == "gps_ping":
        if not trip or not trip.gps_consent_at:
            raise BlockedByRule("no_consent", "GPS consent not recorded")
        ops.record_ping(db, vehicle_id=trip.vehicle_id, trip_id=trip.id, source="phone", lat=pl["lat"], lng=pl["lng"], recorded_at=ev.occurred_at)
        return {"ok": True}
    if ev.event_type == "scan":
        s = ops.scan_package(db, p, label=pl["label"], trip=trip, stage=pl["stage"], occurred_at=ev.occurred_at, client_event_id=ev.client_event_id)
        return {"scan_id": str(s.id), "result": s.result}
    if ev.event_type == "custody":
        b = get_or_404(db, Booking, pl["booking_id"], "Booking")
        c = ops.record_custody(db, p, booking=b, trip=trip, event=pl["event"], package_count=pl.get("package_count"),
                               condition=pl.get("condition"), seal_number=pl.get("seal_number"), note=pl.get("note"), occurred_at=ev.occurred_at)
        return {"custody_id": str(c.id)}
    if ev.event_type == "expense":
        from app.modules.finance.router import ExpenseIn, submit_expense
        return submit_expense(ExpenseIn(**{**pl, "occurred_at": ev.occurred_at}), p, db)
    if ev.event_type == "fuel":
        from app.modules.fleet.router import FuelIn, post_fuel
        return post_fuel(FuelIn(**{**pl, "filled_at": ev.occurred_at}), p, db)
    if ev.event_type == "inspection":
        from app.modules.fleet.router import InspectionIn, post_inspection
        return post_inspection(InspectionIn(**{**pl, "occurred_at": ev.occurred_at}), p, db)
    if ev.event_type == "pod":
        b = get_or_404(db, Booking, pl["booking_id"], "Booking")
        pod = ops.submit_pod(db, p, trip=trip, booking=b, delivered_count=pl["delivered_count"], receiver_name=pl["receiver_name"],
                             receiver_phone=pl.get("receiver_phone"), otp_verified=False, photo_ids=pl.get("photo_document_ids", []),
                             signature_id=pl.get("signature_document_id"), condition=pl.get("condition", "good"), remarks=pl.get("remarks"),
                             delivered_at=ev.occurred_at)
        return {"pod_id": str(pod.id)}
    raise AppError("unsupported", "Unsupported event type")


# ===================================================================== scheduled jobs
@router.post("/jobs/run")
def run_jobs(p: Principal = Depends(require("settings.write")), db: Session = Depends(get_db)):
    from app.worker import run_all
    return run_all(db)
