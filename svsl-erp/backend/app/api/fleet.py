"""Vehicles (lifecycle, summary), maintenance jobs, tyres, warehouse stock, documents, HR, payroll, compliance."""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log
from ..core.deps import AppError, CurrentUser, get_current_user, require
from ..core.money import D, ZERO, r2
from ..db import get_db
from ..models import (
    Attendance, ComplianceRule, ComplianceTask, Consignment, Document, DocumentVersion, Driver, Employee, FuelEntry, Item,
    MaintenanceJob, PayrollRun, Payslip, RegisterEntry, StatutoryRegister, StockDoc, StockMovement, Trip, TripExpense, Tyre,
    TyreEvent, Vehicle, VehicleEvent, Warehouse,
)
from ..services import business, files, layouts, people, pdf
from ..services import settings as app_settings

router = APIRouter(prefix="/api", tags=["fleet & admin"])


def _row(obj) -> dict:
    return jsonable({c.name: getattr(obj, c.name) for c in obj.__table__.columns})


# ------------------------------------------------------------------ vehicles

@router.post("/vehicles/{vid}/events")
def vehicle_event(vid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("vehicles:write"))):
    ev = business.vehicle_event(db, user, vid, data)
    db.commit()
    return _row(ev)


@router.get("/vehicles/{vid}/summary")
def vehicle_summary(vid: int, start: str | None = None, end: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("vehicles:read"))):
    from ..services.reports import fleet_utilization, vehicle_profitability

    v = db.get(Vehicle, vid)
    if not v:
        raise AppError("Not found", 404)
    e = date.fromisoformat(end) if end else date.today()
    s = date.fromisoformat(start) if start else e - timedelta(days=90)
    prof = [r for r in vehicle_profitability(db, s, e)["rows"] if r["vehicle"] == v.registration_no]
    util = [r for r in fleet_utilization(db, s, e)["rows"] if r["vehicle"] == v.registration_no]
    trips = db.query(Trip).filter(Trip.vehicle_id == vid).order_by(Trip.id.desc()).limit(30).all()
    from ..services.operations import mileage

    return jsonable({
        "vehicle": v.registration_no, "period": [s, e], "profit": prof[0] if prof else None, "utilization": util[0] if util else None,
        "trips": [{"id": t.id, "trip_no": t.trip_no, "date": t.trip_date, "route": f"{t.from_place} → {t.to_place}", "stage": t.stage} for t in trips],
        "events": [_row(x) for x in db.query(VehicleEvent).filter_by(vehicle_id=vid).order_by(VehicleEvent.event_date)],
        "maintenance": [_row(j) for j in db.query(MaintenanceJob).filter_by(vehicle_id=vid).order_by(MaintenanceJob.id.desc()).limit(30)],
        "tyres": [_row(t) for t in db.query(Tyre).filter_by(vehicle_id=vid)],
        "mileage": mileage(db, vid)[-10:],
        "documents": [{"id": d.id, "title": d.title, "doc_type": d.doc_type, "expiry_date": d.expiry_date} for d in db.query(Document).filter_by(entity_type="vehicle", entity_id=vid, is_deleted=False)],
    })


# ------------------------------------------------------------------ maintenance

