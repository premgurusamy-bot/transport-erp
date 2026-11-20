from datetime import date
from decimal import Decimal

import pytest

from app.core.deps import AppError
from app.models import RateContract
from app.services.freight import FreightInputs, calculate

from .conftest import make_contract, make_customer


def C(**kw):
    base = dict(id=1, contract_no="T", version=1, rate=Decimal(0), min_freight=Decimal(0), min_weight_kg=Decimal(0), slabs=None, monthly_trips_included=0, extra_trip_rate=Decimal(0),
                waiting_free_hours=Decimal(0), waiting_rate_per_hour=Decimal(0), detention_free_days=Decimal(0), detention_rate_per_day=Decimal(0), loading_charge=Decimal(0),
                unloading_charge=Decimal(0), extra_stop_charge=Decimal(0), return_load_mode="none", return_load_value=Decimal(0))
    base.update(kw)
    c = RateContract()
    for k, v in base.items():
        setattr(c, k, v)
    return c


@pytest.mark.parametrize("basis,rate,inputs,expected", [
    ("per_trip", 12000, {"trips": 2}, "24000.00"),
    ("per_turn", 3000, {"turns": 3}, "9000.00"),
    ("per_vehicle", 15000, {"vehicles": 2}, "30000.00"),
    ("per_km", 32, {"km": 505}, "16160.00"),
    ("per_tonne", 1100, {"weight_kg": 12500}, "13750.00"),
    ("per_kg", "1.25", {"weight_kg": 800}, "1000.00"),
    ("per_piece", 45, {"quantity": 400}, "18000.00"),
    ("per_load", 9000, {"loads": 1}, "9000.00"),
    ("route_fixed", 11000, {"trips": 1}, "11000.00"),
    ("monthly_fixed", 165000, {"months": 1}, "165000.00"),
])
def test_bases(basis, rate, inputs, expected):
    r = calculate(C(basis=basis, rate=Decimal(str(rate))), FreightInputs.from_dict(inputs))
    assert r["total"] == Decimal(expected)


def test_minimum_guarantee_and_min_weight():
    r = calculate(C(basis="per_piece", rate=Decimal(45), min_freight=Decimal(15000)), FreightInputs.from_dict({"quantity": 100}))
    assert r["basic_freight"] == Decimal("15000.00") and r["min_applied"]
    r = calculate(C(basis="per_tonne", rate=Decimal(1000), min_weight_kg=Decimal(9000)), FreightInputs.from_dict({"weight_kg": 4000}))
    assert r["basic_freight"] == Decimal("9000.00")


def test_slabs():
    slabs = [{"from": 0, "to": 100, "rate": 3000, "mode": "flat"}, {"from": 100.01, "to": 500, "rate": 28, "mode": "per_unit"}, {"from": 500.01, "to": None, "rate": 25, "mode": "per_unit"}]
    assert calculate(C(basis="distance_slab", slabs=slabs), FreightInputs.from_dict({"km": 80}))["total"] == Decimal("3000.00")
    assert calculate(C(basis="distance_slab", slabs=slabs), FreightInputs.from_dict({"km": 300}))["total"] == Decimal("8400.00")
    assert calculate(C(basis="distance_slab", slabs=slabs), FreightInputs.from_dict({"km": 700}))["total"] == Decimal("17500.00")
    wslabs = [{"from": 0, "to": 5000, "rate": 6000, "mode": "flat"}, {"from": 5000.01, "to": None, "rate": 1000, "mode": "per_unit"}]
    assert calculate(C(basis="weight_slab", slabs=wslabs), FreightInputs.from_dict({"weight_kg": 9000}))["total"] == Decimal("9000.00")
    with pytest.raises(AppError):
        calculate(C(basis="distance_slab", slabs=[{"from": 0, "to": 10, "rate": 1}]), FreightInputs.from_dict({"km": 50}))


def test_addons_waiting_detention_stops_return():
    c = C(basis="per_trip", rate=Decimal(10000), waiting_free_hours=Decimal(4), waiting_rate_per_hour=Decimal(200), detention_free_days=Decimal(1), detention_rate_per_day=Decimal(2500),
          loading_charge=Decimal(500), unloading_charge=Decimal(400), extra_stop_charge=Decimal(750), return_load_mode="percent", return_load_value=Decimal(60))
    r = calculate(c, FreightInputs.from_dict({"waiting_hours": 7, "detention_days": 3, "extra_stops": 2}))
    assert r["waiting_charges"] == Decimal("600.00")
    assert r["detention_charges"] == Decimal("5000.00")
    assert r["extra_stop_charges"] == Decimal("1500.00")
    assert r["total"] == Decimal("10000") + 600 + 5000 + 500 + 400 + 1500
    ret = calculate(c, FreightInputs.from_dict({"is_return": True, "include_loading": False, "include_unloading": False}))
    assert ret["basic_freight"] == Decimal("6000.00") and ret["total"] == Decimal("6000.00")


def test_monthly_extra_trips():
    c = C(basis="monthly_fixed", rate=Decimal(165000), monthly_trips_included=26, extra_trip_rate=Decimal(6000))
    assert calculate(c, FreightInputs.from_dict({"months": 1, "trips_in_period": 29}))["total"] == Decimal("183000.00")


def test_contract_revision_keeps_history(api):
    cust = make_customer(api)
    c1 = make_contract(api, cust["id"], rate=12000)
    # LR dated before revision uses v1
    calc = api.post("/api/freight/calculate", {"customer_id": cust["id"], "date": "2024-06-01", "inputs": {"trips": 1}})
    assert Decimal(calc["total"]) == Decimal("12000")
    api.post(f"/api/rates/{c1['id']}/revise", {"effective_from": "2025-01-01", "reason": "Diesel price revision", "changes": {"rate": 13500}})
    old = api.post("/api/freight/calculate", {"customer_id": cust["id"], "date": "2024-06-01", "inputs": {"trips": 1}})
    new = api.post("/api/freight/calculate", {"customer_id": cust["id"], "date": "2025-02-01", "inputs": {"trips": 1}})
    assert Decimal(old["total"]) == Decimal("12000") and old["contract_version"] == 1
    assert Decimal(new["total"]) == Decimal("13500") and new["contract_version"] == 2
    hist = api.get(f"/api/rates/{c1['id']}/history")
    assert [h["version"] for h in hist] == [1, 2] and hist[0]["status"] == "Superseded" and hist[0]["effective_to"] == "2024-12-31"


def test_most_specific_contract_wins(api):
    cust = make_customer(api)
    route = api.post("/api/r/routes", {"code": "R-SPEC-1", "origin": "Coimbatore", "destination": "Hosur", "distance_km": 330})
    make_contract(api, cust["id"], rate=9000)
    make_contract(api, cust["id"], rate=10500, route_id=route["id"])
    generic = api.post("/api/freight/calculate", {"customer_id": cust["id"], "inputs": {}})
    specific = api.post("/api/freight/calculate", {"customer_id": cust["id"], "route_id": route["id"], "inputs": {}})
    assert Decimal(generic["total"]) == 9000 and Decimal(specific["total"]) == 10500
