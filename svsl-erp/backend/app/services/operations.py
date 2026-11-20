"""LR (consignment) and trip lifecycle, trip expenses, driver advances and settlements, fuel."""
from __future__ import annotations

import math
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import diff, jsonable, log, snapshot
from ..core.deps import AppError
from ..core.money import D, ZERO, r2
from ..core.numbering import next_number
from ..core.validators import normalize, validate
from ..models import (
    Booking, Consignment, ConsignmentItem, Customer, DeliveryPoint, Driver, DriverAdvance, DriverIncident,
    DriverSettlement, FuelCard, FuelEntry, FuelStation, Invoice, LRAmendment, Route, Trip, TripEvent, TripExpense,
    Vehicle,
)
from ..models.operations import TRIP_STAGES
from . import accounting as acc
from . import freight as fr
from . import notify
from . import settings as app_settings

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


def parse_date(v, field: str = "date") -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        raise AppError(f"Invalid {field}: {v}")


def parse_dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise AppError(f"Invalid date/time: {v}")
    return d if d.tzinfo else d.replace(tzinfo=UTC)


# ------------------------------------------------------------------ LR

LR_EDITABLE = [
    "lr_date", "branch_id", "billing_party", "consignor_name", "consignor_gstin", "consignor_address", "consignor_phone",
    "consignee_name", "consignee_gstin", "consignee_address", "consignee_phone", "loading_address", "delivery_address",
    "from_place", "to_place", "route_id", "distance_km", "load_type", "is_return", "original_lr_id", "goods_value",
    "customer_invoice_no", "customer_invoice_date", "eway_bill_no", "eway_bill_date", "eway_valid_until", "einvoice_ref",
    "packages", "quantity", "weight_kg", "payment_terms", "gst_paid_by", "risk", "remarks", "customer_authorization",
    "advance_freight", "other_charges", "other_charges_note",
]
DATE_FIELDS = {"lr_date", "customer_invoice_date", "eway_bill_date"}
DT_FIELDS = {"eway_valid_until"}
MONEY_FIELDS = {"goods_value", "advance_freight", "other_charges", "distance_km", "quantity", "weight_kg"}


def _apply_fields(lr: Consignment, data: dict) -> None:
    for f in LR_EDITABLE:
        if f not in data:
            continue
        v = data[f]
        if f in DATE_FIELDS:
            v = parse_date(v, f)
        elif f in DT_FIELDS:
            v = parse_dt(v)
        elif f in MONEY_FIELDS:
            v = r2(v) if v not in (None, "") else ZERO
        elif f == "packages":
            v = int(v or 0)
        elif f in ("is_return",):
            v = bool(v)
        elif f in ("route_id", "branch_id", "original_lr_id"):
            v = int(v) if v not in (None, "") else None
        elif isinstance(v, str):
            v = v.strip() or None
        setattr(lr, f, v)
    for f in ("consignor_gstin", "consignee_gstin"):
        val = normalize("gstin", getattr(lr, f))
        setattr(lr, f, val)
        err = validate("gstin", val)
        if err:
            raise AppError(f"{'Consignor' if 'consignor' in f else 'Consignee'} {err}")
    if lr.eway_bill_no:
        lr.eway_bill_no = str(lr.eway_bill_no).replace(" ", "")
        err = validate("ewb", lr.eway_bill_no)
        if err:
            raise AppError(err)
    if lr.load_type not in ("FTL", "PTL"):
        raise AppError("Load type must be FTL or PTL")
    if lr.payment_terms not in ("Paid", "To Pay", "To Be Billed"):
        raise AppError("Payment terms must be Paid, To Pay or To Be Billed")


def _set_vehicle_driver(db: Session, lr: Consignment, vehicle_id, driver_id) -> None:
    if vehicle_id:
        v = db.get(Vehicle, int(vehicle_id))
        if not v or not v.is_active:
            raise AppError("Vehicle not found or inactive")
        lr.vehicle_id, lr.vehicle_no, lr.vehicle_type = v.id, v.registration_no, v.vehicle_type
    if driver_id:
        d = db.get(Driver, int(driver_id))
        if not d or not d.is_active:
            raise AppError("Driver not found or inactive")
        lr.driver_id, lr.driver_name, lr.driver_mobile, lr.driver_licence = d.id, d.name, d.mobile, d.licence_no


def _apply_items(db: Session, lr: Consignment, items: list[dict] | None, points: list[dict] | None) -> None:
    if items is not None:
        db.query(ConsignmentItem).filter(ConsignmentItem.consignment_id == lr.id).delete()
        tp, tq, tw = 0, ZERO, ZERO
        for it in items:
            if not (it.get("description") or "").strip():
                continue
            ci = ConsignmentItem(
                consignment_id=lr.id, description=it["description"].strip(), hsn=(it.get("hsn") or None),
                packages=int(it.get("packages") or 0), package_type=it.get("package_type"),
                quantity=D(it.get("quantity")), uom=it.get("uom") or "NOS", weight_kg=D(it.get("weight_kg")), value=r2(it.get("value")),
            )
            if ci.hsn and (not ci.hsn.isdigit() or len(ci.hsn) not in (4, 6, 8)):
                raise AppError(f"HSN '{ci.hsn}' must be 4, 6 or 8 digits")
            db.add(ci)
            tp += ci.packages
            tq += ci.quantity
            tw += ci.weight_kg
        if items:
            lr.packages, lr.quantity, lr.weight_kg = tp or lr.packages, tq or lr.quantity, tw or lr.weight_kg
    if points is not None:
        db.query(DeliveryPoint).filter(DeliveryPoint.consignment_id == lr.id).delete()
        for i, p in enumerate(points, 1):
            if (p.get("address") or "").strip():
                db.add(DeliveryPoint(consignment_id=lr.id, sequence=i, consignee_name=p.get("consignee_name"), address=p["address"], contact=p.get("contact"), packages=int(p.get("packages") or 0)))


