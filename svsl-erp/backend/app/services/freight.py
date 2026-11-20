"""Freight rate engine.

* Finds the agreed contract for a customer/date/route/vehicle type/goods (most specific wins).
* Calculates freight for every supported basis, plus minimum guarantee, waiting, detention,
  loading/unloading, additional stops and return-load adjustments.
* Revisions create a new contract version; earlier versions keep applying to earlier dates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.audit import log, snapshot
from ..core.deps import AppError
from ..core.money import D, ZERO, r2
from ..models import RateContract
from ..models.operations import FREIGHT_BASES

BASIS_LABELS = {
    "per_trip": ("Per trip", "trip"),
    "per_turn": ("Per turn", "turn"),
    "per_vehicle": ("Per vehicle", "vehicle"),
    "per_km": ("Per kilometre", "km"),
    "per_tonne": ("Per tonne", "tonne"),
    "per_kg": ("Per kilogram", "kg"),
    "per_piece": ("Per number / piece", "nos"),
    "per_load": ("Per load", "load"),
    "monthly_fixed": ("Fixed monthly contract", "month"),
    "route_fixed": ("Route-based contract", "trip"),
    "distance_slab": ("Distance slab", "km"),
    "weight_slab": ("Weight slab", "tonne"),
}


@dataclass
class FreightInputs:
    trips: Decimal = Decimal("1")
    turns: Decimal = Decimal("1")
    vehicles: Decimal = Decimal("1")
    km: Decimal = ZERO
    weight_kg: Decimal = ZERO
    quantity: Decimal = ZERO
    loads: Decimal = Decimal("1")
    months: Decimal = Decimal("1")
    trips_in_period: Decimal = ZERO
    waiting_hours: Decimal = ZERO
    detention_days: Decimal = ZERO
    extra_stops: Decimal = ZERO
    is_return: bool = False
    include_loading: bool = True
    include_unloading: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "FreightInputs":
        data = data or {}
        kw = {}
        for name, f in cls.__dataclass_fields__.items():
            if name in data and data[name] is not None and data[name] != "":
                v = data[name]
                if f.type in ("bool", bool):
                    kw[name] = v.strip().lower() in ("1", "true", "yes", "on") if isinstance(v, str) else bool(v)
                else:
                    kw[name] = D(v)
        return cls(**kw)

    def to_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(self).items()}


def _slab_for(slabs: list[dict] | None, value: Decimal) -> dict:
    for slab in slabs or []:
        lo = D(slab.get("from", 0))
        hi = slab.get("to")
        if value >= lo and (hi in (None, "") or value <= D(hi)):
            return slab
    raise AppError(f"No slab in the contract covers {value}. Add a slab for this range.")


def calculate(contract: RateContract, inp: FreightInputs) -> dict:
    basis = contract.basis
    if basis not in FREIGHT_BASES:
        raise AppError(f"Unknown freight basis {basis}")
    rate = D(contract.rate)
    chargeable_kg = max(D(inp.weight_kg), D(contract.min_weight_kg))
    lines: list[dict] = []
    units = ZERO
    if basis == "per_trip":
        units, basic = inp.trips, rate * inp.trips
    elif basis == "per_turn":
        units, basic = inp.turns, rate * inp.turns
    elif basis == "per_vehicle":
        units, basic = inp.vehicles, rate * inp.vehicles
    elif basis == "per_km":
        units, basic = inp.km, rate * inp.km
    elif basis == "per_tonne":
        units = chargeable_kg / Decimal(1000)
        basic = rate * units
    elif basis == "per_kg":
        units, basic = chargeable_kg, rate * chargeable_kg
    elif basis == "per_piece":
        units, basic = inp.quantity, rate * inp.quantity
    elif basis == "per_load":
        units, basic = inp.loads, rate * inp.loads
    elif basis == "monthly_fixed":
        units = inp.months
        basic = rate * inp.months
        included = D(contract.monthly_trips_included) * inp.months
        extra = max(ZERO, inp.trips_in_period - included) if included > 0 else ZERO
        if extra > 0:
            extra_amt = extra * D(contract.extra_trip_rate)
            lines.append({"label": f"Extra trips beyond {included:g} included ({extra:g} × {r2(contract.extra_trip_rate)})", "amount": str(r2(extra_amt))})
            basic += extra_amt
    elif basis == "route_fixed":
        units, basic = inp.trips, rate * inp.trips
    elif basis == "distance_slab":
        slab = _slab_for(contract.slabs, inp.km)
        units = inp.km
        basic = D(slab["rate"]) * (inp.km if slab.get("mode") == "per_unit" else inp.trips)
        rate = D(slab["rate"])
    elif basis == "weight_slab":
        slab = _slab_for(contract.slabs, chargeable_kg)
        units = chargeable_kg / Decimal(1000)
        basic = D(slab["rate"]) * (units if slab.get("mode") == "per_unit" else inp.trips)
        rate = D(slab["rate"])
    else:  # pragma: no cover
        raise AppError("Unsupported basis")

    label, unit = BASIS_LABELS[basis]
    lines.insert(0, {"label": f"{label}: {units.normalize():f} {unit} × ₹{r2(rate)}", "amount": str(r2(basic))})

    if inp.is_return and contract.return_load_mode in ("percent", "fixed"):
        if contract.return_load_mode == "percent":
            new_basic = basic * D(contract.return_load_value) / Decimal(100)
            lines.append({"label": f"Return load at {D(contract.return_load_value):g}% of forward rate", "amount": str(r2(new_basic - basic))})
        else:
            new_basic = D(contract.return_load_value)
            lines.append({"label": "Return load fixed rate", "amount": str(r2(new_basic - basic))})
        basic = new_basic

    min_applied = False
    if D(contract.min_freight) > 0 and basic < D(contract.min_freight):
        lines.append({"label": f"Minimum guaranteed freight ₹{r2(contract.min_freight)} applied", "amount": str(r2(D(contract.min_freight) - basic))})
        basic = D(contract.min_freight)
        min_applied = True

    waiting = max(ZERO, inp.waiting_hours - D(contract.waiting_free_hours)) * D(contract.waiting_rate_per_hour)
    detention = max(ZERO, inp.detention_days - D(contract.detention_free_days)) * D(contract.detention_rate_per_day)
    loading = D(contract.loading_charge) if inp.include_loading else ZERO
    unloading = D(contract.unloading_charge) if inp.include_unloading else ZERO
    stops = inp.extra_stops * D(contract.extra_stop_charge)
    for lbl, amt in (("Waiting charges", waiting), ("Detention charges", detention), ("Loading charges", loading), ("Unloading charges", unloading), ("Additional stop charges", stops)):
        if amt:
            lines.append({"label": lbl, "amount": str(r2(amt))})

    basic, waiting, detention, loading, unloading, stops = map(r2, (basic, waiting, detention, loading, unloading, stops))
    total = basic + waiting + detention + loading + unloading + stops
    return {
        "contract_id": contract.id,
        "contract_no": contract.contract_no,
        "contract_version": contract.version,
        "basis": basis,
        "basis_label": label,
        "rate": str(r2(rate)) if basis not in ("per_kg",) else str(D(rate)),
        "units": str(units),
        "chargeable_weight_kg": str(chargeable_kg),
        "basic_freight": basic,
        "waiting_charges": waiting,
        "detention_charges": detention,
        "loading_charges": loading,
        "unloading_charges": unloading,
        "extra_stop_charges": stops,
        "min_applied": min_applied,
        "total": total,
        "lines": lines,
        "inputs": inp.to_dict(),
    }


def find_contract(
    db: Session,
    customer_id: int,
    on: date,
    route_id: int | None = None,
    vehicle_type: str | None = None,
    goods: str | None = None,
    basis: str | None = None,
) -> RateContract | None:
    stmt = select(RateContract).where(
        RateContract.customer_id == customer_id,
        RateContract.status.in_(["Active", "Superseded"]),
        RateContract.effective_from <= on,
        or_(RateContract.effective_to.is_(None), RateContract.effective_to >= on),
    )
    if basis:
        stmt = stmt.where(RateContract.basis == basis)
    best, best_score = None, -1
    for c in db.execute(stmt).scalars():
        score = 0
        if c.route_id:
            if c.route_id != route_id:
                continue
            score += 4
        if c.vehicle_type:
            if (vehicle_type or "") != c.vehicle_type:
                continue
            score += 2
        if c.goods_category:
            if not goods or c.goods_category.lower() not in goods.lower():
                continue
            score += 1
        if score > best_score or (score == best_score and best and c.effective_from > best.effective_from):
            best, best_score = c, score
    return best


def revise(db: Session, user, contract_id: int, changes: dict, effective_from: date, reason: str) -> RateContract:
    old = db.get(RateContract, contract_id)
    if not old:
        raise AppError("Contract not found", 404)
    if old.status not in ("Active",):
        raise AppError("Only the active version of a contract can be revised")
    if not reason:
        raise AppError("Revision reason is required")
    if effective_from <= old.effective_from:
        raise AppError("Revision must take effect after the current version's start date")
    latest = db.execute(
        select(RateContract).where(RateContract.contract_no == old.contract_no).order_by(RateContract.version.desc()).limit(1)
    ).scalar_one()
    new = RateContract()
    for col in RateContract.__table__.columns:
        if col.name in ("id", "created_at", "updated_at"):
            continue
        setattr(new, col.name, getattr(old, col.name))
    allowed = {c.name for c in RateContract.__table__.columns} - {"id", "contract_no", "version", "customer_id", "status", "created_at", "updated_at", "created_by", "updated_by", "effective_from", "effective_to"}
    for k, v in changes.items():
        if k in allowed:
            setattr(new, k, v)
    new.version = latest.version + 1
    new.effective_from = effective_from
    new.effective_to = changes.get("effective_to") or old.effective_to
    new.status = "Active"
    new.revision_reason = reason
    new.created_by = user.id
    before = snapshot(old)
    old.effective_to = effective_from - timedelta(days=1)
    old.status = "Superseded"
    db.add(new)
    db.flush()
    log(db, user, "revise", "rate_contracts", old.id, before, snapshot(new), reason)
    return new
