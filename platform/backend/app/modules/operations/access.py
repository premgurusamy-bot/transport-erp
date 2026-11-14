"""Record-level access rules (tenant isolation, driver/owner/vendor scoping).

Every portal/app query goes through these functions so isolation is enforced in one place.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.core.errors import Forbidden, NotFound
from app.modules.commercial.models import Booking
from app.modules.operations.models import Trip, TripLoad


def _uuid(v) -> uuid.UUID | None:
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


def driver_trip_ids(db: Session, p: Principal) -> set[uuid.UUID]:
    if p.scope_trip_id:
        return {p.scope_trip_id}
    if not p.driver_id:
        return set()
    return set(db.execute(select(Trip.id).where(Trip.driver_id == p.driver_id)).scalars())


def assert_trip_access(db: Session, p: Principal, trip: Trip, write: bool = False) -> None:
    if p.is_internal and (p.can("trip.read") or p.can("trip.update")):
        if write and not p.can("trip.update") and not p.can("custody.write"):
            raise Forbidden()
        return
    if p.driver_id and p.can("driver.app"):
        if trip.driver_id == p.driver_id and (not p.scope_trip_id or p.scope_trip_id == trip.id):
            return
    if p.owner_id and p.can("portal.owner") and trip.owner_id == p.owner_id and not write:
        return
    raise NotFound("Trip")  # do not reveal existence (IDOR protection)


def assert_booking_access(db: Session, p: Principal, booking: Booking) -> None:
    if p.is_internal and p.can("booking.read"):
        return
    if p.customer_id and p.can("portal.customer") and booking.customer_id == p.customer_id:
        return
    if p.driver_id and p.can("driver.app"):
        tids = driver_trip_ids(db, p)
        if db.execute(select(TripLoad.id).where(TripLoad.booking_id == booking.id, TripLoad.trip_id.in_(tids))).first():
            return
    raise NotFound("Booking")


def driver_can_see_entity(db: Session, p: Principal, entity: str, entity_id: str) -> bool:
    eid = _uuid(entity_id)
    if eid is None:
        return False
    tids = driver_trip_ids(db, p)
    if entity == "trip":
        return eid in tids
    if entity == "booking":
        return bool(db.execute(select(TripLoad.id).where(TripLoad.booking_id == eid, TripLoad.trip_id.in_(tids))).first())
    if entity == "driver":
        return eid == p.driver_id
    return False


def upload_allowed(db: Session, p: Principal, entity: str, entity_id: str, doc_type: str):
    """Returns (customer_id, visible_to_customer, visible_to_driver) or raises."""
    eid = _uuid(entity_id)
    customer_visible_types = {"pod", "lr", "invoice", "eway_bill", "cargo_photo", "complaint_evidence"}
    if p.is_internal and p.can("documents.write"):
        cust = None
        if entity == "booking" and eid:
            b = db.get(Booking, eid)
            cust = b.customer_id if b else None
        return cust, doc_type in customer_visible_types, doc_type in {"lr", "eway_bill", "trip_sheet", "cargo_photo"}
    if p.driver_id and p.can("driver.app") and driver_can_see_entity(db, p, entity, entity_id):
        cust = None
        if entity == "booking":
            b = db.get(Booking, eid)
            cust = b.customer_id if b else None
        return cust, doc_type in {"pod", "cargo_photo"}, True
    if p.customer_id and p.can("portal.customer") and entity in ("booking", "complaint"):
        if entity == "booking":
            b = db.get(Booking, eid)
            if not b or b.customer_id != p.customer_id:
                raise NotFound("Booking")
        return p.customer_id, True, False
    if p.owner_id and p.can("portal.owner") and entity in ("vehicle", "owner"):
        from app.modules.fleet.models import Vehicle
        if entity == "owner" and eid == p.owner_id:
            return None, False, False
        v = db.get(Vehicle, eid) if eid else None
        if v and v.owner_id == p.owner_id:
            return None, False, False
    if p.vendor_id and p.can("portal.vendor"):
        if entity == "vendor" and eid == p.vendor_id:
            return None, False, False
        if entity == "purchase_order" and eid:
            from app.modules.supply.models import PurchaseOrder
            po = db.get(PurchaseOrder, eid)
            if po and po.vendor_id == p.vendor_id:
                return None, False, False
    raise Forbidden("You cannot upload documents for this record")