def _apply_freight(db: Session, lr: Consignment, data: dict) -> list[str]:
    """Freight from the rate contract (default) or entered manually with a reason."""
    warnings: list[str] = []
    mode = data.get("freight_mode") or ("manual" if data.get("basic_freight") not in (None, "") and not data.get("rate_contract_id") else "contract")
    inputs = dict(data.get("freight_inputs") or {})
    inputs.setdefault("weight_kg", str(lr.weight_kg or 0))
    inputs.setdefault("quantity", str(lr.quantity or 0))
    inputs.setdefault("km", str(lr.distance_km or 0))
    inputs.setdefault("is_return", lr.is_return)
    inputs.setdefault("extra_stops", max(0, len(data.get("delivery_points") or []) - 1))
    if mode == "contract":
        contract = None
        if data.get("rate_contract_id"):
            contract = db.get(fr.RateContract, int(data["rate_contract_id"]))
            if not contract or contract.customer_id != lr.customer_id:
                raise AppError("Selected rate contract does not belong to this customer")
            if contract.effective_from > lr.lr_date or (contract.effective_to and contract.effective_to < lr.lr_date) or contract.status == "Draft":
                raise AppError(f"Contract {contract.contract_no} v{contract.version} is not effective on {lr.lr_date:%d-%m-%Y}")
        else:
            goods = " ".join(filter(None, [data.get("goods_description")] + [i.get("description", "") for i in data.get("items") or []]))
            contract = fr.find_contract(db, lr.customer_id, lr.lr_date, lr.route_id, lr.vehicle_type, goods)
        if contract is None:
            raise AppError("No active rate contract found for this customer, date and route. Enter freight manually or add a contract.")
        result = fr.calculate(contract, fr.FreightInputs.from_dict(inputs))
        lr.rate_contract_id = contract.id
        lr.freight_basis = contract.basis
        lr.freight_rate = D(result["rate"])
        lr.freight_inputs = result["inputs"]
        lr.freight_breakdown = {"lines": result["lines"], "contract_no": contract.contract_no, "version": contract.version, "min_applied": result["min_applied"]}
        lr.basic_freight = result["basic_freight"]
        lr.loading_charges = result["loading_charges"]
        lr.unloading_charges = result["unloading_charges"]
        lr.waiting_charges = result["waiting_charges"]
        lr.detention_charges = result["detention_charges"]
        lr.extra_stop_charges = result["extra_stop_charges"]
        lr.charged_weight_kg = D(result["chargeable_weight_kg"])
    else:
        lr.rate_contract_id = None
        lr.freight_basis = data.get("freight_basis") or "manual"
        lr.freight_rate = D(data.get("freight_rate"))
        lr.basic_freight = r2(data.get("basic_freight"))
        for f in ("loading_charges", "unloading_charges", "waiting_charges", "detention_charges", "extra_stop_charges"):
            setattr(lr, f, r2(data.get(f)))
        lr.freight_inputs = inputs
        lr.freight_breakdown = {"lines": [{"label": "Freight entered manually", "amount": str(lr.basic_freight)}], "manual_reason": data.get("manual_reason")}
        lr.charged_weight_kg = lr.weight_kg
    lr.total_freight = r2(
        D(lr.basic_freight) + D(lr.loading_charges) + D(lr.unloading_charges) + D(lr.waiting_charges)
        + D(lr.detention_charges) + D(lr.extra_stop_charges) + D(lr.other_charges)
    )
    if D(lr.advance_freight) > D(lr.total_freight):
        raise AppError("Advance freight cannot exceed total freight")
    lr.balance_freight = r2(D(lr.total_freight) - D(lr.advance_freight))
    return warnings


def credit_warning(db: Session, customer: Customer, extra: Decimal) -> str | None:
    if not customer.credit_limit or D(customer.credit_limit) <= 0 or not customer.ledger_id:
        return None
    bal = acc.ledger_balance(db, customer.ledger_id)
    unbilled = D(db.execute(select(func.coalesce(func.sum(Consignment.total_freight), 0)).where(
        Consignment.customer_id == customer.id, Consignment.invoice_id.is_(None), Consignment.status != "Cancelled")).scalar())
    exposure = bal + unbilled + D(extra)
    pct = app_settings.get(db, "alerts")["credit_limit_warn_pct"]
    if exposure > D(customer.credit_limit):
        return f"Credit limit exceeded: exposure ₹{r2(exposure)} vs limit ₹{r2(customer.credit_limit)}"
    if exposure > D(customer.credit_limit) * D(pct) / 100:
        return f"Customer has used {r2(exposure / D(customer.credit_limit) * 100)}% of credit limit"
    return None


def create_lr(db: Session, user, data: dict) -> tuple[Consignment, list[str]]:
    customer = db.get(Customer, int(data.get("customer_id") or 0))
    if not customer or not customer.is_active:
        raise AppError("Select an active customer")
    for req in ("consignor_name", "consignee_name", "from_place", "to_place"):
        if not (data.get(req) or "").strip():
            raise AppError(f"{req.replace('_', ' ').capitalize()} is required")
    lr_date = parse_date(data.get("lr_date")) or date.today()
    lr = Consignment(lr_no="PENDING", lr_date=lr_date, customer_id=customer.id, customer_gstin=customer.gstin, status="Booked", created_by=user.id, verify_token=secrets.token_urlsafe(12),
                    load_type="FTL", payment_terms="To Be Billed", gst_paid_by="Consignor", risk="Owner's Risk", billing_party="Customer", is_return=False,
                    goods_value=ZERO, advance_freight=ZERO, other_charges=ZERO, packages=0, quantity=ZERO, weight_kg=ZERO, revision=0)
    _apply_fields(lr, {**data, "lr_date": lr_date})
    if lr.route_id and not lr.distance_km:
        route = db.get(Route, lr.route_id)
        lr.distance_km = route.distance_km if route else None
    trip = None
    if data.get("trip_id"):
        trip = db.get(Trip, int(data["trip_id"]))
        if not trip or trip.stage in ("Closed", "Billed", "Settled", "Cancelled"):
            raise AppError("Trip is closed or cancelled – LR cannot be added")
        lr.trip_id = trip.id
        _set_vehicle_driver(db, lr, data.get("vehicle_id") or trip.vehicle_id, data.get("driver_id") or trip.driver_id)
    else:
        _set_vehicle_driver(db, lr, data.get("vehicle_id"), data.get("driver_id"))
    db.add(lr)
    db.flush()
    _apply_items(db, lr, data.get("items"), data.get("delivery_points"))
    db.flush()
    warnings = _apply_freight(db, lr, data)
    branch_code = ""
    lr.lr_no = next_number(db, "LR", lr.lr_date, branch_code)
    w = credit_warning(db, customer, lr.total_freight)
    if w:
        warnings.append(w)
    threshold = D(app_settings.get(db, "lr")["require_eway_above_value"])
    if D(lr.goods_value) > threshold and not lr.eway_bill_no:
        warnings.append(f"Goods value exceeds ₹{threshold}: an e-way bill number is required before dispatch")
    if trip and trip.stage in ("Booked", "Vehicle Allocated", "Driver Allocated"):
        _move(db, user, trip, "LR Generated", f"LR {lr.lr_no} generated")
    db.flush()
    log(db, user, "create", "consignments", lr.id, None, snapshot(lr))
    notify.event(db, "lr_generated", {"lr_no": lr.lr_no, "customer": customer.name, "from": lr.from_place, "to": lr.to_place, "vehicle": lr.vehicle_no or "-", "amount": str(lr.total_freight)}, customer=customer, entity=("consignments", lr.id))
    return lr, warnings


