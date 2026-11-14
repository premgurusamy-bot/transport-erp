"""Allocation checks, trip lifecycle, GPS source failover, custody, POD, consolidation and load planning."""
from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import money, utcnow
from app.core.errors import AppError, BlockedByRule, Conflict
from app.core.services import get_config, next_number, open_blocking_tasks, raise_exception_task
from app.integrations.adapters import haversine_km
from app.modules.commercial.models import Booking, Package
from app.modules.commercial.pricing import ptl_share
from app.modules.fleet.models import ComplianceItem, Driver, SafetyDefect, Vehicle
from app.modules.masters.models import GoodsCategory, Location, RouteDistance, VehicleOwner
from app.modules.operations.models import (
    CustodyEvent, GpsPing, OwnerOffer, PackageScan, ProofOfDelivery, Trip, TripEvent, TripLoad,
)
from app.modules.platform.models import TempDriverAccess

ACTIVE_TRIP = ("planned", "ready", "dispatched", "in_transit")
VEHICLE_MANDATORY = {"insurance", "road_tax", "fitness", "puc", "rc"}
PERMIT_KINDS = {"national_permit", "state_permit"}
NON_OVERRIDABLE = {"legal", "safety"}


# ------------------------------------------------------------------ helpers
def lane_km(db: Session, origin_id, dest_id) -> float | None:
    rd = db.execute(select(RouteDistance).where(
        ((RouteDistance.origin_id == origin_id) & (RouteDistance.destination_id == dest_id))
        | ((RouteDistance.origin_id == dest_id) & (RouteDistance.destination_id == origin_id)))).scalars().first()
    if rd:
        return float(rd.km)
    a, b = db.get(Location, origin_id), db.get(Location, dest_id)
    if a and b and a.lat is not None and b.lat is not None:
        return round(haversine_km(a.lat, a.lng, b.lat, b.lng) * 1.25, 1)
    return None


def geom(v: Vehicle) -> dict:
    floor = float(v.length_ft * v.width_ft)
    vol = float(v.length_ft * v.width_ft * (v.height_ft or Decimal("7")))
    return {"payload_kg": v.payload_kg, "floor_sqft": floor, "volume_cft": vol, "length_ft": float(v.length_ft)}


def booking_floor(b: Booking) -> float:
    if b.floor_sqft:
        return float(b.floor_sqft)
    if b.volume_cft:
        return float(b.volume_cft) / (4.0 if b.stackable else 2.0)
    return 0.0


def _chk(results, check, ok, severity, message):
    results.append({"check": check, "ok": bool(ok), "severity": severity, "message": message})