@router.get("/maintenance/jobs")
def list_jobs(vehicle_id: int | None = None, status: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:read"))):
    q = db.query(MaintenanceJob)
    if vehicle_id:
        q = q.filter_by(vehicle_id=vehicle_id)
    if status:
        q = q.filter_by(status=status)
    veh = {v.id: v.registration_no for v in db.query(Vehicle)}
    return [_row(j) | {"vehicle": veh.get(j.vehicle_id)} for j in q.order_by(MaintenanceJob.id.desc()).limit(500)]


@router.post("/maintenance/jobs")
def new_job(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:write"))):
    j = business.create_job(db, user, data)
    db.commit()
    return _row(j)


@router.post("/maintenance/jobs/{jid}/complete")
def complete_job(jid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:write"))):
    j = business.complete_job(db, user, jid, data)
    db.commit()
    return _row(j)


@router.get("/maintenance/due")
def maint_due(db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:read"))):
    return jsonable(business.maintenance_due(db))


@router.post("/tyres/{tid}/action")
def tyre_action(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:write"))):
    t = business.tyre_action(db, user, tid, data)
    db.commit()
    return _row(t)


@router.get("/tyres/{tid}/history")
def tyre_hist(tid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("maintenance:read"))):
    t = db.get(Tyre, tid)
    events = [_row(e) for e in db.query(TyreEvent).filter_by(tyre_id=tid).order_by(TyreEvent.at, TyreEvent.id)]
    cpk = r2(D(t.cost) / D(t.total_km)) if t and D(t.total_km) else None
    return {"tyre": _row(t), "events": events, "cost_per_km": jsonable(cpk)}


# ------------------------------------------------------------------ warehouse

@router.post("/warehouse/docs")
def stock_doc(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("warehouse:write"))):
    d = business.post_stock_doc(db, user, data)
    db.commit()
    return _row(d)


@router.get("/warehouse/docs")
def stock_docs(doc_type: str | None = None, warehouse_id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("warehouse:read"))):
    q = db.query(StockDoc)
    if doc_type:
        q = q.filter_by(doc_type=doc_type)
    if warehouse_id:
        q = q.filter_by(warehouse_id=warehouse_id)
    wh = {w.id: w.name for w in db.query(Warehouse)}
    items = {i.id: i.name for i in db.query(Item)}
    out = []
    for d in q.order_by(StockDoc.id.desc()).limit(500):
        lines = [{"item": items.get(m.item_id), "batch_no": m.batch_no, "in": jsonable(m.qty_in), "out": jsonable(m.qty_out), "packages": m.packages} for m in db.query(StockMovement).filter_by(doc_id=d.id)]
        out.append(_row(d) | {"warehouse": wh.get(d.warehouse_id), "lines": lines})
    return out


@router.get("/warehouse/stock")
def stock(warehouse_id: int | None = None, customer_id: int | None = None, item_id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("warehouse:read"))):
    return jsonable(business.stock_balance(db, warehouse_id, item_id, None, customer_id))


@router.get("/warehouse/scan/{code}")
def scan(code: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("warehouse:read"))):
    """Resolve a scanned barcode / QR: item barcode, SKU, 'ITEM:<sku>|BATCH:<no>' labels or an LR number."""
    batch = None
    if code.startswith("ITEM:"):
        parts = dict(p.split(":", 1) for p in code.split("|") if ":" in p)
        code, batch = parts.get("ITEM"), parts.get("BATCH")
    it = db.query(Item).filter((Item.barcode == code) | (Item.sku == code)).first()
    if it:
        return {"type": "item", "item": _row(it), "batch_no": batch, "stock": jsonable(business.stock_balance(db, item_id=it.id))}
    lr = db.query(Consignment).filter(Consignment.lr_no == code.replace("~", "/")).first()
    if lr:
        return {"type": "lr", "id": lr.id, "lr_no": lr.lr_no, "status": lr.status}
    raise AppError("Code not recognised", 404)


@router.get("/warehouse/labels")
def labels(item_id: int, batch_no: str = "", copies: int = 1, db: Session = Depends(get_db), user: CurrentUser = Depends(require("warehouse:read"))):
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table

    it = db.get(Item, item_id)
    if not it:
        raise AppError("Item not found", 404)
    st = pdf.styles(8)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(62 * mm, 40 * mm), leftMargin=2 * mm, rightMargin=2 * mm, topMargin=2 * mm, bottomMargin=2 * mm)
    code = f"ITEM:{it.sku}" + (f"|BATCH:{batch_no}" if batch_no else "")
    story = []
    for _ in range(max(1, min(copies, 200))):
        story.append(Table([[pdf.qr_image(code, 24), [pdf.P(it.name, st["b"]), pdf.P(f"SKU {it.sku}", st["n"]), pdf.P(f"Batch {batch_no}" if batch_no else "", st["n"]), pdf.P(it.uom, st["s"])]]], colWidths=[27 * mm, 31 * mm]))
        story.append(Spacer(1, 1))
    doc.build(story)
    return Response(buf.getvalue(), media_type="application/pdf")


# ------------------------------------------------------------------ documents

def _doc_allowed(user: CurrentUser, d: Document) -> bool:
    return not d.access_roles or user.role in (d.access_roles or []) or "*" in user.permissions