def amend_lr(db: Session, user, lr_id: int, data: dict, reason: str, authorized_by: str) -> Consignment:
    lr = db.get(Consignment, lr_id)
    if not lr:
        raise AppError("LR not found", 404)
    if lr.status == "Cancelled":
        raise AppError("Cancelled LR cannot be amended")
    if lr.invoice_id:
        inv = db.get(Invoice, lr.invoice_id)
        if inv and inv.status != "Cancelled":
            raise AppError(f"LR is billed in invoice {inv.invoice_no}. Cancel the invoice or raise a debit/credit note instead.")
    if not reason or len(reason.strip()) < 5:
        raise AppError("Amendment reason is required")
    if not authorized_by:
        raise AppError("Name of the person authorising the amendment is required")
    before = snapshot(lr)
    before_items = [snapshot(i) for i in db.query(ConsignmentItem).filter_by(consignment_id=lr.id)]
    _apply_fields(lr, data)
    if "vehicle_id" in data or "driver_id" in data:
        _set_vehicle_driver(db, lr, data.get("vehicle_id"), data.get("driver_id"))
    _apply_items(db, lr, data.get("items"), data.get("delivery_points"))
    db.flush()
    recalc = any(k in data for k in ("freight_mode", "basic_freight", "rate_contract_id", "freight_inputs", "weight_kg", "quantity", "distance_km", "other_charges", "advance_freight", "items", "is_return", "route_id", "lr_date"))
    if recalc:
        payload = {**data}
        if "freight_mode" not in payload:
            payload["freight_mode"] = "contract" if lr.rate_contract_id else "manual"
            if payload["freight_mode"] == "manual":
                for f in ("basic_freight", "loading_charges", "unloading_charges", "waiting_charges", "detention_charges", "extra_stop_charges", "freight_rate"):
                    payload.setdefault(f, getattr(lr, f))
                payload.setdefault("freight_basis", lr.freight_basis)
            else:
                payload.setdefault("rate_contract_id", lr.rate_contract_id)
                payload.setdefault("freight_inputs", {**(lr.freight_inputs or {}), **(data.get("freight_inputs") or {})})
                for k in ("weight_kg", "quantity"):
                    if k in data:
                        payload["freight_inputs"][k] = str(data[k])
                if "distance_km" in data:
                    payload["freight_inputs"]["km"] = str(data["distance_km"])
        _apply_freight(db, lr, payload)
    lr.revision = (lr.revision or 0) + 1
    after = snapshot(lr)
    b, a = diff(before, after)
    b["items"] = before_items
    db.add(LRAmendment(consignment_id=lr.id, at=now(), user_id=user.id, authorized_by=authorized_by, reason=reason, before=b, after=a, revision=lr.revision))
    log(db, user, "amend", "consignments", lr.id, b, a, f"{reason} (authorised by {authorized_by})")
    return lr


def cancel_lr(db: Session, user, lr_id: int, reason: str) -> Consignment:
    lr = db.get(Consignment, lr_id)
    if not lr:
        raise AppError("LR not found", 404)
    if lr.status == "Cancelled":
        raise AppError("LR is already cancelled")
    if lr.invoice_id:
        inv = db.get(Invoice, lr.invoice_id)
        if inv and inv.status != "Cancelled":
            raise AppError(f"LR is billed in invoice {inv.invoice_no}; cancel the invoice first")
    if lr.status in ("Delivered", "POD Received"):
        raise AppError("A delivered LR cannot be cancelled")
    if not reason or len(reason.strip()) < 5:
        raise AppError("Cancellation reason is required")
    before = {"status": lr.status}
    lr.status = "Cancelled"
    lr.cancelled_at = now()
    lr.cancel_reason = reason
    lr.cancelled_by = user.id
    log(db, user, "cancel", "consignments", lr.id, before, {"status": "Cancelled"}, reason)
    return lr


def lr_delivered(db: Session, user, lr: Consignment, receiver: str | None, phone: str | None = None, remarks: str | None = None, shortage=0, damage=0, at: datetime | None = None) -> None:
    if lr.status == "Cancelled":
        raise AppError("LR is cancelled")
    lr.status = "Delivered" if lr.status not in ("POD Received", "Billed") else lr.status
    lr.delivered_at = at or now()
    lr.receiver_name = receiver
    lr.receiver_phone = phone
    lr.delivery_remarks = remarks
    lr.shortage_qty = D(shortage)
    lr.damage_qty = D(damage)
    for p in db.query(DeliveryPoint).filter_by(consignment_id=lr.id):
        if p.status == "Pending":
            p.status, p.delivered_at, p.receiver_name = "Delivered", lr.delivered_at, receiver
    log(db, user, "deliver", "consignments", lr.id, None, {"receiver": receiver, "at": lr.delivered_at.isoformat()})