# ------------------------------------------------------------------ allocation checks
def allocation_checks(db: Session, *, vehicle: Vehicle, driver: Driver | None, bookings: list[Booking],
                      planned_start: datetime | None, trip: Trip | None = None) -> list[dict]:
    r: list[dict] = []
    start = planned_start or utcnow()
    km = max((lane_km(db, b.origin_id, b.destination_id) or 0) for b in bookings) if bookings else 0
    kpd = float(get_config(db, "pricing.cost_rates")["km_per_day"])
    end = start + timedelta(days=max(1, math.ceil(km / kpd)) if km else 1)
    end_date = end.date()

    # --- FTL exclusivity
    ftl = [b for b in bookings if b.service_type == "FTL"]
    if ftl and len(bookings) > 1:
        _chk(r, "ftl_exclusive", False, "legal", "FTL booking requires exclusive use - other consignments cannot be added")
    elif ftl:
        _chk(r, "ftl_exclusive", True, "legal", "Exclusive FTL load")

    # --- capacity (legal payload and geometry)
    g = geom(vehicle)
    w = sum(float(b.weight_kg) for b in bookings)
    _chk(r, "payload", w <= g["payload_kg"], "legal",
         f"Total weight {w:.0f} kg vs legal payload {g['payload_kg']} kg")
    floor = sum(booking_floor(b) for b in bookings)
    if floor:
        _chk(r, "floor_area", floor <= g["floor_sqft"], "safety", f"Floor area {floor:.0f} sqft vs {g['floor_sqft']:.0f} sqft")
    vol = sum(float(b.volume_cft or 0) for b in bookings)
    if vol:
        _chk(r, "volume", vol <= g["volume_cft"], "safety", f"Volume {vol:.0f} cft vs {g['volume_cft']:.0f} cft")
    longest = max((float(b.max_package_length_ft or 0) for b in bookings), default=0)
    if longest:
        _chk(r, "length", longest <= g["length_ft"], "safety", f"Longest package {longest} ft vs body {g['length_ft']} ft")
    bodies = {b.required_body_type for b in bookings if b.required_body_type}
    for bt in bodies:
        _chk(r, "body_type", vehicle.body_type == bt, "commercial", f"Required body {bt}, vehicle is {vehicle.body_type}")

    # --- PTL compatibility
    if len(bookings) > 1:
        cats = [db.get(GoodsCategory, b.goods_category_id) for b in bookings if b.goods_category_id]
        bad = []
        for i, a in enumerate(cats):
            for c in cats[i + 1:]:
                if set(a.incompatible_tags or []) & set(c.tags or []) or set(c.incompatible_tags or []) & set(a.tags or []):
                    bad.append(f"{a.name} / {c.name}")
            if a.hazard_class or not a.ptl_allowed:
                bad.append(f"{a.name} not allowed in shared loads")
        _chk(r, "cargo_compatibility", not bad, "safety", "Compatible cargo" if not bad else "Incompatible: " + "; ".join(bad))
        nonstack_fragile = [b.code for b in bookings if b.fragile and not b.stackable]
        if nonstack_fragile:
            _chk(r, "fragile_handling", True, "warning", f"Fragile, non-stackable: {', '.join(nonstack_fragile)} - load on top/floor only")

    # --- vehicle state
    _chk(r, "vehicle_active", vehicle.is_active, "legal", "Vehicle active" if vehicle.is_active else "Vehicle inactive")
    ok_status = vehicle.status == "available" or (trip is not None and vehicle.status == "reserved" and trip.vehicle_id == vehicle.id)
    _chk(r, "vehicle_status", ok_status, "commercial", f"Vehicle status: {vehicle.status}")
    if vehicle.status in ("maintenance", "unavailable"):
        r[-1]["severity"] = "safety"
    clash = db.execute(select(Trip).where(Trip.vehicle_id == vehicle.id, Trip.status.in_(ACTIVE_TRIP),
                                          Trip.id != (trip.id if trip else uuid.uuid4()))).scalars().first()
    _chk(r, "vehicle_double_booking", clash is None, "legal" if clash else "commercial",
         f"Vehicle already on trip {clash.code}" if clash else "No conflicting trip")

    # --- vehicle compliance
    items = list(db.execute(select(ComplianceItem).where(ComplianceItem.subject_type == "vehicle",
                                                         ComplianceItem.subject_id == vehicle.id,
                                                         ComplianceItem.status == "current")).scalars())
    by_kind = {i.kind: i for i in items}
    for kind in sorted(VEHICLE_MANDATORY):
        it = by_kind.get(kind)
        if not it:
            _chk(r, f"compliance_{kind}", False, "legal", f"{kind.replace('_', ' ').title()} not recorded")
        elif it.valid_to and it.valid_to < end_date:
            _chk(r, f"compliance_{kind}", False, "legal", f"{kind.replace('_', ' ').title()} valid only to {it.valid_to} (trip ends {end_date})")
        else:
            _chk(r, f"compliance_{kind}", True, "legal", f"{kind.replace('_', ' ').title()} valid to {it.valid_to}")
    permits = [by_kind[k] for k in PERMIT_KINDS if k in by_kind]
    interstate = len({(db.get(Location, b.origin_id).state, db.get(Location, b.destination_id).state) for b in bookings
                      if db.get(Location, b.origin_id).state != db.get(Location, b.destination_id).state}) > 0
    if not permits or all(p.valid_to and p.valid_to < end_date for p in permits):
        _chk(r, "permit", False, "legal", "No valid goods permit recorded")
    elif interstate and "national_permit" not in by_kind:
        _chk(r, "permit", False, "legal", "Interstate movement needs a national/applicable permit")
    else:
        _chk(r, "permit", True, "legal", "Permit valid")

    # --- safety defects
    defects = list(db.execute(select(SafetyDefect).where(SafetyDefect.vehicle_id == vehicle.id, SafetyDefect.status == "open",
                                                         SafetyDefect.severity == "critical")).scalars())
    _chk(r, "safety_defects", not defects, "safety",
         "No open critical defects" if not defects else "Open critical defect: " + ", ".join(d.item for d in defects))

    # --- driver
    if driver is None:
        _chk(r, "driver_assigned", False, "legal", "No driver assigned")
    else:
        _chk(r, "driver_active", driver.is_active, "legal", "Driver active" if driver.is_active else "Driver inactive")
        lic_ok = driver.licence_valid_to is not None and driver.licence_valid_to >= end_date
        _chk(r, "driver_licence", lic_ok, "legal", f"Licence valid to {driver.licence_valid_to}" if driver.licence_valid_to else "Licence validity not recorded")
        if vehicle.vehicle_class:
            _chk(r, "licence_class", vehicle.vehicle_class in (driver.licence_classes or []), "legal",
                 f"Vehicle class {vehicle.vehicle_class}; licence classes {driver.licence_classes}")
        hazardous = any((db.get(GoodsCategory, b.goods_category_id).hazard_class if b.goods_category_id else None) for b in bookings)
        if hazardous:
            _chk(r, "hazmat_endorsement", driver.hazmat_endorsement, "legal", "Hazardous goods need endorsed driver")
        d_clash = db.execute(select(Trip).where(Trip.driver_id == driver.id, Trip.status.in_(ACTIVE_TRIP),
                                                Trip.id != (trip.id if trip else uuid.uuid4()))).scalars().first()
        _chk(r, "driver_double_booking", d_clash is None, "safety", f"Driver already on trip {d_clash.code}" if d_clash else "Driver free")
        duty = get_config(db, "driver.duty")
        rest_ok = driver.driving_minutes_today <= int(duty["max_driving_hours_day"]) * 60
        _chk(r, "driver_rest", rest_ok, "safety", f"Driven {driver.driving_minutes_today // 60} h today (max {duty['max_driving_hours_day']} h)")
        _chk(r, "driver_status", driver.status in ("available",) or (trip and trip.driver_id == driver.id and driver.status == "available"),
             "commercial", f"Driver status: {driver.status}")
        if vehicle.ownership == "attached" and driver.owner_id and driver.owner_id != vehicle.owner_id:
            _chk(r, "driver_owner_match", False, "commercial", "Driver is registered under a different owner")

    # --- attached vehicle: owner acceptance and status
    if vehicle.ownership == "attached":
        owner = db.get(VehicleOwner, vehicle.owner_id) if vehicle.owner_id else None
        _chk(r, "owner_status", bool(owner and owner.status == "active"), "commercial",
             f"Owner status: {owner.status if owner else 'missing'}")
        _chk(r, "owner_kyc", bool(owner and owner.kyc_status == "verified"), "legal", f"Owner KYC: {owner.kyc_status if owner else 'missing'}")
        q = select(OwnerOffer).where(OwnerOffer.vehicle_id == vehicle.id, OwnerOffer.status == "accepted")
        if trip:
            q = q.where((OwnerOffer.trip_id == trip.id) | (OwnerOffer.trip_id.is_(None)))
        offer = db.execute(q.order_by(OwnerOffer.accepted_at.desc())).scalars().first()
        _chk(r, "owner_acceptance", offer is not None and (driver is None or offer.driver_id == driver.id), "commercial_hard",
             "Owner accepted with this vehicle/driver" if offer else "Owner has not accepted this assignment")

    # --- customer commitments and credit
    for b in bookings:
        if b.deliver_by and end > b.deliver_by:
            _chk(r, f"commitment_{b.code}", False, "commercial", f"{b.code}: estimated arrival {end:%d-%m %H:%M} after promised {b.deliver_by:%d-%m %H:%M}")
        if b.credit_status not in ("ok", "warning", "exception_approved"):
            _chk(r, f"credit_{b.code}", False, "commercial_hard", f"{b.code}: credit status {b.credit_status}")
        if open_blocking_tasks(db, "booking", b.id):
            _chk(r, f"exceptions_{b.code}", False, "safety", f"{b.code}: open blocking exception (custody/damage)")
    return r


