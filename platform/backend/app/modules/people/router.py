"""HR (employees, attendance, leave), payroll (configurable statutory), SOP library, checklists, governance."""
from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.crud import get_or_404, to_dict
from app.core.db import money, utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, Conflict, Forbidden
from app.core.services import get_config, next_number, on_approval, raise_exception_task, request_approval
from app.modules.finance.posting import post_voucher
from app.modules.people.models import (
    Attendance, ChecklistRun, ChecklistTemplate, Employee, LeaveRequest, PayrollRun, Payslip, Sop, SopAck,
)

router = APIRouter(prefix="/api/v1", tags=["people"])

SALARY_FIELDS = {"monthly_salary", "salary_components"}


def emp_out(e: Employee, p: Principal) -> dict:
    d = to_dict(e)
    if not p.can("hr.view_salary"):
        for k in SALARY_FIELDS:
            d[k] = "*** restricted ***"
    return d


class EmployeeIn(BaseModel):
    name: str
    department: str = Field(pattern="^(office|operations|accounts|drivers|store|sales|management)$")
    designation: str | None = None
    employment_type: str = Field("permanent", pattern="^(permanent|temporary|contract)$")
    phone: str | None = None
    email: str | None = None
    joined_on: date | None = None
    emergency_contact: dict | None = None
    monthly_salary: Decimal = Field(Decimal("0"), ge=0)
    salary_components: dict | None = None
    statutory: dict | None = None
    is_driver: bool = False
    backup_employee_id: uuid.UUID | None = None


@router.post("/employees")
def add_employee(body: EmployeeIn, p: Principal = Depends(require("hr.write")), db: Session = Depends(get_db)):
    if body.monthly_salary and not p.can("hr.view_salary"):
        raise Forbidden("Salary details require hr.view_salary")
    e = Employee(code=next_number(db, "EMP", "EMP", fy_bound=False), **body.model_dump())
    db.add(e)
    db.flush()
    write_audit(db, actor=p, action="employee.create", entity="employee", entity_id=e.id, after={"name": e.name})
    return emp_out(e, p)


@router.get("/employees")
def list_employees(p: Principal = Depends(require("hr.read")), db: Session = Depends(get_db)):
    return [emp_out(e, p) for e in db.execute(select(Employee).order_by(Employee.name)).scalars()]


class SalaryChangeIn(BaseModel):
    monthly_salary: Decimal = Field(ge=0)
    salary_components: dict | None = None
    effective_from: date
    reason: str = Field(min_length=3)


@router.post("/employees/{eid}/salary-change")
def salary_change(eid: uuid.UUID, body: SalaryChangeIn, p: Principal = Depends(require("hr.view_salary")), db: Session = Depends(get_db)):
    e = get_or_404(db, Employee, eid, "Employee")
    ar = request_approval(db, p, kind="salary_change", entity="employee", entity_id=e.id, title=f"Salary change {e.name}: Rs {body.monthly_salary}",
                          required_permission="payroll.approve", amount=body.monthly_salary, payload=body.model_dump(mode="json"), reason=body.reason)
    return {"approval": ar.code}


@on_approval("salary_change")
def _salary_ok(db, actor, ar):
    if ar.status == "approved":
        e = db.get(Employee, uuid.UUID(ar.entity_id))
        before = str(e.monthly_salary)
        e.monthly_salary = Decimal(str(ar.payload["monthly_salary"]))
        e.salary_components = ar.payload.get("salary_components") or e.salary_components
        write_audit(db, actor=actor, action="employee.salary", entity="employee", entity_id=e.id, before={"salary": before},
                    after={"salary": str(e.monthly_salary), "effective_from": ar.payload["effective_from"]})


class ExitIn(BaseModel):
    exited_on: date
    reason: str


@router.post("/employees/{eid}/exit")
def employee_exit(eid: uuid.UUID, body: ExitIn, p: Principal = Depends(require("hr.write")), db: Session = Depends(get_db)):
    """Exit revokes system access immediately and creates handover tasks."""
    from app.modules.platform.models import Session as UserSession
    from app.modules.platform.models import User
    e = get_or_404(db, Employee, eid, "Employee")
    e.exited_on, e.status = body.exited_on, "exited"
    for u in db.execute(select(User).where(User.employee_id == e.id)).scalars():
        u.is_active = False
        for s in db.execute(select(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))).scalars():
            s.revoked_at = utcnow()
    raise_exception_task(db, kind="followup", severity="medium", title=f"Handover open tasks of {e.name}", entity="employee",
                         entity_id=e.id, source="exit", owner_role="hr")
    write_audit(db, actor=p, action="employee.exit", entity="employee", entity_id=e.id, reason=body.reason)
    return emp_out(e, p)


