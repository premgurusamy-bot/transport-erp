"""Backlog features: GPS route deviation & long stoppage, transshipment, fleet KPIs, outage paper forms, TOTP two-factor."""
from datetime import date, datetime, timedelta, timezone

from app.core.security import totp
from tests.conftest import login, uniq
from tests.flows import deliver_all, load_and_dispatch, new_customer, new_driver, new_vehicle, quoted_booking


def _ping(drv, trip_id, lat, lng, at):
    drv.post("/api/v1/gps/ping", {"trip_id": trip_id, "lat": lat, "lng": lng, "recorded_at": at.isoformat()})


def test_route_deviation_and_long_stoppage(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    b = quoted_booking(sales, ops, c["id"], lookup)  # Coimbatore -> Chennai
    v, d = new_vehicle(owner), new_driver(owner)
    t = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v["id"], "driver_id": d["id"]})
    drv = load_and_dispatch(client, ops, t, d, v)
    now = datetime.now(timezone.utc)
    _ping(drv, t["id"], 12.05, 78.61, now - timedelta(minutes=50))  # on corridor
    tr = ops.get(f"/api/v1/trips/{t['id']}/track")
    assert tr["evaluation"]["deviation_km"] < 10 and len(tr["corridor"]) == 2
    assert not any("deviation" in x["title"] for x in ops.get(f"/api/v1/tasks?entity=trip&entity_id={t['id']}"))
    _ping(drv, t["id"], 9.95, 76.30, now - timedelta(minutes=40))  # Kochi side: far off corridor
    _ping(drv, t["id"], 9.95, 76.30, now - timedelta(minutes=35))
    tasks = ops.get(f"/api/v1/tasks?entity=trip&entity_id={t['id']}")
    assert any("Route deviation" in x["title"] for x in tasks)
    # Stationary ~70 minutes without a rest/waiting event -> long stoppage alert (welfare/cargo check, not a penalty)
    for m in (30, 15, 0):
        _ping(drv, t["id"], 9.9501, 76.3001, now - timedelta(minutes=m) + timedelta(seconds=1))
    assert ops.get(f"/api/v1/trips/{t['id']}/track")["evaluation"]["stopped_minutes"] >= 35
    owner.put("/api/v1/settings/gps.long_stop_minutes", {"value": 30, "reason": "test"})
    _ping(drv, t["id"], 9.9502, 76.3002, now)
    assert any("Long stoppage" in x["title"] for x in ops.get(f"/api/v1/tasks?entity=trip&entity_id={t['id']}"))
    owner.put("/api/v1/settings/gps.long_stop_minutes", {"value": 60, "reason": "restore"})


def test_transshipment_via_verified_facility(client, owner, ops, accounts, lookup):
    sales = login(client, "sales.marketing@demo.local")
    c = new_customer(owner, accounts)
    b = quoted_booking(sales, ops, c["id"], lookup, service="PTL", weight=1500, packages=3, dest="Chennai")
    v1, d1 = new_vehicle(owner), new_driver(owner)
    t1 = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v1["id"], "driver_id": d1["id"]})
    drv1 = load_and_dispatch(client, ops, t1, d1, v1)
    unverified = next(f for f in owner.get("/api/v1/masters/facilities") if f["code"] == "BASEMENT")
    r = ops.post(f"/api/v1/bookings/{b['id']}/transship", {"trip_id": t1["id"], "facility_id": unverified["id"], "package_count": 3}, expect=422)
    assert r["error"]["code"] == "facility_unverified"
    hub = owner.post("/api/v1/masters/facilities", {"code": uniq("HUB"), "name": "TEST Partner cross-dock Salem", "kind": "cross_dock",
                                                     "verified": True, "verification_notes": "Partner warehouse inspected (test)"})
    res = ops.post(f"/api/v1/bookings/{b['id']}/transship", {"trip_id": t1["id"], "facility_id": hub["id"], "package_count": 3, "location": "Bay 2"})
    assert res["booking_status"] == "confirmed" and res["trip_status"] == "delivered"
    ops.post(f"/api/v1/trips/{t1['id']}/close", {"end_odometer": 1300})  # leg 1 closes without POD (handover recorded)
    chain = ops.get(f"/api/v1/bookings/{b['id']}/custody")
    assert any(e["event"] == "godown_in" and e["package_count"] == 3 for e in chain)
    v2, d2 = new_vehicle(owner), new_driver(owner)
    t2 = ops.post("/api/v1/trips", {"booking_ids": [b["id"]], "vehicle_id": v2["id"], "driver_id": d2["id"]})
    drv2 = load_and_dispatch(client, ops, t2, d2, v2)
    deliver_all(ops, drv2, t2)
    ops.post(f"/api/v1/trips/{t2['id']}/close", {"end_odometer": 1500})
    bk = ops.get(f"/api/v1/bookings/{b['id']}")
    assert bk["status"] == "pod_verified" and bk["lr_number"]  # single LR, final POD on last leg


