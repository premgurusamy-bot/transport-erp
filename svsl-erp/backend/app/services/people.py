"""Payroll, statutory compliance calendar, and the alert scanner."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log
from ..core.deps import AppError
from ..core.money import D, ZERO, r2, r0
from ..core.numbering import fy_bounds
from ..models import (
    Attendance, ComplianceRule, ComplianceTask, Consignment, Customer, Document, Driver, DriverAdvance, Employee,
    Invoice, LeaveRequest, PayrollRun, Payslip, RateContract, SalaryAdvance, Trip, Vehicle,
)
from . import accounting as acc
from . import notify
from . import settings as app_settings

PAID_STATUSES = {"Present": 1, "On Trip": 1, "Week Off": 1, "Holiday": 1, "Leave": 1, "Half Day": Decimal("0.5"), "Absent": 0}


def _paid_days(db: Session, person_type: str, person_id: int, start: date, end: date) -> tuple[Decimal, bool]:
    rows = db.query(Attendance).filter(Attendance.person_type == person_type, Attendance.person_id == person_id, Attendance.att_date.between(start, end)).all()
    if not rows:
        return Decimal((end - start).days + 1), False
    marked = {r.att_date: r.status for r in rows}
    days = ZERO
    d = start
    while d <= end:
        st = marked.get(d)
        if st is None:
            days += 1 if d.weekday() == 6 else 0  # unmarked Sunday counts as weekly off
        elif st == "Leave":
            paid = db.query(LeaveRequest).filter(LeaveRequest.person_type == person_type, LeaveRequest.person_id == person_id, LeaveRequest.status == "Approved", LeaveRequest.from_date <= d, LeaveRequest.to_date >= d).first()
            days += 1 if paid else 0
        else:
            days += D(PAID_STATUSES.get(st, 0))
        d += timedelta(days=1)
    return days, True


def professional_tax(cfg: dict, monthly_gross: Decimal) -> Decimal:
    half_year = monthly_gross * 6
    for slab in cfg["pt_half_yearly_slabs"]:
        if slab["upto"] is None or half_year <= D(slab["upto"]):
            return r0(D(slab["tax"]) / 6)
    return ZERO


def compute_payroll(db: Session, user, month: str) -> PayrollRun:
    try:
        y, m = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        raise AppError("Month must be YYYY-MM")
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    run = db.query(PayrollRun).filter_by(month=month).first()
    if run and run.status == "Posted":
        raise AppError(f"Payroll for {month} is already posted")
    cfg = app_settings.get(db, "payroll")
    if not run:
        run = PayrollRun(month=month, status="Draft", created_by=user.id)
        db.add(run)
        db.flush()
    db.query(Payslip).filter_by(run_id=run.id).delete()
    dim = Decimal((end - start).days + 1)
    people = []
    for e in db.query(Employee).filter(Employee.is_active.is_(True), Employee.joining_date <= end):
        if e.last_working_day and e.last_working_day < start:
            continue
        people.append(("employee", e.id, e.name, D(e.basic), D(e.hra), D(e.other_allowances), e.pf_applicable, e.esi_applicable, e.pt_applicable, D(e.monthly_tds)))
    for d in db.query(Driver).filter(Driver.is_active.is_(True), Driver.monthly_salary > 0, Driver.employment_status.in_(["Active", "On Leave"])):
        if d.joining_date and d.joining_date > end:
            continue
        people.append(("driver", d.id, d.name, D(d.monthly_salary), ZERO, ZERO, d.pf_applicable, d.esi_applicable, True, ZERO))
    totals = {k: ZERO for k in ("gross", "ded", "net", "pf_er", "esi_er")}
    for ptype, pid, name, basic, hra, other, pf_app, esi_app, pt_app, tds in people:
        paid, marked = _paid_days(db, ptype, pid, start, end)
        paid = min(paid, dim)
        f = paid / dim
        b, h, o = r2(basic * f), r2(hra * f), r2(other * f)
        gross = b + h + o
        pf_wage = min(b, D(cfg["pf_wage_ceiling"])) if pf_app else ZERO
        pf_emp = r0(pf_wage * D(cfg["pf_employee_pct"]) / 100)
        pf_er = r0(pf_wage * D(cfg["pf_employer_pct"]) / 100)
        esi_ok = esi_app and (basic + hra + other) <= D(cfg["esi_gross_ceiling"])
        esi_emp = (gross * D(cfg["esi_employee_pct"]) / 100).quantize(Decimal("1"), rounding=ROUND_CEILING) if esi_ok else ZERO
        esi_er = (gross * D(cfg["esi_employer_pct"]) / 100).quantize(Decimal("1"), rounding=ROUND_CEILING) if esi_ok else ZERO
        pt = professional_tax(cfg, gross) if pt_app else ZERO
        adv = ZERO
        adv_detail = []
        if ptype == "employee":
            for a in db.query(SalaryAdvance).filter(SalaryAdvance.employee_id == pid, SalaryAdvance.advance_date <= end):
                left = D(a.amount) - D(a.recovered)
                if left > 0:
                    take = min(left, D(a.monthly_recovery))
                    adv += take
                    adv_detail.append({"advance_id": a.id, "amount": str(take)})
        else:
            for a in db.query(DriverAdvance).filter(DriverAdvance.driver_id == pid, DriverAdvance.purpose == "Salary Advance", DriverAdvance.settlement_id.is_(None), DriverAdvance.advance_date <= end):
                adv += D(a.amount)
                adv_detail.append({"driver_advance_id": a.id, "amount": str(a.amount)})
        deductions = pf_emp + esi_emp + pt + tds
        adv = min(adv, max(ZERO, gross - deductions))
        net = gross - deductions - adv
        db.add(Payslip(run_id=run.id, person_type=ptype, person_id=pid, name=name, days_in_month=dim, paid_days=paid, basic=b, hra=h, allowances=o, gross=gross,
                       pf_employee=pf_emp, esi_employee=esi_emp, professional_tax=pt, tds=tds, advance_recovery=adv, net_pay=net, pf_employer=pf_er, esi_employer=esi_er,
                       details={"attendance_marked": marked, "advances": adv_detail}))
        totals["gross"] += gross
        totals["ded"] += deductions + adv
        totals["net"] += net
        totals["pf_er"] += pf_er
        totals["esi_er"] += esi_er
    run.total_gross, run.total_deductions, run.total_net, run.employer_pf, run.employer_esi = (r2(totals[k]) for k in ("gross", "ded", "net", "pf_er", "esi_er"))
    run.config_snapshot = jsonable(cfg)
    db.flush()
    return run


def post_payroll(db: Session, user, run_id: int) -> PayrollRun:
    run = db.get(PayrollRun, run_id)
    if not run or run.status != "Draft":
        raise AppError("Only a draft payroll can be posted")
    slips = db.query(Payslip).filter_by(run_id=run.id).all()
    if not slips:
        raise AppError("Payroll has no payslips")
    y, m = int(run.month[:4]), int(run.month[5:7])
    on = date(y, m, calendar.monthrange(y, m)[1])
    s = lambda attr: r2(sum((D(getattr(p, attr)) for p in slips), ZERO))  # noqa: E731
    lines = [
        {"ledger_id": acc.sys_ledger(db, "SALARY_EXP"), "debit": s("gross")},
        {"ledger_id": acc.sys_ledger(db, "PF_EMPLOYER_EXP"), "debit": s("pf_employer")},
        {"ledger_id": acc.sys_ledger(db, "ESI_EMPLOYER_EXP"), "debit": s("esi_employer")},
        {"ledger_id": acc.sys_ledger(db, "PF_PAYABLE"), "credit": s("pf_employee") + s("pf_employer")},
        {"ledger_id": acc.sys_ledger(db, "ESI_PAYABLE"), "credit": s("esi_employee") + s("esi_employer")},
        {"ledger_id": acc.sys_ledger(db, "PT_PAYABLE"), "credit": s("professional_tax")},
        {"ledger_id": acc.sys_ledger(db, "TDS_PAYABLE"), "credit": s("tds")},
        {"ledger_id": acc.sys_ledger(db, "SALARY_PAYABLE"), "credit": s("net_pay")},
    ]
    emp_adv = ZERO
    for p in slips:
        for a in (p.details or {}).get("advances", []):
            amt = D(a["amount"])
            if "advance_id" in a:
                adv = db.get(SalaryAdvance, a["advance_id"])
                adv.recovered = r2(D(adv.recovered) + amt)
                emp_adv += amt
            else:
                da = db.get(DriverAdvance, a["driver_advance_id"])
                d = db.get(Driver, da.driver_id)
                lines.append({"ledger_id": acc.party_ledger(db, "driver", d.id, d.name), "credit": amt})
                da.settlement_id = -run.id  # recovered through payroll
    if emp_adv:
        lines.append({"ledger_id": acc.sys_ledger(db, "EMPLOYEE_ADVANCES"), "credit": emp_adv})
    v = acc.post(db, user, "Journal", on, lines, f"Payroll {run.month}", "payroll", run.id)
    run.voucher_id, run.status = v.id, "Posted"
    log(db, user, "post", "payroll_runs", run.id, None, {"month": run.month, "net": str(run.total_net)})
    return run


# ------------------------------------------------------------------ compliance

def _due(year: int, month: int, offset: int, day: int) -> date:
    m = month + offset
    y = year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def generate_compliance(db: Session, fy: str, include_past: bool = False) -> int:
    """Create due-date tasks for the FY. Past due dates are skipped unless include_past (avoids a flood of
    'overdue' items for periods before the ERP was in use)."""
    start, end = fy_bounds(fy)
    created = 0
    for rule in db.query(ComplianceRule).filter_by(is_active=True, applicable=True):
        periods: list[tuple[str, date]] = []
        if rule.frequency == "Monthly":
            d = start
            while d <= end:
                periods.append((f"{d:%Y-%m}", _due(d.year, d.month, rule.due_month_offset or 0, rule.due_day)))
                d = _due(d.year, d.month, 1, 1)
        elif rule.frequency == "Quarterly":
            for q in range(4):
                qe = _due(start.year, start.month, q * 3 + 2, 1)
                periods.append((f"{fy}-Q{q + 1}", _due(qe.year, qe.month, rule.due_month_offset or 0, rule.due_day)))
        elif rule.frequency == "Half-Yearly":
            for h in range(2):
                he = _due(start.year, start.month, h * 6 + 5, 1)
                periods.append((f"{fy}-H{h + 1}", _due(he.year, he.month, rule.due_month_offset or 0, rule.due_day)))
        else:
            periods.append((f"FY{fy}", _due(end.year, end.month, rule.due_month_offset or 0, rule.due_day)))
        for period, due in periods:
            if not include_past and due < date.today():
                continue
            if not db.query(ComplianceTask).filter_by(rule_id=rule.id, period=period).first():
                db.add(ComplianceTask(rule_id=rule.id, period=period, due_date=due, status="Pending"))
                created += 1
    db.flush()
    return created


COMPLIANCE_STATUSES = ["Pending", "In Preparation", "Filed - Awaiting Ack", "Acknowledged", "Not Applicable"]


def update_compliance(db: Session, user, task_id: int, data: dict) -> ComplianceTask:
    t = db.get(ComplianceTask, task_id)
    if not t:
        raise AppError("Not found", 404)
    status = data.get("status") or t.status
    if status not in COMPLIANCE_STATUSES:
        raise AppError("Invalid status")
    if status in ("Filed - Awaiting Ack", "Acknowledged") and not (data.get("arn") or t.arn):
        raise AppError("Enter the ARN / acknowledgement / challan reference shown on the government portal")
    if status == "Acknowledged" and not (data.get("document_id") or t.document_id):
        raise AppError("Upload the acknowledgement downloaded from the portal before marking as acknowledged")
    if status == "Not Applicable" and not data.get("remarks"):
        raise AppError("Give a reason why this filing is not applicable")
    before = {"status": t.status, "arn": t.arn}
    for f in ("arn", "challan_no", "remarks", "document_id"):
        if f in data:
            setattr(t, f, data[f] or None)
    if data.get("filed_on"):
        t.filed_on = date.fromisoformat(str(data["filed_on"])[:10])
    if data.get("amount_paid") not in (None, ""):
        t.amount_paid = r2(data["amount_paid"])
    t.status = status
    if status == "Acknowledged":
        t.confirmed_by, t.confirmed_at = user.id, datetime.now(timezone.utc)
    log(db, user, "update", "compliance_tasks", t.id, before, {"status": status, "arn": t.arn}, "Status recorded by user from government portal acknowledgement")
    return t


# ------------------------------------------------------------------ alerts


def current_alerts(db: Session, on: date | None = None) -> list[dict]:
    on = on or date.today()
    cfg = app_settings.get(db, "alerts")
    horizon = on + timedelta(days=max(cfg["expiry_days"] or [30]))
    out: list[dict] = []

    def add(category, severity, title, body, link, due=None, key=None, event=None):
        out.append({"category": category, "severity": severity, "title": title, "body": body, "link": link, "due": due, "key": key, "event": event})

    vdocs = [("insurance_expiry", "Insurance", "insurance_expiry"), ("fc_expiry", "Fitness certificate", "fc_expiry"), ("national_permit_expiry", "National permit", "permit_expiry"),
             ("state_permit_expiry", "State permit", "permit_expiry"), ("puc_expiry", "Pollution certificate", "fc_expiry"), ("road_tax_expiry", "Road tax", "fc_expiry"),
             ("loan_end_date", None, None)]
    for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True)):
        for field, label, ev in vdocs:
            if not label:
                continue
            d = getattr(v, field)
            if d and d <= horizon:
                days = (d - on).days
                sev = "critical" if days < 0 else "warning" if days <= 7 else "info"
                add("Vehicle documents", sev, f"{v.registration_no}: {label} {'expired' if days < 0 else 'expires'} {d:%d-%m-%Y}", f"{abs(days)} day(s) {'ago' if days < 0 else 'left'}", f"/vehicles/{v.id}", d, f"veh-{v.id}-{field}-{d}", ev)
    for dr in db.query(Driver).filter(Driver.is_active.is_(True), Driver.employment_status == "Active"):
        d = dr.licence_expiry
        if d and d <= horizon:
            days = (d - on).days
            add("Driver licence", "critical" if days < 0 else "warning" if days <= 7 else "info", f"{dr.name}: driving licence {'expired' if days < 0 else 'expires'} {d:%d-%m-%Y}", dr.licence_no, f"/drivers/{dr.id}", d, f"dl-{dr.id}-{d}", "licence_expiry")
    renew = on + timedelta(days=cfg["contract_renewal_days"])
    for c in db.query(Customer).filter(Customer.is_active.is_(True), Customer.contract_end.is_not(None), Customer.contract_end <= renew):
        days = (c.contract_end - on).days
        add("Contracts", "warning" if days <= 7 else "info", f"{c.name}: contract {'ended' if days < 0 else 'ends'} {c.contract_end:%d-%m-%Y}", "Renew the agreement and rate contract", f"/customers/{c.id}", c.contract_end, f"cust-contract-{c.id}-{c.contract_end}", "contract_expiry")
    for rc in db.query(RateContract).filter(RateContract.status == "Active", RateContract.effective_to.is_not(None), RateContract.effective_to <= renew):
        add("Contracts", "info", f"Rate contract {rc.contract_no} ({rc.name}) ends {rc.effective_to:%d-%m-%Y}", "Revise or extend the rate", "/rates", rc.effective_to, f"rate-{rc.id}-{rc.effective_to}", "contract_expiry")
    from .business import maintenance_due

    for m in maintenance_due(db, on):
        add("Maintenance", "warning" if m["overdue"] else "info", f"{m['vehicle']}: {m['task']} {'overdue' if m['overdue'] else 'due'}", m["due"], "/maintenance", m["due_date"], f"svc-{m['schedule_id']}-{m['due_date']}-{m['due_km']}", "service_due")
    pod_cut = datetime.now(timezone.utc) - timedelta(days=cfg["pod_pending_days"])
    for lr in db.query(Consignment).filter(Consignment.delivered_at.is_not(None), Consignment.delivered_at < pod_cut, Consignment.pod_received_at.is_(None), Consignment.status != "Cancelled"):
        days = (datetime.now(timezone.utc) - lr.delivered_at).days
        add("POD pending", "warning", f"POD pending: LR {lr.lr_no}", f"Delivered {days} day(s) ago at {lr.to_place}", f"/lr/{lr.id}", None, f"pod-{lr.id}", "pod_pending")
    grace = timedelta(hours=cfg["delay_grace_hours"])
    nowdt = datetime.now(timezone.utc)
    for t in db.query(Trip).filter(Trip.stage.in_(["Dispatched", "In Transit"]), Trip.expected_delivery_at.is_not(None)):
        if t.expected_delivery_at + grace < nowdt:
            hrs = int((nowdt - t.expected_delivery_at).total_seconds() // 3600)
            add("Delivery delay", "warning", f"Trip {t.trip_no} delayed", f"{t.from_place} → {t.to_place}: {hrs} h past expected delivery", f"/trips/{t.id}", None, f"delay-{t.id}-{t.expected_delivery_at:%Y%m%d}", "delivery_delay")
    for lr in db.query(Consignment).filter(Consignment.eway_valid_until.is_not(None), Consignment.delivered_at.is_(None), Consignment.status.in_(["Booked", "Loaded", "In Transit"])):
        left = (lr.eway_valid_until - nowdt).total_seconds() / 3600
        if left < 12:
            add("E-way bill", "critical" if left < 0 else "warning", f"E-way bill {lr.eway_bill_no} (LR {lr.lr_no}) {'expired' if left < 0 else 'expires soon'}", f"Valid until {lr.eway_valid_until:%d-%m-%Y %H:%M}. Extend on the portal if goods are still in transit.", f"/lr/{lr.id}", None, f"ewb-{lr.id}-{lr.eway_valid_until:%Y%m%d%H}", "eway_expiry")
    overdue: dict[int, list] = {}
    for inv in db.query(Invoice).filter(Invoice.status.in_(["Issued", "Partly Paid"]), Invoice.due_date < on, Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note"])):
        overdue.setdefault(inv.customer_id, []).append(inv)
    for cid, invs in overdue.items():
        c = db.get(Customer, cid)
        amt = sum((D(i.total) - D(i.amount_received) for i in invs), ZERO)
        add("Receivables", "warning", f"Payment overdue: {c.name}", f"{len(invs)} invoice(s), ₹{r2(amt)}", f"/customers/{cid}", None, f"due-{cid}-{on:%Y%m%d}", "payment_due")
    from .operations import credit_warning

    for c in db.query(Customer).filter(Customer.is_active.is_(True), Customer.credit_limit > 0):
        w = credit_warning(db, c, ZERO)
        if w:
            add("Credit limit", "warning" if "exceeded" in w else "info", f"{c.name}: credit limit", w, f"/customers/{c.id}", None, f"credit-{c.id}-{on:%Y%m%d}", "credit_limit")
    from .operations import mileage

    month_ago = on - timedelta(days=30)
    for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True), Vehicle.expected_kmpl > 0):
        for row in mileage(db, v.id, month_ago, on):
            if row["abnormal"]:
                add("Fuel", "warning", f"{v.registration_no}: abnormal diesel consumption", f"{row['kmpl']} km/l vs expected {v.expected_kmpl} km/l ({row['distance']} km, {row['litres']} L) on {row['date']:%d-%m-%Y}", "/fuel", row["date"], f"fuel-{row['entry_id']}", "fuel_abnormal")
    week = on + timedelta(days=7)
    rules = {r.id: r for r in db.query(ComplianceRule)}
    for t in db.query(ComplianceTask).filter(ComplianceTask.status.in_(["Pending", "In Preparation"]), ComplianceTask.due_date <= week):
        r = rules.get(t.rule_id)
        days = (t.due_date - on).days
        add("Compliance", "critical" if days < 0 else "warning", f"{r.name if r else 'Filing'} ({t.period}) {'overdue' if days < 0 else 'due'} {t.due_date:%d-%m-%Y}", r.authority if r else "", "/compliance", t.due_date, f"comp-{t.id}-{'o' if days < 0 else 'd'}", "compliance_due")
    for doc in db.query(Document).filter(Document.is_deleted.is_(False), Document.expiry_date.is_not(None), Document.expiry_date <= horizon):
        days = (doc.expiry_date - on).days
        add("Documents", "critical" if days < 0 else "warning" if days <= 7 else "info", f"Document '{doc.title}' {'expired' if days < 0 else 'expires'} {doc.expiry_date:%d-%m-%Y}", doc.doc_type, "/documents", doc.expiry_date, f"doc-{doc.id}-{doc.expiry_date}", "permit_expiry")
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda a: (order[a["severity"]], str(a["due"] or "")))


def run_alerts(db: Session) -> int:
    """Create in-app (and configured external) notifications for new alerts; dedupe keys prevent repeats."""
    cfg = app_settings.get(db, "alerts")
    thresholds = sorted(cfg["expiry_days"] or [30])
    created = 0
    for a in current_alerts(db):
        key = a["key"]
        if a["due"] is not None:
            days = (a["due"] - date.today()).days
            bucket = next((t for t in thresholds if days <= t), None)
            key = f"{key}-b{bucket if days >= 0 else 'x'}"
        from ..models import InAppNotification

        if db.execute(select(InAppNotification.id).where(InAppNotification.dedupe_key == key)).first():
            continue
        notify.event(db, a["event"] or "permit_expiry", {"title": a["title"], "body": a["body"]}, severity=a["severity"], dedupe_key=key, link=a["link"])
        created += 1
    db.flush()
    return created