class AttendanceIn(BaseModel):
    employee_id: uuid.UUID
    day: date
    status: str = Field(pattern="^(present|absent|half_day|leave|field_duty|holiday)$")
    in_at: datetime | None = None
    out_at: datetime | None = None
    overtime_hours: Decimal = Decimal("0")
    correction_reason: str | None = None


@router.post("/attendance")
def mark_attendance(body: AttendanceIn, p: Principal = Depends(require("hr.write")), db: Session = Depends(get_db)):
    a = db.execute(select(Attendance).where(Attendance.employee_id == body.employee_id, Attendance.day == body.day)).scalar_one_or_none()
    if a:
        if not body.correction_reason:
            raise AppError("reason_required", "Corrections need a reason")
        before = to_dict(a)
        for k, v in body.model_dump().items():
            setattr(a, k, v)
        a.corrected_by = p.user_id
        write_audit(db, actor=p, action="attendance.correct", entity="attendance", entity_id=a.id, before=before, reason=body.correction_reason)
    else:
        a = Attendance(**body.model_dump())
        db.add(a)
    db.flush()
    return to_dict(a)


class LeaveIn(BaseModel):
    employee_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    from_date: date
    to_date: date
    kind: str = "casual"
    reason: str | None = None


@router.post("/leave")
def apply_leave(body: LeaveIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if body.to_date < body.from_date:
        raise AppError("dates", "End before start")
    if not p.can("hr.write"):
        if p.driver_id:
            body.driver_id, body.employee_id = p.driver_id, None
        else:
            raise Forbidden()
    lr = LeaveRequest(**body.model_dump())
    db.add(lr)
    db.flush()
    return to_dict(lr)


class LeaveDecision(BaseModel):
    approve: bool


@router.post("/leave/{lid}/decide")
def decide_leave(lid: uuid.UUID, body: LeaveDecision, p: Principal = Depends(require("hr.write")), db: Session = Depends(get_db)):
    lr = get_or_404(db, LeaveRequest, lid, "Leave")
    lr.status, lr.decided_by = ("approved" if body.approve else "rejected"), p.user_id
    if body.approve and lr.driver_id:
        from app.modules.fleet.models import Driver
        d = db.get(Driver, lr.driver_id)
        if lr.from_date <= date.today() <= lr.to_date:
            d.status = "leave"
    return to_dict(lr)


@router.get("/leave")
def list_leave(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(LeaveRequest).order_by(LeaveRequest.created_at.desc())
    if not p.can("hr.read"):
        q = q.where(LeaveRequest.driver_id == p.driver_id)
    return [to_dict(x) for x in db.execute(q).scalars()]


# ===================================================================== payroll
def statutory_rules(db: Session) -> dict:
    """Configurable placeholders; MUST be verified with a professional before use (see ASSUMPTIONS.md)."""
    return get_config(db, "payroll.statutory") or {
        "pf_employee_pct": 12.0, "pf_wage_ceiling": 15000, "esi_employee_pct": 0.75, "esi_wage_limit": 21000,
        "pt_monthly": 0, "_note": "Verify current PF/ESI/PT rules with your CA/consultant",
    }


@router.post("/payroll/{period}/prepare")
def prepare_payroll(period: str, p: Principal = Depends(require("payroll.prepare")), db: Session = Depends(get_db)):
    y, m = map(int, period.split("-"))
    days_in = monthrange(y, m)[1]
    run = db.execute(select(PayrollRun).where(PayrollRun.period == period)).scalar_one_or_none()
    if run and run.status not in ("draft",):
        raise Conflict("locked", f"Payroll {period} is {run.status}")
    if not run:
        run = PayrollRun(period=period, prepared_by=p.user_id)
        db.add(run)
        db.flush()
    for s in db.execute(select(Payslip).where(Payslip.run_id == run.id)).scalars():
        db.delete(s)
    rules = statutory_rules(db)
    tot = {"gross": Decimal("0"), "net": Decimal("0"), "pf": Decimal("0"), "esi": Decimal("0"), "pt": Decimal("0")}
    for e in db.execute(select(Employee).where(Employee.status == "active")).scalars():
        if not e.monthly_salary:
            continue  # trip-paid drivers handled by driver remuneration to avoid double calculation
        absent = db.execute(select(func.count()).select_from(Attendance).where(
            Attendance.employee_id == e.id, Attendance.status == "absent",
            Attendance.day.between(date(y, m, 1), date(y, m, days_in)))).scalar()
        half = db.execute(select(func.count()).select_from(Attendance).where(
            Attendance.employee_id == e.id, Attendance.status == "half_day",
            Attendance.day.between(date(y, m, 1), date(y, m, days_in)))).scalar()
        payable = Decimal(days_in) - Decimal(absent) - Decimal(half) / 2
        gross = money(Decimal(e.monthly_salary) * payable / days_in)
        st = e.statutory or {}
        pf = money(min(gross, Decimal(str(rules["pf_wage_ceiling"]))) * Decimal(str(rules["pf_employee_pct"])) / 100) if st.get("pf") else Decimal("0")
        esi = money(gross * Decimal(str(rules["esi_employee_pct"])) / 100) if st.get("esi") and gross <= Decimal(str(rules["esi_wage_limit"])) else Decimal("0")
        pt = money(rules["pt_monthly"]) if st.get("pt") else Decimal("0")
        net = gross - pf - esi - pt
        db.add(Payslip(run_id=run.id, employee_id=e.id, days_payable=payable, earnings={"basic_prorated": str(gross)},
                       deductions={"pf": str(pf), "esi": str(esi), "pt": str(pt)}, gross=gross, net=net))
        for k, v in (("gross", gross), ("net", net), ("pf", pf), ("esi", esi), ("pt", pt)):
            tot[k] += v
    run.totals = {k: str(v) for k, v in tot.items()}
    run.rules_snapshot = rules
    db.flush()
    return to_dict(run)


@router.post("/payroll/{period}/submit")
def submit_payroll(period: str, p: Principal = Depends(require("payroll.prepare")), db: Session = Depends(get_db)):
    run = db.execute(select(PayrollRun).where(PayrollRun.period == period)).scalar_one_or_none()
    if not run or run.status != "draft":
        raise Conflict("bad_status", "Prepare payroll first")
    request_approval(db, p, kind="payroll", entity="payroll_run", entity_id=run.id, title=f"Payroll {period}: net Rs {run.totals.get('net')}",
                     required_permission="payroll.approve", amount=Decimal(run.totals.get("gross", "0")))
    run.status = "pending_approval"
    return to_dict(run)


@on_approval("payroll")
def _payroll_ok(db, actor, ar):
    run = db.get(PayrollRun, uuid.UUID(ar.entity_id))
    if ar.status != "approved":
        run.status = "draft"
        return
    run.status, run.approved_by = "approved", actor.user_id
    t = {k: Decimal(v) for k, v in run.totals.items()}
    stat = t["pf"] + t["esi"] + t["pt"]
    lines = [{"account": "5200", "debit": t["gross"]}, {"account": "2030", "credit": t["net"]}]
    if stat:
        lines.append({"account": "2120", "credit": stat})
    if t["gross"]:
        post_voucher(db, actor, vtype="journal", vdate=date.today(), narration=f"Payroll {run.period}", lines=lines,
                     source_entity="payroll", source_id=run.id, approved_by=actor.user_id)


@router.get("/payroll/{period}")
def get_payroll(period: str, p: Principal = Depends(require_any("payroll.prepare", "payroll.approve")), db: Session = Depends(get_db)):
    run = db.execute(select(PayrollRun).where(PayrollRun.period == period)).scalar_one_or_none()
    if not run:
        return None
    slips = [to_dict(s) for s in db.execute(select(Payslip).where(Payslip.run_id == run.id)).scalars()]
    return {**to_dict(run), "payslips": slips}


# ===================================================================== SOP & checklists
class SopIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z0-9-]{3,30}$")
    title: str
    department: str
    purpose: str | None = None
    scope: str | None = None
    owner_role: str | None = None
    approver_role: str | None = None
    steps: list[str] = []
    required_documents: list[str] = []
    escalation: str | None = None
    effective_from: date | None = None
    change_note: str | None = None


@router.post("/sops")
def draft_sop(body: SopIn, p: Principal = Depends(require("sop.write")), db: Session = Depends(get_db)):
    latest = db.execute(select(func.max(Sop.version)).where(Sop.code == body.code)).scalar() or 0
    s = Sop(**body.model_dump(), version=latest + 1)
    db.add(s)
    db.flush()
    return to_dict(s)


@router.post("/sops/{sid}/approve")
def approve_sop(sid: uuid.UUID, p: Principal = Depends(require("sop.approve")), db: Session = Depends(get_db)):
    s = get_or_404(db, Sop, sid, "SOP")
    if s.status != "draft":
        raise Conflict("bad_status", f"SOP is {s.status}")
    for old in db.execute(select(Sop).where(Sop.code == s.code, Sop.status == "approved")).scalars():
        old.status = "superseded"
    s.status, s.approved_by = "approved", p.user_id
    s.effective_from = s.effective_from or date.today()
    write_audit(db, actor=p, action="sop.approve", entity="sop", entity_id=s.id, after={"code": s.code, "version": s.version})
    return to_dict(s)


@router.get("/sops")
def list_sops(p: Principal = Depends(require("sop.read")), db: Session = Depends(get_db)):
    out = []
    for s in db.execute(select(Sop).order_by(Sop.code, Sop.version.desc())).scalars():
        d = to_dict(s)
        d["acknowledged"] = bool(db.execute(select(SopAck).where(SopAck.sop_id == s.id, SopAck.user_id == p.user_id)).first())
        out.append(d)
    return out


@router.post("/sops/{sid}/acknowledge")
def ack_sop(sid: uuid.UUID, p: Principal = Depends(require("sop.read")), db: Session = Depends(get_db)):
    s = get_or_404(db, Sop, sid, "SOP")
    if s.status != "approved":
        raise AppError("not_approved", "Only approved SOPs can be acknowledged")
    if not db.execute(select(SopAck).where(SopAck.sop_id == s.id, SopAck.user_id == p.user_id)).first():
        db.add(SopAck(sop_id=s.id, user_id=p.user_id))
    return {"ok": True}


def period_key(freq: str, d: date) -> str:
    if freq == "daily":
        return d.isoformat()
    if freq == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return d.strftime("%Y-%m")


@router.get("/checklists/today")
def checklists_today(p: Principal = Depends(require("sop.read")), db: Session = Depends(get_db)):
    today = date.today()
    out = []
    for t in db.execute(select(ChecklistTemplate)).scalars():
        key = period_key(t.frequency, today)
        run = db.execute(select(ChecklistRun).where(ChecklistRun.template_id == t.id, ChecklistRun.period_key == key)).scalar_one_or_none()
        mine = t.owner_role in p.roles or t.backup_role in p.roles or "owner_director" in p.roles
        out.append({**to_dict(t), "period_key": key, "status": run.status if run else "open", "results": run.results if run else {}, "mine": mine})
    return out


class ChecklistDoneIn(BaseModel):
    results: dict[str, bool | str]


@router.post("/checklists/{tid}/complete")
def complete_checklist(tid: uuid.UUID, body: ChecklistDoneIn, p: Principal = Depends(require("sop.read")), db: Session = Depends(get_db)):
    t = get_or_404(db, ChecklistTemplate, tid, "Checklist")
    if not ({t.owner_role, t.backup_role} & p.roles or "owner_director" in p.roles):
        raise Forbidden("Only the checklist owner or backup can complete it")
    missing = [i for i in t.items if i not in body.results]
    if missing:
        raise AppError("incomplete", f"Items not answered: {missing}")
    key = period_key(t.frequency, date.today())
    run = db.execute(select(ChecklistRun).where(ChecklistRun.template_id == t.id, ChecklistRun.period_key == key)).scalar_one_or_none()
    if not run:
        run = ChecklistRun(template_id=t.id, period_key=key)
        db.add(run)
    run.results, run.completed_by, run.completed_at, run.status = body.results, p.user_id, utcnow(), "completed"
    fails = [k for k, v in body.results.items() if v is False]
    if fails:
        raise_exception_task(db, severity="medium", title=f"Checklist {t.title}: {len(fails)} item(s) not OK", entity="checklist",
                             entity_id=t.id, source="checklist", detail=", ".join(fails), owner_role=t.owner_role)
    db.flush()
    return to_dict(run)
