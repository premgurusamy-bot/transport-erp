"""Reusable business flows used by the end-to-end tests. Each helper uses only public APIs."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from app.integrations.adapters import _CHARS
from tests.conftest import Api, loc, otp_login, uniq

TODAY = date.today()


def valid_gstin(state="33") -> str:
    letters = "".join(random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(5))
    body = f"{state}{letters}{random.randint(1000, 9999)}{random.choice('ABCDEFGHJK')}1Z"
    total = 0
    for i, ch in enumerate(body):
        v = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return body + _CHARS[(36 - total % 36) % 36]


def new_customer(owner: Api, accounts: Api, limit=500000, days=30, advance_pct=0, with_credit=True) -> dict:
    name = f"TEST {uniq('Cust')} Industries Pvt Ltd"
    c = owner.post("/api/v1/masters/customers", {"name": name, "gstin": valid_gstin(), "status": "active", "gst_mode": "RCM"})
    owner.post("/api/v1/masters/contacts", {"customer_id": c["id"], "name": "Buyer", "email": f"{c['code'].lower()}@test.local",
                                             "phone": f"9{random.randint(100000000, 999999999)}"})
    if with_credit:
        cp = accounts.post("/api/v1/credit-profiles", {"customer_id": c["id"], "limit_amount": limit, "credit_days": days,
                                                       "advance_pct": advance_pct, "reason": "Test credit"})
        approve_pending(owner, "credit_limit", cp["id"])
    return c


def approve_pending(approver: Api, kind: str, entity_id: str, approve=True, note="ok"):
    aps = [a for a in approver.get("/api/v1/approvals") if a["kind"] == kind and a["entity_id"] == str(entity_id)]
    assert aps, f"no pending approval {kind} {entity_id}"
    return approver.post(f"/api/v1/approvals/{aps[0]['id']}/decide", {"approve": approve, "note": note})


def new_vehicle(owner: Api, payload=7000, length=22, ownership="own", owner_id=None, vclass="MGV", compliance=True) -> dict:
    reg = "TN" + str(random.randint(10, 99)) + uniq("")[:2] + str(random.randint(1000, 9999))
    v = owner.post("/api/v1/vehicles", {"registration": reg, "ownership": ownership, "owner_id": owner_id, "payload_kg": payload,
                                        "length_ft": length, "width_ft": 7.5, "body_type": "open", "vehicle_class": vclass,
                                        "tank_litres": 200, "baseline_kmpl": 6, "status": "available", "gps_device_id": "TRK-" + reg,
                                        "dvr_device_id": "DVR-" + reg if ownership == "own" else None})
    if compliance:
        for kind in ("insurance", "road_tax", "fitness", "puc", "rc", "national_permit"):
            owner.post("/api/v1/compliance", {"subject_type": "vehicle", "subject_id": v["id"], "kind": kind, "number": "T-" + kind,
                                              "valid_from": str(TODAY - timedelta(days=10)), "valid_to": str(TODAY + timedelta(days=200))})
    return v


def new_driver(owner: Api, category="company", owner_id=None) -> dict:
    phone = f"8{random.randint(100000000, 999999999)}"
    d = owner.post("/api/v1/drivers", {"name": f"TEST Driver {uniq('')}", "phone": phone, "category": category, "owner_id": owner_id,
                                       "licence_number": "TN" + uniq(""), "licence_classes": ["MGV", "HGV", "TRANS"],
                                       "licence_valid_to": str(TODAY + timedelta(days=700)), "status": "available"})
    role = "attached_driver" if category in ("attached", "temporary") else "driver"
    owner.post("/api/v1/users", {"name": d["name"], "phone": phone, "roles": [role], "driver_id": d["id"]})
    d["phone"] = phone
    return d


def quoted_booking(api_sales: Api, api_ops: Api, customer_id: str, lookup, *, service="FTL", origin="Coimbatore", dest="Chennai",
                   weight=5000, packages=10, selling=None, goods="GEN", deliver_days=3, volume=None, floor=None) -> dict:
    gc = next(g["id"] for g in lookup["goods_categories"] if g["label"].startswith({"GEN": "General", "TEX": "Textiles", "FMCG": "FMCG",
                                                                                     "CHEM": "Non-hazardous", "HAZ": "Hazardous", "MACH": "Machinery"}[goods]))
    now = datetime.now(timezone.utc)
    e = api_sales.post("/api/v1/enquiries", {"source": "phone", "customer_id": customer_id, "service_type": service, "origin_id": loc(lookup, origin),
                                             "destination_id": loc(lookup, dest), "goods_category_id": gc, "goods_description": "Test goods",
                                             "weight_kg": weight, "package_count": packages, "declared_value": 40000, "volume_cft": volume,
                                             "pickup_from": (now + timedelta(hours=2)).isoformat(), "contact_phone": "9876543210"})
    q = api_sales.post("/api/v1/quotations", {"enquiry_id": e["id"], "vehicle_option": "own", "selling_price": selling})
    assert q["status"] == "approved", q
    api_sales.post(f"/api/v1/quotations/{q['id']}/send")
    api_sales.post(f"/api/v1/quotations/{q['id']}/accept", {"accepted_by": "Buyer", "channel": "email"})
    b = api_ops.post("/api/v1/bookings", {"quotation_id": q["id"], "consignor_name": "Consignor Co", "consignee_name": "Consignee Co",
                                          "consignee_phone": "9123456780", "goods_description": "Test goods", "package_count": packages,
                                          "weight_kg": weight, "volume_cft": volume, "floor_sqft": floor, "ptl_consent": service == "PTL",
                                          "goods_category_id": gc, "declared_value": 40000,
                                          "deliver_by": (now + timedelta(days=deliver_days)).isoformat(), "pickup_from": (now + timedelta(hours=2)).isoformat()})
    res = api_ops.post(f"/api/v1/bookings/{b['id']}/confirm")
    assert res["confirmed"], res
    return res["booking"] | {"quotation": q}


def load_and_dispatch(client, ops: Api, trip: dict, driver: dict, vehicle: dict, *, start_odo=1000, ptl=False) -> Api:
    drv = otp_login(client, driver["phone"])
    drv.post(f"/api/v1/trips/{trip['id']}/acknowledge", {"gps_consent": True})
    from app.modules.fleet.router import CRITICAL_ITEMS
    drv.post("/api/v1/inspections", {"vehicle_id": vehicle["id"], "trip_id": trip["id"], "kind": "pre_trip",
                                     "checklist": {k: "ok" for k in CRITICAL_ITEMS}, "odometer_km": start_odo})
    for load in trip["loads"]:
        labels = ops.get(f"/api/v1/bookings/{load['booking_id']}/labels")
        for l in labels:
            drv.post("/api/v1/scans", {"label": l["label"], "trip_id": trip["id"], "stage": "loaded", "client_event_id": uniq("scan")})
        ops.post(f"/api/v1/custody", {"booking_id": load["booking_id"], "trip_id": trip["id"], "event": "loaded",
                                      "package_count": load["packages"], "condition": "good"})
        ops.post(f"/api/v1/trips/{trip['id']}/eway", {"booking_id": load["booking_id"], "use_provider": True})
    r = ops.get(f"/api/v1/trips/{trip['id']}/readiness")
    assert r["ready"], r["blocking"]
    ops.post(f"/api/v1/trips/{trip['id']}/dispatch", {"start_odometer": start_odo})
    return drv


def deliver_all(ops: Api, drv: Api, trip: dict):
    drv.post(f"/api/v1/trips/{trip['id']}/events", {"event": "departed"})
    for load in trip["loads"]:
        otp = drv.post("/api/v1/pod/otp", {"trip_id": trip["id"], "booking_id": load["booking_id"]})["dev_otp"]
        drv.post("/api/v1/pod", {"trip_id": trip["id"], "booking_id": load["booking_id"], "delivered_count": load["packages"],
                                 "receiver_name": "Receiver", "otp": otp, "condition": "good"})
        ops.post(f"/api/v1/pod/{load['booking_id']}/verify", {"approve": True})
