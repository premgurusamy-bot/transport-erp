"""Quotation cost engine. Internal cost, owner quote and margin are computed and protected here."""
from __future__ import annotations

import math
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.db import money
from app.core.services import get_config


def round_up(v: Decimal, step: int = 50) -> Decimal:
    return Decimal(math.ceil(float(v) / step) * step).quantize(Decimal("0.01"))


def ptl_share(db: Session, weight_kg, volume_cft, floor_sqft, ref_payload_kg, ref_volume_cft, ref_floor_sqft) -> dict:
    """Share of a vehicle used by one PTL consignment under the configured, versioned allocation formula."""
    f = get_config(db, "ptl.allocation_formula")
    w = f.get("weights", {"weight": 1})
    parts = {
        "weight": float(weight_kg or 0) / float(ref_payload_kg or 1),
        "volume": float(volume_cft or 0) / float(ref_volume_cft or 1) if volume_cft else float(weight_kg or 0) / float(ref_payload_kg or 1),
        "floor": float(floor_sqft or 0) / float(ref_floor_sqft or 1) if floor_sqft else float(weight_kg or 0) / float(ref_payload_kg or 1),
    }
    method = f.get("method", "hybrid")
    if method == "chargeable_weight":
        share = max(parts["weight"], parts["volume"])
    elif method in parts:
        share = parts[method]
    else:
        share = sum(parts[k] * float(w.get(k, 0)) for k in parts) / (sum(float(v) for v in w.values()) or 1)
    return {"share": round(min(max(share, 0.0), 1.0), 4), "parts": {k: round(v, 4) for k, v in parts.items()},
            "formula_version": f.get("version", 1), "method": method, "weights": w}


def compute_costs(
    db: Session, *, service_type: str, vehicle_option: str, distance_km: Decimal, declared_value: Decimal | None,
    owner_quote: Decimal | None, negotiated_owner_rate: Decimal | None, direct_expenses: list[dict],
    toll_estimate: Decimal | None = None, weight_kg=None, volume_cft=None, floor_sqft=None,
    ref_vehicle: dict | None = None,
) -> dict:
    r = get_config(db, "pricing.cost_rates")
    km = Decimal(str(distance_km or 0))
    lines: list[dict] = []
    if vehicle_option == "own":
        days = max(1, math.ceil(float(km) / float(r["km_per_day"])))
        fuel = money(km * Decimal(str(r["own_fuel_per_km"])))
        maint = money(km * Decimal(str(r["own_maintenance_per_km"])))
        deadhead = money((fuel + maint) * Decimal(str(r["deadhead_pct"])) / 100)
        lines += [
            {"code": "fuel", "label": "Fuel", "amount": fuel},
            {"code": "maintenance", "label": "Tyres/maintenance (per km)", "amount": maint},
            {"code": "deadhead", "label": f"Empty return allowance {r['deadhead_pct']}%", "amount": deadhead},
            {"code": "driver", "label": f"Driver remuneration {days} day(s)", "amount": money(Decimal(days) * Decimal(str(r["own_driver_per_day"])))},
            {"code": "fixed", "label": f"Vehicle fixed cost {days} day(s)", "amount": money(Decimal(days) * Decimal(str(r["own_fixed_per_day"])))},
        ]
    else:
        hire = negotiated_owner_rate or owner_quote
        if hire is None:
            raise ValueError("owner_quote_required")
        lines.append({"code": "owner_hire", "label": "Attached vehicle hire", "amount": money(hire)})
    toll = money(toll_estimate if toll_estimate is not None else km * Decimal(str(r["toll_per_km"])))
    lines.append({"code": "toll", "label": "Toll (estimate)", "amount": toll})
    vehicle_cost = sum((l["amount"] for l in lines), Decimal("0"))
    allocation = None
    if service_type == "PTL" and ref_vehicle:
        allocation = ptl_share(db, weight_kg, volume_cft, floor_sqft, ref_vehicle["payload_kg"],
                               ref_vehicle.get("volume_cft"), ref_vehicle.get("floor_sqft"))
        reserve = Decimal(str(get_config(db, "ptl.capacity_reserve_pct"))) / 100
        share = Decimal(str(allocation["share"])) * (1 + reserve)
        lines = [{**l, "amount": money(l["amount"] * share), "label": l["label"] + f" (PTL share {allocation['share']:.2%})"} for l in lines]
        vehicle_cost = sum((l["amount"] for l in lines), Decimal("0"))
    risk = money(Decimal(str(declared_value or 0)) * Decimal(str(r["insurance_risk_pct"])) / 100)
    if risk:
        lines.append({"code": "insurance_risk", "label": "Insurance/risk provision", "amount": risk})
    direct = money(sum((Decimal(str(e.get("amount", 0))) for e in direct_expenses), Decimal("0")))
    for e in direct_expenses:
        lines.append({"code": e.get("code", "direct"), "label": e.get("label", "Direct expense"), "amount": money(e.get("amount", 0))})
    total = money(vehicle_cost + risk + direct)
    min_margin = Decimal(str(get_config(db, "pricing.min_margin_pct")))
    floor = money(total / (1 - min_margin / 100)) if min_margin < 100 else total
    list_price = round_up(total * Decimal("1.18"))
    return {"lines": [{**l, "amount": str(l["amount"])} for l in lines], "internal_cost": total, "direct_expenses": direct,
            "floor_price": floor, "suggested_price": max(list_price, round_up(floor)), "allocation": allocation,
            "min_margin_pct": float(min_margin)}


def margin(selling: Decimal, cost: Decimal) -> tuple[Decimal, Decimal]:
    contribution = money(Decimal(selling) - Decimal(cost))
    pct = (contribution / Decimal(selling) * 100).quantize(Decimal("0.01")) if selling else Decimal("0")
    return contribution, pct