def test_fleet_kpis(client, owner, ops, accounts, lookup):
    k = owner.get(f"/api/v1/fleet/kpis?frm={date.today() - timedelta(days=30)}&to={date.today()}")
    assert k["vehicles"] and {"km", "fuel_cost_per_km", "maintenance_cost_per_km", "revenue_per_km", "utilisation_pct", "downtime_days"} <= set(k["vehicles"][0])
    assert any(int(float(x["km"])) > 0 for x in k["vehicles"])


def test_outage_paper_forms(client, owner, ops):
    r = client.post("/api/v1/outage-forms", json={"kind": "pod", "count": 2}, headers=ops.h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    import re
    nums = sorted(set(re.findall(rb"PF-POD-\d{5}", r.content)))
    num = nums[0].decode()
    ev = lambda n, cid: {"client_event_id": cid, "device_id": "office-pc", "event_type": "paper_form", "source": "paper_form",
                         "occurred_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
                         "payload": {"kind": "pod", "form_number": n, "booking": "BKG/x", "receiver": "R"}}
    res = ops.post("/api/v1/sync/events", {"events": [ev(num, uniq("pf-"))]})["results"][0]
    assert res["status"] == "needs_review"
    again = ops.post("/api/v1/sync/events", {"events": [ev(num, uniq("pf-"))]})["results"][0]
    assert again["status"] == "rejected" and "already" in again["result"]["error"]
    fake = ops.post("/api/v1/sync/events", {"events": [ev("PF-POD-99999", uniq("pf-"))]})["results"][0]
    assert fake["status"] == "rejected" and "never issued" in fake["result"]["error"]
    ops.post(f"/api/v1/outage-forms/review/{res['client_event_id']}", {"approve": True, "note": "Matches signed copy"}, expect=403)
    owner.post(f"/api/v1/outage-forms/review/{res['client_event_id']}", {"approve": True, "note": "Matches signed copy"})


def test_totp_two_factor(client, owner):
    email = f"{uniq('mfa')}@test.local".lower()
    owner.post("/api/v1/users", {"name": "MFA user", "email": email, "password": "Passw0rd!x1", "roles": ["accounts"]})
    u = login(client, email, "Passw0rd!x1")
    secret = u.post("/api/v1/auth/mfa/setup")["secret"]
    u.post("/api/v1/auth/mfa/enable", {"code": "000000"}, expect=400)
    u.post("/api/v1/auth/mfa/enable", {"code": totp(secret)})
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": "Passw0rd!x1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "mfa_required"
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": "Passw0rd!x1", "totp": "123456" if totp(secret) != "123456" else "654321"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login", json={"identifier": email, "password": "Passw0rd!x1", "totp": totp(secret)})
    assert r.status_code == 200 and r.json()["user"]["mfa_enabled"] is True
    uid = next(x["id"] for x in owner.get("/api/v1/users") if x["email"] == email)
    owner.post(f"/api/v1/users/{uid}/mfa-reset", {"reason": "Lost phone, identity verified in person"})
    assert client.post("/api/v1/auth/login", json={"identifier": email, "password": "Passw0rd!x1"}).status_code == 200
    rows = owner.get("/api/v1/audit?entity=user")
    assert secret not in str(rows)
