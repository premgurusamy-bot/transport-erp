"""LR, trips, bookings, freight engine, fuel, driver advances & settlements, FASTag import."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.audit import jsonable, log
from ..core.deps import AppError, CurrentUser, require
from ..core.money import D, r2
from ..db import get_db
from ..integrations import channels, gst_portals
from ..models import (
    Booking, Consignment, ConsignmentItem, Customer, DeliveryPoint, Document, Driver, DriverSettlement, EwayBill,
    FastagTransaction, LRAmendment, RateContract, Route, Trip, TripEvent, TripExpense, Vehicle,
)
from ..services import freight as fr
from ..services import operations as ops
from ..services import pdf
from ..services import settings as app_settings

router = APIRouter(prefix="/api", tags=["operations"])


def _lr_out(db: Session, lr: Consignment, full: bool = False) -> dict:
    out = {c.name: jsonable(getattr(lr, c.name)) for c in Consignment.__table__.columns}
    cust = db.get(Customer, lr.customer_id)
    out["customer_name"] = cust.name if cust else None
    if full:
        out["items"] = [jsonable({c.name: getattr(i, c.name) for c in ConsignmentItem.__table__.columns}) for i in db.query(ConsignmentItem).filter_by(consignment_id=lr.id).order_by(ConsignmentItem.id)]
        out["delivery_points"] = [jsonable({c.name: getattr(p, c.name) for c in DeliveryPoint.__table__.columns}) for p in db.query(DeliveryPoint).filter_by(consignment_id=lr.id).order_by(DeliveryPoint.sequence)]
        out["amendments"] = [jsonable({"at": a.at, "authorized_by": a.authorized_by, "reason": a.reason, "before": a.before, "after": a.after, "revision": a.revision}) for a in db.query(LRAmendment).filter_by(consignment_id=lr.id).order_by(LRAmendment.id)]
        out["documents"] = [{"id": d.id, "title": d.title, "doc_type": d.doc_type} for d in db.query(Document).filter_by(entity_type="consignment", entity_id=lr.id, is_deleted=False)]
        out["verify_url"] = pdf.verify_url("lr", lr.lr_no, lr.verify_token)
        if lr.trip_id:
            t = db.get(Trip, lr.trip_id)
            out["trip_no"] = t.trip_no if t else None
    return out


# ------------------------------------------------------------------ freight engine

@router.post("/freight/calculate")
def freight_calculate(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    on = date.fromisoformat(str(data.get("date") or date.today())[:10])
    if data.get("rate_contract_id"):
        c = db.get(RateContract, int(data["rate_contract_id"]))
    else:
        c = fr.find_contract(db, int(data.get("customer_id") or 0), on, int(data["route_id"]) if data.get("route_id") else None, data.get("vehicle_type"), data.get("goods"))
    if not c:
        raise AppError("No applicable rate contract found for this customer, date and route")
    res = fr.calculate(c, fr.FreightInputs.from_dict(data.get("inputs") or {}))
    return jsonable(res | {"contract_name": c.name})


@router.get("/rates/{cid}/history")
def rate_history(cid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("rates:read"))):
    c = db.get(RateContract, cid)
    if not c:
        raise AppError("Not found", 404)
    rows = db.query(RateContract).filter(RateContract.contract_no == c.contract_no).order_by(RateContract.version).all()
    return [jsonable({col.name: getattr(r, col.name) for col in RateContract.__table__.columns} | {"lr_count": db.query(Consignment).filter_by(rate_contract_id=r.id).count()}) for r in rows]


@router.post("/rates/{cid}/revise")
def rate_revise(cid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("rates:write", "rates:approve"))):
    from ..services.operations import parse_date

    changes = dict(data.get("changes") or {})
    for k in ("rate", "min_freight", "extra_trip_rate", "waiting_rate_per_hour", "detention_rate_per_day", "loading_charge", "unloading_charge", "extra_stop_charge", "return_load_value", "min_weight_kg", "waiting_free_hours", "detention_free_days"):
        if k in changes and changes[k] not in (None, ""):
            changes[k] = D(changes[k])
    if "effective_to" in changes:
        changes["effective_to"] = parse_date(changes["effective_to"])
    new = fr.revise(db, user, cid, changes, parse_date(data.get("effective_from")), data.get("reason") or "")
    db.commit()
    return {"id": new.id, "version": new.version}


# ------------------------------------------------------------------ LR

@router.get("/lr")
def list_lr(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    p = request.query_params
    q = db.query(Consignment)
    if p.get("q"):
        s = f"%{p['q']}%"
        q = q.filter(or_(Consignment.lr_no.ilike(s), Consignment.consignor_name.ilike(s), Consignment.consignee_name.ilike(s), Consignment.vehicle_no.ilike(s), Consignment.eway_bill_no.ilike(s), Consignment.customer_invoice_no.ilike(s)))
    for f in ("customer_id", "trip_id", "vehicle_id"):
        if p.get(f):
            q = q.filter(getattr(Consignment, f) == int(p[f]))
    if p.get("status"):
        q = q.filter(Consignment.status == p["status"])
    if p.get("unbilled"):
        q = q.filter(Consignment.invoice_id.is_(None), Consignment.status != "Cancelled")
    if p.get("from"):
        q = q.filter(Consignment.lr_date >= date.fromisoformat(p["from"]))
    if p.get("to"):
        q = q.filter(Consignment.lr_date <= date.fromisoformat(p["to"]))
    total = q.count()
    rows = q.order_by(Consignment.id.desc()).limit(min(int(p.get("limit") or 100), 1000)).offset(int(p.get("offset") or 0)).all()
    return {"total": total, "items": [_lr_out(db, l) for l in rows]}


@router.post("/lr")
def create_lr(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:write"))):
    lr, warnings = ops.create_lr(db, user, data)
    db.commit()
    return {"lr": _lr_out(db, lr, True), "warnings": warnings}


@router.get("/lr/{lid}")
def get_lr(lid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("LR not found", 404)
    return _lr_out(db, lr, True)


@router.post("/lr/{lid}/amend")
def amend_lr(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:amend"))):
    lr = ops.amend_lr(db, user, lid, data.get("changes") or {}, data.get("reason") or "", data.get("authorized_by") or "")
    db.commit()
    return _lr_out(db, lr, True)


@router.post("/lr/{lid}/cancel")
def cancel_lr(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:cancel"))):
    lr = ops.cancel_lr(db, user, lid, data.get("reason") or "")
    db.commit()
    return _lr_out(db, lr)


@router.post("/lr/{lid}/deliver")
def deliver_lr(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:write"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    ops.lr_delivered(db, user, lr, data.get("receiver_name"), data.get("receiver_phone"), data.get("remarks"), data.get("shortage_qty") or 0, data.get("damage_qty") or 0, ops.parse_dt(data.get("at")))
    db.commit()
    return _lr_out(db, lr)


@router.post("/lr/{lid}/pod")
def pod_lr(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:write"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    ops.lr_pod(db, user, lr, data.get("document_id"))
    db.commit()
    return _lr_out(db, lr)


def _lr_pdf_bytes(db: Session, lr: Consignment, fmt: str, copy: str | None) -> bytes:
    company = app_settings.company(db)
    cust = db.get(Customer, lr.customer_id)
    items = db.query(ConsignmentItem).filter_by(consignment_id=lr.id).order_by(ConsignmentItem.id).all()
    points = db.query(DeliveryPoint).filter_by(consignment_id=lr.id).order_by(DeliveryPoint.sequence).all()
    from ..services import layouts

    L = layouts.get(db, "lr")
    if copy == "first":
        copy = (L.get("copies") or ["Original"])[0]
    return pdf.lr_pdf(lr, company, cust, items, points, [copy] if copy else None, fmt, L, layouts.get(db, "thermal"))


@router.get("/lr/{lid}/pdf")
def lr_pdf(lid: int, fmt: str = "A4", copy: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    data = _lr_pdf_bytes(db, lr, fmt, copy)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="LR_{lr.lr_no.replace("/", "-")}.pdf"'})


@router.post("/lr/{lid}/share")
def share_lr(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    cust = db.get(Customer, lr.customer_id)
    text = f"LR {lr.lr_no} dt {lr.lr_date:%d-%m-%Y}: {lr.from_place} → {lr.to_place}, vehicle {lr.vehicle_no or '-'}. Verify: {pdf.verify_url('lr', lr.lr_no, lr.verify_token)}"
    channel = data.get("channel") or "whatsapp_link"
    if channel == "whatsapp_link":
        return {"status": "link", "url": channels.whatsapp_share_link(data.get("to") or (cust.whatsapp or cust.mobile if cust else None), text)}
    if channel == "email":
        to = data.get("to") or (cust.email if cust else None)
        if not to:
            raise AppError("No email address")
        status, err = channels.send_email(to, f"LR {lr.lr_no}", text, [(f"LR_{lr.lr_no.replace('/', '-')}.pdf", _lr_pdf_bytes(db, lr, "A4", "first"), "application/pdf")])
    elif channel == "whatsapp":
        status, err = channels.send_whatsapp(data.get("to") or (cust.whatsapp or cust.mobile), text)
    else:
        raise AppError("Unknown channel")
    from ..models import NotificationLog

    db.add(NotificationLog(event="lr_share", channel=channel, recipient=data.get("to"), body=text, status=status, error=err, entity="consignments", entity_id=str(lr.id)))
    db.commit()
    return {"status": status, "error": err}


@router.get("/lr/{lid}/ewaybill-json")
def lr_ewb_json(lid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:read"))):
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    return {"version": "1.0.0621", "billLists": [gst_portals.build_ewaybill_json(lr, app_settings.company(db))]}


@router.post("/lr/{lid}/ewaybill")
def lr_record_ewb(lid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("lr:write"))):
    """Record an e-way bill generated on the portal (or update Part-B vehicle). The API route is used when configured."""
    lr = db.get(Consignment, lid)
    if not lr:
        raise AppError("Not found", 404)
    from ..core.validators import validate

    ewb_no = str(data.get("ewb_no") or lr.eway_bill_no or "").replace(" ", "")
    err = validate("ewb", ewb_no)
    if err:
        raise AppError(err)
    gen = ops.parse_dt(data.get("ewb_date")) or datetime.now(timezone.utc)
    valid = ops.parse_dt(data.get("valid_until"))
    if not valid:
        days = gst_portals.ewb_validity_days(lr.distance_km)
        valid = (gen + timedelta(days=days)).replace(hour=23, minute=59, second=0)
    e = db.query(EwayBill).filter_by(ewb_no=ewb_no).first()
    if not e:
        e = EwayBill(ewb_no=ewb_no, ewb_date=gen, valid_until=valid, consignment_id=lr.id, vehicle_no=lr.vehicle_no, from_place=lr.from_place, to_place=lr.to_place, distance_km=lr.distance_km, goods_value=lr.goods_value, source="Manual (portal)", part_b_history=[], created_by=user.id)
        db.add(e)
    if data.get("vehicle_no") and data["vehicle_no"] != e.vehicle_no:
        if gst_portals.ewb_configured():
            try:
                gst_portals.update_part_b(ewb_no, data["vehicle_no"], data.get("reason") or "")
            except (gst_portals.PortalError, gst_portals.NotConfigured) as exc:
                raise AppError(str(exc))
        e.part_b_history = list(e.part_b_history or []) + [{"at": datetime.now(timezone.utc).isoformat(), "from": e.vehicle_no, "to": data["vehicle_no"], "reason": data.get("reason"), "by": user.username, "via": "recorded from portal"}]
        e.vehicle_no = data["vehicle_no"]
    if data.get("valid_until"):
        e.valid_until = valid
        e.status = "Extended" if e.status == "Active" and data.get("extended") else e.status
    lr.eway_bill_no, lr.eway_bill_date, lr.eway_valid_until = ewb_no, e.ewb_date.date(), e.valid_until
    log(db, user, "ewaybill", "consignments", lr.id, None, {"ewb_no": ewb_no, "valid_until": e.valid_until.isoformat()})
    db.commit()
    return jsonable({"ewb_no": e.ewb_no, "valid_until": e.valid_until, "part_b_history": e.part_b_history})


# ------------------------------------------------------------------ trips

def _trip_out(db: Session, t: Trip, full: bool = False) -> dict:
    out = {c.name: jsonable(getattr(t, c.name)) for c in Trip.__table__.columns}
    v = db.get(Vehicle, t.vehicle_id) if t.vehicle_id else None
    d = db.get(Driver, t.driver_id) if t.driver_id else None
    c = db.get(Customer, t.customer_id) if t.customer_id else None
    out.update({"vehicle_no": v.registration_no if v else None, "driver_name": d.name if d else None, "driver_mobile": d.mobile if d else None, "customer_name": c.name if c else None})
    exp = t.expected_delivery_at
    out["delayed"] = bool(exp and not t.delivered_at and exp < datetime.now(timezone.utc))
    if full:
        out["lrs"] = [_lr_out(db, l) for l in ops.trip_lrs(db, t.id)]
        out["expenses"] = [jsonable({c.name: getattr(e, c.name) for c in TripExpense.__table__.columns}) for e in db.query(TripExpense).filter_by(trip_id=t.id).order_by(TripExpense.id)]
        out["events"] = [jsonable({"at": e.at, "stage": e.stage, "note": e.note, "odometer": e.odometer, "lat": e.lat, "lng": e.lng}) for e in db.query(TripEvent).filter_by(trip_id=t.id).order_by(TripEvent.id)]
        out["pnl"] = jsonable(ops.trip_pnl(db, t))
        r = db.get(Route, t.route_id) if t.route_id else None
        out["route"] = jsonable({"code": r.code, "distance_km": r.distance_km, "via": r.via, "est_hours": r.est_hours, "est_toll": r.est_toll}) if r else None
        out["fastag"] = [jsonable({"at": f.txn_at, "plaza": f.plaza_name, "amount": f.amount}) for f in db.query(FastagTransaction).filter_by(trip_id=t.id)]
    return out


@router.get("/trips")
def list_trips(request: Request, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:read"))):
    p = request.query_params
    q = db.query(Trip)
    for f in ("customer_id", "vehicle_id", "driver_id"):
        if p.get(f):
            q = q.filter(getattr(Trip, f) == int(p[f]))
    if p.get("stage"):
        q = q.filter(Trip.stage.in_(p["stage"].split(",")))
    if p.get("open"):
        q = q.filter(Trip.stage.in_(ops.OPEN_STAGES))
    if p.get("from"):
        q = q.filter(Trip.trip_date >= date.fromisoformat(p["from"]))
    if p.get("to"):
        q = q.filter(Trip.trip_date <= date.fromisoformat(p["to"]))
    if p.get("q"):
        q = q.filter(or_(Trip.trip_no.ilike(f"%{p['q']}%"), Trip.from_place.ilike(f"%{p['q']}%"), Trip.to_place.ilike(f"%{p['q']}%")))
    total = q.count()
    rows = q.order_by(Trip.id.desc()).limit(min(int(p.get("limit") or 100), 1000)).offset(int(p.get("offset") or 0)).all()
    return {"total": total, "items": [_trip_out(db, t) for t in rows]}


@router.post("/trips")
def create_trip(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    t = ops.create_trip(db, user, data)
    db.commit()
    return _trip_out(db, t, True)


@router.get("/trips/{tid}")
def get_trip(tid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:read"))):
    t = db.get(Trip, tid)
    if not t:
        raise AppError("Trip not found", 404)
    return _trip_out(db, t, True)


@router.put("/trips/{tid}")
def update_trip(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    t = db.get(Trip, tid)
    if not t:
        raise AppError("Trip not found", 404)
    if t.stage in ("Closed", "Billed", "Settled", "Cancelled"):
        raise AppError("Closed trips cannot be edited")
    before = {f: jsonable(getattr(t, f)) for f in ("expected_delivery_at", "remarks", "start_km", "customer_id", "route_id")}
    for f in ("remarks", "from_place", "to_place"):
        if f in data:
            setattr(t, f, data[f])
    for f in ("customer_id", "route_id", "co_driver_id"):
        if f in data:
            setattr(t, f, int(data[f]) if data[f] else None)
    if "expected_delivery_at" in data:
        t.expected_delivery_at = ops.parse_dt(data["expected_delivery_at"])
    if "start_km" in data and not t.dispatched_at:
        t.start_km = D(data["start_km"]) if data["start_km"] not in (None, "") else None
    if data.get("vehicle_id") or data.get("driver_id"):
        ops.allocate(db, user, t, int(data["vehicle_id"]) if data.get("vehicle_id") else None, int(data["driver_id"]) if data.get("driver_id") else None)
    log(db, user, "update", "trips", t.id, before, {f: jsonable(getattr(t, f)) for f in before})
    db.commit()
    return _trip_out(db, t, True)


@router.post("/trips/{tid}/stage")
def trip_stage(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    t = db.get(Trip, tid)
    if not t:
        raise AppError("Trip not found", 404)
    ops.advance(db, user, t, data.get("stage"), data)
    db.commit()
    return _trip_out(db, t, True)


@router.post("/trips/{tid}/cancel")
def trip_cancel(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    t = db.get(Trip, tid)
    if not t:
        raise AppError("Trip not found", 404)
    ops.cancel_trip(db, user, t, data.get("reason") or "")
    db.commit()
    return _trip_out(db, t)


@router.post("/trips/{tid}/expenses")
def add_expense(tid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    t = db.get(Trip, tid)
    if not t:
        raise AppError("Trip not found", 404)
    ops.add_trip_expense(db, user, t, data)
    db.commit()
    return _trip_out(db, t, True)


@router.delete("/trips/{tid}/expenses/{eid}")
def remove_expense(tid: int, eid: int, reason: str = "", db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write", "accounts:cancel"))):
    e = db.get(TripExpense, eid)
    if not e or e.trip_id != tid:
        raise AppError("Not found", 404)
    ops.delete_trip_expense(db, user, e, reason or "Removed")
    db.commit()
    return {"ok": True}


@router.post("/trips/{tid}/approve-expense/{eid}")
def approve_expense(tid: int, eid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    e = db.get(TripExpense, eid)
    if not e or e.trip_id != tid:
        raise AppError("Not found", 404)
    e.approved = True
    log(db, user, "approve", "trip_expenses", e.id)
    db.commit()
    return {"ok": True}


@router.post("/bookings/{bid}/convert")
def convert_booking(bid: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    b = db.get(Booking, bid)
    if not b or b.status not in ("Requested", "Confirmed"):
        raise AppError("Booking is not open")
    route = db.get(Route, b.route_id) if b.route_id else None
    t = ops.create_trip(db, user, {"trip_date": data.get("trip_date") or b.required_date, "customer_id": b.customer_id, "route_id": b.route_id, "booking_id": b.id,
                                   "from_place": data.get("from_place") or (route.origin if route else b.pickup_address[:120]), "to_place": data.get("to_place") or (route.destination if route else b.drop_address[:120]),
                                   "vehicle_id": data.get("vehicle_id"), "driver_id": data.get("driver_id"), "remarks": b.remarks})
    db.commit()
    return _trip_out(db, t, True)


@router.get("/fleet/availability")
def availability(db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:read"))):
    vehicles = []
    for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).order_by(Vehicle.registration_no):
        t = db.query(Trip).filter(Trip.vehicle_id == v.id, Trip.stage.in_(ops.OPEN_STAGES)).order_by(Trip.id.desc()).first()
        vehicles.append({"id": v.id, "registration_no": v.registration_no, "vehicle_type": v.vehicle_type, "status": v.status, "payload_kg": jsonable(v.payload_kg), "branch_id": v.branch_id, "odometer": jsonable(v.current_odometer),
                         "trip": {"id": t.id, "trip_no": t.trip_no, "stage": t.stage, "to": t.to_place} if t else None})
    drivers = [{"id": d.id, "name": d.name, "mobile": d.mobile, "status": d.status, "licence_expiry": jsonable(d.licence_expiry)} for d in db.query(Driver).filter(Driver.is_active.is_(True), Driver.employment_status == "Active").order_by(Driver.name)]
    return {"vehicles": vehicles, "drivers": drivers}


# ------------------------------------------------------------------ fuel

@router.post("/fuel")
def add_fuel(data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fuel:write"))):
    fe = ops.record_fuel(db, user, data)
    db.commit()
    return {"id": fe.id, "amount": jsonable(fe.amount)}


@router.get("/fuel/mileage/{vehicle_id}")
def vehicle_mileage(vehicle_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("fuel:read"))):
    return jsonable(ops.mileage(db, vehicle_id))


# ------------------------------------------------------------------ driver settlement

@router.get("/drivers/{did}/settlement-preview")
def settlement_preview(did: int, upto: str | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("drivers:read"))):
    return jsonable(ops.settlement_preview(db, did, date.fromisoformat(upto) if upto else date.today()))


@router.post("/drivers/{did}/settle")
def settle(did: int, data: dict, db: Session = Depends(get_db), user: CurrentUser = Depends(require("drivers:write", "accounts:write"))):
    s = ops.post_settlement(db, user, did, date.fromisoformat(str(data.get("upto") or date.today())[:10]), data.get("trip_ids"), data.get("other_deductions") or 0, data.get("pay_mode"), data.get("bank_ledger_id"), data.get("remarks"))
    db.commit()
    return jsonable({"id": s.id, "settlement_no": s.settlement_no, "net_payable": s.net_payable, "status": s.status})


@router.get("/driver-settlements")
def list_settlements(driver_id: int | None = None, db: Session = Depends(get_db), user: CurrentUser = Depends(require("drivers:read"))):
    q = db.query(DriverSettlement)
    if driver_id:
        q = q.filter_by(driver_id=driver_id)
    names = {d.id: d.name for d in db.query(Driver)}
    return [jsonable({c.name: getattr(s, c.name) for c in DriverSettlement.__table__.columns if c.name != "details"} | {"driver": names.get(s.driver_id)}) for s in q.order_by(DriverSettlement.id.desc()).limit(500)]


@router.get("/drivers/{did}/salary")
def driver_salary_estimate(did: int, month: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require("drivers:read", "hr:salary"))):
    import calendar

    from ..services.people import _paid_days

    d = db.get(Driver, did)
    y, m = int(month[:4]), int(month[5:7])
    start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
    paid, marked = _paid_days(db, "driver", did, start, end)
    dim = (end - start).days + 1
    trips = db.query(Trip).filter(Trip.driver_id == did, Trip.trip_date.between(start, end), Trip.stage != "Cancelled").count()
    return jsonable({"driver": d.name, "month": month, "monthly_salary": d.monthly_salary, "paid_days": paid, "days": dim, "attendance_marked": marked, "salary": r2(D(d.monthly_salary) * paid / dim), "trips": trips})


# ------------------------------------------------------------------ FASTag import & matching

@router.post("/fastag/import")
async def fastag_import(file: UploadFile = File(...), provider: str = "", db: Session = Depends(get_db), user: CurrentUser = Depends(require("routes:write"))):
    from ..services.exports import pick, read_table

    rows = read_table(file.filename or "", await file.read())
    batch = uuid.uuid4().hex[:10]
    vehicles = {v.registration_no: v.id for v in db.query(Vehicle)}
    added, skipped, errors = 0, 0, []
    for i, r in enumerate(rows, 2):
        txn = pick(r, "transaction id", "txn id", "transactionid", "reference no", "unique transaction id", "txnid")
        when = pick(r, "transaction date time", "txn date", "transaction date", "date time", "date", "processing date")
        veh = pick(r, "vehicle number", "vehicle no", "vrn", "vehicle reg no", "vehicle")
        amt = pick(r, "amount", "txn amount", "transaction amount", "debit", "toll amount")
        plaza = pick(r, "plaza name", "toll plaza", "plaza", "location", "description")
        typ = (pick(r, "type", "txn type", "dr/cr", "transaction type") or "Debit")
        if not (txn and when and veh and amt):
            errors.append(f"Row {i}: missing transaction id / date / vehicle / amount")
            continue
        if db.query(FastagTransaction).filter_by(txn_id=str(txn)).first():
            skipped += 1
            continue
        try:
            dt = when if isinstance(when, datetime) else None
            if dt is None:
                s = str(when).strip()
                for fmt in ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(s, fmt)
                        break
                    except ValueError:
                        continue
            if dt is None:
                raise ValueError(f"unrecognised date '{when}'")
            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30))) if dt.tzinfo is None else dt
            amount = abs(D(str(amt).replace(",", "")))
        except (ValueError, ArithmeticError) as exc:
            errors.append(f"Row {i}: {exc}")
            continue
        vno = str(veh).upper().replace(" ", "").replace("-", "")
        kind = "Credit" if str(typ).strip().lower() in ("cr", "credit", "recharge", "refund") else "Debit"
        f = FastagTransaction(txn_id=str(txn), txn_at=dt, vehicle_no=vno, vehicle_id=vehicles.get(vno), plaza_name=str(plaza or "")[:200], amount=amount, txn_type=kind, provider=provider or None, import_batch=batch, imported_at=datetime.now(timezone.utc))
        db.add(f)
        added += 1
    db.flush()
    matched = match_fastag(db)
    log(db, user, "import", "fastag_transactions", batch, None, {"added": added, "skipped": skipped, "matched": matched, "errors": len(errors)})
    db.commit()
    return {"added": added, "duplicates_skipped": skipped, "matched_to_trips": matched, "errors": errors[:50]}


def match_fastag(db: Session) -> int:
    n = 0
    for f in db.query(FastagTransaction).filter(FastagTransaction.trip_id.is_(None), FastagTransaction.vehicle_id.is_not(None)):
        t = db.query(Trip).filter(Trip.vehicle_id == f.vehicle_id, Trip.dispatched_at.is_not(None), Trip.dispatched_at <= f.txn_at,
                                  or_(Trip.closed_at.is_(None), Trip.closed_at >= f.txn_at)).order_by(Trip.dispatched_at.desc()).first()
        if t:
            f.trip_id, f.match_status = t.id, "Matched"
            n += 1
        else:
            f.match_status = "No trip"
    return n


@router.get("/fastag")
def fastag_list(vehicle_id: int | None = None, unmatched: bool = False, db: Session = Depends(get_db), user: CurrentUser = Depends(require("routes:read"))):
    q = db.query(FastagTransaction)
    if vehicle_id:
        q = q.filter_by(vehicle_id=vehicle_id)
    if unmatched:
        q = q.filter(FastagTransaction.trip_id.is_(None))
    trips = {t.id: t.trip_no for t in db.query(Trip)}
    return [jsonable({c.name: getattr(f, c.name) for c in FastagTransaction.__table__.columns} | {"trip_no": trips.get(f.trip_id)}) for f in q.order_by(FastagTransaction.txn_at.desc()).limit(1000)]


@router.post("/fastag/{fid}/post-to-trip")
def fastag_post(fid: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require("trips:write"))):
    """Book a matched FASTag debit as a trip toll expense (paid from FASTag wallet)."""
    f = db.get(FastagTransaction, fid)
    if not f or not f.trip_id or f.txn_type != "Debit":
        raise AppError("Only matched debits can be posted")
    if f.match_status == "Posted":
        raise AppError("Already posted")
    t = db.get(Trip, f.trip_id)
    ops.add_trip_expense(db, user, t, {"category": "Toll", "amount": f.amount, "paid_by": "FASTag", "expense_date": f.txn_at.date(), "remarks": f"FASTag {f.plaza_name}", "bill_no": f.txn_id})
    f.match_status = "Posted"
    db.commit()
    return {"ok": True}
