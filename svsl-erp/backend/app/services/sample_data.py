"""Sample (DEMO) data for training and for the downloadable sample backup.

Builds about three months of realistic activity through the application's own services, so every LR, trip, invoice,
receipt and expense is posted to the books exactly as real work would be. Everything is clearly marked DEMO; no real
GSTIN, PAN, bank account or vehicle number is invented (vehicle numbers use the non-existent state code 00).
Only ever run this on an empty training database.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.deps import AppError, CurrentUser
from ..models import (
    Booking, Complaint, Customer, Driver, DriverAdvance, Item, MaintenanceJob, Route, Trip, Vehicle, Vendor, Warehouse,
)
from . import accounting as acc
from . import billing, business, people
from . import operations as ops

IST = timezone(timedelta(hours=5, minutes=30))
DAYS = 90


def _at(d: date, hour: int, minute: int = 0) -> str:
    return datetime.combine(d, time(hour, minute), IST).isoformat()


def build(db: Session, today: date | None = None) -> dict:
    """Create DEMO masters and ~3 months of activity. Refuses to run on a database that already has customers."""
    from ..seed import bootstrap, demo

    if db.execute(select(Customer)).first():
        raise AppError("Sample data can only be created on an empty database")
    rnd = random.Random(2026)
    today = today or date.today()
    start = today - timedelta(days=DAYS)
    user = CurrentUser(id=1, username="admin", full_name="Admin", role="Super Admin", permissions=["*"])
    bootstrap(db)
    demo(db)  # DEMO customers, 24 vehicles, 8 drivers, routes, rate contracts, one open trip
    db.flush()

    custs = db.execute(select(Customer).order_by(Customer.id)).scalars().all()
    vehicles = db.execute(select(Vehicle).order_by(Vehicle.id)).scalars().all()
    drivers = db.execute(select(Driver).order_by(Driver.id)).scalars().all()
    r_maa = db.execute(select(Route).where(Route.code == "DEMO-CBE-MAA")).scalar_one()
    r_blr = db.execute(select(Route).where(Route.code == "DEMO-CBE-BLR")).scalar_one()
    r_hsr = Route(code="DEMO-CBE-HSR", origin="Coimbatore", destination="Hosur", distance_km=320, est_hours=7, est_toll=1200, origin_state_code="33", destination_state_code="33")
    db.add(r_hsr)
    workshop = Vendor(code="DEMO-V2", name="DEMO Workshop & Spares", category="Repairs & Maintenance", state_code="33", credit_days=30)
    tyres = Vendor(code="DEMO-V3", name="DEMO Tyre Dealer", category="Tyres", state_code="33", credit_days=30)
    db.add_all([workshop, tyres])
    db.flush()

    # ---------------------------------------------------------------- trips, LRs and trip expenses
    plan = [  # customer index, route, freight, consignee, goods
        (0, r_maa, None, "DEMO Consignee – Chennai Assembly Plant", "DEMO auto components"),
        (1, r_blr, None, "DEMO Consignee – Bengaluru Vehicle Plant", "DEMO engine parts"),
        (2, r_hsr, 7500, "DEMO Consignee – Hosur Factory", "DEMO industrial goods"),
    ]
    odo = {v.id: int(v.current_odometer or 100000) for v in vehicles}
    # the DEMO trip created by seed.demo (today, LR generated) stays open: keep its vehicle out of the history
    free_on: dict[int, date] = {t.vehicle_id: today + timedelta(days=5) for t in db.execute(select(Trip)).scalars().all() if t.vehicle_id}
    trips_done = 0
    lrs_by_customer: dict[int, list] = {c.id: [] for c in custs}
    day = start
    n = 0
    while day < today - timedelta(days=2):
        for _ in range(2 if day.weekday() < 6 else 1):
            ci, route, manual, consignee, goods = plan[n % len(plan)]
            vi = n % len(vehicles)
            v, d = vehicles[vi], drivers[n % len(drivers)]
            if free_on.get(v.id, start) > day:
                n += 1
                continue
            cust = custs[ci]
            km = int(route.distance_km)
            t = ops.create_trip(db, user, {"trip_date": day, "customer_id": cust.id, "route_id": route.id, "vehicle_id": v.id, "driver_id": d.id,
                                           "planned_departure": _at(day, 7), "expected_delivery_at": _at(day + timedelta(days=1), 18)})
            qty = rnd.choice([300, 350, 400, 450])
            lr_data = {"customer_id": cust.id, "trip_id": t.id, "route_id": route.id, "lr_date": day, "consignor_name": "DEMO Consignor – Coimbatore Unit",
                       "consignee_name": consignee, "from_place": route.origin, "to_place": route.destination, "goods_value": 45000,
                       "items": [{"description": goods, "packages": qty // 10, "quantity": qty, "weight_kg": rnd.choice([5000, 6000, 7500]), "hsn": "8708"}]}
            if manual:
                lr_data.update({"freight_mode": "manual", "basic_freight": manual, "manual_reason": "DEMO spot rate"})
            lr, _ = ops.create_lr(db, user, lr_data)
            start_km = odo[v.id]
            ops.advance(db, user, t, "Dispatched", {"start_km": start_km, "at": _at(day, 8)})
            ops.add_trip_expense(db, user, t, {"category": "Toll", "amount": int(route.est_toll), "paid_by": "FASTag" if n % 3 else "Driver Cash", "expense_date": day})
            ops.add_trip_expense(db, user, t, {"category": "Driver Bata", "amount": 400, "paid_by": "Driver Cash", "expense_date": day})
            odo[v.id] = start_km + km + rnd.randint(0, 25)
            litres = round(km / rnd.choice([3.6, 3.9, 4.1, 4.3]))
            ops.add_trip_expense(db, user, t, {"category": "Diesel", "litres": litres, "rate": 92.5, "odometer": odo[v.id], "full_tank": True, "paid_by": "Company Cash", "expense_date": day})
            late = n % 9 == 4  # a few late deliveries so the on-time gauge is realistic
            delivered = _at(day + timedelta(days=1), 20 if late else 15)
            ops.advance(db, user, t, "Delivered", {"receiver_name": "DEMO Receiver", "at": delivered})
            ops.lr_pod(db, user, lr, None)
            lr.pod_received_at = datetime.fromisoformat(_at(day + timedelta(days=2), 10))
            ops.advance(db, user, t, "POD Collected", {"at": _at(day + timedelta(days=2), 11)})
            ops.advance(db, user, t, "Closed", {"end_km": odo[v.id], "fuel_closing_litres": 20, "at": _at(day + timedelta(days=2), 17)})
            v.current_odometer = odo[v.id]
            free_on[v.id] = day + timedelta(days=3)
            lrs_by_customer[cust.id].append(lr)
            trips_done += 1
            n += 1
        day += timedelta(days=1)

    # ---------------------------------------------------------------- invoices (weekly, LR-wise) and receipts
    invoices = []
    for cust in custs:
        lrs = sorted(lrs_by_customer[cust.id], key=lambda x: x.lr_date)
        batch: list = []
        for lr in lrs:
            batch.append(lr)
            if len(batch) == 4:
                inv = billing.create_invoice(db, user, {"customer_id": cust.id, "lr_ids": [x.id for x in batch], "invoice_date": batch[-1].lr_date + timedelta(days=3)})
                invoices.append(inv)
                batch = []
    db.flush()
    for i, inv in enumerate(sorted(invoices, key=lambda x: x.invoice_date)):
        age = (today - inv.invoice_date).days
        if age > 35 or (age > 20 and i % 2 == 0):  # older bills are paid; some recent ones are still outstanding
            billing.record_receipt(db, user, {"customer_id": inv.customer_id, "amount": inv.total, "mode": "Cash", "date": min(today, inv.invoice_date + timedelta(days=min(age, 30))),
                                              "narration": f"DEMO receipt against {inv.invoice_no}", "allocations": [{"invoice_id": inv.id, "amount": inv.total, "tds_amount": 0}]})

    # ---------------------------------------------------------------- trips still on the road today (dashboard / trip board)
    open_specs = [("Dispatched", 0, False), ("In Transit", 1, False), ("In Transit", 2, True), ("LR Generated", 0, False), ("Booked", 0, False)]
    for k, (stage, back, delayed) in enumerate(open_specs):
        v = next(x for x in vehicles[::-1] if free_on.get(x.id, start) <= today and x.status == "Available")
        d = drivers[k % len(drivers)]
        cust, route = custs[k % 2], (r_maa, r_blr)[k % 2]
        tday = today - timedelta(days=back)
        t = ops.create_trip(db, user, {"trip_date": tday, "customer_id": cust.id, "route_id": route.id, "vehicle_id": v.id if stage != "Booked" else None, "driver_id": d.id if stage != "Booked" else None,
                                       "planned_departure": _at(tday, 7), "expected_delivery_at": _at(today - timedelta(days=1), 18) if delayed else _at(today + timedelta(days=1), 18)})
        if stage != "Booked":
            ops.create_lr(db, user, {"customer_id": cust.id, "trip_id": t.id, "route_id": route.id, "lr_date": tday, "consignor_name": "DEMO Consignor – Coimbatore Unit", "consignee_name": "DEMO Consignee",
                                     "from_place": route.origin, "to_place": route.destination, "goods_value": 45000, "items": [{"description": "DEMO components", "packages": 40, "quantity": 400, "weight_kg": 6000}]})
        if stage in ("Dispatched", "In Transit"):
            ops.advance(db, user, t, "Dispatched", {"start_km": odo[v.id], "at": _at(tday, 8)})
            ops.add_trip_expense(db, user, t, {"category": "Toll", "amount": 900, "paid_by": "FASTag", "expense_date": tday})
        if stage == "In Transit":
            ops.advance(db, user, t, "In Transit", {"at": _at(tday, 14)})
        free_on[v.id] = today + timedelta(days=5)

    # ---------------------------------------------------------------- diesel bought outside trips, maintenance, vendor bills
    for k, v in enumerate(vehicles[:6]):
        odo[v.id] += 40
        ops.record_fuel(db, user, {"vehicle_id": v.id, "entry_date": today - timedelta(days=10 + k), "litres": 60, "rate": 92.5, "odometer": odo[v.id], "full_tank": True, "payment_mode": "Cash"})
    for k, (veh, cat, labour, parts, done) in enumerate([
        (vehicles[3], "Preventive Service", 3500, [("Engine oil 15W40 (litres)", 18, 310), ("Oil filter", 1, 850)], True),
        (vehicles[7], "Brake Work", 4200, [("Brake lining set", 1, 6800)], True),
        (vehicles[11], "Electrical", 1800, [("Battery 12V 150Ah", 1, 11500)], True),
        (vehicles[15], "Breakdown Repair", 0, [], False),
    ]):
        job = business.create_job(db, user, {"vehicle_id": veh.id, "category": cat, "job_type": "Preventive" if cat == "Preventive Service" else "Breakdown", "vendor_id": workshop.id,
                                             "workshop": "DEMO Workshop & Spares", "date_in": today - timedelta(days=20 - k * 4), "complaint": f"DEMO {cat.lower()}", "vehicle_off_road": True})
        if done:
            business.complete_job(db, user, job.id, {"parts": [{"name": p, "qty": q, "rate": r} for p, q, r in parts], "labour_amount": labour, "gst_amount": 0,
                                                     "date_out": today - timedelta(days=19 - k * 4), "odometer": odo[veh.id], "work_done": "DEMO work completed", "bill_no": f"DEMO-WS-{k + 1}"})
    bill = business.create_vendor_bill(db, user, {"vendor_id": tyres.id, "bill_no": "DEMO-TYRE-001", "bill_date": today - timedelta(days=25), "category": "Tyres", "itc_eligible": True,
                                                  "lines": [{"description": "DEMO tyres 10.00 R20 (4 nos)", "amount": 76000, "gst_rate": 28}]})
    business.pay_vendor(db, user, {"vendor_id": tyres.id, "amount": 50000, "mode": "Cash", "date": today - timedelta(days=5), "narration": "DEMO part payment for tyres"})

    # ---------------------------------------------------------------- driver advances, bookings, complaint, warehouse, payroll
    for k, d in enumerate(drivers[:4]):
        adv = DriverAdvance(driver_id=d.id, advance_date=today - timedelta(days=3 + k), amount=2000 + 500 * k, mode="Cash", purpose="Trip Advance", remarks="DEMO advance")
        db.add(adv)
        db.flush()
        ops.pay_driver_advance(db, user, adv)
    for k in range(3):
        db.add(Booking(booking_no=f"DEMO-BK-{k + 1:03d}", booking_date=today - timedelta(days=k), customer_id=custs[k].id, source=["Phone", "Email", "Customer Portal"][k],
                       pickup_address="DEMO pickup – Coimbatore", drop_address="DEMO drop – Chennai", route_id=r_maa.id, required_date=today + timedelta(days=1 + k),
                       vehicle_type="Closed Body Truck", vehicles_required=1, goods_description="DEMO goods", status="Requested"))
    db.add(Complaint(complaint_no="DEMO-CMP-001", customer_id=custs[1].id, subject="DEMO: delivery reached late", description="DEMO complaint for training – consignment reached after the promised time.", status="Open"))
    wh = db.execute(select(Warehouse).where(Warehouse.code == "DEMO-WH1")).scalar_one()
    items = [Item(sku=f"DEMO-SKU-{k}", name=name, uom="BOX", customer_id=custs[0].id) for k, name in enumerate(["DEMO brake assemblies", "DEMO wiring harness", "DEMO radiator units"], 1)]
    db.add_all(items)
    db.flush()
    business.post_stock_doc(db, user, {"doc_type": "Inward", "warehouse_id": wh.id, "customer_id": custs[0].id, "doc_date": today - timedelta(days=15), "party_doc_no": "DEMO-GRN-1",
                                       "lines": [{"item_id": it.id, "qty": 120, "packages": 12} for it in items]})
    business.post_stock_doc(db, user, {"doc_type": "Outward", "warehouse_id": wh.id, "customer_id": custs[0].id, "doc_date": today - timedelta(days=6), "party_doc_no": "DEMO-DC-1",
                                       "lines": [{"item_id": it.id, "qty": 45, "packages": 5} for it in items]})
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    run = people.compute_payroll(db, user, last_month)
    people.post_payroll(db, user, run.id)
    db.flush()
    return {"trips": trips_done + len(open_specs), "invoices": len(invoices), "from": start, "to": today,
            "open_maintenance": db.query(MaintenanceJob).filter(MaintenanceJob.status == "Open").count(), "ledger_check": acc.trial_balance(db, start.replace(month=4, day=1) if start.month >= 4 else date(start.year - 1, 4, 1), today)["balanced"]}