@router.post("/documents/upload")
async def upload(file: UploadFile = File(...), title: str = Form(""), doc_type: str = Form("Other"), entity_type: str = Form(""), entity_id: int | None = Form(None),
                 doc_number: str = Form(""), issue_date: str = Form(""), expiry_date: str = Form(""), document_id: int | None = Form(None), note: str = Form(""),
                 db: Session = Depends(get_db), user: CurrentUser = Depends(require("documents:write"))):
    content = await file.read()
    if document_id:
        d = db.get(Document, document_id)
        if not d or d.is_deleted or not _doc_allowed(user, d):
            raise AppError("Document not found", 404)
    else:
        from ..models.hr import DOC_TYPES

        if doc_type not in DOC_TYPES:
            raise AppError("Unknown document type")
        d = Document(title=title or file.filename, doc_type=doc_type, entity_type=entity_type or None, entity_id=entity_id, doc_number=doc_number or None,
                     issue_date=date.fromisoformat(issue_date) if issue_date else None, expiry_date=date.fromisoformat(expiry_date) if expiry_date else None, created_by=user.id)
        db.add(d)
        db.flush()
    if expiry_date and document_id:
        d.expiry_date = date.fromisoformat(expiry_date)
    files.store_upload(db, user, d, file.filename or "file", content, file.content_type, note or None)
    db.commit()
    return _row(d)


@router.get("/documents/{did}/versions")
def versions(did: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("documents:read"))):
    d = db.get(Document, did)
    if not d or not _doc_allowed(user, d):
        raise AppError("Not found", 404)
    return [_row(v) for v in db.query(DocumentVersion).filter_by(document_id=did).order_by(DocumentVersion.version.desc())]


@router.get("/documents/{did}/download")
def download(did: int, version: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("documents:read"))):
    d = db.get(Document, did)
    if not d or d.is_deleted or not _doc_allowed(user, d):
        raise AppError("Not found", 404)
    v = db.query(DocumentVersion).filter_by(document_id=did, version=version or d.current_version).first()
    if not v:
        raise AppError("No file uploaded", 404)
    log(db, user, "download", "documents", d.id, None, {"version": v.version})
    db.commit()
    return Response(files.read_version(v), media_type=v.mime or "application/octet-stream", headers={"Content-Disposition": f'inline; filename="{v.file_name}"'})


@router.post("/documents/{did}/delete")
def delete_doc(did: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("documents:write"))):
    d = db.get(Document, did)
    if not d:
        raise AppError("Not found", 404)
    d.is_deleted = True  # files and versions are retained for audit
    log(db, user, "delete", "documents", d.id, None, None, data.get("reason"))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ attendance & payroll

@router.get("/attendance")
def get_attendance(person_type: str, on: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("hr:read"))):
    d = date.fromisoformat(on)
    people_list = ([{"id": e.id, "name": e.name, "code": e.code} for e in db.query(Employee).filter_by(is_active=True).order_by(Employee.name)] if person_type == "employee"
                   else [{"id": x.id, "name": x.name, "code": x.code} for x in db.query(Driver).filter_by(is_active=True).order_by(Driver.name)])
    marks = {a.person_id: a for a in db.query(Attendance).filter_by(person_type=person_type, att_date=d)}
    for p in people_list:
        a = marks.get(p["id"])
        p.update({"status": a.status if a else None, "in_time": a.in_time if a else None, "out_time": a.out_time if a else None, "remarks": a.remarks if a else None})
    return people_list


@router.post("/attendance")
def save_attendance(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("hr:write"))):
    ptype, d = data.get("person_type"), date.fromisoformat(data["date"])
    if ptype not in ("employee", "driver"):
        raise AppError("person_type must be employee or driver")
    n = 0
    for r in data.get("rows") or []:
        if not r.get("status"):
            continue
        if r["status"] not in ("Present", "Absent", "Half Day", "Leave", "On Trip", "Week Off", "Holiday"):
            raise AppError(f"Invalid status {r['status']}")
        a = db.query(Attendance).filter_by(person_type=ptype, person_id=int(r["id"]), att_date=d).first()
        if not a:
            a = Attendance(person_type=ptype, person_id=int(r["id"]), att_date=d, created_by=user.id)
            db.add(a)
        a.status, a.in_time, a.out_time, a.remarks, a.updated_by = r["status"], r.get("in_time"), r.get("out_time"), r.get("remarks"), user.id
        n += 1
    log(db, user, "attendance", ptype, data["date"], None, {"rows": n})
    db.commit()
    return {"saved": n}


@router.post("/payroll/{month}/compute")
def payroll_compute(month: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("payroll:write", "hr:salary"))):
    run = people.compute_payroll(db, user, month)
    db.commit()
    return payroll_get(month, db, user)


