"""Dashboard, reports & exports, customer portal, driver app, public QR verification."""
from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log
from ..core.deps import AppError, CurrentUser, require
from ..core.money import D, ZERO, r2
from ..core.numbering import financial_year, fy_bounds, next_number
from ..core.security import sign
from ..db import get_db
from ..models import (
    BillAllocation, Booking, Complaint, Consignment, Customer, Document, DocumentVersion, Driver, DriverIncident, FuelEntry,
    Invoice, Ledger, LocationPing, MaintenanceJob, Trip, TripEvent, TripExpense, Vehicle, Vendor, Voucher, VoucherEntry,
)
from ..services import accounting as acc
from ..services import exports, files, notify, pdf, people
from ..services import operations as ops
from ..services import reports as rep
from ..services import settings as app_settings

router = APIRouter(prefix="/api", tags=["dashboard, reports, portal, driver"])


# ------------------------------------------------------------------ dashboard

@router.get("/dashboard")
def dashboard(start: str | None = None, end: str | None = None, customer_id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("dashboard:read"))):
    today = date.today()
    e = date.fromisoformat(end) if end else today
    s = date.fromisoformat(start) if start else e.replace(day=1)
    vq = db.query(Vehicle).filter(Vehicle.is_active.is_(True))
    status_counts = dict(db.query(Vehicle.status, func.count(Vehicle.id)).filter(Vehicle.is_active.is_(True)).group_by(Vehicle.status).all())
    lrq = db.query(Consignment).filter(Consignment.status != "Cancelled")
    tq = db.query(Trip).filter(Trip.stage != "Cancelled")
    iq = db.query(Invoice).filter(Invoice.status != "Cancelled", Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note", "credit_note"]))
    if customer_id:
        lrq, tq, iq = lrq.filter(Consignment.customer_id == customer_id), tq.filter(Trip.customer_id == customer_id), iq.filter(Invoice.customer_id == customer_id)

    def inv_sum(q, field="total"):
        tot = ZERO
        for i in q:
            tot += D(getattr(i, field)) * (-1 if i.doc_type == "credit_note" else 1)
        return r2(tot)

    pnl = acc.profit_and_loss(db, s, e)
    groups = acc.groups_map(db)
    bal = acc.ledger_balances(db, upto=today)
    receivable = payable = cashbank = ZERO
    for b in bal.values():
        g = groups[b["ledger"].group_id]
        if g.name == "Sundry Debtors":
            receivable += max(ZERO, b["closing"]) if not customer_id or b["ledger"].party_id == customer_id else ZERO
        elif g.name == "Sundry Creditors":
            payable += max(ZERO, -b["closing"])
        elif g.cash_flow == "cash":
            cashbank += b["closing"]
    fuel = D(db.execute(select(func.coalesce(func.sum(FuelEntry.amount), 0)).where(FuelEntry.entry_date.between(s, e))).scalar())
    maint = D(db.execute(select(func.coalesce(func.sum(MaintenanceJob.total_amount), 0)).where(MaintenanceJob.status == "Completed", MaintenanceJob.date_out.between(s, e))).scalar())
    trend = []
    m = date(e.year, e.month, 1)
    for _ in range(6):
        import calendar

        me = date(m.year, m.month, calendar.monthrange(m.year, m.month)[1])
        p = acc.profit_and_loss(db, m, me)
        trend.insert(0, {"month": m.strftime("%b %y"), "income": r2(p["totals"]["Direct Incomes"] + p["totals"]["Indirect Incomes"]), "expenses": r2(p["totals"]["Direct Expenses"] + p["totals"]["Indirect Expenses"]), "profit": p["net_profit"]})
        m = (m - timedelta(days=1)).replace(day=1)
    top = rep.customer_profitability(db, s, e)["rows"][:5]
    alerts = people.current_alerts(db)
    drivers = dict(db.query(Driver.status, func.count(Driver.id)).filter(Driver.is_active.is_(True), Driver.employment_status == "Active").group_by(Driver.status).all())
    return jsonable({
        "period": {"start": s, "end": e},
        "fleet": {"total": vq.count(), "available": status_counts.get("Available", 0), "on_trip": status_counts.get("On Trip", 0), "maintenance": status_counts.get("Maintenance", 0) + status_counts.get("Breakdown", 0), "by_status": status_counts},
        "drivers": {"available": drivers.get("Available", 0), "on_trip": drivers.get("On Trip", 0), "total": sum(drivers.values())},
        "today": {"trips": tq.filter(Trip.trip_date == today).count(), "lrs": lrq.filter(Consignment.lr_date == today).count(), "billing": inv_sum(iq.filter(Invoice.invoice_date == today))},
        "period_stats": {
            "freight_booked": r2(sum((D(l.total_freight) for l in lrq.filter(Consignment.lr_date.between(s, e))), ZERO)),
            "billing": inv_sum(iq.filter(Invoice.invoice_date.between(s, e)), "taxable_value"),
            "income": r2(pnl["totals"]["Direct Incomes"] + pnl["totals"]["Indirect Incomes"]), "expenses": r2(pnl["totals"]["Direct Expenses"] + pnl["totals"]["Indirect Expenses"]),
            "gross_profit": pnl["gross_profit"], "net_profit": pnl["net_profit"], "fuel": r2(fuel), "maintenance": r2(maint),
            "completed_trips": tq.filter(Trip.trip_date.between(s, e), Trip.stage.in_(["Closed", "Billed", "Settled"])).count(),
            "trips": tq.filter(Trip.trip_date.between(s, e)).count(),
        },
        "monthly_revenue": inv_sum(iq.filter(Invoice.invoice_date.between(today.replace(day=1), today)), "taxable_value"),
        "receivables": r2(receivable), "payables": r2(payable), "cash_bank": r2(cashbank),
        "pending_deliveries": lrq.filter(Consignment.status.in_(["Booked", "Loaded", "In Transit"])).count(),
        "pending_pod": lrq.filter(Consignment.delivered_at.is_not(None), Consignment.pod_received_at.is_(None)).count(),
        "unbilled_lrs": lrq.filter(Consignment.invoice_id.is_(None), Consignment.status.in_(["Delivered", "POD Received"])).count(),
        "expiring_documents": [a for a in alerts if a["category"] in ("Vehicle documents", "Driver licence", "Documents")][:15],
        "alerts": alerts[:25], "alert_count": len(alerts), "trend": trend, "top_customers": top,
    })


# ------------------------------------------------------------------ reports

REPORT_PERMS = {"Accounts": "accounts:read", "Finance": "accounts:read", "GST": "invoices:read", "HR": "payroll:read", "Warehouse": "warehouse:read"}


@router.get("/reports")
def report_list(user: CurrentUser = Depends(require("reports:read"))):
    return [{"key": k, "group": g, "title": t} for k, (g, t, _) in rep.REPORTS.items() if user.can(REPORT_PERMS.get(g, "reports:read"))]


@router.get("/reports/{key}")
def report_run(key: str, request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("reports:read"))):
    if key not in rep.REPORTS:
        raise AppError("Unknown report", 404)
    need = REPORT_PERMS.get(rep.REPORTS[key][0])
    if need and not user.can(need):
        raise AppError("You do not have permission for this report", 403)
    params = dict(request.query_params)
    if key == "payroll_register" and not user.can("hr:salary"):
        raise AppError("Salary information is restricted", 403)
    data = rep.run(db, key, params)
    fmt = params.get("format")
    name = key + "_" + date.today().isoformat()
    company = app_settings.company(db)
    if fmt == "xlsx":
        return Response(exports.report_xlsx(data, company.legal_name), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    if fmt == "pdf":
        return Response(pdf.report_pdf(data, company), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})
    if fmt == "csv":
        return Response(exports.report_csv(data), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return jsonable(data)


@router.get("/export/all")
def export_all(db: Session = Depends(get_db), user: CurrentUser = Depends(require("backup:write"))):
    """Complete data export: one Excel workbook with a sheet per table (secrets excluded)."""
    import io

    from openpyxl import Workbook

    from ..core.audit import SECRET_FIELDS
    from ..models import Base

    wb = Workbook()
    wb.remove(wb.active)
    for t in Base.metadata.sorted_tables:
        if t.name in ("user_sessions",):
            continue
        ws = wb.create_sheet(t.name[:31])
        cols = [c.name for c in t.columns if c.name not in SECRET_FIELDS]
        ws.append(cols)
        for r in db.execute(t.select()):
            m = r._mapping
            ws.append([exports._val(m[c], None) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    log(db, user, "export", "all", None)
    db.commit()
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="SVSL_ERP_EXPORT_{date.today()}.xlsx"'})


# ------------------------------------------------------------------ customer portal

def portal_user(user: CurrentUser = Depends(require("portal:access"))) -> CurrentUser:
    if not user.customer_id:
        raise AppError("This login is not linked to a customer", 403)
    return user


def _own_lr(db: Session, user: CurrentUser, lid: int) -> Consignment:
    lr = db.get(Consignment, lid)
    if not lr or lr.customer_id != user.customer_id:
        raise AppError("Not found", 404)
    return lr


@router.get("/portal/summary")
def portal_summary(db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    c = db.get(Customer, user.customer_id)
    bal = acc.ledger_balance(db, c.ledger_id) if c.ledger_id else ZERO
    lrs = db.query(Consignment).filter(Consignment.customer_id == c.id, Consignment.status != "Cancelled")
    return jsonable({"customer": c.name, "outstanding": bal, "in_transit": lrs.filter(Consignment.status.in_(["Booked", "Loaded", "In Transit"])).count(), "delivered_30d": lrs.filter(Consignment.delivered_at >= datetime.now(timezone.utc) - timedelta(days=30)).count(),
                     "open_bookings": db.query(Booking).filter(Booking.customer_id == c.id, Booking.status.in_(["Requested", "Confirmed"])).count(), "credit_limit": c.credit_limit})


@router.get("/portal/bookings")
def portal_bookings(db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    return [jsonable({col.name: getattr(b, col.name) for col in Booking.__table__.columns}) for b in db.query(Booking).filter_by(customer_id=user.customer_id).order_by(Booking.id.desc()).limit(200)]


@router.post("/portal/bookings")
def portal_book(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    for f in ("pickup_address", "drop_address", "required_date"):
        if not data.get(f):
            raise AppError(f"{f.replace('_', ' ').capitalize()} is required")
    req = date.fromisoformat(str(data["required_date"])[:10])
    if req < date.today():
        raise AppError("Required date cannot be in the past")
    b = Booking(booking_no=next_number(db, "BOOKING", date.today()), booking_date=date.today(), customer_id=user.customer_id, source="Customer Portal", pickup_address=data["pickup_address"], drop_address=data["drop_address"],
                required_date=req, vehicle_type=data.get("vehicle_type"), vehicles_required=int(data.get("vehicles_required") or 1), goods_description=data.get("goods_description"),
                weight_kg=D(data.get("weight_kg")) or None, quantity=D(data.get("quantity")) or None, contact_person=data.get("contact_person"), contact_phone=data.get("contact_phone"), remarks=data.get("remarks"), status="Requested", created_by=user.id)
    db.add(b)
    db.flush()
    notify.in_app(db, f"New portal booking {b.booking_no}", f"{db.get(Customer, user.customer_id).name}: {b.pickup_address[:60]} → {b.drop_address[:60]} on {req:%d-%m-%Y}", "/bookings", "info")
    log(db, user, "create", "bookings", b.id, None, {"booking_no": b.booking_no, "via": "portal"})
    db.commit()
    return {"id": b.id, "booking_no": b.booking_no}


@router.get("/portal/shipments")
def portal_shipments(q: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    query = db.query(Consignment).filter(Consignment.customer_id == user.customer_id)
    if q:
        query = query.filter(or_(Consignment.lr_no.ilike(f"%{q}%"), Consignment.customer_invoice_no.ilike(f"%{q}%"), Consignment.consignee_name.ilike(f"%{q}%")))
    out = []
    for l in query.order_by(Consignment.id.desc()).limit(300):
        t = db.get(Trip, l.trip_id) if l.trip_id else None
        out.append(jsonable({"id": l.id, "lr_no": l.lr_no, "lr_date": l.lr_date, "from": l.from_place, "to": l.to_place, "consignee": l.consignee_name, "vehicle_no": l.vehicle_no, "driver": l.driver_name,
                             "status": l.status, "trip_stage": t.stage if t else None, "dispatched_at": t.dispatched_at if t else None, "expected_delivery_at": t.expected_delivery_at if t else None,
                             "delivered_at": l.delivered_at, "receiver": l.receiver_name, "pod_available": bool(l.pod_document_id), "freight": l.total_freight, "invoice_no": l.customer_invoice_no, "eway_bill_no": l.eway_bill_no}))
    return out


@router.get("/portal/lr/{lid}/pdf")
def portal_lr_pdf(lid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    from .operations import _lr_pdf_bytes

    lr = _own_lr(db, user, lid)
    return Response(_lr_pdf_bytes(db, lr, "A4", "Consignor Copy"), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="LR_{lr.lr_no.replace("/", "-")}.pdf"'})


@router.get("/portal/lr/{lid}/pod")
def portal_pod(lid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    lr = _own_lr(db, user, lid)
    if not lr.pod_document_id:
        raise AppError("POD not yet available", 404)
    d = db.get(Document, lr.pod_document_id)
    v = db.query(DocumentVersion).filter_by(document_id=d.id, version=d.current_version).first()
    if not v:
        raise AppError("POD not yet available", 404)
    return Response(files.read_version(v), media_type=v.mime, headers={"Content-Disposition": f'inline; filename="{v.file_name}"'})


@router.get("/portal/invoices")
def portal_invoices(db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    rows = db.query(Invoice).filter(Invoice.customer_id == user.customer_id, Invoice.status != "Draft").order_by(Invoice.id.desc()).limit(500)
    return [jsonable({"id": i.id, "invoice_no": i.invoice_no, "doc_type": i.doc_type, "date": i.invoice_date, "due_date": i.due_date, "total": i.total, "received": i.amount_received, "balance": r2(D(i.total) - D(i.amount_received)), "status": i.status}) for i in rows]


@router.get("/portal/invoices/{iid}/pdf")
def portal_invoice_pdf(iid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    from .finance import invoice_pdf_bytes

    inv = db.get(Invoice, iid)
    if not inv or inv.customer_id != user.customer_id:
        raise AppError("Not found", 404)
    return Response(invoice_pdf_bytes(db, inv), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{inv.invoice_no.replace("/", "-")}.pdf"'})


@router.get("/portal/payments")
def portal_payments(db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    c = db.get(Customer, user.customer_id)
    if not c.ledger_id:
        return []
    rows = (db.query(Voucher).join(VoucherEntry, Voucher.id == VoucherEntry.voucher_id)
            .filter(VoucherEntry.ledger_id == c.ledger_id, Voucher.voucher_type == "Receipt").order_by(Voucher.voucher_date.desc()).limit(300).all())
    return [jsonable({"date": v.voucher_date, "receipt_no": v.voucher_no, "amount": v.total, "reference": v.reference, "status": v.status}) for v in rows]


@router.get("/portal/statement")
def portal_statement(start: str | None = None, end: str | None = None, format: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    fs, _ = fy_bounds(financial_year(date.today()))
    data = rep.customer_statement(db, date.fromisoformat(start) if start else fs, date.fromisoformat(end) if end else date.today(), customer_id=user.customer_id)
    company = app_settings.company(db)
    if format == "pdf":
        return Response(pdf.report_pdf(data, company), media_type="application/pdf")
    if format == "xlsx":
        return Response(exports.report_xlsx(data, company.legal_name), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="statement.xlsx"'})
    return jsonable(data)


@router.get("/portal/complaints")
def portal_complaints(db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    return [jsonable({col.name: getattr(c, col.name) for col in Complaint.__table__.columns}) for c in db.query(Complaint).filter_by(customer_id=user.customer_id).order_by(Complaint.id.desc())]


@router.post("/portal/complaints")
def portal_complain(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(portal_user)):
    if not data.get("subject") or not data.get("description"):
        raise AppError("Subject and description are required")
    lr_id = int(data["consignment_id"]) if data.get("consignment_id") else None
    if lr_id:
        _own_lr(db, user, lr_id)
    c = Complaint(complaint_no=next_number(db, "COMPLAINT", date.today()), customer_id=user.customer_id, consignment_id=lr_id, subject=data["subject"][:200], description=data["description"], created_by=user.id)
    db.add(c)
    db.flush()
    notify.in_app(db, f"Customer complaint {c.complaint_no}", f"{c.subject}", "/complaints", "warning")
    db.commit()
    return {"id": c.id, "complaint_no": c.complaint_no}


@router.get("/complaints")
def staff_complaints(db: Session = Depends(get_db), user: CurrentUser = Depends(require("customers:read"))):
    names = {c.id: c.name for c in db.query(Customer)}
    return [jsonable({col.name: getattr(c, col.name) for col in Complaint.__table__.columns} | {"customer": names.get(c.customer_id)}) for c in db.query(Complaint).order_by(Complaint.id.desc()).limit(500)]


@router.put("/complaints/{cid}")
def staff_complaint_update(cid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("customers:write"))):
    c = db.get(Complaint, cid)
    if not c:
        raise AppError("Not found", 404)
    if data.get("status") not in (None, "Open", "In Progress", "Resolved", "Closed"):
        raise AppError("Invalid status")
    c.status = data.get("status") or c.status
    c.response = data.get("response", c.response)
    if c.status in ("Resolved", "Closed"):
        c.resolved_at = datetime.now(timezone.utc)
    log(db, user, "update", "complaints", c.id, None, {"status": c.status})
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ driver app

def driver_user(user: CurrentUser = Depends(require("driver_app:access"))) -> CurrentUser:
    if not user.driver_id:
        raise AppError("This login is not linked to a driver", 403)
    return user


def _own_trip(db: Session, user: CurrentUser, tid: int) -> Trip:
    t = db.get(Trip, tid)
    if not t or t.driver_id != user.driver_id:
        raise AppError("Trip not found", 404)
    return t


@router.get("/driver/me")
def driver_me(db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    d = db.get(Driver, user.driver_id)
    return jsonable({"name": d.name, "mobile": d.mobile, "licence_no": d.licence_no, "licence_expiry": d.licence_expiry, "gps_consent": d.gps_consent, "status": d.status})


@router.post("/driver/consent")
def driver_consent(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    d = db.get(Driver, user.driver_id)
    d.gps_consent = bool(data.get("consent"))
    d.gps_consent_at = datetime.now(timezone.utc) if d.gps_consent else None
    log(db, user, "gps_consent", "drivers", d.id, None, {"consent": d.gps_consent})
    db.commit()
    return {"gps_consent": d.gps_consent}


@router.get("/driver/trips")
def driver_trips(db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    from .operations import _trip_out

    rows = db.query(Trip).filter(Trip.driver_id == user.driver_id, or_(Trip.stage.in_(ops.OPEN_STAGES), Trip.trip_date >= date.today() - timedelta(days=15))).order_by(Trip.id.desc()).limit(30)
    return [_trip_out(db, t) for t in rows]


@router.get("/driver/trips/{tid}")
def driver_trip(tid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    from .operations import _trip_out

    t = _own_trip(db, user, tid)
    out = _trip_out(db, t, True)
    out.pop("pnl", None)
    for lr in out["lrs"]:
        for k in ("total_freight", "basic_freight", "freight_rate", "freight_breakdown", "balance_freight", "advance_freight", "freight_inputs"):
            lr.pop(k, None)
    return out


@router.post("/driver/trips/{tid}/stage")
def driver_stage(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    from .operations import _trip_out

    t = _own_trip(db, user, tid)
    stage = data.get("stage")
    if stage not in ("Loading", "Dispatched", "In Transit", "Delivered"):
        raise AppError("Drivers can confirm loading, departure, in-transit and delivery")
    payload = {k: data.get(k) for k in ("start_km", "receiver_name", "receiver_phone", "remarks", "fuel_opening_litres")}
    ops.advance(db, user, t, stage, payload)
    if data.get("odometer") or data.get("lat"):
        db.add(TripEvent(trip_id=t.id, at=datetime.now(timezone.utc), stage=stage, note="driver app", user_id=user.id, odometer=D(data.get("odometer")) or None,
                                                                        lat=D(data["lat"]) if data.get("lat") and db.get(Driver, user.driver_id).gps_consent else None, lng=D(data["lng"]) if data.get("lng") and db.get(Driver, user.driver_id).gps_consent else None))
    db.commit()
    return _trip_out(db, t)


@router.post("/driver/trips/{tid}/pod")
async def driver_pod(tid: int, lr_id: int = Form(...), receiver_name: str = Form(""), file: UploadFile = File(...), db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    t = _own_trip(db, user, tid)
    lr = db.get(Consignment, lr_id)
    if not lr or lr.trip_id != t.id:
        raise AppError("LR not on this trip", 404)
    d = Document(title=f"POD {lr.lr_no}", doc_type="POD", entity_type="consignment", entity_id=lr.id, doc_number=lr.lr_no, created_by=user.id)
    db.add(d)
    db.flush()
    files.store_upload(db, user, d, file.filename or "pod.jpg", await file.read(), file.content_type, "Uploaded from driver app")
    if receiver_name and not lr.receiver_name:
        lr.receiver_name = receiver_name
    ops.lr_pod(db, user, lr, d.id)
    db.commit()
    return {"ok": True, "document_id": d.id}


@router.post("/driver/trips/{tid}/document")
async def driver_doc(tid: int, kind: str = Form("Receipt"), file: UploadFile = File(...), db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    t = _own_trip(db, user, tid)
    if kind not in ("Receipt", "Invoice", "Photo"):
        raise AppError("Invalid document type")
    d = Document(title=f"{kind} – trip {t.trip_no}", doc_type=kind, entity_type="trip", entity_id=t.id, created_by=user.id)
    db.add(d)
    db.flush()
    files.store_upload(db, user, d, file.filename or "upload.jpg", await file.read(), file.content_type, "Driver app")
    db.commit()
    return {"document_id": d.id}


@router.post("/driver/trips/{tid}/expense")
def driver_expense(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    t = _own_trip(db, user, tid)
    if data.get("category") == "Diesel" and data.get("litres") and data.get("odometer"):
        ops.record_fuel(db, user, {"vehicle_id": t.vehicle_id, "driver_id": t.driver_id, "trip_id": t.id, "litres": data["litres"], "rate": data.get("rate") or (D(data.get("amount")) / D(data["litres"])), "amount": data.get("amount"),
                                   "odometer": data["odometer"], "full_tank": data.get("full_tank", True), "payment_mode": "Driver Cash", "bill_no": data.get("bill_no"), "entered_via": "Driver App", "remarks": data.get("remarks")})
    else:
        ops.add_trip_expense(db, user, t, {**data, "paid_by": "Driver Cash", "document_id": data.get("document_id")}, via="Driver App")
    db.commit()
    return {"ok": True}


@router.post("/driver/trips/{tid}/incident")
def driver_incident(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    t = _own_trip(db, user, tid)
    if not data.get("description"):
        raise AppError("Describe what happened")
    kind = data.get("kind") if data.get("kind") in ("Accident", "Fine / Challan", "Breakdown", "Theft", "Damage", "Other") else "Other"
    inc = DriverIncident(driver_id=user.driver_id, vehicle_id=t.vehicle_id, trip_id=t.id, kind=kind, incident_date=date.today(), location=data.get("location"), description=data["description"], amount=D(data.get("amount")), reported_via="Driver App", created_by=user.id)
    db.add(inc)
    if kind == "Breakdown":
        v = db.get(Vehicle, t.vehicle_id)
        v.status = "Breakdown"
    db.flush()
    notify.in_app(db, f"{kind} reported – trip {t.trip_no}", data["description"][:200], f"/trips/{t.id}", "critical" if kind in ("Accident", "Theft") else "warning")
    db.commit()
    return {"id": inc.id}


@router.post("/driver/location")
def driver_location(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(driver_user)):
    d = db.get(Driver, user.driver_id)
    if not d.gps_consent:
        raise AppError("Location sharing is off. Give consent in the app to share location during trips.", 403)
    t = db.query(Trip).filter(Trip.driver_id == d.id, Trip.stage.in_(["Loading", "Dispatched", "In Transit"])).first()
    if not t:
        return {"stored": False, "reason": "Location is recorded only during an active trip"}
    db.add(LocationPing(driver_id=d.id, trip_id=t.id, at=datetime.now(timezone.utc), lat=D(data["lat"]), lng=D(data["lng"]), accuracy_m=D(data.get("accuracy")) or None))
    db.commit()
    return {"stored": True}


@router.get("/trips/{tid}/locations")
def trip_locations(tid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:read"))):
    return [jsonable({"at": p.at, "lat": p.lat, "lng": p.lng}) for p in db.query(LocationPing).filter_by(trip_id=tid).order_by(LocationPing.at)]


# ------------------------------------------------------------------ public verification (QR)

@router.get("/public/verify/{kind}/{number}", response_class=HTMLResponse)
def verify(kind: str, number: str, s: str = "", db: Session = Depends(get_db)):
    no = number.replace("~", "/")
    company = app_settings.company(db)
    rows, ok = [], False
    if kind == "lr":
        lr = db.query(Consignment).filter_by(lr_no=no).first()
        if lr and s == sign("lr" + lr.lr_no + (lr.verify_token or "")):
            ok = True
            rows = [("LR number", lr.lr_no), ("Date", lr.lr_date.strftime("%d-%m-%Y")), ("Route", f"{lr.from_place} → {lr.to_place}"), ("Vehicle", lr.vehicle_no or "-"), ("Packages", lr.packages), ("Status", lr.status)]
    elif kind == "inv":
        inv = db.query(Invoice).filter_by(invoice_no=no).first()
        if inv and s == sign("inv" + inv.invoice_no + (inv.verify_token or "")):
            ok = True
            rows = [("Document", inv.invoice_no), ("Date", inv.invoice_date.strftime("%d-%m-%Y")), ("Billed to", inv.billing_name), ("Total", f"₹ {inv.total}"), ("Status", inv.status)]
    body = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    msg = "<p style='color:#137333;font-weight:bold'>✔ Genuine document issued by " + html.escape(company.trade_name or company.legal_name) + "</p>" if ok else "<p style='color:#b3261e;font-weight:bold'>✖ This document could not be verified.</p>"
    return f"<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Verify</title><style>body{{font-family:sans-serif;padding:16px;max-width:520px;margin:auto;background:#fff;color:#111}}th{{text-align:left;padding:4px 12px 4px 0;color:#555}}</style></head><body><h2>{html.escape(company.trade_name or company.legal_name)}</h2>{msg}<table>{body}</table></body></html>"