def lr_pod(db: Session, user, lr: Consignment, document_id: int | None) -> None:
    if lr.status == "Cancelled":
        raise AppError("LR is cancelled")
    if not lr.delivered_at:
        lr_delivered(db, user, lr, lr.receiver_name)
    lr.pod_received_at = now()
    lr.pod_document_id = document_id or lr.pod_document_id
    if lr.status != "Billed":
        lr.status = "POD Received"
    log(db, user, "pod", "consignments", lr.id, None, {"document_id": document_id})


# ------------------------------------------------------------------ trips

OPEN_STAGES = [s for s in TRIP_STAGES if s not in ("Closed", "Billed", "Settled", "Cancelled")]


def _event(db: Session, user, trip: Trip, stage: str, note: str | None = None, odometer=None, lat=None, lng=None) -> None:
    db.add(TripEvent(trip_id=trip.id, at=now(), stage=stage, note=note, user_id=getattr(user, "id", None), odometer=odometer, lat=lat, lng=lng))


def _check_vehicle(db: Session, vehicle_id: int, trip_id: int | None, on: date | None = None) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if not v or not v.is_active or v.status in ("Inactive", "Sold"):
        raise AppError("Vehicle is not active")
    if v.status in ("Maintenance", "Breakdown"):
        raise AppError(f"Vehicle {v.registration_no} is under {v.status.lower()}")
    clash = db.execute(select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.stage.in_(["Loading", "Dispatched", "In Transit"]), Trip.id != (trip_id or 0))).scalars().first()
    if clash:
        raise AppError(f"Vehicle {v.registration_no} is already on trip {clash.trip_no}")
    on = on or date.today()
    expired = [n for n, d in (("insurance", v.insurance_expiry), ("FC", v.fc_expiry), ("PUC", v.puc_expiry)) if d and d < on]
    if expired:
        raise AppError(f"Vehicle {v.registration_no}: {', '.join(expired)} expired – renew before allocation")
    return v


def _check_driver(db: Session, driver_id: int, trip_id: int | None, on: date | None = None) -> Driver:
    d = db.get(Driver, driver_id)
    if not d or not d.is_active or d.employment_status not in ("Active",):
        raise AppError("Driver is not active")
    if d.licence_expiry and d.licence_expiry < (on or date.today()):
        raise AppError(f"Driving licence of {d.name} expired on {d.licence_expiry:%d-%m-%Y}")
    clash = db.execute(select(Trip).where(Trip.driver_id == driver_id, Trip.stage.in_(["Loading", "Dispatched", "In Transit"]), Trip.id != (trip_id or 0))).scalars().first()
    if clash:
        raise AppError(f"Driver {d.name} is already on trip {clash.trip_no}")
    return d


def create_trip(db: Session, user, data: dict) -> Trip:
    trip_date = parse_date(data.get("trip_date")) or date.today()
    trip = Trip(trip_no="PENDING", trip_date=trip_date, stage="Booked", created_by=user.id)
    for f in ("customer_id", "route_id", "booking_id", "co_driver_id", "branch_id", "return_of_trip_id"):
        if data.get(f):
            setattr(trip, f, int(data[f]))
    for f in ("from_place", "to_place", "remarks"):
        if data.get(f):
            setattr(trip, f, data[f])
    trip.is_return = bool(data.get("is_return") or data.get("return_of_trip_id"))
    trip.planned_departure = parse_dt(data.get("planned_departure"))
    trip.expected_delivery_at = parse_dt(data.get("expected_delivery_at"))
    if trip.route_id:
        route = db.get(Route, trip.route_id)
        if route:
            trip.from_place = trip.from_place or route.origin
            trip.to_place = trip.to_place or route.destination
    if not trip.from_place or not trip.to_place:
        raise AppError("From and To places (or a route) are required")
    trip.trip_no = next_number(db, "TRIP", trip_date)
    db.add(trip)
    db.flush()
    _event(db, user, trip, "Booked", "Trip created")
    if data.get("vehicle_id"):
        allocate(db, user, trip, vehicle_id=int(data["vehicle_id"]), driver_id=int(data["driver_id"]) if data.get("driver_id") else None)
    if trip.booking_id:
        b = db.get(Booking, trip.booking_id)
        if b:
            b.status, b.trip_id = "Converted", trip.id
    log(db, user, "create", "trips", trip.id, None, snapshot(trip))
    return trip


def allocate(db: Session, user, trip: Trip, vehicle_id: int | None = None, driver_id: int | None = None) -> Trip:
    if trip.stage not in ("Booked", "Vehicle Allocated", "Driver Allocated", "LR Generated", "Loading"):
        raise AppError("Vehicle/driver can only be changed before dispatch")
    if vehicle_id:
        v = _check_vehicle(db, vehicle_id, trip.id, trip.trip_date)
        trip.vehicle_id = v.id
        if trip.start_km is None:
            trip.start_km = v.current_odometer
        if trip.stage == "Booked":
            _move(db, user, trip, "Vehicle Allocated", f"Vehicle {v.registration_no}")
    if driver_id:
        d = _check_driver(db, driver_id, trip.id, trip.trip_date)
        trip.driver_id = d.id
        if trip.stage in ("Booked", "Vehicle Allocated"):
            _move(db, user, trip, "Driver Allocated", f"Driver {d.name}")
    for lr in db.query(Consignment).filter(Consignment.trip_id == trip.id, Consignment.status != "Cancelled"):
        _set_vehicle_driver(db, lr, trip.vehicle_id, trip.driver_id)
    return trip


def _move(db: Session, user, trip: Trip, stage: str, note: str | None = None) -> None:
    trip.stage = stage
    _event(db, user, trip, stage, note)


def trip_lrs(db: Session, trip_id: int) -> list[Consignment]:
    return db.query(Consignment).filter(Consignment.trip_id == trip_id, Consignment.status != "Cancelled").order_by(Consignment.id).all()


