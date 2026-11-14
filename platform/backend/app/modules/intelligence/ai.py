"""Central AI Gateway (Level 2 - controlled automation).

* Provider-independent: mock (default), Anthropic and OpenAI adapters activate only when API keys are configured.
* Assistants call SCOPED, READ-ONLY tools that reuse validated backend queries with the caller's principal.
  There is no direct database access for the model and no write tool: the AI can only create recommendations
  that a permitted human executes through the normal APIs (which re-check permissions and approvals).
* Usage, tokens and INR cost are tracked; daily/monthly budgets pause non-essential assistants at the cap.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import Principal
from app.core.errors import AppError, Forbidden
from app.core.services import get_config, raise_exception_task
from app.modules.people.models import AiRecommendation, AiUsage

PROMPT_VERSION = "2026.11-v1"


# ------------------------------------------------------------------ providers
class MockProvider:
    name, model, mode = "mock", "mock-deterministic", "MOCK"
    inr_per_1k = Decimal("0")

    def complete(self, system: str, user: str, context: dict) -> tuple[str, int, int]:
        lines = ["[MOCK AI - deterministic summary, no language model used]"]
        for tool, data in context.items():
            lines.append(f"- {tool}: {_summarise(data)}")
        if not context:
            lines.append("I could not find data for that question within your permissions.")
        text = "\n".join(lines)
        return text, len(user) // 4, len(text) // 4


class HttpProvider:
    """Generic adapter. Activated only when an API key env var is present. Data minimisation: only tool results are sent."""

    def __init__(self, name: str, url: str, model: str, key_env: str, inr_per_1k: str):
        self.name, self.url, self.model, self.key_env, self.mode = name, url, model, key_env, "LIVE"
        self.inr_per_1k = Decimal(inr_per_1k)

    @property
    def available(self) -> bool:
        return bool(os.environ.get(self.key_env))

    def complete(self, system: str, user: str, context: dict) -> tuple[str, int, int]:
        key = os.environ[self.key_env]
        msg = f"{user}\n\nAuthorised data (JSON):\n{json.dumps(context, default=str)[:12000]}"
        if self.name == "anthropic":
            body = {"model": self.model, "max_tokens": 800, "system": system, "messages": [{"role": "user", "content": msg}]}
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        else:
            body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": msg}], "max_tokens": 800}
            headers = {"authorization": f"Bearer {key}", "content-type": "application/json"}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        if self.name == "anthropic":
            text = "".join(c.get("text", "") for c in data.get("content", []))
            u = data.get("usage", {})
            return text, u.get("input_tokens", 0), u.get("output_tokens", 0)
        u = data.get("usage", {})
        return data["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


PROVIDERS = {
    "mock": MockProvider(),
    "anthropic": HttpProvider("anthropic", "https://api.anthropic.com/v1/messages", os.environ.get("GRL_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
                              "GRL_ANTHROPIC_API_KEY", "0.30"),
    "openai": HttpProvider("openai", "https://api.openai.com/v1/chat/completions", os.environ.get("GRL_OPENAI_MODEL", "gpt-4o-mini"),
                           "GRL_OPENAI_API_KEY", "0.05"),
}


def _summarise(data) -> str:
    if isinstance(data, list):
        return f"{len(data)} record(s)" + (": " + "; ".join(_summarise(x) for x in data[:5]) if data else "")
    if isinstance(data, dict):
        keys = list(data)[:8]
        return ", ".join(f"{k}={data[k] if not isinstance(data[k], (list, dict)) else '…'}" for k in keys)
    return str(data)


# ------------------------------------------------------------------ assistants & scoped tools
@dataclass
class Assistant:
    code: str
    title: str
    permission: str
    apps: set[str]
    essential: bool
    tools: dict = field(default_factory=dict)


def _t_customer_bookings(db: Session, p: Principal):
    from app.modules.commercial.models import Booking
    if not p.customer_id:
        raise Forbidden()
    return [{"code": b.code, "status": b.status, "service": b.service_type} for b in
            db.execute(select(Booking).where(Booking.customer_id == p.customer_id).order_by(Booking.created_at.desc()).limit(10)).scalars()]


def _t_customer_invoices(db: Session, p: Principal):
    from app.modules.finance.models import Invoice
    if not p.customer_id:
        raise Forbidden()
    return [{"number": i.number, "total": str(i.total), "status": i.status, "due": str(i.due_date)} for i in
            db.execute(select(Invoice).where(Invoice.customer_id == p.customer_id, Invoice.status != "cancelled")).scalars()]


def _t_unplanned(db: Session, p: Principal):
    from app.modules.commercial.models import Booking
    return [{"code": b.code, "type": b.service_type, "weight": str(b.weight_kg), "deliver_by": str(b.deliver_by)} for b in
            db.execute(select(Booking).where(Booking.status == "confirmed").order_by(Booking.deliver_by)).scalars()]


def _t_active_trips(db: Session, p: Principal):
    from app.modules.operations.models import Trip
    return [{"code": t.code, "status": t.status, "last_ping": str(t.last_ping_at), "delay_min": t.delay_minutes} for t in
            db.execute(select(Trip).where(Trip.status.in_(("dispatched", "in_transit")))).scalars()]


def _t_my_trips(db: Session, p: Principal):
    from app.modules.operations.access import driver_trip_ids
    from app.modules.operations.models import Trip
    ids = driver_trip_ids(db, p)
    return [{"code": t.code, "status": t.status, "planned_start": str(t.planned_start)} for t in
            db.execute(select(Trip).where(Trip.id.in_(ids), Trip.status.in_(("planned", "ready", "dispatched", "in_transit")))).scalars()]


def _t_my_earnings(db: Session, p: Principal):
    from app.modules.fleet.models import DriverEarning
    return [{"gross": str(e.gross), "status": e.status} for e in
            db.execute(select(DriverEarning).where(DriverEarning.driver_id == p.driver_id)).scalars()]


def _t_overdue(db: Session, p: Principal):
    from app.modules.finance.reports import ageing
    return ageing(db, "receivable")["rows"][:10]


def _t_unreconciled(db: Session, p: Principal):
    from app.modules.finance.models import BankTransaction
    return [{"date": str(t.txn_date), "credit": str(t.credit), "debit": str(t.debit), "desc": t.description[:60], "status": t.status}
            for t in db.execute(select(BankTransaction).where(BankTransaction.status.in_(("unmatched", "suggested"))).limit(20)).scalars()]


def _t_cash(db: Session, p: Principal):
    from app.modules.finance.reports import cashflow_forecast
    f = cashflow_forecast(db, 4)
    return [{"week": w["week_start"], "in": w["inflow"], "out": w["outflow"], "net": w["net"]} for w in f["weeks"]]


def _t_compliance(db: Session, p: Principal):
    from app.modules.fleet.models import ComplianceItem
    lim = date.today() + timedelta(days=30)
    return [{"kind": c.kind, "subject": str(c.subject_id), "valid_to": str(c.valid_to)} for c in
            db.execute(select(ComplianceItem).where(ComplianceItem.status == "current", ComplianceItem.valid_to <= lim)).scalars()]


def _t_fuel(db: Session, p: Principal):
    from app.modules.fleet.models import FuelEntry
    return [{"id": str(f.id), "flags": f.anomaly_flags, "kmpl": str(f.computed_kmpl)} for f in
            db.execute(select(FuelEntry).where(FuelEntry.review_status == "needs_review")).scalars()]


def _t_maint(db: Session, p: Principal):
    from app.modules.fleet.models import SafetyDefect
    return [{"vehicle": str(d.vehicle_id), "item": d.item, "severity": d.severity} for d in
            db.execute(select(SafetyDefect).where(SafetyDefect.status == "open")).scalars()]


def _t_profit(db: Session, p: Principal):
    from app.modules.finance.reports import profitability_summary
    t = date.today()
    return profitability_summary(db, t.replace(day=1), t)["by_service"]


def _t_legal(db: Session, p: Principal):
    from app.modules.risk.models import LegalCase
    if not p.can("legal.read"):
        return "not permitted"
    return [{"code": l.code, "due": str(l.response_due), "status": l.status} for l in db.execute(select(LegalCase)).scalars()]


ASSISTANTS: dict[str, Assistant] = {
    "customer": Assistant("customer", "Customer AI", "portal.customer", {"portal", "web"}, True,
                          {"bookings": _t_customer_bookings, "invoices": _t_customer_invoices}),
    "booking_dispatch": Assistant("booking_dispatch", "Booking & Dispatch AI", "dispatch.plan", {"web", "management"}, True,
                                  {"unplanned_bookings": _t_unplanned, "active_trips": _t_active_trips}),
    "driver": Assistant("driver", "Driver AI", "driver.app", {"driver", "web"}, True, {"my_trips": _t_my_trips, "my_earnings": _t_my_earnings}),
    "accounts": Assistant("accounts", "Accounts AI", "accounts.read", {"web", "management"}, False,
                          {"overdue": _t_overdue, "unreconciled": _t_unreconciled, "cash_forecast": _t_cash}),
    "fleet": Assistant("fleet", "Fleet AI", "fleet.read", {"web"}, False, {"compliance_due": _t_compliance, "fuel_review": _t_fuel, "open_defects": _t_maint}),
    "profit_bi": Assistant("profit_bi", "Profit & BI AI", "reports.read", {"web", "management"}, False, {"profitability": _t_profit}),
    "compliance": Assistant("compliance", "Compliance AI", "compliance.read", {"web"}, False, {"compliance_due": _t_compliance, "legal_deadlines": _t_legal}),
}

SYSTEM = ("You are a G ROAD LINES business assistant. Use ONLY the authorised data provided. You may summarise, analyse, draft and "
          "recommend. You must never claim to have executed payments, approvals, filings, price/discount changes, credit changes or "
          "any action; tell the user which authorised person/screen executes it. Never reveal data not in the provided context. "
          "State data freshness and uncertainty. Do not give final legal, tax or insurance-coverage determinations.")


# ------------------------------------------------------------------ budget
def spend(db: Session) -> dict:
    today = utcnow().date()
    day = db.execute(select(func.coalesce(func.sum(AiUsage.cost_inr), 0)).where(func.date(AiUsage.at) == today)).scalar()
    month = db.execute(select(func.coalesce(func.sum(AiUsage.cost_inr), 0)).where(AiUsage.at >= utcnow().replace(day=1, hour=0, minute=0, second=0))).scalar()
    b = get_config(db, "ai.budget")
    return {"day_inr": str(day), "month_inr": str(month), "daily_cap": b["daily_inr"], "monthly_cap": b["monthly_inr"],
            "day_pct": round(float(day) / float(b["daily_inr"]) * 100, 1) if b["daily_inr"] else 0,
            "month_pct": round(float(month) / float(b["monthly_inr"]) * 100, 1) if b["monthly_inr"] else 0, "alert_pcts": b["alert_pcts"]}


def _pick_provider(db: Session, essential: bool) -> tuple[object, str]:
    s = spend(db)
    at_cap = s["day_pct"] >= 100 or s["month_pct"] >= 100
    routing = get_config(db, "ai.routing")
    pref = PROVIDERS.get(routing.get("default", "mock"), PROVIDERS["mock"])
    if at_cap:
        if not essential:
            raise AppError("ai_budget_cap", "AI budget cap reached - non-essential assistants are paused. Core ERP is unaffected.", status=429)
        return PROVIDERS["mock"], "fallback_budget"
    if pref is not PROVIDERS["mock"] and not getattr(pref, "available", False):
        return PROVIDERS["mock"], "fallback_unconfigured"
    return pref, "ok"


def ask(db: Session, p: Principal, assistant_code: str, question: str) -> dict:
    a = ASSISTANTS.get(assistant_code)
    if not a:
        raise AppError("unknown_assistant", "Unknown assistant")
    if not p.can(a.permission) or not p.can("ai.use") and assistant_code != "customer":
        raise Forbidden(f"{a.title} is not available for your role")
    if p.app not in a.apps and p.app != "web":
        raise Forbidden(f"{a.title} is not available in this app")
    q = question.lower()
    context = {}
    used = []
    for name, fn in a.tools.items():
        # Intent: run tools whose name words appear in the question, or all tools for a general question
        if any(w in q for w in name.split("_")) or len(a.tools) <= 2 or "summary" in q or "today" in q:
            context[name] = fn(db, p)
            used.append(name)
    provider, status = _pick_provider(db, a.essential)
    t0 = time.time()
    try:
        text, tin, tout = provider.complete(SYSTEM, question[:2000], context)
    except Exception as e:  # provider down → deterministic fallback, core continues
        provider, status = PROVIDERS["mock"], "fallback_error"
        text, tin, tout = PROVIDERS["mock"].complete(SYSTEM, question, context)
        text += f"\n(Provider error: {type(e).__name__})"
    cost = (Decimal(tin + tout) / 1000 * provider.inr_per_1k).quantize(Decimal("0.0001"))
    db.add(AiUsage(provider=provider.name, model=provider.model, assistant=a.code, user_id=p.user_id, app=p.app, input_tokens=tin,
                   output_tokens=tout, cost_inr=cost, status=status, prompt_version=PROMPT_VERSION, tools_used=used))
    db.flush()
    s = spend(db)
    for pct in s["alert_pcts"]:
        if s["month_pct"] >= pct:
            raise_exception_task(db, kind="alert", severity="high" if pct >= 90 else "low", title=f"AI monthly budget {pct}% used",
                                 entity="ai_budget", entity_id=utcnow().strftime("%Y-%m"), source="ai_gateway", owner_role="owner_director")
    return {"assistant": a.title, "answer": text, "provider": provider.name, "mode": provider.mode, "status": status,
            "tools_used": used, "latency_ms": int((time.time() - t0) * 1000), "data_as_of": utcnow().isoformat(),
            "disclaimer": "AI output is advisory. Actions require an authorised person through the normal screens."}


def recommend(db: Session, *, assistant: str, kind: str, title: str, reasoning: str, confidence: float, entity=None, entity_id=None,
              proposed_action: dict | None = None, for_user=None, freshness: str | None = None) -> AiRecommendation:
    r = AiRecommendation(assistant=assistant, kind=kind, title=title, reasoning=reasoning, confidence=Decimal(str(confidence)),
                         entity=entity, entity_id=str(entity_id) if entity_id else None, proposed_action=proposed_action,
                         for_user=for_user, data_freshness=freshness or utcnow().isoformat())
    db.add(r)
    db.flush()
    return r


def generate_recommendations(db: Session) -> int:
    """Scheduled: deterministic recommendations (no model needed) with reason, confidence and freshness."""
    from app.modules.commercial.models import Booking
    from app.modules.operations.models import Trip
    n = 0
    stale = int(get_config(db, "gps.stale_minutes"))
    for t in db.execute(select(Trip).where(Trip.status.in_(("dispatched", "in_transit")))).scalars():
        if t.last_ping_at is None or utcnow() - t.last_ping_at > timedelta(minutes=stale * 2):
            recommend(db, assistant="booking_dispatch", kind="call_driver", title=f"Call driver of {t.code}: tracking stale",
                      reasoning=f"Last position {t.last_ping_at or 'never'}; threshold {stale} min", confidence=0.9, entity="trip", entity_id=t.id)
            n += 1
    for b in db.execute(select(Booking).where(Booking.status == "confirmed", Booking.deliver_by.isnot(None),
                                              Booking.deliver_by < utcnow() + timedelta(hours=36))).scalars():
        recommend(db, assistant="booking_dispatch", kind="allocate_urgent", title=f"Allocate {b.code} - delivery due {b.deliver_by:%d-%m %H:%M}",
                  reasoning="Confirmed booking without trip close to promised delivery", confidence=0.85, entity="booking", entity_id=b.id,
                  proposed_action={"endpoint": f"/api/v1/allocation/candidates/{b.id}", "method": "GET"})
        n += 1
    return n