def blocking_failures(checks: list[dict], override: dict | None) -> list[dict]:
    """Legal/safety failures always block. Commercial failures block unless authorised override.
    'commercial_hard' (credit) can only be cleared by a credit exception approval, never a dispatch override."""
    overridden = set((override or {}).get("checks", []))
    out = []
    for c in checks:
        if c["ok"] or c["severity"] == "warning":
            continue
        if c["severity"] in NON_OVERRIDABLE or c["severity"] == "commercial_hard" or c["check"] not in overridden:
            out.append(c)
    return out


# ------------------------------------------------------------------ trip creation
def create_trip(db: Session, actor, *, booking_ids: list[uuid.UUID], vehicle_id: uuid.UUID, driver_id: uuid.UUID | None,
                planned_start: datetime | None, owner_hire_amount: Decimal | None = None,
                override_checks: list[str] | None = None, override_reason: str | None = None) -> tuple[Trip, list[dict]]:
    vehicle = db.execute(select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()).scalar_one_or_none()
    if not vehicle:
        raise AppError("vehicle_missing", "Vehicle not found")
    bookings = [db.execute(select(Booking).where(Booking.id == i).with_for_update()).scalar_one_or_none() for i in booking_ids]
    if not bookings or any(b is None for b in bookings):
        raise AppError("booking_missing", "Booking not found")
    for b in bookings:
        if b.status != "confirmed":
            raise BlockedByRule("booking_status", f"{b.code} must be confirmed (is {b.status})")
        if db.execute(select(TripLoad).where(TripLoad.booking_id == b.id, TripLoad.status.notin_(("removed", "transshipped")))).first():
            raise Conflict("already_planned", f"{b.code} is already on a trip")
    driver = db.get(Driver, driver_id) if driver_id else None
    checks = allocation_checks(db, vehicle=vehicle, driver=driver, bookings=bookings, planned_start=planned_start)
    override = None
    if override_checks:
        if not actor.can("dispatch.override"):
            raise AppError("forbidden", "Override needs dispatch.override permission", status=403)
        if not override_reason:
            raise AppError("reason_required", "Override needs a reason")
        override = {"by": str(actor.user_id), "reason": override_reason, "checks": override_checks, "at": utcnow().isoformat()}
    fails = blocking_failures(checks, override)
    if fails:
        raise BlockedByRule("allocation_blocked", "Allocation failed mandatory checks", details=fails)
    mode = "FTL" if bookings[0].service_type == "FTL" else "PTL"
    trip = Trip(code=next_number(db, "TRP", "TRP"), trip_mode=mode, fleet_type=vehicle.ownership, vehicle_id=vehicle.id,
                driver_id=driver.id if driver else None, owner_id=vehicle.owner_id if vehicle.ownership == "attached" else None,
                exclusive_booking_id=bookings[0].id if mode == "FTL" else None, planned_start=planned_start or utcnow(),
                planned_km=Decimal(str(max(lane_km(db, b.origin_id, b.destination_id) or 0 for b in bookings))),
                allocation_checks=checks, override=override, owner_hire_amount=money(owner_hire_amount or 0))
    db.add(trip)
    db.flush()
    order = sequence_bookings(db, bookings)
    alloc = estimate_allocation(db, trip, bookings, vehicle)
    for i, b in enumerate(order["pickup"], 1):
        db.add(TripLoad(trip_id=trip.id, booking_id=b.id, pickup_seq=i, drop_seq=order["drop"].index(b) + 1,
                        allocated_cost_est=alloc[b.id]["cost"], allocation_basis=alloc[b.id]["basis"]))
        b.status = "planned"
    vehicle.status = "reserved"
    if vehicle.ownership == "attached":
        offer = db.execute(select(OwnerOffer).where(OwnerOffer.vehicle_id == vehicle.id, OwnerOffer.status == "accepted",
                                                    OwnerOffer.trip_id.is_(None))).scalars().first()
        if offer:
            offer.trip_id = trip.id
            trip.owner_hire_amount = money(offer.negotiated_rate or offer.owner_quote or 0)
            trip.owner_advance = money(trip.owner_hire_amount * Decimal(offer.advance_pct) / 100)
    if driver and driver.category in ("attached", "temporary"):
        grant_temp_access(db, trip, driver)
    trip.load_plan = load_plan(db, trip)
    write_audit(db, actor=actor, action="trip.create", entity="trip", entity_id=trip.id,
                after={"code": trip.code, "vehicle": vehicle.registration, "bookings": [b.code for b in bookings], "override": override})
    return trip, checks


def grant_temp_access(db: Session, trip: Trip, driver: Driver):
    db.add(TempDriverAccess(trip_id=trip.id, driver_id=driver.id, phone=driver.phone,
                            expires_at=(trip.planned_start or utcnow()) + timedelta(days=7)))


def revoke_temp_access(db: Session, trip: Trip, reason: str):
    for g in db.execute(select(TempDriverAccess).where(TempDriverAccess.trip_id == trip.id, TempDriverAccess.revoked_at.is_(None))).scalars():
        g.revoked_at, g.revoke_reason = utcnow(), reason


def release_trip_resources(db: Session, trip: Trip):
    v = db.get(Vehicle, trip.vehicle_id)
    if v and v.status in ("reserved", "loading", "transit", "unloading"):
        v.status = "available"
    if trip.driver_id:
        d = db.get(Driver, trip.driver_id)
        if d and d.status == "on_trip":
            d.status = "available"
    revoke_temp_access(db, trip, f"trip {trip.status}")