def advance(db: Session, user, trip: Trip, to_stage: str, data: dict | None = None) -> Trip:
    data = data or {}
    if to_stage not in TRIP_STAGES or to_stage in ("Billed", "Settled", "Cancelled"):
        raise AppError("Invalid stage")
    order = TRIP_STAGES.index
    if trip.stage in ("Closed", "Billed", "Settled", "Cancelled"):
        raise AppError(f"Trip is {trip.stage.lower()}")
    if order(to_stage) <= order(trip.stage):
        raise AppError(f"Trip is already at '{trip.stage}'")
    at = parse_dt(data.get("at")) or now()
    lrs = trip_lrs(db, trip.id)
    target = order(to_stage)
    if target >= order("Vehicle Allocated") and not trip.vehicle_id:
        raise AppError("Allocate a vehicle first")
    if target >= order("Driver Allocated") and not trip.driver_id:
        raise AppError("Allocate a driver first")
    if target >= order("LR Generated") and not lrs:
        raise AppError("Generate at least one LR for this trip first")
    if target >= order("Loading") and not trip.loading_at:
        trip.loading_at = at if to_stage == "Loading" else (trip.loading_at or at)
        for lr in lrs:
            if lr.status == "Booked":
                lr.status = "Loaded"
    if target >= order("Dispatched") and not trip.dispatched_at:
        if data.get("start_km") not in (None, ""):
            trip.start_km = D(data["start_km"])
        if trip.start_km is None:
            raise AppError("Enter the starting kilometre reading")
        threshold = D(app_settings.get(db, "lr")["require_eway_above_value"])
        missing = [lr.lr_no for lr in lrs if D(lr.goods_value) > threshold and not lr.eway_bill_no]
        if missing:
            raise AppError(f"E-way bill number missing for {', '.join(missing)} (goods value above ₹{threshold})")
        _check_vehicle(db, trip.vehicle_id, trip.id, at.date())
        _check_driver(db, trip.driver_id, trip.id, at.date())
        if data.get("fuel_opening_litres") not in (None, ""):
            trip.fuel_opening_litres = D(data["fuel_opening_litres"])
        trip.dispatched_at = at
        db.get(Vehicle, trip.vehicle_id).status = "On Trip"
        db.get(Driver, trip.driver_id).status = "On Trip"
        for lr in lrs:
            if lr.status in ("Booked", "Loaded"):
                lr.status = "In Transit"
        if not trip.expected_delivery_at and trip.route_id:
            route = db.get(Route, trip.route_id)
            if route and route.est_hours:
                from datetime import timedelta

                trip.expected_delivery_at = at + timedelta(hours=float(route.est_hours))
        cust = db.get(Customer, trip.customer_id) if trip.customer_id else None
        notify.event(db, "vehicle_dispatched", {"trip_no": trip.trip_no, "vehicle": db.get(Vehicle, trip.vehicle_id).registration_no, "lrs": ", ".join(l.lr_no for l in lrs), "from": trip.from_place, "to": trip.to_place, "customer": cust.name if cust else ""}, customer=cust, entity=("trips", trip.id))
    if target >= order("Delivered") and not trip.delivered_at:
        trip.delivered_at = at
        for lr in lrs:
            if not lr.delivered_at:
                lr_delivered(db, user, lr, data.get("receiver_name") or lr.receiver_name, data.get("receiver_phone"), data.get("remarks"), at=at)
        cust = db.get(Customer, trip.customer_id) if trip.customer_id else None
        notify.event(db, "delivery_completed", {"trip_no": trip.trip_no, "lrs": ", ".join(l.lr_no for l in lrs), "to": trip.to_place, "customer": cust.name if cust else ""}, customer=cust, entity=("trips", trip.id))
    if target >= order("POD Collected"):
        pending = [lr.lr_no for lr in lrs if not lr.pod_received_at]
        if pending and not data.get("pod_all"):
            raise AppError(f"POD not yet received for {', '.join(pending)}")
        for lr in lrs:
            if not lr.pod_received_at:
                lr_pod(db, user, lr, None)
        trip.pod_received_at = trip.pod_received_at or at
    if target >= order("Closed"):
        if data.get("end_km") not in (None, ""):
            trip.end_km = D(data["end_km"])
        if trip.end_km is None:
            raise AppError("Enter the closing kilometre reading")
        if trip.start_km is not None and D(trip.end_km) < D(trip.start_km):
            raise AppError("Closing km cannot be less than starting km")
        if data.get("fuel_closing_litres") not in (None, ""):
            trip.fuel_closing_litres = D(data["fuel_closing_litres"])
        for f in ("waiting_hours", "detention_days"):
            if data.get(f) not in (None, ""):
                setattr(trip, f, D(data[f]))
        trip.closed_at = at
        start = trip.dispatched_at or trip.loading_at or at
        trip.trip_days = Decimal(max(1, math.ceil((at - start).total_seconds() / 86400)))
        v = db.get(Vehicle, trip.vehicle_id)
        if v:
            v.status = "Available" if v.status == "On Trip" else v.status
            if D(trip.end_km) > D(v.current_odometer):
                v.current_odometer = trip.end_km
        d = db.get(Driver, trip.driver_id)
        if d and d.status == "On Trip":
            d.status = "Available"
    _move(db, user, trip, to_stage, data.get("remarks"))
    log(db, user, "stage", "trips", trip.id, None, {"stage": to_stage})
    return trip


def cancel_trip(db: Session, user, trip: Trip, reason: str) -> Trip:
    if trip.dispatched_at:
        raise AppError("A dispatched trip cannot be cancelled; close it instead")
    if trip_lrs(db, trip.id):
        raise AppError("Cancel or move the LRs of this trip first")
    if not reason:
        raise AppError("Reason is required")
    trip.stage, trip.cancel_reason = "Cancelled", reason
    _event(db, user, trip, "Cancelled", reason)
    log(db, user, "cancel", "trips", trip.id, None, {"stage": "Cancelled"}, reason)
    return trip


