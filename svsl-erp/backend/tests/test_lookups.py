"""Every dropdown the screens can show must have a working lookup list (a 404 here means an empty dropdown)."""
import re
from pathlib import Path

from app.api.crud import REGISTRY
from app.models.base import Base

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _refs_used_by_forms() -> set[str]:
    refs = set()
    for res in REGISTRY.values():  # generic forms show a dropdown for every column with a ref
        for col in res.model.__table__.columns:
            if (col.info or {}).get("ref"):
                refs.add(col.info["ref"])
    for table in Base.metadata.tables.values():  # custom screens reuse the same model metadata
        for col in table.columns:
            if (col.info or {}).get("ref"):
                refs.add(col.info["ref"])
    for f in FRONTEND.rglob("*.tsx"):  # dropdowns written directly in the screens
        text = f.read_text(encoding="utf-8")
        refs.update(re.findall(r'refName="([a-z_]+)"', text))
        refs.update(re.findall(r'useLookup\("([a-z_]+)"', text))
        for block in re.findall(r"REF: Record<string, string> = \{([^}]*)\}", text):
            refs.update(re.findall(r':\s*"([a-z_]+)"', block))
    return refs


def test_every_dropdown_has_a_lookup(client, admin):
    refs = _refs_used_by_forms()
    assert {"trips", "consignments"} <= refs
    broken = {ref: client.get(f"/api/r/{ref}?lookup=1", headers=admin).status_code for ref in sorted(refs)}
    broken = {k: v for k, v in broken.items() if v != 200}
    assert not broken, f"dropdown lookups failing: {broken}"


def test_trip_and_lr_lookups_are_read_only(client, admin):
    for name in ("trips", "consignments"):
        assert isinstance(client.get(f"/api/r/{name}?lookup=1", headers=admin).json(), list)
        assert client.get(f"/api/r/{name}", headers=admin).status_code == 404
        assert client.get(f"/api/r/{name}/meta", headers=admin).status_code == 404
        assert client.get(f"/api/r/{name}/1", headers=admin).status_code == 404
        assert client.post(f"/api/r/{name}", json={}, headers=admin).status_code == 404
        assert client.put(f"/api/r/{name}/1", json={}, headers=admin).status_code == 404
        assert client.delete(f"/api/r/{name}/1", headers=admin).status_code == 404


def test_list_summaries_and_dashboards(client, admin):
    from app.api.crud import REGISTRY

    for name, res in REGISTRY.items():
        r = client.get(f"/api/r/{name}/summary", headers=admin)
        if res.lookup_only:
            from app.api.crud import STATS

            assert r.status_code == (200 if name in STATS else 404), name
            continue
        assert r.status_code == 200, f"{name}: {r.text}"
        s = r.json()
        assert s["total"] >= 0
        if "by" in s:
            assert sum(c["count"] for c in s["by"]["counts"]) <= s["total"]
    # restricted fields are never used for the breakdown
    assert client.get("/api/r/employees/summary", headers=admin).json().get("by", {}).get("field") not in ("basic", "hra")

    d = client.get("/api/dashboard", headers=admin).json()
    for k in ("prev", "on_time", "utilization_pct", "open_trips", "delayed_trips", "ongoing", "maintenance_due"):
        assert k in d, k
    a = client.get("/api/accounts/summary", headers=admin).json()
    assert [b["bucket"] for b in a["ar_ageing"]] == ["Not due", "0-30", "31-60", "61-90", "90+"]
    assert {"billing", "purchases", "receipts", "payments"} <= set(a["compare"])
    assert a["fy"]["trend"] and {"month", "income", "expenses", "net"} <= set(a["fy"]["trend"][0])


def test_summaries_for_workflow_screens(client, admin):
    from app.api.crud import STATS

    for name in STATS:
        r = client.get(f"/api/r/{name}/summary", headers=admin)
        assert r.status_code == 200, f"{name}: {r.text}"
        assert "total" in r.json()


def test_global_search_and_filters(client, admin):
    r = client.post("/api/r/vehicles", json={"registration_no": "TN99ZZ4321", "vehicle_type": "Closed Body Truck", "ownership": "Owned"}, headers=admin)
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    groups = client.get("/api/search?q=tn 99-zz 4321", headers=admin).json()  # spaces / hyphens ignored for vehicle numbers
    veh = next(g for g in groups if g["kind"] == "vehicle")
    assert veh["items"][0]["id"] == vid
    assert client.get("/api/search?q=a", headers=admin).json() == []  # at least 2 characters
    for url in (f"/api/trips?vehicle_id={vid}", f"/api/lr?vehicle_id={vid}&driver_id=1&route_id=1", f"/api/vouchers?vehicle_id={vid}", f"/api/maintenance/jobs?vehicle_id={vid}&from=2020-01-01&to=2099-01-01",
                f"/api/vendor-bills?vehicle_id={vid}&from=2020-01-01", f"/api/r/fuel_entries?vehicle_id={vid}&from=2020-01-01&to=2099-12-31"):
        assert client.get(url, headers=admin).status_code == 200, url
    assert client.get("/api/r/fuel_entries/meta", headers=admin).json()["date_field"] == "entry_date"


def test_restricted_fields_cannot_be_used_to_filter_or_sort(client):
    import pytest
    from app.api.crud import REGISTRY, _query
    from app.core.deps import AppError, CurrentUser
    from app.db import SessionLocal

    hr_only = CurrentUser(id=1, username="hr", full_name="HR", role="HR", permissions=["hr:read"])
    db = SessionLocal()
    try:
        with pytest.raises(AppError) as e:
            _query(db, REGISTRY["employees"], {"basic": "23456"}, hr_only)
        assert e.value.status_code == 403
        _query(db, REGISTRY["employees"], {"basic": "23456"}, CurrentUser(id=1, username="a", full_name="A", role="Admin", permissions=["hr:read", "hr:salary"]))
    finally:
        db.close()