# ------------------------------------------------------------------ sequencing and allocation
def sequence_bookings(db: Session, bookings: list[Booking]) -> dict:
    """Pickup nearest-first from the first origin; drops nearest-first from the last pickup.
    Loading order is reverse of drop order (last drop loaded first)."""
    def loc(i):
        return db.get(Location, i)
    if len(bookings) == 1:
        return {"pickup": bookings, "drop": bookings}
    base = loc(bookings[0].origin_id)
    def dist(a, b):
        return haversine_km(a.lat, a.lng, b.lat, b.lng) if a and b and a.lat is not None and b.lat is not None else 0
    pickup = sorted(bookings, key=lambda b: dist(base, loc(b.origin_id)))
    last = loc(pickup[-1].origin_id)
    drop = sorted(bookings, key=lambda b: dist(last, loc(b.destination_id)))
    return {"pickup": pickup, "drop": drop}


def estimate_allocation(db: Session, trip: Trip, bookings: list[Booking], vehicle: Vehicle) -> dict:
    g = geom(vehicle)
    if len(bookings) == 1:
        return {bookings[0].id: {"cost": None, "basis": {"method": "exclusive", "share": 1.0}}}
    shares = {b.id: ptl_share(db, b.weight_kg, b.volume_cft, booking_floor(b) or None, g["payload_kg"], g["volume_cft"], g["floor_sqft"])
              for b in bookings}
    total = sum(s["share"] for s in shares.values()) or 1
    out = {}
    for b in bookings:
        norm = shares[b.id]["share"] / total
        out[b.id] = {"cost": None, "basis": {**shares[b.id], "normalised_share": round(norm, 4)}}
    return out


def load_plan(db: Session, trip: Trip) -> dict:
    v = db.get(Vehicle, trip.vehicle_id)
    g = geom(v)
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    rows = []
    w = f = vol = 0.0
    for tl in sorted(loads, key=lambda x: -x.drop_seq):  # last drop loaded first (front of body)
        b = db.get(Booking, tl.booking_id)
        bf = booking_floor(b)
        w += float(b.weight_kg)
        f += bf
        vol += float(b.volume_cft or 0)
        rows.append({"booking": b.code, "drop_seq": tl.drop_seq, "weight_kg": float(b.weight_kg), "floor_sqft": round(bf, 1),
                     "packages": b.package_count, "fragile": b.fragile, "stackable": b.stackable,
                     "position": "front" if tl.drop_seq == max(x.drop_seq for x in loads) else "towards rear",
                     "note": "Load on top / do not stack" if b.fragile else ""})
    axle_note = "Axle loads not computed - vehicle axle limits not recorded"
    if v.axle_limits_kg:
        # Uniform-distribution estimate only; physical weighbridge/loading validation is required.
        front_share = 0.35
        est = [round(w * front_share), round(w * (1 - front_share))]
        ok = all(e <= lim for e, lim in zip(est, v.axle_limits_kg))
        axle_note = f"ESTIMATE front/rear payload {est} kg vs limits {v.axle_limits_kg}: {'within' if ok else 'EXCEEDS'} limits"
    return {"loading_order": rows, "utilisation": {
        "weight_pct": round(w / g["payload_kg"] * 100, 1), "floor_pct": round(f / g["floor_sqft"] * 100, 1) if f else None,
        "volume_pct": round(vol / g["volume_cft"] * 100, 1) if vol else None},
        "axle": axle_note, "securing": "Lash/secure every row; heavy items low and centred; fragile on top.",
        "status": "PROVISIONAL - requires operations review and physical loading validation"}


# ------------------------------------------------------------------ dispatch readiness
def dispatch_readiness(db: Session, trip: Trip) -> list[dict]:
    from app.modules.fleet.models import Inspection
    from app.modules.operations.lr import eway_ok_for_dispatch
    from app.modules.operations.models import EwayBill, LorryReceipt
    r: list[dict] = []
    v = db.get(Vehicle, trip.vehicle_id)
    d = db.get(Driver, trip.driver_id) if trip.driver_id else None
    bookings = [db.get(Booking, tl.booking_id) for tl in
                db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars()]
    checks = allocation_checks(db, vehicle=v, driver=d, bookings=bookings, planned_start=trip.planned_start, trip=trip)
    for c in checks:
        r.append(c)
    insp = db.execute(select(Inspection).where(Inspection.trip_id == trip.id, Inspection.kind == "pre_trip")
                      .order_by(Inspection.occurred_at.desc())).scalars().first()
    _chk(r, "pre_trip_inspection", bool(insp and insp.passed), "safety",
         "Pre-trip inspection passed" if insp and insp.passed else "Pre-trip inspection missing or failed")
    _chk(r, "driver_ack", trip.driver_ack_at is not None, "safety", "Driver acknowledged trip" if trip.driver_ack_at else "Driver acknowledgement pending")
    for b in bookings:
        loaded = db.execute(select(func.count(func.distinct(PackageScan.package_id))).where(
            PackageScan.trip_id == trip.id, PackageScan.stage == "loaded", PackageScan.result == "ok",
            PackageScan.package_id.in_(select(Package.id).where(Package.booking_id == b.id)))).scalar()
        custody = db.execute(select(CustodyEvent).where(CustodyEvent.booking_id == b.id, CustodyEvent.trip_id == trip.id,
                                                        CustodyEvent.event == "loaded").order_by(CustodyEvent.occurred_at.desc())).scalars().first()
        count_ok = loaded == b.package_count or (custody is not None and custody.package_count == b.package_count)
        if trip.trip_mode == "PTL":
            count_ok = loaded == b.package_count  # PTL needs package-level scans
        _chk(r, f"loading_{b.code}", count_ok, "safety",
             f"{b.code}: {loaded if trip.trip_mode == 'PTL' else (custody.package_count if custody else loaded)}/{b.package_count} packages loaded")
        lr = db.execute(select(LorryReceipt).where(LorryReceipt.booking_id == b.id, LorryReceipt.status != "cancelled")).scalar_one_or_none()
        _chk(r, f"lr_{b.code}", lr is not None, "legal", f"{b.code}: LR {lr.number}" if lr else f"{b.code}: LR missing")
        ew = db.execute(select(EwayBill).where(EwayBill.booking_id == b.id).order_by(EwayBill.created_at.desc())).scalars().first()
        ok, msg = eway_ok_for_dispatch(ew)
        _chk(r, f"eway_{b.code}", ok, "legal", f"{b.code}: {msg}")
    return r