def _credit_ledger_for(db: Session, paid_by: str, driver_id: int | None, vendor_id: int | None, bank_ledger_id: int | None) -> int:
    if paid_by == "Driver Cash":
        if not driver_id:
            raise AppError("Driver is required for expenses paid by driver")
        d = db.get(Driver, driver_id)
        return acc.party_ledger(db, "driver", d.id, d.name)
    if paid_by == "Company Cash" or paid_by == "Cash":
        return acc.sys_ledger(db, "CASH")
    if paid_by == "Bank":
        if bank_ledger_id:
            return int(bank_ledger_id)
        from ..models import Ledger

        lid = db.execute(select(Ledger.id).where(Ledger.is_bank.is_(True), Ledger.is_active.is_(True)).order_by(Ledger.id)).scalars().first()
        if not lid:
            raise AppError("No bank account configured – add one in Company → Bank accounts")
        return lid
    if paid_by == "Fuel Card":
        return acc.sys_ledger(db, "FUEL_CARD")
    if paid_by == "FASTag":
        return acc.sys_ledger(db, "FASTAG_WALLET")
    if paid_by == "Vendor Credit":
        from ..models import Vendor

        v = db.get(Vendor, int(vendor_id or 0))
        if not v:
            raise AppError("Select the vendor for credit purchases")
        return acc.party_ledger(db, "vendor", v.id, v.name, v.gstin)
    raise AppError(f"Unknown payment mode {paid_by}")


def add_trip_expense(db: Session, user, trip: Trip, data: dict, via: str = "Office") -> TripExpense:
    if trip.stage in ("Cancelled", "Settled"):
        raise AppError(f"Trip is {trip.stage.lower()}")
    category = data.get("category")
    from ..models.operations import EXPENSE_CATEGORIES

    if category not in EXPENSE_CATEGORIES:
        raise AppError("Select a valid expense category")
    if category == "Diesel" and data.get("litres") and data.get("odometer"):
        fe = record_fuel(db, user, {**data, "vehicle_id": trip.vehicle_id, "driver_id": trip.driver_id, "trip_id": trip.id, "payment_mode": data.get("paid_by") or "Driver Cash", "entry_date": data.get("expense_date"), "entered_via": via})
        return db.query(TripExpense).filter_by(fuel_entry_id=fe.id).one()
    amount = r2(data.get("amount"))
    if amount <= 0:
        raise AppError("Amount must be greater than zero")
    exp = TripExpense(
        trip_id=trip.id, expense_date=parse_date(data.get("expense_date")) or date.today(), category=category, amount=amount,
        litres=D(data.get("litres")) or None, rate=D(data.get("rate")) or None, paid_by=data.get("paid_by") or "Driver Cash",
        vendor_id=int(data["vendor_id"]) if data.get("vendor_id") else None, bill_no=data.get("bill_no"), remarks=data.get("remarks"),
        entered_via=via, approved=via == "Office", document_id=data.get("document_id"), created_by=user.id,
    )
    db.add(exp)
    db.flush()
    _post_expense(db, user, trip, exp, data.get("bank_ledger_id"))
    log(db, user, "create", "trip_expenses", exp.id, None, snapshot(exp))
    return exp


def _post_expense(db: Session, user, trip: Trip, exp: TripExpense, bank_ledger_id=None) -> None:
    dr = acc.sys_ledger(db, acc.EXPENSE_LEDGER_FOR.get(exp.category, "TRIP_OTHER_EXP"))
    cr = _credit_ledger_for(db, exp.paid_by, trip.driver_id, exp.vendor_id, bank_ledger_id)
    v = acc.post(db, user, "Payment" if exp.paid_by in ("Company Cash", "Bank") else "Journal", exp.expense_date, [
        {"ledger_id": dr, "debit": exp.amount, "vehicle_id": trip.vehicle_id, "trip_id": trip.id},
        {"ledger_id": cr, "credit": exp.amount},
    ], f"{exp.category} – trip {trip.trip_no}" + (f" ({exp.remarks})" if exp.remarks else ""), "trip_expense", exp.id, exp.bill_no)
    exp.voucher_id = v.id


def delete_trip_expense(db: Session, user, exp: TripExpense, reason: str) -> None:
    trip = db.get(Trip, exp.trip_id)
    if trip.driver_settlement_id:
        raise AppError("Trip is already settled with the driver")
    if exp.voucher_id:
        acc.reverse(db, user, exp.voucher_id, reason or "Trip expense removed")
    if exp.fuel_entry_id:
        fe = db.get(FuelEntry, exp.fuel_entry_id)
        if fe:
            fe.remarks = f"[REVERSED] {fe.remarks or ''}"
            fe.litres = ZERO
            fe.amount = ZERO
    log(db, user, "delete", "trip_expenses", exp.id, snapshot(exp), None, reason)
    db.delete(exp)


def trip_pnl(db: Session, trip: Trip) -> dict:
    lrs = trip_lrs(db, trip.id)
    revenue = sum((D(l.total_freight) for l in lrs), ZERO)
    by_cat: dict[str, Decimal] = {}
    for e in db.query(TripExpense).filter_by(trip_id=trip.id):
        by_cat[e.category] = by_cat.get(e.category, ZERO) + D(e.amount)
    expenses = sum(by_cat.values(), ZERO)
    km = (D(trip.end_km) - D(trip.start_km)) if trip.end_km is not None and trip.start_km is not None else ZERO
    litres = sum((D(f.litres) for f in db.query(FuelEntry).filter_by(trip_id=trip.id)), ZERO)
    return {
        "revenue": r2(revenue), "expenses": r2(expenses), "profit": r2(revenue - expenses), "by_category": {k: r2(v) for k, v in by_cat.items()},
        "km": km, "diesel_litres": litres, "kmpl": r2(km / litres) if litres else None,
        "margin_pct": r2((revenue - expenses) / revenue * 100) if revenue else None,
    }


# ------------------------------------------------------------------ driver money


