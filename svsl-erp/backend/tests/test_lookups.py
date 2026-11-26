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