# ------------------------------------------------------------------ GPS
def record_ping(db: Session, *, vehicle_id, trip_id, source: str, lat: float, lng: float, recorded_at: datetime,
                speed: float | None = None, accuracy: float | None = None) -> GpsPing:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise AppError("bad_coordinates", "Invalid coordinates")
    if recorded_at > utcnow() + timedelta(minutes=5):
        raise AppError("future_time", "Ping time is in the future")
    p = GpsPing(vehicle_id=vehicle_id, trip_id=trip_id, source=source, lat=lat, lng=lng, recorded_at=recorded_at,
                speed_kmph=speed, accuracy_m=accuracy)
    db.add(p)
    if trip_id:
        t = db.get(Trip, trip_id)
        if t and (t.last_ping_at is None or recorded_at >= t.last_ping_at):
            t.last_lat, t.last_lng, t.last_ping_at, t.last_ping_source = lat, lng, recorded_at, source
        db.flush()
        if t and t.status in ("dispatched", "in_transit"):
            evaluate_track(db, t)
    db.flush()
    return p


# ------------------------------------------------------------------ track monitoring (deviation / long stoppage)
def _point_segment_km(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from point p to segment a-b using a local equirectangular projection (good to <1% at trip scale)."""
    import math as _m
    lat0 = _m.radians((a[0] + b[0] + p[0]) / 3)
    def xy(q):
        return (_m.radians(q[1]) * _m.cos(lat0) * 6371.0, _m.radians(q[0]) * 6371.0)
    (px, py), (ax, ay), (bx, by) = xy(p), xy(a), xy(b)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return _m.hypot(px - cx, py - cy)


def trip_corridor(db: Session, trip: Trip) -> list[tuple[float, float]]:
    """Ordered waypoints: pickups in pickup order, then drops in drop order. Straight-line corridor (no road geometry yet)."""
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    pts = []
    for tl in sorted(loads, key=lambda x: x.pickup_seq):
        o = db.get(Location, db.get(Booking, tl.booking_id).origin_id)
        if o and o.lat is not None:
            pts.append((o.lat, o.lng))
    for tl in sorted(loads, key=lambda x: x.drop_seq):
        d = db.get(Location, db.get(Booking, tl.booking_id).destination_id)
        if d and d.lat is not None:
            pts.append((d.lat, d.lng))
    out = []
    for q in pts:
        if not out or out[-1] != q:
            out.append(q)
    return out


def corridor_distance_km(points: list[tuple[float, float]], lat: float, lng: float) -> float | None:
    if not points:
        return None
    if len(points) == 1:
        return haversine_km(points[0][0], points[0][1], lat, lng)
    return min(_point_segment_km((lat, lng), points[i], points[i + 1]) for i in range(len(points) - 1))


def evaluate_track(db: Session, trip: Trip) -> dict:
    """Raise exceptions for route deviation (2 consecutive pings outside the corridor) and long stoppage
    (no movement beyond the radius for longer than the configured minutes, unless a rest/waiting event explains it).
    Alerts trigger human follow-up only - never automatic conclusions about the driver."""
    cfg_dev = float(get_config(db, "gps.deviation_km") or 25)
    long_min = int(get_config(db, "gps.long_stop_minutes"))
    pings = list(db.execute(select(GpsPing).where(GpsPing.trip_id == trip.id).order_by(GpsPing.recorded_at.desc()).limit(40)).scalars())
    result = {"deviation_km": None, "stopped_minutes": 0}
    if not pings:
        return result
    corridor = trip_corridor(db, trip)
    d0 = corridor_distance_km(corridor, pings[0].lat, pings[0].lng)
    result["deviation_km"] = round(d0, 1) if d0 is not None else None
    if d0 is not None and d0 > cfg_dev and len(pings) > 1:
        d1 = corridor_distance_km(corridor, pings[1].lat, pings[1].lng)
        if d1 is not None and d1 > cfg_dev:
            raise_exception_task(db, kind="alert", severity="high", title=f"Route deviation on trip {trip.code}", entity="trip",
                                 entity_id=trip.id, source="gps_monitor", owner_role="dispatcher",
                                 detail=f"{d0:.1f} km from planned corridor (limit {cfg_dev} km, straight-line corridor). Call driver to confirm.")
    radius_km = 0.3
    anchor = pings[0]
    oldest_still = anchor
    for pg in pings[1:]:
        if haversine_km(anchor.lat, anchor.lng, pg.lat, pg.lng) > radius_km:
            break
        oldest_still = pg
    stopped = int((anchor.recorded_at - oldest_still.recorded_at).total_seconds() // 60)
    result["stopped_minutes"] = stopped
    if stopped >= long_min:
        explained = db.execute(select(TripEvent).where(
            TripEvent.trip_id == trip.id, TripEvent.event.in_(("rest_start", "waiting", "unloading", "loading_started", "arrived_drop", "arrived_pickup", "breakdown")),
            TripEvent.occurred_at >= oldest_still.recorded_at - timedelta(minutes=10))).first()
        if not explained:
            raise_exception_task(db, kind="alert", severity="medium", title=f"Long stoppage on trip {trip.code}", entity="trip",
                                 entity_id=trip.id, source="gps_monitor", owner_role="dispatcher",
                                 detail=f"Stationary about {stopped} min at {anchor.lat:.4f},{anchor.lng:.4f} with no rest/waiting event. Check on driver welfare and cargo.")
    return result


def position(db: Session, vehicle_id, trip_id=None) -> dict:
    """Phone is primary; if the phone feed is stale and the tracker is fresh, fail over to the tracker.
    Never fabricates: if both are stale, return last known position with its timestamp and 'stale'."""
    stale_min = int(get_config(db, "gps.stale_minutes"))
    now = utcnow()
    latest = {}
    for src in ("phone", "tracker", "manual"):
        q = select(GpsPing).where(GpsPing.vehicle_id == vehicle_id, GpsPing.source == src)
        if trip_id and src == "phone":
            q = q.where(GpsPing.trip_id == trip_id)
        latest[src] = db.execute(q.order_by(GpsPing.recorded_at.desc()).limit(1)).scalar_one_or_none()

    def fresh(p):
        return p is not None and (now - p.recorded_at) <= timedelta(minutes=stale_min)
    if fresh(latest["phone"]):
        chosen, state = latest["phone"], "live"
    elif fresh(latest["tracker"]):
        chosen, state = latest["tracker"], "live_failover" if latest["phone"] else "live"
    else:
        cands = [p for p in latest.values() if p]
        chosen = max(cands, key=lambda p: p.recorded_at) if cands else None
        state = "stale" if chosen else "unavailable"
    return {
        "state": state, "source": chosen.source if chosen else None, "lat": chosen.lat if chosen else None,
        "lng": chosen.lng if chosen else None, "recorded_at": chosen.recorded_at if chosen else None,
        "age_minutes": int((now - chosen.recorded_at).total_seconds() // 60) if chosen else None,
        "stale_after_minutes": stale_min,
        "sources": {k: {"recorded_at": v.recorded_at if v else None, "fresh": fresh(v)} for k, v in latest.items()},
    }


# ------------------------------------------------------------------ custody
def record_custody(db: Session, actor, *, booking: Booking, trip: Trip | None, event: str, package_count: int | None,
                   condition: str | None, seal_number: str | None = None, from_party: str | None = None,
                   to_party: str | None = None, note: str | None = None, photo_ids: list | None = None,
                   lat=None, lng=None, occurred_at: datetime | None = None, facility_id=None, handler_vendor_id=None) -> CustodyEvent:
    expected = booking.package_count
    ev = CustodyEvent(booking_id=booking.id, trip_id=trip.id if trip else None, event=event, package_count=package_count,
                      expected_count=expected, condition=condition, seal_number=seal_number, from_party=from_party,
                      to_party=to_party, note=note, photo_document_ids=photo_ids or [], lat=lat, lng=lng,
                      occurred_at=occurred_at or utcnow(), by_user=actor.user_id, facility_id=facility_id,
                      handler_vendor_id=handler_vendor_id)
    db.add(ev)
    db.flush()
    problems = []
    if package_count is not None and package_count != expected and event not in ("pickup_inspection",):
        problems.append(f"count {package_count}/{expected}")
    if event == "pickup_inspection" and package_count is not None and package_count != expected:
        problems.append(f"pickup count {package_count} differs from booked {expected}")
    if condition and condition != "good":
        problems.append(f"condition {condition}")
    if event == "seal_checked" and trip:
        applied = db.execute(select(CustodyEvent).where(CustodyEvent.booking_id == booking.id, CustodyEvent.trip_id == trip.id,
                                                        CustodyEvent.event == "seal_applied").order_by(CustodyEvent.occurred_at.desc())).scalars().first()
        if applied and applied.seal_number != seal_number:
            problems.append(f"seal mismatch {applied.seal_number} → {seal_number}")
    if problems:
        t = raise_exception_task(db, severity="high", title=f"Custody exception {booking.code}: {', '.join(problems)}",
                                 entity="booking", entity_id=booking.id, source=f"custody:{event}",
                                 detail=note, owner_role="operations_manager", blocking=True)
        ev.exception_task_id = t.id
    write_audit(db, actor=actor, action=f"custody.{event}", entity="booking", entity_id=booking.id,
                after={"count": package_count, "expected": expected, "condition": condition, "problems": problems})
    return ev


def scan_package(db: Session, actor, *, label: str, trip: Trip | None, stage: str, occurred_at: datetime | None,
                 client_event_id: str | None) -> PackageScan:
    if client_event_id:
        prior = db.execute(select(PackageScan).where(PackageScan.client_event_id == client_event_id)).scalar_one_or_none()
        if prior:
            return prior  # idempotent replay
    pkg = db.execute(select(Package).where(Package.label == label)).scalar_one_or_none()
    if not pkg:
        raise AppError("unknown_package", f"Label {label} not found")
    result = "ok"
    if trip:
        on_trip = db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.booking_id == pkg.booking_id,
                                                    TripLoad.status != "removed")).first()
        if not on_trip:
            result = "wrong_trip"
    dup = db.execute(select(PackageScan).where(PackageScan.package_id == pkg.id, PackageScan.stage == stage,
                                               PackageScan.trip_id == (trip.id if trip else None), PackageScan.result == "ok")).first()
    if dup and result == "ok":
        result = "duplicate"
    s = PackageScan(package_id=pkg.id, trip_id=trip.id if trip else None, stage=stage, result=result,
                    occurred_at=occurred_at or utcnow(), by_user=actor.user_id, client_event_id=client_event_id)
    db.add(s)
    if result == "ok":
        pkg.status = {"loaded": "loaded", "unloaded": "in_transit", "delivered": "delivered", "godown_in": "in_godown",
                      "godown_out": "picked", "picked": "picked"}.get(stage, pkg.status)
    if result == "wrong_trip":
        raise_exception_task(db, severity="high", title=f"Package {label} scanned on wrong trip {trip.code}",
                             entity="trip", entity_id=trip.id, source="scan", owner_role="dispatcher", blocking=True)
    db.flush()
    return s


# ------------------------------------------------------------------ POD and closure
def submit_pod(db: Session, actor, *, trip: Trip, booking: Booking, delivered_count: int, receiver_name: str,
               receiver_phone: str | None, otp_verified: bool, photo_ids: list, signature_id, condition: str,
               remarks: str | None, delivered_at: datetime | None, lat=None, lng=None) -> ProofOfDelivery:
    tl = db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.booking_id == booking.id,
                                           TripLoad.status != "removed")).scalar_one_or_none()
    if not tl:
        raise AppError("not_on_trip", "Booking is not on this trip")
    if db.execute(select(ProofOfDelivery).where(ProofOfDelivery.booking_id == booking.id)).first():
        raise Conflict("pod_exists", "POD already submitted for this consignment")
    if not (otp_verified or signature_id or photo_ids):
        raise BlockedByRule("pod_evidence", "POD needs OTP, signature or photo evidence")
    pod = ProofOfDelivery(booking_id=booking.id, trip_id=trip.id, delivered_count=delivered_count,
                          expected_count=booking.package_count, receiver_name=receiver_name, receiver_phone=receiver_phone,
                          otp_verified=otp_verified, photo_document_ids=photo_ids, signature_document_id=signature_id,
                          condition=condition, remarks=remarks, delivered_at=delivered_at or utcnow(), lat=lat, lng=lng)
    db.add(pod)
    tl.delivered_count = delivered_count
    if delivered_count == 0:
        tl.status, booking.delivery_status = "failed", "failed"
    elif delivered_count < booking.package_count:
        tl.status, booking.delivery_status = "partial", "partial"
    else:
        tl.status, booking.delivery_status = "delivered", "full"
    booking.status, booking.delivered_at = "delivered", pod.delivered_at
    if delivered_count != booking.package_count or condition != "good":
        raise_exception_task(db, severity="high", title=f"Delivery exception {booking.code}: {delivered_count}/{booking.package_count}, {condition}",
                             entity="booking", entity_id=booking.id, source="pod", owner_role="operations_manager", blocking=True,
                             detail=remarks)
    db.add(TripEvent(trip_id=trip.id, booking_id=booking.id, event="delivered", occurred_at=pod.delivered_at, by_user=actor.user_id,
                     lat=lat, lng=lng, customer_visible=True, note=f"Delivered {delivered_count}/{booking.package_count}"))
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    if all(x.status in ("delivered", "partial", "failed", "returned", "transshipped") for x in loads):
        trip.status, trip.actual_end = "delivered", pod.delivered_at
        v = db.get(Vehicle, trip.vehicle_id)
        v.status = "unloading"
    db.flush()
    write_audit(db, actor=actor, action="pod.submit", entity="booking", entity_id=booking.id,
                after={"delivered": delivered_count, "expected": booking.package_count, "otp": otp_verified, "condition": condition})
    return pod


def close_trip(db: Session, actor, trip: Trip, end_odometer: int | None) -> dict:
    from app.modules.finance.models import Expense
    problems = []
    if trip.status != "delivered":
        problems.append(f"Trip status is {trip.status} (must be delivered)")
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    for tl in loads:
        b = db.get(Booking, tl.booking_id)
        if tl.status == "transshipped":
            # Leg ended with a recorded custody handover at a verified facility; POD comes on the final leg.
            if open_blocking_tasks(db, "booking", b.id):
                problems.append(f"{b.code}: open exception must be resolved")
            continue
        pod = db.execute(select(ProofOfDelivery).where(ProofOfDelivery.booking_id == tl.booking_id)).scalar_one_or_none()
        if not pod or pod.status != "verified":
            problems.append(f"{b.code}: POD not verified")
        if open_blocking_tasks(db, "booking", b.id):
            problems.append(f"{b.code}: open exception must be resolved")
    if open_blocking_tasks(db, "trip", trip.id):
        problems.append("Trip has open blocking exceptions")
    pending = db.execute(select(func.count()).select_from(Expense).where(Expense.trip_id == trip.id, Expense.status == "submitted")).scalar()
    if pending:
        problems.append(f"{pending} trip expense(s) not reviewed")
    if trip.fleet_type == "own" and end_odometer is None and trip.end_odometer is None:
        problems.append("End odometer required for own-fleet trip")
    if problems:
        raise BlockedByRule("trip_not_closable", "Trip cannot be closed yet", details=[{"check": "closure", "ok": False, "message": p} for p in problems])
    if end_odometer is not None:
        if trip.start_odometer and end_odometer < trip.start_odometer:
            raise AppError("odometer", "End odometer is less than start odometer")
        trip.end_odometer = end_odometer
        v = db.get(Vehicle, trip.vehicle_id)
        v.odometer_km = max(v.odometer_km, end_odometer)
        if trip.start_odometer:
            run = end_odometer - trip.start_odometer
            trip.loaded_km = Decimal(str(min(run, float(trip.planned_km or run))))
            trip.empty_km = Decimal(str(max(0, run - float(trip.loaded_km))))
    trip.status, trip.closed_by, trip.closed_at = "closed", actor.user_id, utcnow()
    for tl in loads:
        b = db.get(Booking, tl.booking_id)
        if b.status == "pod_verified":
            pass
    release_trip_resources(db, trip)
    write_audit(db, actor=actor, action="trip.close", entity="trip", entity_id=trip.id, after={"end_odometer": end_odometer})
    return {"closed": True}


# ------------------------------------------------------------------ PTL consolidation engine
def consolidation_proposals(db: Session, *, vehicle: Vehicle, candidate_ids: list[uuid.UUID] | None = None,
                            max_detour_pct: float = 20.0) -> dict:
    """Greedy corridor-based proposal. PROVISIONAL: needs operations review and physical loading validation."""
    q = select(Booking).where(Booking.service_type == "PTL", Booking.status == "confirmed")
    if candidate_ids:
        q = q.where(Booking.id.in_(candidate_ids))
    cands = [b for b in db.execute(q).scalars()
             if not db.execute(select(TripLoad).where(TripLoad.booking_id == b.id, TripLoad.status.notin_(("removed", "transshipped")))).first()]
    g = geom(vehicle)
    reserve = float(get_config(db, "ptl.capacity_reserve_pct")) / 100
    cap_w = g["payload_kg"] * (1 - reserve)
    cap_f = g["floor_sqft"] * (1 - reserve)
    rejected: list[dict] = []
    for b in cands:
        if not b.ptl_consent:
            rejected.append({"booking": b.code, "reason": "No PTL shared-transport consent"})
        cat = db.get(GoodsCategory, b.goods_category_id) if b.goods_category_id else None
        if cat and (cat.hazard_class or not cat.ptl_allowed):
            rejected.append({"booking": b.code, "reason": f"{cat.name} not allowed in shared loads"})
        if b.credit_status not in ("ok", "warning", "exception_approved"):
            rejected.append({"booking": b.code, "reason": f"credit {b.credit_status}"})
    bad = {r["booking"] for r in rejected}
    pool = sorted([b for b in cands if b.code not in bad], key=lambda b: (b.deliver_by or datetime.max.replace(tzinfo=utcnow().tzinfo)))

    def loc(i):
        return db.get(Location, i)

    def d(a, b):
        if a is None or b is None or a.lat is None or b.lat is None:
            return None
        return haversine_km(a.lat, a.lng, b.lat, b.lng)
    proposals = []
    used: set = set()
    for seed in pool:
        if seed.id in used:
            continue
        so, sd = loc(seed.origin_id), loc(seed.destination_id)
        base = d(so, sd)
        group, w, f = [seed], float(seed.weight_kg), booking_floor(seed)
        if w > cap_w:
            rejected.append({"booking": seed.code, "reason": "Heavier than vehicle capacity after reserve"})
            continue
        reasons = {}
        for c in pool:
            if c.id in used or c.id == seed.id or c in group:
                continue
            co, cd = loc(c.origin_id), loc(c.destination_id)
            if base is None or d(so, co) is None:
                continue
            # detour: seed origin → c origin → (c dest and seed dest in better order)
            via = d(so, co) + min(d(co, cd) + d(cd, sd), d(co, sd) + d(sd, cd)) if d(co, cd) is not None else None
            if via is None:
                continue
            detour = (via - base) / base * 100 if base else 999
            if detour > max_detour_pct:
                continue
            cat_ok = True
            for gmem in group:
                a = db.get(GoodsCategory, gmem.goods_category_id) if gmem.goods_category_id else None
                bcat = db.get(GoodsCategory, c.goods_category_id) if c.goods_category_id else None
                if a and bcat and (set(a.incompatible_tags or []) & set(bcat.tags or []) or set(bcat.incompatible_tags or []) & set(a.tags or [])):
                    cat_ok = False
            if not cat_ok:
                continue
            if c.pickup_to and seed.pickup_from and c.pickup_to < seed.pickup_from:
                continue
            if c.pickup_from and seed.pickup_to and c.pickup_from > seed.pickup_to + timedelta(hours=12):
                continue
            if w + float(c.weight_kg) > cap_w or f + booking_floor(c) > cap_f:
                continue
            group.append(c)
            w += float(c.weight_kg)
            f += booking_floor(c)
            reasons[c.code] = f"detour {detour:.1f}%"
        for x in group:
            used.add(x.id)
        shares = {x.code: ptl_share(db, x.weight_kg, x.volume_cft, booking_floor(x) or None, g["payload_kg"], g["volume_cft"], g["floor_sqft"])["share"]
                  for x in group}
        revenue = sum(float(x.freight_amount) for x in group)
        proposals.append({
            "bookings": [x.code for x in group], "booking_ids": [str(x.id) for x in group],
            "weight_kg": round(w), "weight_utilisation_pct": round(w / g["payload_kg"] * 100, 1),
            "floor_utilisation_pct": round(f / g["floor_sqft"] * 100, 1) if f else None,
            "revenue": round(revenue, 2), "allocation_shares": shares, "inclusion_reasons": reasons,
            "status": "PROVISIONAL - requires operations review and physical loading validation",
        })
    return {"vehicle": vehicle.registration, "capacity_after_reserve_kg": round(cap_w), "proposals": proposals, "rejected": rejected}


def driving_date() -> date:
    return utcnow().date()


# ------------------------------------------------------------------ cross-dock / transshipment
def transship(db: Session, actor, *, booking: Booking, trip: Trip, facility, package_count: int, condition: str,
              location: str | None = None, note: str | None = None, photo_ids: list | None = None):
    """End this booking's leg at a VERIFIED facility with a counted custody handover. The booking returns to
    'confirmed' so it can be planned on an onward trip; the consignment keeps its single LR and final POD."""
    from app.modules.supply.models import GodownEntry
    if not facility.verified:
        raise BlockedByRule("facility_unverified", f"{facility.name} is not a verified facility; transshipment is not allowed there")
    if trip.status not in ("dispatched", "in_transit"):
        raise BlockedByRule("trip_status", f"Trip is {trip.status}; transshipment happens during an active trip")
    tl = db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.booking_id == booking.id,
                                           TripLoad.status.in_(("loaded", "planned")))).scalar_one_or_none()
    if not tl:
        raise AppError("not_on_trip", "Booking is not an active load on this trip")
    if trip.trip_mode == "FTL":
        raise BlockedByRule("ftl_transship", "FTL loads are exclusive door-to-door; rebook with customer consent to transship")
    ev = record_custody(db, actor, booking=booking, trip=trip, event="godown_in", package_count=package_count, condition=condition,
                        facility_id=facility.id, from_party=f"Trip {trip.code}", to_party=facility.name, note=note, photo_ids=photo_ids)
    g = GodownEntry(code=next_number(db, "GRN-G", "GDN"), facility_id=facility.id, booking_id=booking.id, package_count=package_count,
                    condition=condition, location=location, photo_document_ids=photo_ids or [])
    db.add(g)
    tl.status, tl.delivered_count = "transshipped", package_count
    booking.status = "confirmed"
    for pkg in db.execute(select(Package).where(Package.booking_id == booking.id)).scalars():
        if pkg.status not in ("short", "damaged"):
            pkg.status, pkg.godown_location = "in_godown", location
    db.add(TripEvent(trip_id=trip.id, booking_id=booking.id, event="note", occurred_at=utcnow(), by_user=actor.user_id,
                     customer_visible=True, note=f"Transferred at {facility.name} for onward movement"))
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    if all(x.status in ("delivered", "partial", "failed", "returned", "transshipped") for x in loads):
        trip.status, trip.actual_end = "delivered", utcnow()
    db.flush()
    write_audit(db, actor=actor, action="booking.transship", entity="booking", entity_id=booking.id,
                after={"trip": trip.code, "facility": facility.name, "count": package_count, "custody_event": str(ev.id)})
    return g
