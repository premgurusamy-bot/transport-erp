"""Allocation, dispatch, trip operations, GPS, camera, custody, POD, LR/e-way, owner offers, consolidation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.crud import get_or_404, to_dict
from app.core.db import utcnow
from app.core.deps import Principal, current_principal, get_db, require, require_any
from app.core.errors import AppError, BlockedByRule, Conflict, Forbidden, NotFound
from app.core.notify import queue
from app.core.security import new_otp, otp_hash
from app.core.services import raise_exception_task
from app.integrations.adapters import get_adapter
from app.modules.commercial.models import Booking, Package
from app.modules.fleet.models import Driver, Vehicle
from app.modules.masters.models import Contact, Location
from app.modules.operations import service as ops
from app.modules.operations.access import assert_booking_access, assert_trip_access
from app.modules.operations.lr import amend_lr, ensure_eway
from app.modules.operations.models import (
    CustodyEvent, LorryReceipt, OwnerOffer, ProofOfDelivery, Trip, TripEvent, TripLoad,
)
from app.modules.platform.models import OtpChallenge

router = APIRouter(prefix="/api/v1", tags=["operations"])


def trip_out(db: Session, t: Trip, *, for_customer_id=None) -> dict:
    d = to_dict(t)
    v = db.get(Vehicle, t.vehicle_id)
    dr = db.get(Driver, t.driver_id) if t.driver_id else None
    d["vehicle_registration"] = v.registration if v else None
    d["driver_name"] = dr.name if dr else None
    d["driver_phone"] = dr.phone if dr else None
    loads = []
    for tl in db.execute(select(TripLoad).where(TripLoad.trip_id == t.id, TripLoad.status != "removed").order_by(TripLoad.pickup_seq)).scalars():
        b = db.get(Booking, tl.booking_id)
        if for_customer_id and b.customer_id != for_customer_id:
            continue  # PTL confidentiality: other customers' loads are never shown
        o, de = db.get(Location, b.origin_id), db.get(Location, b.destination_id)
        loads.append({**to_dict(tl), "booking_code": b.code, "origin": o.city, "destination": de.city,
                      "consignee": b.consignee_name, "consignee_phone": b.consignee_phone, "packages": b.package_count,
                      "weight_kg": b.weight_kg, "instructions": b.instructions, "booking_status": b.status})
    d["loads"] = loads
    if for_customer_id:
        for k in ("owner_hire_amount", "owner_advance", "allocation_checks", "override", "load_plan", "owner_id",
                  "driver_phone", "start_odometer", "end_odometer"):
            d.pop(k, None)
    return d


# ===================================================================== allocation & trips
class AllocIn(BaseModel):
    booking_ids: list[uuid.UUID] = Field(min_length=1)
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID | None = None
    planned_start: datetime | None = None


@router.post("/allocation/check")
def allocation_check(body: AllocIn, p: Principal = Depends(require("dispatch.plan")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    d = db.get(Driver, body.driver_id) if body.driver_id else None
    bs = [get_or_404(db, Booking, i, "Booking") for i in body.booking_ids]
    checks = ops.allocation_checks(db, vehicle=v, driver=d, bookings=bs, planned_start=body.planned_start)
    fails = ops.blocking_failures(checks, None)
    return {"checks": checks, "can_allocate": not fails,
            "overridable": [c["check"] for c in fails if c["severity"] == "commercial"],
            "blocking": [c for c in fails if c["severity"] != "commercial"]}


@router.get("/allocation/candidates/{booking_id}")
def candidates(booking_id: uuid.UUID, p: Principal = Depends(require("dispatch.plan")), db: Session = Depends(get_db)):
    """Rank available vehicles/drivers for a booking by passing checks (AI-free deterministic recommendation)."""
    b = get_or_404(db, Booking, booking_id, "Booking")
    out = []
    drivers = list(db.execute(select(Driver).where(Driver.is_active.is_(True), Driver.status == "available")).scalars())
    for v in db.execute(select(Vehicle).where(Vehicle.is_active.is_(True))).scalars():
        best = None
        for d in [x for x in drivers if (v.ownership == "own" and x.category == "company") or (v.ownership == "attached" and x.owner_id == v.owner_id)] or [None]:
            checks = ops.allocation_checks(db, vehicle=v, driver=d, bookings=[b], planned_start=b.pickup_from)
            fails = ops.blocking_failures(checks, None)
            score = (len(fails), 0 if v.ownership == "own" else 1)
            if best is None or score < best[0]:
                best = (score, d, fails)
        out.append({"vehicle_id": str(v.id), "registration": v.registration, "ownership": v.ownership, "payload_kg": v.payload_kg,
                    "driver_id": str(best[1].id) if best[1] else None, "driver": best[1].name if best[1] else None,
                    "failures": best[2], "eligible": not best[2]})
    return sorted(out, key=lambda x: (not x["eligible"], len(x["failures"])))


class TripIn(AllocIn):
    owner_hire_amount: Decimal | None = Field(None, ge=0)
    override_checks: list[str] | None = None
    override_reason: str | None = None


@router.post("/trips")
def post_trip(body: TripIn, p: Principal = Depends(require("dispatch.plan")), db: Session = Depends(get_db)):
    t, checks = ops.create_trip(db, p, booking_ids=body.booking_ids, vehicle_id=body.vehicle_id, driver_id=body.driver_id,
                                planned_start=body.planned_start, owner_hire_amount=body.owner_hire_amount,
                                override_checks=body.override_checks, override_reason=body.override_reason)
    if t.driver_id:
        d = db.get(Driver, t.driver_id)
        queue(db, channel="sms", recipient=d.phone, template="duty_offer", code=t.code, lane=", ".join(l["origin"] + "→" + l["destination"] for l in trip_out(db, t)["loads"]))
    return trip_out(db, t)


@router.get("/trips")
def list_trips(status: str | None = None, p: Principal = Depends(require("trip.read")), db: Session = Depends(get_db)):
    q = select(Trip).order_by(Trip.created_at.desc()).limit(500)
    if status:
        q = q.where(Trip.status.in_(status.split(",")))
    return [trip_out(db, t) for t in db.execute(q).scalars()]


@router.get("/trips/{tid}")
def get_trip(tid: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    assert_trip_access(db, p, t)
    out = trip_out(db, t)
    out["events"] = [to_dict(e) for e in db.execute(select(TripEvent).where(TripEvent.trip_id == t.id).order_by(TripEvent.occurred_at)).scalars()]
    if p.can("gps.view") or (p.driver_id and t.driver_id == p.driver_id):
        out["position"] = ops.position(db, t.vehicle_id, t.id)
    if p.is_internal:
        out["readiness"] = ops.dispatch_readiness(db, t) if t.status in ("planned", "ready") else None
    return out


@router.get("/trips/{tid}/readiness")
def readiness(tid: uuid.UUID, p: Principal = Depends(require("trip.read")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    r = ops.dispatch_readiness(db, t)
    fails = ops.blocking_failures(r, t.override)
    return {"checks": r, "ready": not fails, "blocking": fails}


class EwayIn(BaseModel):
    booking_id: uuid.UUID
    use_provider: bool = True
    number: str | None = None
    valid_until: datetime | None = None


@router.post("/trips/{tid}/eway")
def trip_eway(tid: uuid.UUID, body: EwayIn, p: Principal = Depends(require("lr.write")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    b = get_or_404(db, Booking, body.booking_id, "Booking")
    v = db.get(Vehicle, t.vehicle_id)
    ew = ensure_eway(db, p, b, v.registration, float(t.planned_km or 100), use_provider=body.use_provider and not body.number)
    if body.number:
        ew.number, ew.valid_until, ew.status, ew.source, ew.vehicle_registration = body.number, body.valid_until, "active", "manual", v.registration
        ew.valid_from = utcnow()
    write_audit(db, actor=p, action="eway.update", entity="booking", entity_id=b.id, after={"number": ew.number, "source": ew.source})
    return {**to_dict(ew), "mode_label": "MOCK e-way bill - not filed on the GST portal" if ew.source == "provider_mock" else None}


class AckIn(BaseModel):
    gps_consent: bool


@router.post("/trips/{tid}/acknowledge")
def acknowledge(tid: uuid.UUID, body: AckIn, p: Principal = Depends(require("driver.app")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    assert_trip_access(db, p, t)
    t.driver_ack_at = utcnow()
    if body.gps_consent:
        t.gps_consent_at = utcnow()
    write_audit(db, actor=p, action="trip.driver_ack", entity="trip", entity_id=t.id, after={"gps_consent": body.gps_consent})
    return {"ok": True, "gps_notice": "Your phone location is shared with G ROAD LINES only during this authorised trip."}


class DispatchIn(BaseModel):
    start_odometer: int | None = Field(None, ge=0)
    note: str | None = None


@router.post("/trips/{tid}/dispatch")
def dispatch(tid: uuid.UUID, body: DispatchIn, p: Principal = Depends(require("dispatch.authorize")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip", lock=True)
    if t.status not in ("planned", "ready"):
        raise Conflict("bad_status", f"Trip is {t.status}")
    checks = ops.dispatch_readiness(db, t)
    fails = ops.blocking_failures(checks, t.override)
    if fails:
        raise BlockedByRule("dispatch_blocked", "Dispatch blocked by mandatory checks", details=fails)
    v = db.get(Vehicle, t.vehicle_id)
    if t.fleet_type == "own" and body.start_odometer is None:
        raise AppError("odometer_required", "Start odometer required")
    if body.start_odometer is not None and body.start_odometer < v.odometer_km:
        raise AppError("odometer", f"Start odometer {body.start_odometer} is below last recorded {v.odometer_km}")
    t.status, t.actual_start, t.start_odometer = "dispatched", utcnow(), body.start_odometer
    t.dispatch_authorized_by, t.dispatch_authorized_at = p.user_id, utcnow()
    t.eta, t.eta_source = t.planned_start + timedelta(days=max(1, int(float(t.planned_km or 0) // 350) + 1)), "planned"
    v.status = "transit"
    if t.driver_id:
        d = db.get(Driver, t.driver_id)
        d.status, d.duty_started_at = "on_trip", utcnow()
    for tl in db.execute(select(TripLoad).where(TripLoad.trip_id == t.id, TripLoad.status != "removed")).scalars():
        tl.status = "loaded"
        b = db.get(Booking, tl.booking_id)
        b.status = "dispatched"
        for lr in db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id, LorryReceipt.status != "cancelled")).scalars():
            if lr.content.get("vehicle") != v.registration:
                lr.content = {**lr.content, "vehicle": v.registration}
            lr.trip_id = t.id
        contact = db.execute(select(Contact).where(Contact.customer_id == b.customer_id)).scalars().first()
        if contact and (contact.phone or contact.email):
            queue(db, channel="sms" if contact.phone else "email", recipient=contact.phone or contact.email, template="trip_dispatched",
                  code=b.code, vehicle=v.registration, entity="booking", entity_id=b.id)
    db.add(TripEvent(trip_id=t.id, event="dispatched", occurred_at=utcnow(), by_user=p.user_id, source="office",
                     customer_visible=True, note=body.note))
    write_audit(db, actor=p, action="trip.dispatch", entity="trip", entity_id=t.id, after={"odometer": body.start_odometer})
    return trip_out(db, t)


class EventIn(BaseModel):
    event: str = Field(pattern="^(arrived_pickup|loading_started|loaded|departed|checkpoint|delay|breakdown|accident|sos|arrived_drop|unloading|waiting|note|rest_start|rest_end)$")
    booking_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    lat: float | None = None
    lng: float | None = None
    note: str | None = None
    delay_minutes: int | None = None
    source: str = "app"


def record_event(db: Session, p: Principal, t: Trip, body: EventIn) -> TripEvent:
    customer_visible = body.event in ("arrived_pickup", "loaded", "departed", "delay", "arrived_drop")
    e = TripEvent(trip_id=t.id, booking_id=body.booking_id, event=body.event, occurred_at=body.occurred_at or utcnow(),
                  lat=body.lat, lng=body.lng, note=body.note, by_user=p.user_id, source=body.source,
                  customer_visible=customer_visible, data={"delay_minutes": body.delay_minutes} if body.delay_minutes else None)
    db.add(e)
    if body.event == "departed" and t.status == "dispatched":
        t.status = "in_transit"
        for tl in db.execute(select(TripLoad).where(TripLoad.trip_id == t.id)).scalars():
            b = db.get(Booking, tl.booking_id)
            if b.status == "dispatched":
                b.status = "in_transit"
    if body.event == "delay":
        t.delay_minutes += int(body.delay_minutes or 0)
        if t.eta:
            t.eta, t.eta_source = t.eta + timedelta(minutes=int(body.delay_minutes or 0)), "manual"
        raise_exception_task(db, severity="medium", title=f"Delay on trip {t.code}: {body.note or ''}"[:240], entity="trip",
                             entity_id=t.id, source="driver_event", owner_role="customer_support")
    if body.event in ("breakdown", "accident", "sos"):
        sev = "critical" if body.event in ("accident", "sos") else "high"
        raise_exception_task(db, severity=sev, title=f"{body.event.upper()} on trip {t.code}", entity="trip", entity_id=t.id,
                             source="driver_event", owner_role="operations_manager", blocking=body.event != "breakdown",
                             detail=f"{body.note or ''} at {body.lat},{body.lng}")
        from app.modules.risk.models import Incident
        from app.core.services import next_number
        if body.event in ("accident", "breakdown"):
            db.add(Incident(code=next_number(db, "INC", "INC"), kind=body.event, severity=sev, occurred_at=e.occurred_at,
                            lat=body.lat, lng=body.lng, vehicle_id=t.vehicle_id, driver_id=t.driver_id, trip_id=t.id,
                            description=body.note or body.event, source="driver_app", reported_by=p.user_id))
    if body.event == "rest_end" and t.driver_id:
        db.get(Driver, t.driver_id).last_rest_ended_at = e.occurred_at
    db.flush()
    return e


@router.post("/trips/{tid}/events")
def post_event(tid: uuid.UUID, body: EventIn, p: Principal = Depends(require_any("trip.update", "driver.app")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    assert_trip_access(db, p, t, write=True)
    if t.status not in ("dispatched", "in_transit", "planned", "ready", "delivered"):
        raise Conflict("bad_status", f"Trip is {t.status}")
    return to_dict(record_event(db, p, t, body))


class CloseIn(BaseModel):
    end_odometer: int | None = None


@router.post("/trips/{tid}/close")
def post_close(tid: uuid.UUID, body: CloseIn, p: Principal = Depends(require("trip.close")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip", lock=True)
    res = ops.close_trip(db, p, t, body.end_odometer)
    from app.modules.fleet.drivers import calculate_trip_earning
    if t.driver_id and t.fleet_type == "own":
        res["driver_earning"] = calculate_trip_earning(db, p, t)
    return {**res, "trip": trip_out(db, t)}


class CancelTripIn(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/trips/{tid}/cancel")
def cancel_trip(tid: uuid.UUID, body: CancelTripIn, p: Principal = Depends(require("dispatch.plan")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip", lock=True)
    if t.status not in ("planned", "ready"):
        raise BlockedByRule("not_cancellable", "Only planned trips can be cancelled; dispatched trips need an exception/transfer workflow")
    t.status, t.cancel_reason, t.exclusive_booking_id = "cancelled", body.reason, None
    for tl in db.execute(select(TripLoad).where(TripLoad.trip_id == t.id, TripLoad.status == "planned")).scalars():
        tl.status = "removed"
        b = db.get(Booking, tl.booking_id)
        if b.status == "planned":
            b.status = "confirmed"
    ops.release_trip_resources(db, t)
    write_audit(db, actor=p, action="trip.cancel", entity="trip", entity_id=t.id, reason=body.reason)
    return trip_out(db, t)


# ===================================================================== GPS & camera
class PingIn(BaseModel):
    trip_id: uuid.UUID
    lat: float
    lng: float
    recorded_at: datetime
    speed_kmph: float | None = None
    accuracy_m: float | None = None


@router.post("/gps/ping")
def phone_ping(body: PingIn, p: Principal = Depends(require("driver.app")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, body.trip_id, "Trip")
    assert_trip_access(db, p, t, write=True)
    if t.status not in ("dispatched", "in_transit"):
        raise BlockedByRule("not_on_trip", "Location is collected only during an authorised active trip")
    if not t.gps_consent_at:
        raise BlockedByRule("no_consent", "GPS notice/consent not recorded for this trip")
    ops.record_ping(db, vehicle_id=t.vehicle_id, trip_id=t.id, source="phone", lat=body.lat, lng=body.lng,
                    recorded_at=body.recorded_at, speed=body.speed_kmph, accuracy=body.accuracy_m)
    return {"ok": True}


class TrackerPingIn(BaseModel):
    device_id: str
    lat: float
    lng: float
    recorded_at: datetime
    speed_kmph: float | None = None


@router.post("/gps/tracker-webhook")
def tracker_ping(body: TrackerPingIn, x_tracker_key: str | None = Header(None), db: Session = Depends(get_db)):
    """Dedicated tracker feed (own vehicles). Authenticated by a shared key set in GRL_TRACKER_KEY (MOCK until vendor verified)."""
    import os
    key = os.environ.get("GRL_TRACKER_KEY", "dev-tracker-key" if not get_settings().is_production else None)
    if not key or x_tracker_key != key:
        raise Forbidden("Invalid tracker key")
    v = db.execute(select(Vehicle).where(Vehicle.gps_device_id == body.device_id)).scalar_one_or_none()
    if not v:
        raise NotFound("Device")
    t = db.execute(select(Trip).where(Trip.vehicle_id == v.id, Trip.status.in_(("dispatched", "in_transit")))).scalars().first()
    ops.record_ping(db, vehicle_id=v.id, trip_id=t.id if t else None, source="tracker", lat=body.lat, lng=body.lng,
                    recorded_at=body.recorded_at, speed=body.speed_kmph)
    return {"ok": True}


@router.get("/vehicles/{vid}/position")
def vehicle_position(vid: uuid.UUID, p: Principal = Depends(require("gps.view")), db: Session = Depends(get_db)):
    get_or_404(db, Vehicle, vid, "Vehicle")
    return ops.position(db, vid)


@router.post("/vehicles/{vid}/camera/{channel}/live")
def camera_live(vid: uuid.UUID, channel: int, p: Principal = Depends(require("camera.view")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, vid, "Vehicle")
    if not v.dvr_device_id:
        raise AppError("no_camera", "No DVR registered for this vehicle")
    if v.ownership == "attached" and not v.camera_permission:
        raise Forbidden("Owner has not permitted camera access for this attached vehicle")
    if channel not in (1, 2):
        raise AppError("bad_channel", "Channel 1 = road-facing, 2 = cargo-facing")
    res = get_adapter("camera").live_stream(v.dvr_device_id, channel)
    write_audit(db, actor=p, action="camera.live", entity="vehicle", entity_id=v.id, after={"channel": channel, "mode": res.mode})
    return {**res.data, "mode": res.mode}


# ===================================================================== custody & scans
class CustodyIn(BaseModel):
    booking_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    event: str = Field(pattern="^(pickup_inspection|loaded|seal_applied|seal_checked|handover|godown_in|godown_out|unloaded|exception)$")
    package_count: int | None = Field(None, ge=0)
    condition: str | None = Field(None, pattern="^(good|damaged|wet|open|leaking)$")
    seal_number: str | None = None
    from_party: str | None = None
    to_party: str | None = None
    note: str | None = None
    photo_document_ids: list[uuid.UUID] = []
    lat: float | None = None
    lng: float | None = None
    occurred_at: datetime | None = None
    facility_id: uuid.UUID | None = None
    handler_vendor_id: uuid.UUID | None = None


@router.post("/custody")
def post_custody(body: CustodyIn, p: Principal = Depends(require_any("custody.write", "driver.app")), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, body.booking_id, "Booking")
    assert_booking_access(db, p, b)
    t = None
    if body.trip_id:
        t = get_or_404(db, Trip, body.trip_id, "Trip")
        assert_trip_access(db, p, t, write=True)
    if body.event in ("godown_in", "godown_out") and body.facility_id:
        from app.modules.masters.models import Facility
        f = get_or_404(db, Facility, body.facility_id, "Facility")
        if not f.verified:
            raise BlockedByRule("facility_unverified", f"{f.name} is not a verified facility for custody")
    ev = ops.record_custody(db, p, booking=b, trip=t, event=body.event, package_count=body.package_count, condition=body.condition,
                            seal_number=body.seal_number, from_party=body.from_party, to_party=body.to_party, note=body.note,
                            photo_ids=[str(x) for x in body.photo_document_ids], lat=body.lat, lng=body.lng,
                            occurred_at=body.occurred_at, facility_id=body.facility_id, handler_vendor_id=body.handler_vendor_id)
    return to_dict(ev)


@router.get("/bookings/{bid}/custody")
def custody_chain(bid: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    assert_booking_access(db, p, b)
    return [to_dict(e) for e in db.execute(select(CustodyEvent).where(CustodyEvent.booking_id == b.id).order_by(CustodyEvent.occurred_at)).scalars()]


class ScanIn(BaseModel):
    label: str
    trip_id: uuid.UUID | None = None
    stage: str = Field(pattern="^(picked|godown_in|godown_out|loaded|unloaded|delivered)$")
    occurred_at: datetime | None = None
    client_event_id: str | None = None


@router.post("/scans")
def post_scan(body: ScanIn, p: Principal = Depends(require_any("custody.write", "driver.app")), db: Session = Depends(get_db)):
    t = None
    if body.trip_id:
        t = get_or_404(db, Trip, body.trip_id, "Trip")
        assert_trip_access(db, p, t, write=True)
    s = ops.scan_package(db, p, label=body.label, trip=t, stage=body.stage, occurred_at=body.occurred_at, client_event_id=body.client_event_id)
    return to_dict(s)


@router.get("/bookings/{bid}/labels")
def labels(bid: uuid.UUID, p: Principal = Depends(require("booking.read")), db: Session = Depends(get_db)):
    """QR label payloads (the QR encodes only the opaque label, never customer details)."""
    b = get_or_404(db, Booking, bid, "Booking")
    d = db.get(Location, b.destination_id)
    return [{"label": x.label, "qr": x.label, "seq": f"{x.seq}/{b.package_count}", "to_city": d.city, "fragile": x.fragile}
            for x in db.execute(select(Package).where(Package.booking_id == b.id).order_by(Package.seq)).scalars()]


# ===================================================================== POD
class PodOtpIn(BaseModel):
    trip_id: uuid.UUID
    booking_id: uuid.UUID


@router.post("/pod/otp")
def pod_otp(body: PodOtpIn, p: Principal = Depends(require_any("custody.write", "driver.app")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, body.trip_id, "Trip")
    assert_trip_access(db, p, t, write=True)
    b = get_or_404(db, Booking, body.booking_id, "Booking")
    if not b.consignee_phone:
        raise AppError("no_phone", "Consignee phone not recorded - use signature/photo POD")
    otp = new_otp()
    db.add(OtpChallenge(purpose="pod", target=str(b.id), otp_hash=otp_hash(otp, "pod"), expires_at=utcnow() + timedelta(minutes=30)))
    queue(db, channel="sms", recipient=b.consignee_phone, template="pod_otp", code=b.code, otp=otp, entity="booking", entity_id=b.id)
    out = {"sent_to": "consignee phone on record"}
    if get_settings().expose_dev_otp:
        out["dev_otp"] = otp
    return out


class PodIn(BaseModel):
    trip_id: uuid.UUID
    booking_id: uuid.UUID
    delivered_count: int = Field(ge=0)
    receiver_name: str = Field(min_length=2)
    receiver_phone: str | None = None
    otp: str | None = None
    signature_document_id: uuid.UUID | None = None
    photo_document_ids: list[uuid.UUID] = []
    condition: str = Field("good", pattern="^(good|damaged|wet|open|short)$")
    remarks: str | None = None
    delivered_at: datetime | None = None
    lat: float | None = None
    lng: float | None = None


@router.post("/pod")
def post_pod(body: PodIn, p: Principal = Depends(require_any("custody.write", "driver.app")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, body.trip_id, "Trip", lock=True)
    assert_trip_access(db, p, t, write=True)
    b = get_or_404(db, Booking, body.booking_id, "Booking", lock=True)
    otp_ok = False
    if body.otp:
        from app.modules.platform.router import verify_otp
        verify_otp(db, "pod", str(b.id), body.otp)
        otp_ok = True
    pod = ops.submit_pod(db, p, trip=t, booking=b, delivered_count=body.delivered_count, receiver_name=body.receiver_name,
                         receiver_phone=body.receiver_phone, otp_verified=otp_ok, photo_ids=[str(x) for x in body.photo_document_ids],
                         signature_id=body.signature_document_id, condition=body.condition, remarks=body.remarks,
                         delivered_at=body.delivered_at, lat=body.lat, lng=body.lng)
    return to_dict(pod)


class PodVerifyIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/pod/{booking_id}/verify")
def verify_pod(booking_id: uuid.UUID, body: PodVerifyIn, p: Principal = Depends(require("trip.close")), db: Session = Depends(get_db)):
    pod = db.execute(select(ProofOfDelivery).where(ProofOfDelivery.booking_id == booking_id)).scalar_one_or_none()
    if not pod:
        raise NotFound("POD")
    if pod.status != "submitted":
        raise Conflict("already", f"POD is {pod.status}")
    b = db.get(Booking, booking_id)
    if body.approve:
        pod.status, pod.verified_by, pod.verified_at = "verified", p.user_id, utcnow()
        b.status, b.pod_verified_at = "pod_verified", utcnow()
        contact = db.execute(select(Contact).where(Contact.customer_id == b.customer_id)).scalars().first()
        if contact and (contact.phone or contact.email):
            queue(db, channel="sms" if contact.phone else "email", recipient=contact.phone or contact.email, template="delivered",
                  code=b.code, receiver=pod.receiver_name, time=f"{pod.delivered_at:%d-%m-%Y %H:%M} UTC", entity="booking", entity_id=b.id)
    else:
        if not body.note:
            raise AppError("reason_required", "Give a reason for rejecting the POD")
        pod.status = "rejected"
        raise_exception_task(db, severity="high", title=f"POD rejected for {b.code}", entity="booking", entity_id=b.id,
                             source="pod_review", detail=body.note, blocking=True, owner_role="operations_manager")
    write_audit(db, actor=p, action="pod.verify" if body.approve else "pod.reject", entity="booking", entity_id=b.id, reason=body.note)
    return to_dict(pod)


# ===================================================================== LR
@router.get("/lr/{number:path}/verify")
def verify_lr_public(number: str, token: str, db: Session = Depends(get_db)):
    """Public QR verification. Shows authenticity and status only - no customer details."""
    lr = db.execute(select(LorryReceipt).where(LorryReceipt.number == number)).scalar_one_or_none()
    if not lr or lr.verify_token != token:
        raise NotFound("LR")
    b = db.get(Booking, lr.booking_id)
    return {"number": lr.number, "status": lr.status, "version": lr.version, "issued_by": "G ROAD LINES",
            "consignment_status": b.status, "issued_at": lr.created_at}


@router.get("/bookings/{bid}/lr")
def get_lr(bid: uuid.UUID, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    b = get_or_404(db, Booking, bid, "Booking")
    assert_booking_access(db, p, b)
    lr = db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id).order_by(LorryReceipt.created_at.desc())).scalars().first()
    if not lr:
        raise NotFound("LR")
    out = to_dict(lr)
    out["qr_payload"] = f"/api/v1/lr/{lr.number}/verify?token={lr.verify_token}"
    if not p.is_internal:
        out.pop("verify_token", None)
    return out


class LrAmendIn(BaseModel):
    changes: dict
    reason: str = Field(min_length=3)


@router.post("/lr/{lr_id}/amend")
def post_amend(lr_id: uuid.UUID, body: LrAmendIn, p: Principal = Depends(require("lr.write")), db: Session = Depends(get_db)):
    lr = get_or_404(db, LorryReceipt, lr_id, "LR", lock=True)
    protected = {"booking", "company", "company_gstin"}
    if protected & set(body.changes):
        raise AppError("protected", "These LR fields cannot be amended")
    return to_dict(amend_lr(db, p, lr, body.changes, body.reason))


# ===================================================================== owner offers (attached vehicles)
class OfferIn(BaseModel):
    owner_id: uuid.UUID
    booking_id: uuid.UUID | None = None
    lane: str
    vehicle_requirement: str | None = None
    required_on: datetime | None = None
    terms: str | None = None


@router.post("/owner-offers")
def create_offer(body: OfferIn, p: Principal = Depends(require("owner.write")), db: Session = Depends(get_db)):
    from app.core.services import next_number
    from app.modules.masters.models import VehicleOwner
    o = get_or_404(db, VehicleOwner, body.owner_id, "Owner")
    if o.status != "active":
        raise BlockedByRule("owner_status", f"Owner is {o.status}")
    offer = OwnerOffer(code=next_number(db, "OFR", "OFR"), **body.model_dump())
    db.add(offer)
    db.flush()
    if o.phone:
        queue(db, channel="whatsapp", recipient=o.phone, template="generic",
              text=f"G ROAD LINES load request {offer.code}: {body.lane}. Please quote in the owner portal.")
    return to_dict(offer)


@router.get("/owner-offers")
def list_offers(p: Principal = Depends(require("owner.read")), db: Session = Depends(get_db)):
    return [to_dict(o) for o in db.execute(select(OwnerOffer).order_by(OwnerOffer.created_at.desc())).scalars()]


class NegotiateIn(BaseModel):
    negotiated_rate: Decimal = Field(gt=0)
    advance_pct: Decimal = Field(Decimal("0"), ge=0, le=90)
    note: str | None = None


@router.post("/owner-offers/{oid}/negotiate")
def negotiate(oid: uuid.UUID, body: NegotiateIn, p: Principal = Depends(require("owner.write")), db: Session = Depends(get_db)):
    o = get_or_404(db, OwnerOffer, oid, "Offer")
    if o.status not in ("quoted", "negotiated"):
        raise Conflict("bad_status", f"Offer is {o.status}")
    o.negotiated_rate, o.advance_pct, o.status = body.negotiated_rate, body.advance_pct, "negotiated"
    write_audit(db, actor=p, action="owner_offer.negotiate", entity="owner_offer", entity_id=o.id,
                after={"rate": body.negotiated_rate, "advance_pct": body.advance_pct}, reason=body.note)
    return to_dict(o)


# ===================================================================== PTL consolidation
class ConsolidationIn(BaseModel):
    vehicle_id: uuid.UUID
    booking_ids: list[uuid.UUID] | None = None
    max_detour_pct: float = Field(20.0, ge=0, le=100)


@router.post("/consolidation/proposals")
def consolidation(body: ConsolidationIn, p: Principal = Depends(require("consolidation.plan")), db: Session = Depends(get_db)):
    v = get_or_404(db, Vehicle, body.vehicle_id, "Vehicle")
    return ops.consolidation_proposals(db, vehicle=v, candidate_ids=body.booking_ids, max_detour_pct=body.max_detour_pct)


@router.get("/trips/{tid}/load-plan")
def get_load_plan(tid: uuid.UUID, p: Principal = Depends(require("trip.read")), db: Session = Depends(get_db)):
    t = get_or_404(db, Trip, tid, "Trip")
    t.load_plan = ops.load_plan(db, t)
    return t.load_plan



# ===================================================================== GPS track & transshipment
@router.get("/trips/{tid}/track")
def trip_track(tid: uuid.UUID, p: Principal = Depends(require("gps.view")), db: Session = Depends(get_db)):
    from app.modules.operations.models import GpsPing
    t = get_or_404(db, Trip, tid, "Trip")
    pings = [{"lat": g.lat, "lng": g.lng, "source": g.source, "at": g.recorded_at, "speed": g.speed_kmph} for g in
             db.execute(select(GpsPing).where(GpsPing.trip_id == t.id).order_by(GpsPing.recorded_at).limit(5000)).scalars()]
    return {"corridor": ops.trip_corridor(db, t), "pings": pings,
            "evaluation": ops.evaluate_track(db, t) if t.status in ("dispatched", "in_transit") else None,
            "corridor_basis": "Straight lines between pickup/drop locations (no road geometry until a maps provider is connected)"}


class TransshipIn(BaseModel):
    trip_id: uuid.UUID
    facility_id: uuid.UUID
    package_count: int = Field(ge=0)
    condition: str = Field("good", pattern="^(good|damaged|wet|open)$")
    location: str | None = None
    note: str | None = None
    photo_document_ids: list[uuid.UUID] = []


@router.post("/bookings/{bid}/transship")
def post_transship(bid: uuid.UUID, body: TransshipIn, p: Principal = Depends(require("custody.write")), db: Session = Depends(get_db)):
    from app.modules.masters.models import Facility
    b = get_or_404(db, Booking, bid, "Booking", lock=True)
    t = get_or_404(db, Trip, body.trip_id, "Trip", lock=True)
    f = get_or_404(db, Facility, body.facility_id, "Facility")
    g = ops.transship(db, p, booking=b, trip=t, facility=f, package_count=body.package_count, condition=body.condition,
                      location=body.location, note=body.note, photo_ids=[str(x) for x in body.photo_document_ids])
    return {"godown_entry": to_dict(g), "booking_status": b.status, "trip_status": t.status}
