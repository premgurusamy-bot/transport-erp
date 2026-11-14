"""Vehicles, compliance & renewals, inspections, safety defects, fuel, maintenance, tyres; drivers & remuneration."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import snapshot, write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden
from app.core.resource import register_crud
from app.core.services import (
    get_config, next_number, on_approval, raise_exception_task, request_approval,
)
from app.modules.fleet.drivers import new_rule_version
from app.modules.fleet.models import (
    ComplianceItem, ComplianceRenewal, Driver, DriverAdvance, DriverEarning, FuelEntry, Grievance, Inspection, JobCard,
    RemunerationRule, SafetyDefect, Tyre, TyreEvent, Vehicle,
)
from app.modules.operations.access import assert_trip_access
from app.modules.operations.models import Trip
from app.modules.platform.models import ApprovalRequest

router = APIRouter(prefix="/api/v1", tags=["fleet"])


def _vehicle_before(db, p, obj, data, creating):
    if "registration" in data and data["registration"]:
        data["registration"] = data["registration"].upper().replace(" ", "").replace("-", "")
    if data.get("ownership") == "attached" and not (data.get("owner_id") or obj.owner_id):
        raise AppError("owner_required", "Attached vehicles must be linked to an owner")
    if "status" in data and not creating and data["status"] == "available":
        if db.execute(select(SafetyDefect).where(SafetyDefect.vehicle_id == obj.id, SafetyDefect.status == "open",
                                                 SafetyDefect.severity == "critical")).first():
            raise BlockedByRule("open_defect", "Vehicle has an open critical defect - release it first")


register_crud(router, "vehicles", Vehicle, read_perm="fleet.read", write_perm="fleet.write", before_save=_vehicle_before,
              search_fields=("registration", "make", "model"))
register_crud(router, "drivers", Driver, read_perm="driver.read", write_perm="driver.write", code_field="code", code_prefix="DRV",
              search_fields=("name", "phone"))
register_crud(router, "tyres", Tyre, read_perm="fleet.read", write_perm="fleet.write", search_fields=("serial", "brand"),
              readonly_fields={"km_run", "retread_count", "vehicle_id", "position", "fitted_odometer"})


# ===================================================================== compliance
class ComplianceIn(BaseModel):
    subject_type: str = Field(pattern="^(vehicle|driver|owner|vendor)$")
    subject_id: uuid.UUID
    kind: str = Field(pattern="^(insurance|road_tax|national_permit|state_permit|fitness|puc|rc|licence|hazmat_licence|medical|kyc|other)$")
    number: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    mandatory_for_dispatch: bool = True
    document_id: uuid.UUID | None = None
    meta: dict | None = None


def add_compliance(db: Session, actor, body: ComplianceIn) -> ComplianceItem:
    for old in db.execute(select(ComplianceItem).where(ComplianceItem.subject_type == body.subject_type,
                                                       ComplianceItem.subject_id == body.subject_id,
                                                       ComplianceItem.kind == body.kind, ComplianceItem.status == "current")).scalars():
        old.status = "superseded"
    it = ComplianceItem(**body.model_dump())
    db.add(it)
    db.flush()
    if body.subject_type == "driver" and body.kind == "licence":
        d = db.get(Driver, body.subject_id)
        if d:
            d.licence_valid_to, d.licence_number = body.valid_to, body.number or d.licence_number
    write_audit(db, actor=actor, action="compliance.record", entity=body.subject_type, entity_id=body.subject_id,
                after={"kind": body.kind, "valid_to": body.valid_to, "number": body.number})
    return it


@router.post("/compliance")
def post_compliance(body: ComplianceIn, p: Principal = Depends(require("compliance.write")), db: Session = Depends(get_db)):
    return to_dict(add_compliance(db, p, body))


@router.get("/compliance")
def list_compliance(subject_id: uuid.UUID | None = None, due_in_days: int | None = None,
                    p: Principal = Depends(require("compliance.read")), db: Session = Depends(get_db)):
    q = select(ComplianceItem).where(ComplianceItem.status == "current")
    if subject_id:
        q = q.where(ComplianceItem.subject_id == subject_id)
    if due_in_days is not None:
        q = q.where(ComplianceItem.valid_to <= date.today() + timedelta(days=due_in_days))
    out = []
    for it in db.execute(q.order_by(ComplianceItem.valid_to)).scalars():
        d = to_dict(it)
        d["days_left"] = (it.valid_to - date.today()).days if it.valid_to else None
        d["subject_label"] = _subject_label(db, it)
        out.append(d)
    return out


def _subject_label(db, it):
    if it.subject_type == "vehicle":
        v = db.get(Vehicle, it.subject_id)
        return v.registration if v else None
    if it.subject_type == "driver":
        d = db.get(Driver, it.subject_id)
        return d.name if d else None
    return str(it.subject_id)


def compliance_alerts(db: Session) -> int:
    """Daily job: raise reminder tasks at configured days-before-expiry. Returns count raised."""
    days = sorted(get_config(db, "compliance.alert_days"), reverse=True)
    n = 0
    for it in db.execute(select(ComplianceItem).where(ComplianceItem.status == "current", ComplianceItem.valid_to.isnot(None))).scalars():
        left = (it.valid_to - date.today()).days
        if left <= days[0]:
            sev = "critical" if left <= 1 else "high" if left <= 7 else "medium"
            raise_exception_task(db, kind="alert", severity=sev, title=f"{it.kind} for {_subject_label(db, it)} expires {it.valid_to}",
                                 entity=it.subject_type, entity_id=it.subject_id, source="compliance", owner_role="compliance_coordinator")
            n += 1
    return n


# ----------------------------------------------------------------- renewals (Owner/Director approval always)
class RenewalIn(BaseModel):
    compliance_item_id: uuid.UUID


@router.post("/compliance/renewals")
def start_renewal(body: RenewalIn, p: Principal = Depends(require("compliance.write")), db: Session = Depends(get_db)):
    it = get_or_404(db, ComplianceItem, body.compliance_item_id, "Compliance item")
    r = ComplianceRenewal(code=next_number(db, "REN", "REN"), compliance_item_id=it.id)
    db.add(r)
    db.flush()
    return to_dict(r)


class RenewalQuoteIn(BaseModel):
    vendor_id: uuid.UUID | None = None
    quote_amount: Decimal = Field(gt=0)
    quote_document_id: uuid.UUID | None = None
    reason: str = "Compliance renewal"


@router.post("/compliance/renewals/{rid}/quote")
def renewal_quote(rid: uuid.UUID, body: RenewalQuoteIn, p: Principal = Depends(require("compliance.write")), db: Session = Depends(get_db)):
    r = get_or_404(db, ComplianceRenewal, rid, "Renewal")
    if r.status not in ("initiated", "quoted", "rejected"):
        raise Conflict("bad_status", f"Renewal is {r.status}")
    r.vendor_id, r.quote_amount, r.quote_document_id = body.vendor_id, body.quote_amount, body.quote_document_id
    it = db.get(ComplianceItem, r.compliance_item_id)
    ar = request_approval(db, p, kind="compliance_renewal", entity="compliance_renewal", entity_id=r.id,
                          title=f"Renewal {it.kind} for {_subject_label(db, it)}: Rs {body.quote_amount}",
                          required_permission="compliance.approve_renewal", amount=body.quote_amount, reason=body.reason)
    r.status, r.approval_id = "pending_approval", ar.id
    return to_dict(r)


@on_approval("compliance_renewal")
def _renewal_decided(db, actor, ar):
    r = db.get(ComplianceRenewal, uuid.UUID(ar.entity_id))
    r.status = "approved" if ar.status == "approved" else "rejected"


class RenewalCompleteIn(BaseModel):
    payment_reference: str = Field(min_length=3)
    payment_document_id: uuid.UUID | None = None
    new_number: str | None = None
    new_valid_from: date
    new_valid_to: date
    new_document_id: uuid.UUID | None = None


@router.post("/compliance/renewals/{rid}/complete")
def renewal_complete(rid: uuid.UUID, body: RenewalCompleteIn, p: Principal = Depends(require("compliance.write")), db: Session = Depends(get_db)):
    from app.modules.finance.models import Expense
    r = get_or_404(db, ComplianceRenewal, rid, "Renewal", lock=True)
    if r.status != "approved":
        raise BlockedByRule("not_approved", "Renewal expense must be approved by the Owner/Director before completion")
    if body.new_valid_to <= body.new_valid_from:
        raise AppError("dates", "Validity end must be after start")
    old = db.get(ComplianceItem, r.compliance_item_id)
    new = add_compliance(db, p, ComplianceIn(subject_type=old.subject_type, subject_id=old.subject_id, kind=old.kind,
                                             number=body.new_number or old.number, valid_from=body.new_valid_from,
                                             valid_to=body.new_valid_to, document_id=body.new_document_id,
                                             mandatory_for_dispatch=old.mandatory_for_dispatch, meta=old.meta))
    exp = Expense(code=next_number(db, "EXP", "EXP"), category="compliance", expense_date=date.today(), amount=r.quote_amount,
                  vendor_id=r.vendor_id, vehicle_id=old.subject_id if old.subject_type == "vehicle" else None,
                  bill_number=body.payment_reference, status="approved", submitted_by=p.user_id,
                  approved_by=db.get(ApprovalRequest, r.approval_id).checker_id,
                  receipt_document_id=body.payment_document_id, payment_mode="neft")
    db.add(exp)
    db.flush()
    r.status, r.payment_reference, r.payment_document_id, r.new_item_id, r.expense_id = "completed", body.payment_reference, body.payment_document_id, new.id, exp.id
    from app.modules.finance.posting import post_expense
    post_expense(db, p, exp)
    write_audit(db, actor=p, action="compliance.renewed", entity="compliance_renewal", entity_id=r.id,
                after={"valid_to": body.new_valid_to, "expense": exp.code})
    return {"renewal": to_dict(r), "compliance": to_dict(new), "expense": exp.code}


# ===================================================================== inspections & defects
class InspectionIn(BaseModel):
    vehicle_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    kind: str = Field("pre_trip", pattern="^(pre_trip|post_trip|periodic)$")
    checklist: dict[str, str]  # item -> ok|defect|na
    odometer_km: int | None = Field(None, ge=0)
    fuel_level_pct: int | None = Field(None, ge=0, le=100)
    notes: str | None = None
    occurred_at: datetime | None = None


CRITICAL_ITEMS = {"brakes", "steering", "tyres", "lights", "horn", "wipers", "seat_belt", "fire_extinguisher", "leaks", "load_securing"}
DEFAULT_CHECKLIST = sorted(CRITICAL_ITEMS | {"mirrors", "documents", "first_aid", "body_condition", "cleanliness", "reflectors"})


@router.get("/inspections/checklist")
def checklist_template(p: Principal = Depends(current_principal)):
    return {"items": DEFAULT_CHECKLIST, "critical": sorted(CRITICAL_ITEMS)}


@router.post("/inspections")
def post_inspection(body: InspectionIn, p: Principal = Depends(require_any("fleet.write", "driver.app")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    if body.trip_id:
        t = get_or_404(db, Trip, body.trip_id, "Trip")
        assert_trip_access(db, p, t, write=True)
        if t.vehicle_id != v.id:
            raise AppError("vehicle_mismatch", "Vehicle is not assigned to this trip")
    elif not p.can("fleet.write"):
        raise Forbidden()
    missing = [i for i in CRITICAL_ITEMS if i not in body.checklist]
    if body.kind == "pre_trip" and missing:
        raise AppError("incomplete", f"Checklist incomplete: {', '.join(sorted(missing))}")
    defects = [k for k, val in body.checklist.items() if val == "defect"]
    critical = [k for k in defects if k in CRITICAL_ITEMS]
    insp = Inspection(vehicle_id=v.id, trip_id=body.trip_id, driver_id=p.driver_id, kind=body.kind, checklist=body.checklist,
                      odometer_km=body.odometer_km, fuel_level_pct=body.fuel_level_pct, passed=not critical, notes=body.notes,
                      occurred_at=body.occurred_at or utcnow())
    db.add(insp)
    db.flush()
    for k in defects:
        sev = "critical" if k in CRITICAL_ITEMS else "minor"
        db.add(SafetyDefect(vehicle_id=v.id, item=k, severity=sev, description=body.notes, reported_by=p.user_id, inspection_id=insp.id))
    if critical:
        v.status = "maintenance"
        raise_exception_task(db, severity="critical", title=f"Critical defect on {v.registration}: {', '.join(critical)}",
                             entity="vehicle", entity_id=v.id, source="inspection", owner_role="fleet_maintenance", blocking=True)
    write_audit(db, actor=p, action="inspection.record", entity="vehicle", entity_id=v.id, after={"passed": insp.passed, "defects": defects})
    return to_dict(insp)


@router.get("/defects")
def list_defects(status: str = "open", p: Principal = Depends(require("fleet.read")), db: Session = Depends(get_db)):
    return [to_dict(d) for d in db.execute(select(SafetyDefect).where(SafetyDefect.status == status)).scalars()]


class ReleaseIn(BaseModel):
    note: str = Field(min_length=5)
    job_card_id: uuid.UUID | None = None


@router.post("/defects/{did}/release")
def release_defect(did: uuid.UUID, body: ReleaseIn, p: Principal = Depends(require("fleet.release_defect")), db: Session = Depends(get_db)):
    d = get_or_404(db, SafetyDefect, did, "Defect", lock=True)
    if d.status != "open":
        raise Conflict("released", "Already released")
    if d.reported_by == p.user_id and d.severity == "critical":
        raise Forbidden("The person who reported a critical defect cannot also release it", code="self_approval")
    d.status, d.released_by, d.release_note, d.job_card_id = "released", p.user_id, body.note, body.job_card_id
    v = db.get(Vehicle, d.vehicle_id)
    still = db.execute(select(SafetyDefect).where(SafetyDefect.vehicle_id == v.id, SafetyDefect.status == "open",
                                                  SafetyDefect.severity == "critical", SafetyDefect.id != d.id)).first()
    if not still and v.status == "maintenance":
        v.status = "available"
    write_audit(db, actor=p, action="defect.release", entity="vehicle", entity_id=v.id, after={"item": d.item}, reason=body.note)
    return to_dict(d)


# ===================================================================== fuel
class FuelIn(BaseModel):
    vehicle_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    filled_at: datetime
    odometer_km: int = Field(ge=0)
    litres: Decimal = Field(gt=0)
    rate: Decimal = Field(gt=0)
    amount: Decimal | None = Field(None, gt=0)
    station: str | None = None
    bill_number: str | None = None
    payment_mode: str = Field("cash", pattern="^(cash|card|fleet_card|credit|upi)$")
    full_tank: bool = True
    is_adblue: bool = False
    receipt_document_id: uuid.UUID | None = None
    lat: float | None = None
    lng: float | None = None


def fuel_anomalies(db: Session, v: Vehicle, f: FuelEntry) -> list[str]:
    cfg = get_config(db, "fuel.anomaly")
    flags = []
    if v.tank_litres and Decimal(f.litres) > Decimal(v.tank_litres) * (1 + Decimal(str(cfg["max_fill_over_tank_pct"])) / 100):
        flags.append(f"Litres {f.litres} exceed tank capacity {v.tank_litres}")
    prev = db.execute(select(FuelEntry).where(FuelEntry.vehicle_id == v.id, FuelEntry.is_adblue.is_(False), FuelEntry.id != f.id,
                                              FuelEntry.filled_at < f.filled_at).order_by(FuelEntry.filled_at.desc()).limit(1)).scalar_one_or_none()
    if prev and f.odometer_km < prev.odometer_km:
        flags.append(f"Odometer {f.odometer_km} lower than previous fill {prev.odometer_km}")
    if f.amount and abs(Decimal(f.amount) - money(Decimal(f.litres) * Decimal(f.rate))) > Decimal("5"):
        flags.append("Amount does not equal litres x rate")
    if f.bill_number:
        dup = db.execute(select(FuelEntry).where(FuelEntry.bill_number == f.bill_number, FuelEntry.id != f.id,
                                                 FuelEntry.station == f.station)).first()
        if dup:
            flags.append(f"Duplicate bill number {f.bill_number}")
    window = timedelta(hours=float(cfg["duplicate_window_hours"]))
    near = db.execute(select(FuelEntry).where(FuelEntry.vehicle_id == v.id, FuelEntry.id != f.id, FuelEntry.is_adblue == f.is_adblue,
                                              FuelEntry.filled_at.between(f.filled_at - window, f.filled_at + window))).first()
    if near:
        flags.append("Another fill for this vehicle within the duplicate window")
    # Mileage: full-to-full method only
    if f.full_tank and not f.is_adblue and prev and prev.full_tank and f.odometer_km > prev.odometer_km:
        km = f.odometer_km - prev.odometer_km
        kmpl = (Decimal(km) / Decimal(f.litres)).quantize(Decimal("0.01"))
        f.computed_kmpl = kmpl
        if v.baseline_kmpl and kmpl < Decimal(v.baseline_kmpl) * (1 - Decimal(str(cfg["mileage_drop_pct"])) / 100):
            flags.append(f"Mileage {kmpl} km/l below baseline {v.baseline_kmpl} by more than {cfg['mileage_drop_pct']}%")
    return flags


@router.post("/fuel")
def post_fuel(body: FuelIn, p: Principal = Depends(require_any("fleet.write", "driver.app")), db: Session = Depends(get_db)):
    from app.modules.finance.models import Expense
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    if body.trip_id:
        t = get_or_404(db, Trip, body.trip_id, "Trip")
        assert_trip_access(db, p, t, write=True)
    elif not p.can("fleet.write"):
        raise Forbidden()
    data = body.model_dump()
    data["amount"] = money(body.amount or body.litres * body.rate)
    f = FuelEntry(**data, driver_id=p.driver_id)
    db.add(f)
    db.flush()
    f.anomaly_flags = fuel_anomalies(db, v, f)
    if f.anomaly_flags:
        # Anomalies trigger human review - never automatic accusation or deduction.
        f.review_status = "needs_review"
        raise_exception_task(db, kind="alert", severity="medium", title=f"Fuel entry needs review: {v.registration}",
                             entity="fuel_entry", entity_id=f.id, source="fuel_anomaly", detail="; ".join(f.anomaly_flags),
                             owner_role="fleet_maintenance")
    if v.ownership == "own":
        exp = Expense(code=next_number(db, "EXP", "EXP"), category="fuel", expense_date=f.filled_at.date(), amount=f.amount,
                      vendor_name=f.station, bill_number=f.bill_number, trip_id=f.trip_id, vehicle_id=v.id, driver_id=p.driver_id,
                      paid_by="driver_cash" if body.payment_mode == "cash" and p.driver_id else "company",
                      payment_mode=body.payment_mode, receipt_document_id=f.receipt_document_id, submitted_by=p.user_id,
                      occurred_at=f.filled_at, source="fuel")
        db.add(exp)
        db.flush()
        f.expense_id = exp.id
    v.odometer_km = max(v.odometer_km, f.odometer_km)
    return to_dict(f)


@router.get("/fuel")
def list_fuel(vehicle_id: uuid.UUID | None = None, p: Principal = Depends(require("fleet.read")), db: Session = Depends(get_db)):
    q = select(FuelEntry).order_by(FuelEntry.filled_at.desc()).limit(500)
    if vehicle_id:
        q = q.where(FuelEntry.vehicle_id == vehicle_id)
    return [to_dict(f) for f in db.execute(q).scalars()]


class FuelReviewIn(BaseModel):
    note: str = Field(min_length=3)


@router.post("/fuel/{fid}/review")
def review_fuel(fid: uuid.UUID, body: FuelReviewIn, p: Principal = Depends(require("fleet.write")), db: Session = Depends(get_db)):
    f = get_or_404(db, FuelEntry, fid, "Fuel entry")
    f.review_status = "reviewed"
    write_audit(db, actor=p, action="fuel.review", entity="fuel_entry", entity_id=f.id, reason=body.note)
    return to_dict(f)


# ===================================================================== maintenance
class JobIn(BaseModel):
    vehicle_id: uuid.UUID
    kind: str = Field(pattern="^(preventive|breakdown|repair|accident)$")
    description: str
    vendor_id: uuid.UUID | None = None
    estimate: Decimal = Field(Decimal("0"), ge=0)
    odometer_km: int | None = None
    reason: str | None = None


@router.post("/job-cards")
def post_job(body: JobIn, p: Principal = Depends(require("fleet.write")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    j = JobCard(code=next_number(db, "JOB", "JOB"), **body.model_dump(exclude={"reason"}))
    db.add(j)
    db.flush()
    threshold = Decimal(str(get_config(db, "approval.thresholds")["repair"]))
    if body.estimate > threshold:
        request_approval(db, p, kind="repair", entity="job_card", entity_id=j.id, title=f"Repair {j.code} {v.registration}: Rs {body.estimate}",
                         required_permission="accounts.approve", amount=body.estimate, reason=body.reason or body.description)
        j.status = "pending_approval"
    else:
        j.status = "approved"
    if body.kind in ("breakdown", "accident") and v.status == "available":
        v.status = "maintenance"
    return to_dict(j)


@on_approval("repair")
def _repair_decided(db, actor, ar):
    j = db.get(JobCard, uuid.UUID(ar.entity_id))
    j.status = "approved" if ar.status == "approved" else "cancelled"


class JobCompleteIn(BaseModel):
    parts_cost: Decimal = Field(Decimal("0"), ge=0)
    labour_cost: Decimal = Field(Decimal("0"), ge=0)
    odometer_km: int | None = None
    warranty_until: date | None = None
    bill_number: str | None = None
    invoice_document_id: uuid.UUID | None = None


@router.post("/job-cards/{jid}/complete")
def complete_job(jid: uuid.UUID, body: JobCompleteIn, p: Principal = Depends(require("fleet.write")), db: Session = Depends(get_db)):
    from app.modules.finance.models import Expense
    j = get_or_404(db, JobCard, jid, "Job card", lock=True)
    if j.status not in ("approved", "in_progress"):
        raise BlockedByRule("not_approved", f"Job card is {j.status}")
    total = money(body.parts_cost + body.labour_cost)
    threshold = Decimal(str(get_config(db, "approval.thresholds")["repair"]))
    if total > max(Decimal(j.estimate) * Decimal("1.10"), threshold) and Decimal(j.estimate) > 0:
        raise BlockedByRule("over_estimate", f"Actual Rs {total} exceeds approved estimate Rs {j.estimate} by >10% - re-approval needed")
    j.parts_cost, j.labour_cost, j.status, j.completed_at = body.parts_cost, body.labour_cost, "completed", utcnow()
    j.warranty_until = body.warranty_until
    iv = get_config(db, "maintenance.intervals")
    v = db.get(Vehicle, j.vehicle_id)
    odo = body.odometer_km or v.odometer_km
    if j.kind == "preventive":
        j.next_due_km, j.next_due_date = odo + int(iv["service_km"]), date.today() + timedelta(days=int(iv["service_days"]))
    exp = Expense(code=next_number(db, "EXP", "EXP"), category="repair", expense_date=date.today(), amount=total, vendor_id=j.vendor_id,
                  bill_number=body.bill_number, vehicle_id=v.id, status="submitted", submitted_by=p.user_id,
                  receipt_document_id=body.invoice_document_id, source="job_card")
    db.add(exp)
    db.flush()
    j.expense_id = exp.id
    return to_dict(j)


@router.get("/job-cards")
def list_jobs(p: Principal = Depends(require("fleet.read")), db: Session = Depends(get_db)):
    return [to_dict(j) for j in db.execute(select(JobCard).order_by(JobCard.opened_at.desc())).scalars()]


@router.get("/maintenance/due")
def maintenance_due(p: Principal = Depends(require("fleet.read")), db: Session = Depends(get_db)):
    iv = get_config(db, "maintenance.intervals")
    out = []
    for v in db.execute(select(Vehicle).where(Vehicle.ownership == "own", Vehicle.is_active.is_(True))).scalars():
        last = db.execute(select(JobCard).where(JobCard.vehicle_id == v.id, JobCard.kind == "preventive", JobCard.status == "completed")
                          .order_by(JobCard.completed_at.desc())).scalars().first()
        due_km = last.next_due_km if last and last.next_due_km else None
        due_date = last.next_due_date if last else None
        out.append({"vehicle": v.registration, "odometer": v.odometer_km, "due_km": due_km, "due_date": due_date,
                    "overdue": bool((due_km and v.odometer_km >= due_km) or (due_date and due_date <= date.today())),
                    "note": None if last else f"No preventive service recorded - schedule (every {iv['service_km']} km / {iv['service_days']} days)"})
    return out


# ===================================================================== tyres
class TyreEventIn(BaseModel):
    event: str = Field(pattern="^(fit|remove|rotate|retread|repair|inspect|scrap)$")
    vehicle_id: uuid.UUID | None = None
    position: str | None = None
    odometer_km: int | None = None
    tread_mm: Decimal | None = None
    cost: Decimal = Decimal("0")
    note: str | None = None


@router.post("/tyres/{tid}/events")
def tyre_event(tid: uuid.UUID, body: TyreEventIn, p: Principal = Depends(require("fleet.write")), db: Session = Depends(get_db)):
    t = get_or_404(db, Tyre, tid, "Tyre", lock=True)
    if body.event == "fit":
        if t.status == "fitted":
            raise Conflict("fitted", "Tyre already fitted")
        if not (body.vehicle_id and body.position and body.odometer_km is not None):
            raise AppError("fields", "vehicle, position and odometer required")
        occupied = db.execute(select(Tyre).where(Tyre.vehicle_id == body.vehicle_id, Tyre.position == body.position, Tyre.status == "fitted")).first()
        if occupied:
            raise Conflict("position_taken", "Another tyre is fitted at this position")
        t.vehicle_id, t.position, t.fitted_odometer, t.status = body.vehicle_id, body.position, body.odometer_km, "fitted"
    elif body.event in ("remove", "rotate", "scrap", "retread"):
        if t.status == "fitted" and body.odometer_km is not None and t.fitted_odometer is not None:
            t.km_run += max(0, body.odometer_km - t.fitted_odometer)
        if body.event == "rotate":
            t.position, t.fitted_odometer = body.position, body.odometer_km
        else:
            t.vehicle_id, t.position, t.fitted_odometer = None, None, None
            t.status = {"remove": "in_stock", "scrap": "scrapped", "retread": "retread"}[body.event]
            if body.event == "retread":
                t.retread_count += 1
    if body.tread_mm is not None:
        t.tread_mm = body.tread_mm
    db.add(TyreEvent(tyre_id=t.id, **body.model_dump()))
    cost_total = Decimal(t.cost) + (db.execute(select(func.coalesce(func.sum(TyreEvent.cost), 0)).where(TyreEvent.tyre_id == t.id)).scalar() or 0)
    out = to_dict(t)
    out["cost_per_km"] = str((cost_total / t.km_run).quantize(Decimal("0.01"))) if t.km_run else None
    return out


# ===================================================================== drivers: remuneration, advances, grievances
class RuleIn(BaseModel):
    driver_id: uuid.UUID
    component: str = Field(pattern="^(fixed_monthly|per_trip|per_km|duty_day|night|waiting_hour|incentive_on_time)$")
    rate: Decimal = Field(ge=0)
    conditions: dict | None = None
    effective_from: date
    reason: str = Field(min_length=3)


@router.post("/remuneration-rules")
def propose_rule(body: RuleIn, p: Principal = Depends(require("remuneration.write")), db: Session = Depends(get_db)):
    if body.effective_from < date.today() and "owner_director" not in p.roles:
        raise BlockedByRule("retrospective", "Remuneration changes are prospective; back-dated corrections need Owner/Director")
    r = RemunerationRule(**body.model_dump(), status="pending", proposed_by=p.user_id,
                         version=new_rule_version(db, body.driver_id, body.component))
    db.add(r)
    db.flush()
    request_approval(db, p, kind="remuneration_rule", entity="remuneration_rule", entity_id=r.id,
                     title=f"Driver pay rule {body.component} = Rs {body.rate} from {body.effective_from}",
                     required_permission="remuneration.approve", payload=body.model_dump(mode="json"), reason=body.reason)
    return to_dict(r)


@on_approval("remuneration_rule")
def _rule_decided(db, actor, ar):
    r = db.get(RemunerationRule, uuid.UUID(ar.entity_id))
    if ar.status != "approved":
        r.status = "rejected"
        return
    for old in db.execute(select(RemunerationRule).where(RemunerationRule.driver_id == r.driver_id, RemunerationRule.component == r.component,
                                                         RemunerationRule.status == "active", RemunerationRule.id != r.id)).scalars():
        old.status = "superseded"
        old.effective_to = r.effective_from - timedelta(days=1)
    r.status, r.approved_by = "active", actor.user_id


@router.get("/drivers/{did}/remuneration")
def driver_rules(did: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if not (p.can("driver.read") or p.driver_id == did):
        raise Forbidden()
    rules = [to_dict(r) for r in db.execute(select(RemunerationRule).where(RemunerationRule.driver_id == did)
                                            .order_by(RemunerationRule.component, RemunerationRule.version)).scalars()]
    earnings = [to_dict(e) for e in db.execute(select(DriverEarning).where(DriverEarning.driver_id == did).order_by(DriverEarning.created_at.desc())).scalars()]
    advances = [to_dict(a) for a in db.execute(select(DriverAdvance).where(DriverAdvance.driver_id == did)).scalars()]
    summary = {
        "earned": str(sum((Decimal(e["gross"]) for e in earnings if e["status"] in ("approved", "paid")), Decimal("0"))),
        "pending_approval": str(sum((Decimal(e["gross"]) for e in earnings if e["status"] in ("calculated", "pending_approval")), Decimal("0"))),
        "paid": str(sum((Decimal(e["net"]) for e in earnings if e["status"] == "paid"), Decimal("0"))),
        "advances_outstanding": str(sum((Decimal(a["amount"]) for a in advances if a["status"] == "paid"), Decimal("0"))),
    }
    return {"rules": rules, "earnings": earnings, "advances": advances, "summary": summary}


class EarningDecisionIn(BaseModel):
    reason: str = "Trip settlement readiness verified"


@router.post("/driver-earnings/{eid}/submit")
def submit_earning(eid: uuid.UUID, body: EarningDecisionIn, p: Principal = Depends(require("settlement.prepare")), db: Session = Depends(get_db)):
    from app.modules.operations.models import ProofOfDelivery, TripLoad
    e = get_or_404(db, DriverEarning, eid, "Earning")
    if e.status != "calculated":
        raise Conflict("bad_status", f"Earning is {e.status}")
    if e.trip_id:
        t = db.get(Trip, e.trip_id)
        if t.status != "closed":
            raise BlockedByRule("trip_open", "Trip must be closed (POD verified, expenses reviewed) before settlement")
    request_approval(db, p, kind="driver_earning", entity="driver_earning", entity_id=e.id, title=f"Driver earning Rs {e.gross}",
                     required_permission="settlement.approve", amount=e.gross, reason=body.reason)
    e.status = "pending_approval"
    return to_dict(e)


@on_approval("driver_earning")
def _earning_decided(db, actor, ar):
    e = db.get(DriverEarning, uuid.UUID(ar.entity_id))
    e.status = "approved" if ar.status == "approved" else "calculated"


class AdvanceIn(BaseModel):
    driver_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    purpose: str


@router.post("/driver-advances")
def request_advance(body: AdvanceIn, p: Principal = Depends(require_any("settlement.prepare", "driver.app")), db: Session = Depends(get_db)):
    if p.driver_id and not p.can("settlement.prepare") and body.driver_id != p.driver_id:
        raise Forbidden()
    a = DriverAdvance(**body.model_dump())
    db.add(a)
    db.flush()
    request_approval(db, p, kind="driver_advance", entity="driver_advance", entity_id=a.id, title=f"Driver advance Rs {body.amount}: {body.purpose}",
                     required_permission="settlement.approve", amount=body.amount, reason=body.purpose)
    return to_dict(a)


@on_approval("driver_advance")
def _adv_decided(db, actor, ar):
    a = db.get(DriverAdvance, uuid.UUID(ar.entity_id))
    a.status = "paid" if ar.status == "approved" else "rejected"
    if ar.status == "approved":
        a.paid_at = utcnow()


class GrievanceIn(BaseModel):
    topic: str = Field(pattern="^(attendance|fuel|expense|damage|remuneration|safety|other)$")
    entity: str | None = None
    entity_id: str | None = None
    description: str = Field(min_length=5)


@router.post("/grievances")
def raise_grievance(body: GrievanceIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = Grievance(code=next_number(db, "GRV", "GRV"), raised_by_user=p.user_id, driver_id=p.driver_id, **body.model_dump())
    db.add(g)
    db.flush()
    if body.topic == "remuneration" and body.entity == "driver_earning" and body.entity_id:
        e = db.get(DriverEarning, uuid.UUID(body.entity_id))
        if e and (e.driver_id == p.driver_id or p.can("hr.write")):
            e.status = "disputed"
    raise_exception_task(db, kind="followup", severity="medium", title=f"Grievance {g.code} ({body.topic})", entity="grievance",
                         entity_id=g.id, source="grievance", owner_role="hr")
    return to_dict(g)


@router.get("/grievances")
def list_grievances(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(Grievance).order_by(Grievance.created_at.desc())
    if not p.can("hr.read"):
        q = q.where(Grievance.raised_by_user == p.user_id)
    return [to_dict(g) for g in db.execute(q).scalars()]


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=5)


@router.post("/grievances/{gid}/resolve")
def resolve_grievance(gid: uuid.UUID, body: ResolveIn, p: Principal = Depends(require("hr.write")), db: Session = Depends(get_db)):
    g = get_or_404(db, Grievance, gid, "Grievance")
    if g.raised_by_user == p.user_id:
        raise Forbidden("You cannot resolve your own grievance", code="self_approval")
    g.status, g.resolution, g.resolved_by = "resolved", body.resolution, p.user_id
    write_audit(db, actor=p, action="grievance.resolve", entity="grievance", entity_id=g.id, reason=body.resolution)
    return to_dict(g)