def pay_driver_advance(db: Session, user, adv: DriverAdvance, bank_ledger_id=None) -> DriverAdvance:
    d = db.get(Driver, adv.driver_id)
    if not d:
        raise AppError("Driver not found")
    if D(adv.amount) <= 0:
        raise AppError("Amount must be greater than zero")
    dl = acc.party_ledger(db, "driver", d.id, d.name)
    d.ledger_id = dl
    cr = _credit_ledger_for(db, "Company Cash" if adv.mode == "Cash" else "Bank", None, None, bank_ledger_id)
    v = acc.post(db, user, "Payment", adv.advance_date, [{"ledger_id": dl, "debit": adv.amount, "trip_id": adv.trip_id}, {"ledger_id": cr, "credit": adv.amount}], f"{adv.purpose or 'Advance'} to driver {d.name}", "driver_advance", adv.id)
    adv.voucher_id = v.id
    if adv.trip_id:
        t = db.get(Trip, adv.trip_id)
        if t:
            t.advance_to_driver = r2(D(t.advance_to_driver) + D(adv.amount))
    return adv


def settlement_preview(db: Session, driver_id: int, upto: date, trip_ids: list[int] | None = None) -> dict:
    d = db.get(Driver, driver_id)
    if not d:
        raise AppError("Driver not found", 404)
    q = db.query(Trip).filter(Trip.driver_id == driver_id, Trip.driver_settlement_id.is_(None), Trip.stage.in_(["Closed", "Billed", "POD Collected", "Delivered"]))
    if trip_ids:
        q = q.filter(Trip.id.in_(trip_ids))
    trips = [t for t in q.order_by(Trip.trip_date) if t.trip_date <= upto and t.closed_at]
    lines = []
    tot = {k: ZERO for k in ("days", "bata", "food", "trip_allowance", "km_allowance", "driver_paid")}
    for t in trips:
        days = D(t.trip_days or 1)
        km = max(ZERO, D(t.end_km) - D(t.start_km)) if t.end_km is not None else ZERO
        paid = sum((D(e.amount) for e in db.query(TripExpense).filter_by(trip_id=t.id, paid_by="Driver Cash")), ZERO)
        line = {"trip_id": t.id, "trip_no": t.trip_no, "date": t.trip_date.isoformat(), "route": f"{t.from_place} → {t.to_place}", "days": str(days), "km": str(km),
                "bata": r2(days * D(d.daily_bata)), "food": r2(days * D(d.food_allowance_per_day)), "trip_allowance": r2(d.trip_allowance), "km_allowance": r2(km * D(d.per_km_allowance)), "driver_paid": r2(paid)}
        lines.append(line)
        tot["days"] += days
        for k in ("bata", "food", "trip_allowance", "km_allowance", "driver_paid"):
            tot[k] += line[k]
    advances = db.query(DriverAdvance).filter(DriverAdvance.driver_id == driver_id, DriverAdvance.settlement_id.is_(None), DriverAdvance.advance_date <= upto, DriverAdvance.purpose != "Salary Advance").all()
    adv_total = sum((D(a.amount) for a in advances), ZERO)
    fines = db.query(DriverIncident).filter(DriverIncident.driver_id == driver_id, DriverIncident.recover_from_driver.is_(True), DriverIncident.status != "Closed").all()
    fine_total = sum((D(f.amount) for f in fines), ZERO)
    earnings = tot["bata"] + tot["food"] + tot["trip_allowance"] + tot["km_allowance"]
    net = earnings + tot["driver_paid"] - adv_total - fine_total
    ledger_bal = acc.ledger_balance(db, d.ledger_id) if d.ledger_id else ZERO
    return {
        "driver_id": d.id, "driver": d.name, "trips": lines, "totals": {k: r2(v) for k, v in tot.items()},
        "earnings": r2(earnings), "advances": [{"id": a.id, "date": a.advance_date.isoformat(), "amount": r2(a.amount), "trip_id": a.trip_id} for a in advances],
        "advances_total": r2(adv_total), "fines": [{"id": f.id, "kind": f.kind, "amount": r2(f.amount)} for f in fines], "fines_total": r2(fine_total),
        "net_payable": r2(net), "ledger_balance_before": r2(ledger_bal),
    }


def post_settlement(db: Session, user, driver_id: int, upto: date, trip_ids: list[int] | None, other_deductions=0, pay_mode: str | None = None, bank_ledger_id=None, remarks: str | None = None) -> DriverSettlement:
    p = settlement_preview(db, driver_id, upto, trip_ids)
    if not p["trips"] and not p["advances"]:
        raise AppError("Nothing to settle for this driver")
    d = db.get(Driver, driver_id)
    dl = acc.party_ledger(db, "driver", d.id, d.name)
    d.ledger_id = dl
    other = r2(other_deductions)
    net = r2(D(p["net_payable"]) - other)
    s = DriverSettlement(
        settlement_no=next_number(db, "DRIVER_SETTLEMENT", upto), driver_id=driver_id, settlement_date=upto,
        period_from=min((date.fromisoformat(t["date"]) for t in p["trips"]), default=upto), period_to=upto,
        trip_ids=[t["trip_id"] for t in p["trips"]], trip_days=p["totals"]["days"], bata_total=p["totals"]["bata"], food_total=p["totals"]["food"],
        trip_allowance_total=p["totals"]["trip_allowance"], km_allowance_total=p["totals"]["km_allowance"], driver_paid_expenses=p["totals"]["driver_paid"],
        advances_total=p["advances_total"], fines_recovered=p["fines_total"], other_deductions=other, net_payable=net, remarks=remarks,
        details=jsonable(p), created_by=user.id,
    )
    db.add(s)
    db.flush()
    lines = []
    if D(p["earnings"]) > 0:
        lines += [{"ledger_id": acc.sys_ledger(db, "DRIVER_BATA_EXP"), "debit": p["earnings"]}, {"ledger_id": dl, "credit": p["earnings"]}]
    deductions = D(p["fines_total"]) + other
    if deductions > 0:
        lines += [{"ledger_id": dl, "debit": deductions}, {"ledger_id": acc.sys_ledger(db, "FINES_EXP"), "credit": deductions}]
    if lines:
        v = acc.post(db, user, "Journal", upto, lines, f"Driver settlement {s.settlement_no} – {d.name}", "driver_settlement", s.id)
        s.voucher_id = v.id
    if pay_mode and net > 0:
        cr = _credit_ledger_for(db, "Company Cash" if pay_mode == "Cash" else "Bank", None, None, bank_ledger_id)
        acc.post(db, user, "Payment", upto, [{"ledger_id": dl, "debit": net}, {"ledger_id": cr, "credit": net}], f"Payment of driver settlement {s.settlement_no}", "driver_settlement_payment", s.id)
        s.status = "Paid"
    for t in db.query(Trip).filter(Trip.id.in_(s.trip_ids or [0])):
        t.driver_settlement_id = s.id
        if t.stage == "Billed":
            _move(db, user, t, "Settled", f"Driver settlement {s.settlement_no}")
    for a in db.query(DriverAdvance).filter(DriverAdvance.id.in_([a["id"] for a in p["advances"]] or [0])):
        a.settlement_id = s.id
    for f in db.query(DriverIncident).filter(DriverIncident.id.in_([f["id"] for f in p["fines"]] or [0])):
        f.status = "Closed"
    log(db, user, "create", "driver_settlements", s.id, None, {"no": s.settlement_no, "net": str(net)})
    return s