@router.get("/payroll/{month}")
def payroll_get(month: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("payroll:read", "hr:salary"))):
    run = db.query(PayrollRun).filter_by(month=month).first()
    if not run:
        return {"run": None, "slips": []}
    return {"run": _row(run), "slips": [_row(s) for s in db.query(Payslip).filter_by(run_id=run.id).order_by(Payslip.name)]}


@router.post("/payroll/{month}/post")
def payroll_post(month: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("payroll:write", "accounts:write", "hr:salary"))):
    run = db.query(PayrollRun).filter_by(month=month).first()
    if not run:
        raise AppError("Compute payroll first")
    people.post_payroll(db, user, run.id)
    db.commit()
    return payroll_get(month, db, user)


@router.get("/payslips/{sid}/pdf")
def payslip_pdf(sid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("payroll:read", "hr:salary"))):
    s = db.get(Payslip, sid)
    if not s:
        raise AppError("Not found", 404)
    run = db.get(PayrollRun, s.run_id)
    rows = [{"head": h, "amount": v} for h, v in (("Paid days", f"{s.paid_days} / {s.days_in_month}"), ("Basic + DA", s.basic), ("HRA", s.hra), ("Allowances", s.allowances), ("GROSS", s.gross), ("EPF (employee)", s.pf_employee), ("ESI (employee)", s.esi_employee), ("Professional tax", s.professional_tax), ("TDS", s.tds), ("Advance recovery", s.advance_recovery), ("NET PAY", s.net_pay))]
    rep = {"title": f"Payslip – {s.name} – {run.month}", "columns": [{"key": "head", "label": "Particulars", "w": 3}, {"key": "amount", "label": "Amount", "type": None}], "rows": rows}
    return Response(pdf.report_pdf(rep, app_settings.company(db), layouts.get(db, "report")), media_type="application/pdf")


# ------------------------------------------------------------------ compliance

@router.post("/compliance/generate")
def compliance_generate(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:write"))):
    from ..core.numbering import financial_year

    n = people.generate_compliance(db, data.get("fy") or financial_year(date.today()), bool(data.get("include_past")))
    db.commit()
    return {"created": n}


@router.get("/compliance/tasks")
def compliance_tasks(status: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:read"))):
    rules = {r.id: r for r in db.query(ComplianceRule)}
    q = db.query(ComplianceTask)
    if status:
        q = q.filter(ComplianceTask.status.in_(status.split(",")))
    out = []
    for t in q.order_by(ComplianceTask.due_date):
        r = rules.get(t.rule_id)
        out.append(_row(t) | {"name": r.name if r else "", "category": r.category if r else "", "authority": r.authority if r else "", "overdue": t.status in ("Pending", "In Preparation") and t.due_date < date.today()})
    return out


@router.put("/compliance/tasks/{tid}")
def compliance_update(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:write"))):
    t = people.update_compliance(db, user, tid, data)
    db.commit()
    return _row(t)


@router.get("/compliance/dashboard")
def compliance_dashboard(db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:read"))):
    today = date.today()
    tasks = compliance_tasks(None, db, user)
    statutory_docs = [a for a in people.current_alerts(db) if a["category"] in ("Vehicle documents", "Driver licence", "Documents")]
    return jsonable({
        "overdue": [t for t in tasks if t["overdue"]], "due_30": [t for t in tasks if t["status"] in ("Pending", "In Preparation") and today <= date.fromisoformat(t["due_date"]) <= today + timedelta(days=30)],
        "awaiting_ack": [t for t in tasks if t["status"] == "Filed - Awaiting Ack"], "document_alerts": statutory_docs,
        "note": "Filings are never marked complete automatically. Record the ARN/acknowledgement from the government portal and upload the proof.",
    })


@router.get("/registers/{rid}/entries")
def register_entries(rid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:read"))):
    return [_row(e) for e in db.query(RegisterEntry).filter_by(register_id=rid).order_by(RegisterEntry.entry_date.desc())]


@router.post("/registers/{rid}/entries")
def add_register_entry(rid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("compliance:write"))):
    if not db.get(StatutoryRegister, rid):
        raise AppError("Register not found", 404)
    e = RegisterEntry(register_id=rid, entry_date=date.fromisoformat(data.get("entry_date") or str(date.today())), data=data.get("data") or {}, created_by=user.id)
    db.add(e)
    db.flush()
    log(db, user, "create", "register_entries", e.id, None, e.data)
    db.commit()
    return _row(e)
