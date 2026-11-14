"""Driver remuneration: versioned, approved rules → transparent per-trip calculation → approval → settlement."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import money
from app.modules.fleet.models import DriverEarning, RemunerationRule
from app.modules.operations.models import Trip, TripEvent

PER_TRIP_COMPONENTS = {"per_trip", "per_km", "duty_day", "night", "waiting_hour", "incentive_on_time"}


def active_rules(db: Session, driver_id, on: date) -> list[RemunerationRule]:
    rows = db.execute(select(RemunerationRule).where(
        RemunerationRule.driver_id == driver_id, RemunerationRule.status.in_(("active", "superseded")),
        RemunerationRule.effective_from <= on)).scalars()
    best: dict[str, RemunerationRule] = {}
    for r in rows:
        if r.effective_to and r.effective_to < on:
            continue
        if r.component not in best or r.effective_from > best[r.component].effective_from:
            best[r.component] = r
    return list(best.values())


def calculate_trip_earning(db: Session, actor, trip: Trip) -> dict:
    """Uses only approved rules in force on the trip start date (changes are prospective)."""
    if db.execute(select(DriverEarning).where(DriverEarning.trip_id == trip.id, DriverEarning.driver_id == trip.driver_id)).first():
        e = db.execute(select(DriverEarning).where(DriverEarning.trip_id == trip.id)).scalar_one()
        return {"id": str(e.id), "gross": str(e.gross), "status": e.status}
    on = (trip.actual_start or trip.planned_start).date()
    rules = [r for r in active_rules(db, trip.driver_id, on) if r.component in PER_TRIP_COMPONENTS]
    km = Decimal(str((trip.end_odometer or 0) - (trip.start_odometer or 0))) if trip.end_odometer and trip.start_odometer else Decimal(trip.planned_km or 0)
    days = max(1, ((trip.actual_end or trip.closed_at) - trip.actual_start).days + 1) if trip.actual_start and (trip.actual_end or trip.closed_at) else 1
    waiting_h = Decimal("0")
    evs = list(db.execute(select(TripEvent).where(TripEvent.trip_id == trip.id, TripEvent.event == "waiting")).scalars())
    for e in evs:
        waiting_h += Decimal(str((e.data or {}).get("hours", 0)))
    lines = []
    for r in rules:
        cond = r.conditions or {}
        if r.component == "per_trip":
            qty = Decimal("1")
        elif r.component == "per_km":
            qty = km if km >= Decimal(str(cond.get("min_km", 0))) else Decimal("0")
        elif r.component == "duty_day":
            qty = Decimal(days)
        elif r.component == "night":
            qty = Decimal(str(cond.get("nights", max(0, days - 1))))
        elif r.component == "waiting_hour":
            qty = max(Decimal("0"), waiting_h - Decimal(str(cond.get("free_hours", 0))))
        elif r.component == "incentive_on_time":
            qty = Decimal("1") if trip.delay_minutes <= int(cond.get("grace_minutes", 0)) else Decimal("0")
        else:
            continue
        amt = money(qty * Decimal(r.rate))
        lines.append({"component": r.component, "rule_id": str(r.id), "rule_version": r.version, "rate": str(r.rate),
                      "qty": str(qty), "amount": str(amt), "formula": f"{qty} x {r.rate}"})
    gross = money(sum((Decimal(l["amount"]) for l in lines), Decimal("0")))
    e = DriverEarning(driver_id=trip.driver_id, trip_id=trip.id, breakdown=lines, gross=gross, net=gross, status="calculated")
    db.add(e)
    db.flush()
    write_audit(db, actor=actor, action="driver_earning.calculate", entity="driver_earning", entity_id=e.id,
                after={"trip": trip.code, "gross": gross, "lines": len(lines)})
    return {"id": str(e.id), "gross": str(gross), "lines": lines, "status": e.status,
            "note": "Calculated from approved rules. Requires authorised approval before settlement." if lines else
                    "No approved per-trip remuneration rules for this driver"}


def new_rule_version(db: Session, driver_id: uuid.UUID, component: str) -> int:
    rows = db.execute(select(RemunerationRule.version).where(RemunerationRule.driver_id == driver_id,
                                                              RemunerationRule.component == component)).scalars().all()
    return (max(rows) + 1) if rows else 1