# ------------------------------------------------------------------ fuel


def record_fuel(db: Session, user, data: dict) -> FuelEntry:
    vehicle = db.get(Vehicle, int(data.get("vehicle_id") or 0))
    if not vehicle:
        raise AppError("Select a vehicle")
    litres, rate = D(data.get("litres")), D(data.get("rate"))
    if litres <= 0 or rate <= 0:
        raise AppError("Litres and rate must be greater than zero")
    odo = D(data.get("odometer"))
    if odo <= 0:
        raise AppError("Odometer reading is required")
    last = db.query(FuelEntry).filter(FuelEntry.vehicle_id == vehicle.id).order_by(FuelEntry.odometer.desc()).first()
    if last and odo < D(last.odometer):
        raise AppError(f"Odometer {odo} is less than the previous fuel entry ({last.odometer})")
    amount = r2(data.get("amount")) if data.get("amount") not in (None, "") else r2(litres * rate)
    fe = FuelEntry(
        entry_date=parse_date(data.get("entry_date")) or date.today(), vehicle_id=vehicle.id,
        driver_id=int(data["driver_id"]) if data.get("driver_id") else None, trip_id=int(data["trip_id"]) if data.get("trip_id") else None,
        station_id=int(data["station_id"]) if data.get("station_id") else None, fuel_card_id=int(data["fuel_card_id"]) if data.get("fuel_card_id") else None,
        litres=litres, rate=rate, amount=amount, odometer=odo, full_tank=bool(data.get("full_tank", True)), payment_mode=data.get("payment_mode") or "Vendor Credit",
        bill_no=data.get("bill_no"), entered_via=data.get("entered_via") or "Office", remarks=data.get("remarks"), created_by=user.id,
    )
    db.add(fe)
    db.flush()
    vendor_id = data.get("vendor_id")
    if fe.payment_mode == "Vendor Credit" and not vendor_id and fe.station_id:
        st = db.get(FuelStation, fe.station_id)
        vendor_id = st.vendor_id if st else None
    mode_map = {"Cash": "Company Cash", "Bank": "Bank", "Fuel Card": "Fuel Card", "Vendor Credit": "Vendor Credit", "Driver Cash": "Driver Cash"}
    cr = _credit_ledger_for(db, mode_map.get(fe.payment_mode, fe.payment_mode), fe.driver_id, vendor_id, data.get("bank_ledger_id"))
    v = acc.post(db, user, "Purchase" if fe.payment_mode == "Vendor Credit" else "Journal", fe.entry_date, [
        {"ledger_id": acc.sys_ledger(db, "DIESEL_EXP"), "debit": amount, "vehicle_id": vehicle.id, "trip_id": fe.trip_id},
        {"ledger_id": cr, "credit": amount},
    ], f"Diesel {litres} L @ {rate} – {vehicle.registration_no}", "fuel_entry", fe.id, fe.bill_no)
    fe.voucher_id = v.id
    if D(odo) > D(vehicle.current_odometer):
        vehicle.current_odometer = odo
    if fe.trip_id:
        db.add(TripExpense(trip_id=fe.trip_id, expense_date=fe.entry_date, category="Diesel", amount=amount, litres=litres, rate=rate,
                           paid_by=mode_map.get(fe.payment_mode, fe.payment_mode), vendor_id=int(vendor_id) if vendor_id else None, bill_no=fe.bill_no,
                           voucher_id=v.id, fuel_entry_id=fe.id, entered_via=fe.entered_via, created_by=user.id))
    db.flush()
    log(db, user, "create", "fuel_entries", fe.id, None, snapshot(fe))
    return fe


def mileage(db: Session, vehicle_id: int, start: date | None = None, end: date | None = None) -> list[dict]:
    """km/l between consecutive full-tank fills: distance since previous full tank / litres filled since then."""
    v = db.get(Vehicle, vehicle_id)
    entries = db.query(FuelEntry).filter(FuelEntry.vehicle_id == vehicle_id, FuelEntry.litres > 0).order_by(FuelEntry.odometer, FuelEntry.id).all()
    tol = D(app_settings.get(db, "alerts")["fuel_tolerance_pct"])
    rows, prev_full, litres_since = [], None, ZERO
    for e in entries:
        litres_since += D(e.litres)
        if e.full_tank:
            if prev_full is not None:
                dist = D(e.odometer) - D(prev_full.odometer)
                kmpl = r2(dist / litres_since) if litres_since else None
                abnormal = bool(v.expected_kmpl and kmpl is not None and kmpl < D(v.expected_kmpl) * (1 - tol / 100))
                if (not start or e.entry_date >= start) and (not end or e.entry_date <= end):
                    rows.append({"date": e.entry_date, "from_km": prev_full.odometer, "to_km": e.odometer, "distance": dist, "litres": r2(litres_since),
                                 "kmpl": kmpl, "expected": v.expected_kmpl, "abnormal": abnormal, "driver_id": e.driver_id, "entry_id": e.id})
            prev_full, litres_since = e, ZERO
    return rows
