"""All reports return {title, subtitle, columns, rows, totals} so one renderer exports them to PDF/Excel/CSV."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.deps import AppError
from ..core.money import D, ZERO, fmt_date, r2
from ..core.numbering import financial_year, fy_bounds
from ..models import (
    Consignment, Customer, Driver, DriverIncident, FastagTransaction, FuelEntry, GstTreatment, Invoice, Item, Ledger,
    MaintenanceJob, PayrollRun, Payslip, RateContract, Route, StockDoc, StockMovement, Trip, TripExpense, Tyre, TyreEvent,
    Vehicle, Vendor, VendorBill, Voucher, Warehouse,
)
from . import accounting as acc
from . import business, operations

M, N, Dt = "money", "number", "date"


def col(key, label, typ=None, w=None):
    c = {"key": key, "label": label, "type": typ}
    if w:
        c["w"] = w
    return c


def _totals(rows, keys):
    return {k: r2(sum((D(r.get(k)) for r in rows), ZERO)) for k in keys}


def _dt_range(start: date, end: date):
    return datetime.combine(start, datetime.min.time(), timezone.utc), datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc)


def _names(db, model, attr="name"):
    return {o.id: getattr(o, attr) for o in db.query(model)}


# ------------------------------------------------------------------ operations


def trip_sheet(db: Session, start: date, end: date, vehicle_id=None, driver_id=None, customer_id=None, **_):
    q = db.query(Trip).filter(Trip.trip_date.between(start, end), Trip.stage != "Cancelled")
    if vehicle_id:
        q = q.filter(Trip.vehicle_id == int(vehicle_id))
    if driver_id:
        q = q.filter(Trip.driver_id == int(driver_id))
    if customer_id:
        q = q.filter(Trip.customer_id == int(customer_id))
    veh, drv, cust = _names(db, Vehicle, "registration_no"), _names(db, Driver), _names(db, Customer)
    rows = []
    for t in q.order_by(Trip.trip_date, Trip.id):
        p = operations.trip_pnl(db, t)
        rows.append({"trip_no": t.trip_no, "date": t.trip_date, "vehicle": veh.get(t.vehicle_id), "driver": drv.get(t.driver_id), "customer": cust.get(t.customer_id),
                     "route": f"{t.from_place} → {t.to_place}", "stage": t.stage, "lrs": ", ".join(l.lr_no for l in operations.trip_lrs(db, t.id)),
                     "start_km": t.start_km, "end_km": t.end_km, "km": p["km"], "diesel": p["diesel_litres"], "kmpl": p["kmpl"], "revenue": p["revenue"], "expenses": p["expenses"], "profit": p["profit"]})
    return {"title": "Trip sheet", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [
        col("trip_no", "Trip"), col("date", "Date", Dt), col("vehicle", "Vehicle"), col("driver", "Driver"), col("customer", "Customer"), col("route", "Route", w=3), col("stage", "Stage"), col("lrs", "LRs"),
        col("start_km", "Start km", N), col("end_km", "End km", N), col("km", "Km", N), col("diesel", "Diesel L", N), col("kmpl", "Km/L", N), col("revenue", "Revenue", M), col("expenses", "Expenses", M), col("profit", "Profit", M)],
        "rows": rows, "totals": _totals(rows, ["km", "diesel", "revenue", "expenses", "profit"])}


def lr_register(db: Session, start: date, end: date, customer_id=None, status=None, **_):
    q = db.query(Consignment).filter(Consignment.lr_date.between(start, end))
    if customer_id:
        q = q.filter(Consignment.customer_id == int(customer_id))
    if status:
        q = q.filter(Consignment.status == status)
    cust = _names(db, Customer)
    inv = {i.id: i.invoice_no for i in db.query(Invoice)}
    rows = [{"lr_no": l.lr_no, "date": l.lr_date, "customer": cust.get(l.customer_id), "consignor": l.consignor_name, "consignee": l.consignee_name, "route": f"{l.from_place} → {l.to_place}",
             "vehicle": l.vehicle_no, "pkgs": l.packages, "weight": l.weight_kg, "basis": l.freight_basis, "freight": l.total_freight if l.status != "Cancelled" else ZERO, "advance": l.advance_freight,
             "ewb": l.eway_bill_no, "status": l.status, "invoice": inv.get(l.invoice_id)} for l in q.order_by(Consignment.lr_date, Consignment.id)]
    return {"title": "LR register", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [
        col("lr_no", "LR No"), col("date", "Date", Dt), col("customer", "Customer"), col("consignor", "Consignor"), col("consignee", "Consignee"), col("route", "Route"), col("vehicle", "Vehicle"),
        col("pkgs", "Pkgs", N), col("weight", "Weight kg", N), col("basis", "Basis"), col("freight", "Freight", M), col("advance", "Advance", M), col("ewb", "E-way bill"), col("status", "Status"), col("invoice", "Invoice")],
        "rows": rows, "totals": _totals(rows, ["pkgs", "weight", "freight", "advance"])}


def pending_deliveries(db: Session, **_):
    cust = _names(db, Customer)
    now = datetime.now(timezone.utc)
    rows = []
    for l in db.query(Consignment).filter(Consignment.status.in_(["Booked", "Loaded", "In Transit"])).order_by(Consignment.lr_date):
        t = db.get(Trip, l.trip_id) if l.trip_id else None
        exp = t.expected_delivery_at if t else None
        rows.append({"lr_no": l.lr_no, "date": l.lr_date, "customer": cust.get(l.customer_id), "route": f"{l.from_place} → {l.to_place}", "vehicle": l.vehicle_no, "status": l.status,
                     "dispatched": fmt_date(t.dispatched_at) if t and t.dispatched_at else "", "expected": fmt_date(exp) if exp else "", "delayed": "YES" if exp and exp < now else "", "age_days": (date.today() - l.lr_date).days})
    return {"title": "Pending deliveries", "columns": [col("lr_no", "LR"), col("date", "LR date", Dt), col("customer", "Customer"), col("route", "Route"), col("vehicle", "Vehicle"), col("status", "Status"),
                                                       col("dispatched", "Dispatched"), col("expected", "Expected"), col("delayed", "Delayed"), col("age_days", "Age (days)", N)], "rows": rows}


def pending_pod(db: Session, **_):
    cust = _names(db, Customer)
    rows = [{"lr_no": l.lr_no, "date": l.lr_date, "customer": cust.get(l.customer_id), "route": f"{l.from_place} → {l.to_place}", "vehicle": l.vehicle_no, "delivered": fmt_date(l.delivered_at),
             "days": (datetime.now(timezone.utc) - l.delivered_at).days, "receiver": l.receiver_name}
            for l in db.query(Consignment).filter(Consignment.delivered_at.is_not(None), Consignment.pod_received_at.is_(None), Consignment.status != "Cancelled").order_by(Consignment.delivered_at)]
    return {"title": "POD pending", "columns": [col("lr_no", "LR"), col("date", "LR date", Dt), col("customer", "Customer"), col("route", "Route"), col("vehicle", "Vehicle"), col("delivered", "Delivered"), col("days", "Days pending", N), col("receiver", "Receiver")], "rows": rows}


# ------------------------------------------------------------------ profitability


def _trip_rows(db: Session, start: date, end: date, customer_id=None):
    q = db.query(Trip).filter(Trip.trip_date.between(start, end), Trip.stage != "Cancelled")
    if customer_id:
        q = q.filter(Trip.customer_id == int(customer_id))
    out = []
    for t in q:
        p = operations.trip_pnl(db, t)
        out.append((t, p))
    return out


def vehicle_profitability(db: Session, start: date, end: date, **_):
    rows = []
    for v in db.query(Vehicle).order_by(Vehicle.registration_no):
        rev = D(db.execute(select(func.coalesce(func.sum(Consignment.total_freight), 0)).where(Consignment.vehicle_id == v.id, Consignment.status != "Cancelled", Consignment.lr_date.between(start, end))).scalar())
        trip_ids = [t.id for t in db.query(Trip.id).filter(Trip.vehicle_id == v.id)]
        trip_exp = D(db.execute(select(func.coalesce(func.sum(TripExpense.amount), 0)).where(TripExpense.trip_id.in_(trip_ids or [0]), TripExpense.expense_date.between(start, end))).scalar())
        fuel_free = D(db.execute(select(func.coalesce(func.sum(FuelEntry.amount), 0)).where(FuelEntry.vehicle_id == v.id, FuelEntry.trip_id.is_(None), FuelEntry.entry_date.between(start, end))).scalar())
        maint = D(db.execute(select(func.coalesce(func.sum(MaintenanceJob.total_amount), 0)).where(MaintenanceJob.vehicle_id == v.id, MaintenanceJob.status == "Completed", MaintenanceJob.date_out.between(start, end))).scalar())
        other = D(db.execute(select(func.coalesce(func.sum(VendorBill.taxable_value), 0)).where(VendorBill.vehicle_id == v.id, VendorBill.status != "Cancelled", VendorBill.bill_date.between(start, end), func.coalesce(VendorBill.source_type, "") != "maintenance_job")).scalar())
        months = Decimal(max(1, (end.year - start.year) * 12 + end.month - start.month + 1))
        emi = D(v.emi_amount) * months if v.emi_amount and (not v.loan_end_date or v.loan_end_date >= start) else ZERO
        trips = db.query(Trip).filter(Trip.vehicle_id == v.id, Trip.trip_date.between(start, end), Trip.stage != "Cancelled").count()
        km = D(db.execute(select(func.coalesce(func.sum(Trip.end_km - Trip.start_km), 0)).where(Trip.vehicle_id == v.id, Trip.trip_date.between(start, end), Trip.end_km.is_not(None))).scalar())
        cost = trip_exp + fuel_free + maint + other
        if not (rev or cost or trips):
            continue
        rows.append({"vehicle": v.registration_no, "type": v.vehicle_type, "ownership": v.ownership, "trips": trips, "km": km, "revenue": r2(rev), "trip_expenses": r2(trip_exp), "fuel_other": r2(fuel_free), "maintenance": r2(maint),
                     "other_bills": r2(other), "profit": r2(rev - cost), "per_km": r2((rev - cost) / km) if km else None, "emi": r2(emi), "after_emi": r2(rev - cost - emi)})
    return {"title": "Vehicle-wise profitability", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [
        col("vehicle", "Vehicle"), col("type", "Type"), col("ownership", "Ownership"), col("trips", "Trips", N), col("km", "Km", N), col("revenue", "Revenue", M), col("trip_expenses", "Trip exp.", M), col("fuel_other", "Other diesel", M),
        col("maintenance", "Maintenance", M), col("other_bills", "Other bills", M), col("profit", "Operating profit", M), col("per_km", "Profit/km", M), col("emi", "EMI", M), col("after_emi", "After EMI", M)],
        "rows": rows, "totals": _totals(rows, ["trips", "km", "revenue", "trip_expenses", "fuel_other", "maintenance", "other_bills", "profit", "emi", "after_emi"]),
        "notes": ["Revenue = freight of LRs on the vehicle (by LR date). EMI is shown separately because the principal portion is not an expense."]}


def _group_profit(db: Session, start, end, keyfn, label, title, customer_id=None):
    agg: dict = defaultdict(lambda: {"trips": 0, "km": ZERO, "revenue": ZERO, "expenses": ZERO})
    for t, p in _trip_rows(db, start, end, customer_id):
        k = keyfn(t)
        a = agg[k]
        a["trips"] += 1
        a["km"] += D(p["km"])
        a["revenue"] += p["revenue"]
        a["expenses"] += p["expenses"]
    rows = [{"key": k, "trips": a["trips"], "km": a["km"], "revenue": r2(a["revenue"]), "expenses": r2(a["expenses"]), "profit": r2(a["revenue"] - a["expenses"]),
             "margin": r2((a["revenue"] - a["expenses"]) / a["revenue"] * 100) if a["revenue"] else None} for k, a in agg.items()]
    rows.sort(key=lambda r: -r["profit"])
    return {"title": title, "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("key", label, w=3), col("trips", "Trips", N), col("km", "Km", N), col("revenue", "Revenue", M), col("expenses", "Trip expenses", M), col("profit", "Profit", M), col("margin", "Margin %", N)],
            "rows": rows, "totals": _totals(rows, ["trips", "km", "revenue", "expenses", "profit"])}


def customer_profitability(db: Session, start: date, end: date, customer_id=None, **_):
    cust = _names(db, Customer)
    return _group_profit(db, start, end, lambda t: cust.get(t.customer_id) or "(no customer)", "Customer", "Customer-wise profitability", customer_id)


def route_profitability(db: Session, start: date, end: date, customer_id=None, **_):
    routes = {r.id: f"{r.code}: {r.origin} → {r.destination}" for r in db.query(Route)}
    return _group_profit(db, start, end, lambda t: routes.get(t.route_id) or f"{t.from_place} → {t.to_place}", "Route", "Route-wise profitability", customer_id)


def trip_profitability(db: Session, start: date, end: date, customer_id=None, **_):
    return trip_sheet(db, start, end, customer_id=customer_id) | {"title": "Trip-wise profit / loss"}


def contract_profitability(db: Session, start: date, end: date, **_):
    contracts = {c.id: c for c in db.query(RateContract)}
    cust = _names(db, Customer)
    agg: dict = defaultdict(lambda: {"lrs": 0, "revenue": ZERO, "expenses": ZERO})
    for l in db.query(Consignment).filter(Consignment.lr_date.between(start, end), Consignment.status != "Cancelled"):
        c = contracts.get(l.rate_contract_id)
        key = f"{c.contract_no} – {c.name} ({cust.get(c.customer_id)})" if c else "Manual / no contract"
        agg[key]["lrs"] += 1
        agg[key]["revenue"] += D(l.total_freight)
        if l.trip_id:
            t = db.get(Trip, l.trip_id)
            lrs = operations.trip_lrs(db, t.id)
            trip_rev = sum((D(x.total_freight) for x in lrs), ZERO)
            trip_exp = operations.trip_pnl(db, t)["expenses"]
            agg[key]["expenses"] += trip_exp * (D(l.total_freight) / trip_rev) if trip_rev else trip_exp / len(lrs)
    for inv in db.query(Invoice).filter(Invoice.basis == "monthly_contract", Invoice.status != "Cancelled", Invoice.invoice_date.between(start, end)):
        agg["Monthly contract invoices"]["revenue"] += D(inv.taxable_value)
    rows = [{"key": k, "lrs": a["lrs"], "revenue": r2(a["revenue"]), "expenses": r2(a["expenses"]), "profit": r2(a["revenue"] - a["expenses"])} for k, a in agg.items()]
    return {"title": "Contract-wise profitability", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("key", "Contract", w=4), col("lrs", "LRs", N), col("revenue", "Revenue", M), col("expenses", "Allocated trip expenses", M), col("profit", "Profit", M)],
            "rows": rows, "totals": _totals(rows, ["lrs", "revenue", "expenses", "profit"]), "notes": ["Trip expenses are allocated to LRs in proportion to freight."]}


def driver_performance(db: Session, start: date, end: date, **_):
    rows = []
    for d in db.query(Driver).order_by(Driver.name):
        trips = db.query(Trip).filter(Trip.driver_id == d.id, Trip.trip_date.between(start, end), Trip.stage != "Cancelled").all()
        if not trips:
            continue
        km = sum((max(ZERO, D(t.end_km) - D(t.start_km)) for t in trips if t.end_km is not None and t.start_km is not None), ZERO)
        litres = D(db.execute(select(func.coalesce(func.sum(FuelEntry.litres), 0)).where(FuelEntry.driver_id == d.id, FuelEntry.entry_date.between(start, end))).scalar())
        rev = sum((operations.trip_pnl(db, t)["revenue"] for t in trips), ZERO)
        delivered = [t for t in trips if t.delivered_at]
        on_time = [t for t in delivered if not t.expected_delivery_at or t.delivered_at <= t.expected_delivery_at + timedelta(hours=6)]
        inc = db.query(DriverIncident).filter(DriverIncident.driver_id == d.id, DriverIncident.incident_date.between(start, end))
        acc_n = inc.filter(DriverIncident.kind == "Accident").count()
        fines = inc.filter(DriverIncident.kind == "Fine / Challan").count()
        rows.append({"driver": d.name, "trips": len(trips), "km": km, "revenue": r2(rev), "kmpl": r2(km / litres) if litres else None, "on_time": r2(D(len(on_time)) / len(delivered) * 100) if delivered else None, "accidents": acc_n, "fines": fines})
    return {"title": "Driver-wise performance", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("driver", "Driver"), col("trips", "Trips", N), col("km", "Km", N), col("revenue", "Revenue", M), col("kmpl", "Km/L", N), col("on_time", "On-time %", N), col("accidents", "Accidents", N), col("fines", "Fines", N)],
            "rows": rows, "totals": _totals(rows, ["trips", "km", "revenue"])}


def fleet_utilization(db: Session, start: date, end: date, **_):
    days = (end - start).days + 1
    lo, hi = _dt_range(start, end)
    rows = []
    for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).order_by(Vehicle.registration_no):
        busy = ZERO
        for t in db.query(Trip).filter(Trip.vehicle_id == v.id, Trip.dispatched_at.is_not(None), Trip.dispatched_at < hi):
            a = max(t.dispatched_at, lo)
            b = min(t.closed_at or t.delivered_at or datetime.now(timezone.utc), hi)
            if b > a:
                busy += D((b - a).total_seconds() / 86400)
        down = ZERO
        for j in db.query(MaintenanceJob).filter(MaintenanceJob.vehicle_id == v.id, MaintenanceJob.date_in <= end, MaintenanceJob.status != "Cancelled"):
            a, b = max(j.date_in, start), min(j.date_out or date.today(), end)
            if b >= a:
                down += (b - a).days + 1
        rows.append({"vehicle": v.registration_no, "type": v.vehicle_type, "status": v.status, "days": days, "on_trip_days": r2(busy), "downtime_days": down, "idle_days": r2(max(ZERO, days - busy - down)), "utilization": r2(busy / days * 100)})
    return {"title": "Fleet utilisation & downtime", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("vehicle", "Vehicle"), col("type", "Type"), col("status", "Status"), col("days", "Days", N), col("on_trip_days", "On trip", N), col("downtime_days", "Downtime", N), col("idle_days", "Idle", N), col("utilization", "Utilisation %", N)], "rows": rows}


# ------------------------------------------------------------------ fleet costs


def fuel_mileage(db: Session, start: date, end: date, vehicle_id=None, **_):
    rows = []
    vq = db.query(Vehicle).order_by(Vehicle.registration_no)
    if vehicle_id:
        vq = vq.filter(Vehicle.id == int(vehicle_id))
    drv = _names(db, Driver)
    for v in vq:
        for m in operations.mileage(db, v.id, start, end):
            rows.append({"vehicle": v.registration_no, "date": m["date"], "driver": drv.get(m["driver_id"]), "from_km": m["from_km"], "to_km": m["to_km"], "distance": m["distance"], "litres": m["litres"], "kmpl": m["kmpl"], "expected": m["expected"], "flag": "ABNORMAL" if m["abnormal"] else ""})
    return {"title": "Fuel efficiency (full-tank to full-tank)", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("vehicle", "Vehicle"), col("date", "Fill date", Dt), col("driver", "Driver"), col("from_km", "From km", N), col("to_km", "To km", N), col("distance", "Distance", N), col("litres", "Litres", N), col("kmpl", "Km/L", N), col("expected", "Expected", N), col("flag", "Alert")],
            "rows": rows, "totals": _totals(rows, ["distance", "litres"]), "notes": ["Mileage = distance travelled ÷ diesel consumed, measured between consecutive full-tank fills."]}


def fuel_summary(db: Session, start: date, end: date, group="vehicle", **_):
    veh, drv = _names(db, Vehicle, "registration_no"), _names(db, Driver)
    agg: dict = defaultdict(lambda: {"fills": 0, "litres": ZERO, "amount": ZERO})
    for f in db.query(FuelEntry).filter(FuelEntry.entry_date.between(start, end), FuelEntry.litres > 0):
        k = drv.get(f.driver_id) or "(no driver)" if group == "driver" else veh.get(f.vehicle_id)
        agg[k]["fills"] += 1
        agg[k]["litres"] += D(f.litres)
        agg[k]["amount"] += D(f.amount)
    mil: dict = defaultdict(lambda: [ZERO, ZERO])
    for v in db.query(Vehicle):
        for m in operations.mileage(db, v.id, start, end):
            k = (drv.get(m["driver_id"]) or "(no driver)") if group == "driver" else v.registration_no
            mil[k][0] += D(m["distance"])
            mil[k][1] += D(m["litres"])
    rows = [{"key": k, "fills": a["fills"], "litres": r2(a["litres"]), "amount": r2(a["amount"]), "avg_rate": r2(a["amount"] / a["litres"]) if a["litres"] else None, "kmpl": r2(mil[k][0] / mil[k][1]) if mil[k][1] else None} for k, a in agg.items()]
    return {"title": f"Diesel summary – {group}-wise", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("key", group.title()), col("fills", "Fills", N), col("litres", "Litres", N), col("amount", "Amount", M), col("avg_rate", "Avg ₹/L", M), col("kmpl", "Km/L", N)],
            "rows": rows, "totals": _totals(rows, ["fills", "litres", "amount"])}


def maintenance_cost(db: Session, start: date, end: date, **_):
    veh = _names(db, Vehicle, "registration_no")
    vend = _names(db, Vendor)
    rows = [{"job": j.job_no, "vehicle": veh.get(j.vehicle_id), "category": j.category, "type": j.job_type, "vendor": vend.get(j.vendor_id) or j.workshop, "date_in": j.date_in, "date_out": j.date_out,
             "downtime": ((j.date_out or date.today()) - j.date_in).days + 1, "odometer": j.odometer, "parts": j.parts_amount, "labour": j.labour_amount, "gst": j.gst_amount, "total": j.total_amount, "status": j.status}
            for j in db.query(MaintenanceJob).filter(MaintenanceJob.date_in.between(start, end)).order_by(MaintenanceJob.date_in)]
    return {"title": "Maintenance & workshop register", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("job", "Job"), col("vehicle", "Vehicle"), col("category", "Category"), col("type", "Type"), col("vendor", "Workshop"), col("date_in", "In", Dt), col("date_out", "Out", Dt), col("downtime", "Days", N), col("odometer", "Km", N), col("parts", "Parts", M), col("labour", "Labour", M), col("gst", "GST", M), col("total", "Total", M), col("status", "Status")],
            "rows": rows, "totals": _totals(rows, ["downtime", "parts", "labour", "gst", "total"])}


def tyre_history(db: Session, **_):
    veh = _names(db, Vehicle, "registration_no")
    tyres = {t.id: t for t in db.query(Tyre)}
    rows = [{"serial": tyres[e.tyre_id].serial_no if e.tyre_id in tyres else "", "kind": tyres[e.tyre_id].kind if e.tyre_id in tyres else "", "brand": tyres[e.tyre_id].brand if e.tyre_id in tyres else "", "date": e.at, "event": e.event, "vehicle": veh.get(e.vehicle_id), "position": e.position, "odometer": e.odometer, "km_run": e.km_run, "cost": e.cost}
            for e in db.query(TyreEvent).order_by(TyreEvent.tyre_id, TyreEvent.at, TyreEvent.id)]
    summary = [{"serial": t.serial_no, "kind": t.kind, "brand": t.brand, "date": t.purchase_date, "event": f"Current: {t.status}", "vehicle": veh.get(t.vehicle_id), "position": t.position, "odometer": None, "km_run": t.total_km, "cost": t.cost} for t in tyres.values()]
    return {"title": "Tyre & battery history", "columns": [col("serial", "Serial"), col("kind", "Type"), col("brand", "Brand"), col("date", "Date", Dt), col("event", "Event"), col("vehicle", "Vehicle"), col("position", "Position"), col("odometer", "Odometer", N), col("km_run", "Km run", N), col("cost", "Cost", M)],
            "rows": summary + rows, "notes": ["Cost per km = purchase cost ÷ total km run (first rows show the current status of each tyre/battery)."]}


def toll_statement(db: Session, start: date, end: date, vehicle_id=None, **_):
    lo, hi = _dt_range(start, end)
    q = db.query(FastagTransaction).filter(FastagTransaction.txn_at >= lo, FastagTransaction.txn_at < hi)
    if vehicle_id:
        q = q.filter(FastagTransaction.vehicle_id == int(vehicle_id))
    trips = {t.id: t.trip_no for t in db.query(Trip)}
    rows = [{"date": f.txn_at.strftime("%d-%m-%Y %H:%M"), "vehicle": f.vehicle_no, "plaza": f.plaza_name, "amount": f.amount if f.txn_type == "Debit" else -D(f.amount), "type": f.txn_type, "trip": trips.get(f.trip_id), "match": f.match_status, "txn": f.txn_id} for f in q.order_by(FastagTransaction.txn_at)]
    return {"title": "Vehicle-wise toll statement (FASTag)", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("date", "Date/time"), col("vehicle", "Vehicle"), col("plaza", "Toll plaza", w=3), col("amount", "Amount", M), col("type", "Type"), col("trip", "Trip"), col("match", "Match"), col("txn", "Txn ID")],
            "rows": rows, "totals": _totals(rows, ["amount"])}


def toll_reconciliation(db: Session, start: date, end: date, **_):
    rows = []
    veh = _names(db, Vehicle, "registration_no")
    for t in db.query(Trip).filter(Trip.trip_date.between(start, end), Trip.stage != "Cancelled").order_by(Trip.trip_date):
        claimed = D(db.execute(select(func.coalesce(func.sum(TripExpense.amount), 0)).where(TripExpense.trip_id == t.id, TripExpense.category == "Toll")).scalar())
        fastag = D(db.execute(select(func.coalesce(func.sum(FastagTransaction.amount), 0)).where(FastagTransaction.trip_id == t.id, FastagTransaction.txn_type == "Debit")).scalar())
        est = D(db.get(Route, t.route_id).est_toll) if t.route_id and db.get(Route, t.route_id) else ZERO
        if not (claimed or fastag or est):
            continue
        diff = claimed - fastag
        rows.append({"trip": t.trip_no, "date": t.trip_date, "vehicle": veh.get(t.vehicle_id), "route": f"{t.from_place} → {t.to_place}", "estimated": est, "fastag": fastag, "booked": claimed, "difference": diff, "flag": "CHECK" if abs(diff) > 1 else ""})
    return {"title": "Toll reconciliation (trip expenses vs FASTag)", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("trip", "Trip"), col("date", "Date", Dt), col("vehicle", "Vehicle"), col("route", "Route"), col("estimated", "Route estimate", M), col("fastag", "FASTag debits", M), col("booked", "Booked as expense", M), col("difference", "Difference", M), col("flag", "Flag")],
            "rows": rows, "totals": _totals(rows, ["estimated", "fastag", "booked", "difference"])}


# ------------------------------------------------------------------ finance


def outstanding(db: Session, kind: str = "customer", on: date | None = None, **_):
    on = on or date.today()
    rows = acc.ageing(db, kind, on)
    by: dict = defaultdict(lambda: {"Not due": ZERO, "0-30": ZERO, "31-60": ZERO, "61-90": ZERO, "90+": ZERO})
    for r in rows:
        by[r["party"]][r["bucket"]] += D(r["balance"])
    out = [{"party": p, "not_due": b["Not due"], "b30": b["0-30"], "b60": b["31-60"], "b90": b["61-90"], "b90p": b["90+"], "total": sum(b.values(), ZERO)} for p, b in sorted(by.items(), key=lambda kv: kv[0] or "")]
    return {"title": f"{'Customer' if kind == 'customer' else 'Supplier'} outstanding – ageing", "subtitle": f"As on {fmt_date(on)}", "columns": [col("party", "Party", w=3), col("not_due", "Not due", M), col("b30", "0-30 days", M), col("b60", "31-60", M), col("b90", "61-90", M), col("b90p", "Over 90", M), col("total", "Total", M)],
            "rows": out, "totals": _totals(out, ["not_due", "b30", "b60", "b90", "b90p", "total"])}


def outstanding_bills(db: Session, kind: str = "customer", on: date | None = None, **_):
    on = on or date.today()
    rows = acc.ageing(db, kind, on)
    return {"title": f"{'Customer' if kind == 'customer' else 'Supplier'} bill-wise outstanding", "subtitle": f"As on {fmt_date(on)}", "columns": [col("party", "Party"), col("doc_no", "Bill"), col("doc_date", "Date", Dt), col("due_date", "Due", Dt), col("amount", "Bill amount", M), col("balance", "Balance", M), col("days_overdue", "Days overdue", N), col("bucket", "Bucket")],
            "rows": rows, "totals": _totals(rows, ["amount", "balance"])}


def sales_register(db: Session, start: date, end: date, customer_id=None, **_):
    q = db.query(Invoice).filter(Invoice.invoice_date.between(start, end), Invoice.doc_type != "proforma")
    if customer_id:
        q = q.filter(Invoice.customer_id == int(customer_id))
    sign = lambda i: -1 if i.doc_type == "credit_note" else 1  # noqa: E731
    rows = []
    for i in q.order_by(Invoice.invoice_date, Invoice.id):
        s = 0 if i.status == "Cancelled" else sign(i)
        rows.append({"no": i.invoice_no, "date": i.invoice_date, "type": i.doc_type.replace("_", " "), "customer": i.billing_name, "gstin": i.customer_gstin, "pos": i.place_of_supply, "mech": i.charge_mechanism, "rate": i.gst_rate,
                     "taxable": D(i.taxable_value) * s, "cgst": D(i.cgst) * s, "sgst": D(i.sgst) * s, "igst": D(i.igst) * s, "rcm": D(i.rcm_tax) * s, "total": D(i.total) * s, "status": i.status, "irn": "Yes" if i.irn else ""})
    return {"title": "Sales register (outward supplies)", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("no", "Invoice"), col("date", "Date", Dt), col("type", "Type"), col("customer", "Customer"), col("gstin", "GSTIN"), col("pos", "POS"), col("mech", "Charge"), col("rate", "Rate %", N),
                                                                                                                       col("taxable", "Taxable", M), col("cgst", "CGST", M), col("sgst", "SGST", M), col("igst", "IGST", M), col("rcm", "Tax under RCM", M), col("total", "Total", M), col("status", "Status"), col("irn", "IRN")],
            "rows": rows, "totals": _totals(rows, ["taxable", "cgst", "sgst", "igst", "rcm", "total"]), "notes": ["Cancelled documents are shown with zero value."]}


def gst_summary(db: Session, start: date, end: date, **_):
    agg: dict = defaultdict(lambda: {"count": 0, "taxable": ZERO, "cgst": ZERO, "sgst": ZERO, "igst": ZERO, "rcm": ZERO})
    for i in db.query(Invoice).filter(Invoice.invoice_date.between(start, end), Invoice.status != "Cancelled", Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note", "credit_note"])):
        s = -1 if i.doc_type == "credit_note" else 1
        reg = "B2B" if i.customer_gstin else "B2C"
        k = (i.sac or "", i.charge_mechanism, str(D(i.gst_rate)), reg, "Inter-state" if i.is_interstate else "Intra-state")
        a = agg[k]
        a["count"] += 1
        for f, src in (("taxable", "taxable_value"), ("cgst", "cgst"), ("sgst", "sgst"), ("igst", "igst"), ("rcm", "rcm_tax")):
            a[f] += D(getattr(i, src)) * s
    rows = [{"sac": k[0], "mech": k[1], "rate": k[2], "reg": k[3], "supply": k[4], **{f: r2(v) if f != "count" else v for f, v in a.items()}} for k, a in sorted(agg.items())]
    itc = {"cgst": ZERO, "sgst": ZERO, "igst": ZERO}
    for b in db.query(VendorBill).filter(VendorBill.bill_date.between(start, end), VendorBill.status != "Cancelled", VendorBill.itc_eligible.is_(True)):
        itc["cgst"] += D(b.cgst)
        itc["sgst"] += D(b.sgst)
        itc["igst"] += D(b.igst)
    rows.append({"sac": "INWARD", "mech": "ITC", "rate": "", "reg": "", "supply": "Eligible input tax (vendor bills)", "count": None, "taxable": None, "cgst": r2(itc["cgst"]), "sgst": r2(itc["sgst"]), "igst": r2(itc["igst"]), "rcm": None})
    return {"title": "GST summary (HSN/SAC-wise) – for GSTR-1 / GSTR-3B preparation", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("sac", "SAC"), col("mech", "Mechanism"), col("rate", "Rate %"), col("reg", "B2B/B2C"), col("supply", "Supply"), col("count", "Docs", N), col("taxable", "Taxable", M), col("cgst", "CGST", M), col("sgst", "SGST", M), col("igst", "IGST", M), col("rcm", "RCM (payable by recipient)", M)],
            "rows": rows, "notes": ["This is a working summary. File returns on the GST portal after review by your GST practitioner."]}


def purchase_register(db: Session, start: date, end: date, **_):
    vend = {v.id: v for v in db.query(Vendor)}
    rows = [{"entry": b.entry_no, "bill": b.bill_no, "date": b.bill_date, "vendor": vend[b.vendor_id].name if b.vendor_id in vend else "", "gstin": vend[b.vendor_id].gstin if b.vendor_id in vend else "", "category": b.category,
             "taxable": b.taxable_value, "cgst": b.cgst, "sgst": b.sgst, "igst": b.igst, "rcm": "Yes" if b.is_rcm else "", "itc": "Yes" if b.itc_eligible else "No", "tds": b.tds_amount, "total": b.total, "paid": b.amount_paid, "status": b.status}
            for b in db.query(VendorBill).filter(VendorBill.bill_date.between(start, end)).order_by(VendorBill.bill_date)]
    return {"title": "Purchase register", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("entry", "Entry"), col("bill", "Bill no"), col("date", "Date", Dt), col("vendor", "Vendor"), col("gstin", "GSTIN"), col("category", "Category"), col("taxable", "Taxable", M), col("cgst", "CGST", M), col("sgst", "SGST", M), col("igst", "IGST", M), col("rcm", "RCM"), col("itc", "ITC"), col("tds", "TDS", M), col("total", "Total", M), col("paid", "Paid", M), col("status", "Status")],
            "rows": rows, "totals": _totals(rows, ["taxable", "cgst", "sgst", "igst", "tds", "total", "paid"])}


def trial_balance_report(db: Session, start: date, end: date, **_):
    tb = acc.trial_balance(db, start, end)
    return {"title": "Trial balance", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("group", "Group"), col("ledger", "Ledger", w=3), col("opening", "Opening (Dr+)", M), col("debit", "Debit", M), col("credit", "Credit", M), col("closing_dr", "Closing Dr", M), col("closing_cr", "Closing Cr", M)],
            "rows": tb["rows"], "totals": _totals(tb["rows"], ["debit", "credit", "closing_dr", "closing_cr"]), "notes": ["Balanced" if tb["balanced"] else "NOT BALANCED – contact support"]}


def pnl_report(db: Session, start: date, end: date, **_):
    p = acc.profit_and_loss(db, start, end)
    rows = []
    for sec in ("Direct Incomes", "Direct Expenses"):
        rows.append({"head": sec.upper(), "amount": p["totals"][sec]})
        rows += [{"head": "   " + x["ledger"], "amount": x["amount"]} for x in p["sections"].get(sec, [])]
    rows.append({"head": "GROSS PROFIT", "amount": p["gross_profit"]})
    for sec in ("Indirect Incomes", "Indirect Expenses"):
        rows.append({"head": sec.upper(), "amount": p["totals"][sec]})
        rows += [{"head": "   " + x["ledger"], "amount": x["amount"]} for x in p["sections"].get(sec, [])]
    rows.append({"head": "NET PROFIT", "amount": p["net_profit"]})
    return {"title": "Profit & loss account", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("head", "Particulars", w=4), col("amount", "Amount", M)], "rows": rows}


def balance_sheet_report(db: Session, start: date, end: date, **_):
    b = acc.balance_sheet(db, end, start)
    rows = [{"side": "LIABILITIES & CAPITAL", "head": "", "amount": None}]
    for g, items in b["liabilities"].items():
        rows.append({"side": "", "head": g, "amount": r2(sum((x["amount"] for x in items), ZERO))})
        rows += [{"side": "", "head": "   " + x["ledger"], "amount": x["amount"]} for x in items]
    rows.append({"side": "Total", "head": "", "amount": b["total_liabilities"]})
    rows.append({"side": "ASSETS", "head": "", "amount": None})
    for g, items in b["assets"].items():
        rows.append({"side": "", "head": g, "amount": r2(sum((x["amount"] for x in items), ZERO))})
        rows += [{"side": "", "head": "   " + x["ledger"], "amount": x["amount"]} for x in items]
    rows.append({"side": "Total", "head": "", "amount": b["total_assets"]})
    return {"title": "Balance sheet", "subtitle": f"As on {fmt_date(end)}", "columns": [col("side", "Side"), col("head", "Particulars", w=4), col("amount", "Amount", M)], "rows": rows, "notes": [f"Difference: {b['difference']}"]}


def cash_flow_report(db: Session, start: date, end: date, **_):
    c = acc.cash_flow(db, start, end)
    rows = [{"head": "Opening cash & bank", "amount": c["opening_cash"]}]
    for sec in ("operating", "investing", "financing"):
        rows.append({"head": f"Cash flow from {sec} activities", "amount": c["totals"][sec]})
        rows += [{"head": "   " + x["head"], "amount": x["amount"]} for x in c["sections"][sec]]
    rows += [{"head": "Net change", "amount": c["net_change"]}, {"head": "Closing cash & bank", "amount": c["closing_cash"]}]
    return {"title": "Cash flow statement (direct method)", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("head", "Particulars", w=4), col("amount", "Amount", M)], "rows": rows}


def day_book_report(db: Session, start: date, end: date, ledger_type=None, **_):
    ids = None
    if ledger_type == "cash":
        ids = {acc.sys_ledger(db, "CASH")}
    elif ledger_type == "bank":
        ids = {l.id for l in db.query(Ledger).filter(Ledger.is_bank.is_(True))}
    rows = []
    for v in acc.day_book(db, start, end, ids):
        for i, e in enumerate(v["entries"]):
            rows.append({"date": v["date"] if i == 0 else None, "voucher_no": v["voucher_no"] if i == 0 else "", "type": v["type"] if i == 0 else "", "ledger": e["ledger"], "debit": e["debit"] or None, "credit": e["credit"] or None, "narration": v["narration"] if i == 0 else "", "status": v["status"] if i == 0 else ""})
    title = {"cash": "Cash book", "bank": "Bank book"}.get(ledger_type, "Day book")
    return {"title": title, "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("date", "Date", Dt), col("voucher_no", "Voucher"), col("type", "Type"), col("ledger", "Ledger", w=3), col("debit", "Debit", M), col("credit", "Credit", M), col("narration", "Narration", w=3), col("status", "Status")],
            "rows": rows, "totals": _totals(rows, ["debit", "credit"])}


def ledger_report(db: Session, start: date, end: date, ledger_id=None, **_):
    if not ledger_id:
        raise AppError("Select a ledger")
    s = acc.ledger_statement(db, int(ledger_id), start, end)
    rows = [{"date": start, "voucher_no": "", "type": "", "narration": "Opening balance", "debit": None, "credit": None, "balance": s["opening"]}] + s["rows"]
    return {"title": f"Ledger: {s['ledger']}", "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("date", "Date", Dt), col("voucher_no", "Voucher"), col("type", "Type"), col("narration", "Particulars", w=4), col("debit", "Debit", M), col("credit", "Credit", M), col("balance", "Balance (Dr+)", M)],
            "rows": rows, "totals": _totals(s["rows"], ["debit", "credit"]) | {"balance": s["closing"]}}


def customer_statement(db: Session, start: date, end: date, customer_id=None, **_):
    c = db.get(Customer, int(customer_id or 0))
    if not c:
        raise AppError("Select a customer")
    if not c.ledger_id:
        c.ledger_id = acc.party_ledger(db, "customer", c.id, c.name, c.gstin)
    r = ledger_report(db, start, end, c.ledger_id)
    r["title"] = f"Statement of account – {c.name}"
    return r


def monthly_comparison(db: Session, start: date, end: date, **_):
    fy = financial_year(end)
    fs, fe = fy_bounds(fy)
    rows = []
    d = fs
    while d <= fe:
        me = date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
        p = acc.profit_and_loss(db, d, me)
        inc = p["totals"]["Direct Incomes"] + p["totals"]["Indirect Incomes"]
        exp = p["totals"]["Direct Expenses"] + p["totals"]["Indirect Expenses"]
        trips = db.query(Trip).filter(Trip.trip_date.between(d, me), Trip.stage != "Cancelled").count()
        lrs = db.query(Consignment).filter(Consignment.lr_date.between(d, me), Consignment.status != "Cancelled").count()
        diesel = D(db.execute(select(func.coalesce(func.sum(FuelEntry.amount), 0)).where(FuelEntry.entry_date.between(d, me))).scalar())
        maint = D(db.execute(select(func.coalesce(func.sum(MaintenanceJob.total_amount), 0)).where(MaintenanceJob.date_out.between(d, me), MaintenanceJob.status == "Completed")).scalar())
        rows.append({"month": d.strftime("%b %Y"), "trips": trips, "lrs": lrs, "income": r2(inc), "expenses": r2(exp), "diesel": r2(diesel), "maintenance": r2(maint), "profit": r2(inc - exp)})
        d = me + timedelta(days=1)
    return {"title": f"Monthly comparison – FY {fy}", "columns": [col("month", "Month"), col("trips", "Trips", N), col("lrs", "LRs", N), col("income", "Income", M), col("expenses", "Expenses", M), col("diesel", "Diesel", M), col("maintenance", "Maintenance", M), col("profit", "Net profit", M)],
            "rows": rows, "totals": _totals(rows, ["trips", "lrs", "income", "expenses", "diesel", "maintenance", "profit"])}


def yearly_comparison(db: Session, start: date, end: date, years=3, **_):
    rows = []
    fy = financial_year(end)
    y0 = int(fy[:4])
    for y in range(y0 - int(years) + 1, y0 + 1):
        fs, fe = fy_bounds(f"{y}-{str(y + 1)[-2:]}")
        p = acc.profit_and_loss(db, fs, fe)
        inc = p["totals"]["Direct Incomes"] + p["totals"]["Indirect Incomes"]
        exp = p["totals"]["Direct Expenses"] + p["totals"]["Indirect Expenses"]
        trips = db.query(Trip).filter(Trip.trip_date.between(fs, fe), Trip.stage != "Cancelled").count()
        rows.append({"fy": f"FY {y}-{str(y + 1)[-2:]}", "trips": trips, "income": r2(inc), "expenses": r2(exp), "profit": r2(inc - exp)})
    return {"title": "Yearly comparison", "columns": [col("fy", "Year"), col("trips", "Trips", N), col("income", "Income", M), col("expenses", "Expenses", M), col("profit", "Net profit", M)], "rows": rows}


# ------------------------------------------------------------------ warehouse & HR


def stock_register(db: Session, warehouse_id=None, customer_id=None, **_):
    cust = _names(db, Customer)
    rows = [r | {"customer": cust.get(r["customer_id"])} for r in business.stock_balance(db, int(warehouse_id) if warehouse_id else None, customer_id=int(customer_id) if customer_id else None)]
    return {"title": "Stock register", "columns": [col("warehouse", "Godown"), col("sku", "SKU"), col("item", "Item", w=3), col("batch_no", "Batch"), col("customer", "Owner"), col("uom", "Unit"), col("qty_in", "In", N), col("qty_out", "Out", N), col("balance", "Balance", N)],
            "rows": rows, "totals": _totals(rows, ["qty_in", "qty_out", "balance"])}


def stock_movements(db: Session, start: date, end: date, doc_type=None, warehouse_id=None, **_):
    q = db.query(StockDoc).filter(StockDoc.doc_date.between(start, end))
    if doc_type:
        q = q.filter(StockDoc.doc_type == doc_type)
    if warehouse_id:
        q = q.filter(StockDoc.warehouse_id == int(warehouse_id))
    items = {i.id: i for i in db.query(Item)}
    wh, cust = _names(db, Warehouse), _names(db, Customer)
    rows = []
    for d in q.order_by(StockDoc.doc_date, StockDoc.id):
        for m in db.query(StockMovement).filter(StockMovement.doc_id == d.id, StockMovement.warehouse_id == d.warehouse_id):
            it = items.get(m.item_id)
            rows.append({"doc": d.doc_no, "date": d.doc_date, "type": d.doc_type, "godown": wh.get(d.warehouse_id), "customer": cust.get(d.customer_id or m.customer_id), "vehicle": d.vehicle_no, "item": it.name if it else "", "batch": m.batch_no, "in": m.qty_in or None, "out": m.qty_out or None, "pkgs": m.packages, "remarks": m.remarks or d.remarks})
    title = {"Inward": "Unloading / inward register", "Outward": "Loading / outward register", "Damage": "Damage register", "Shortage": "Shortage register"}.get(doc_type, "Stock movement register")
    return {"title": title, "subtitle": f"{fmt_date(start)} to {fmt_date(end)}", "columns": [col("doc", "Doc"), col("date", "Date", Dt), col("type", "Type"), col("godown", "Godown"), col("customer", "Customer"), col("vehicle", "Vehicle"), col("item", "Item"), col("batch", "Batch"), col("in", "In", N), col("out", "Out", N), col("pkgs", "Pkgs", N), col("remarks", "Remarks")],
            "rows": rows, "totals": _totals(rows, ["in", "out", "pkgs"])}


def payroll_register(db: Session, month=None, **_):
    run = db.query(PayrollRun).filter_by(month=month).first() if month else db.query(PayrollRun).order_by(PayrollRun.month.desc()).first()
    if not run:
        raise AppError("No payroll found")
    rows = [{"name": p.name, "type": p.person_type, "days": p.paid_days, "gross": p.gross, "pf": p.pf_employee, "esi": p.esi_employee, "pt": p.professional_tax, "tds": p.tds, "advance": p.advance_recovery, "net": p.net_pay, "pf_er": p.pf_employer, "esi_er": p.esi_employer} for p in db.query(Payslip).filter_by(run_id=run.id).order_by(Payslip.name)]
    return {"title": f"Payroll register – {run.month} ({run.status})", "columns": [col("name", "Name"), col("type", "Type"), col("days", "Paid days", N), col("gross", "Gross", M), col("pf", "EPF", M), col("esi", "ESI", M), col("pt", "PT", M), col("tds", "TDS", M), col("advance", "Advance", M), col("net", "Net pay", M), col("pf_er", "Employer EPF", M), col("esi_er", "Employer ESI", M)],
            "rows": rows, "totals": _totals(rows, ["gross", "pf", "esi", "pt", "tds", "advance", "net", "pf_er", "esi_er"])}


def expiry_report(db: Session, **_):
    from .people import current_alerts

    rows = [{"category": a["category"], "severity": a["severity"], "title": a["title"], "detail": a["body"], "due": a["due"]} for a in current_alerts(db)]
    return {"title": "Alerts & expiring documents", "columns": [col("category", "Category"), col("severity", "Severity"), col("title", "Alert", w=4), col("detail", "Detail", w=3), col("due", "Due", Dt)], "rows": rows}


REPORTS = {
    "trip_sheet": ("Operations", "Daily trip sheet / trip register", trip_sheet),
    "lr_register": ("Operations", "LR register", lr_register),
    "pending_deliveries": ("Operations", "Pending deliveries", pending_deliveries),
    "pending_pod": ("Operations", "POD pending", pending_pod),
    "fleet_utilization": ("Operations", "Fleet utilisation & downtime", fleet_utilization),
    "vehicle_profitability": ("Profitability", "Vehicle-wise profit", vehicle_profitability),
    "customer_profitability": ("Profitability", "Customer-wise profit", customer_profitability),
    "route_profitability": ("Profitability", "Route-wise profit", route_profitability),
    "trip_profitability": ("Profitability", "Trip-wise profit / loss", trip_profitability),
    "contract_profitability": ("Profitability", "Contract-wise profit", contract_profitability),
    "driver_performance": ("Profitability", "Driver-wise performance", driver_performance),
    "fuel_mileage": ("Fleet", "Fuel efficiency (km/L)", fuel_mileage),
    "fuel_vehicle": ("Fleet", "Diesel summary – vehicle-wise", lambda db, **kw: fuel_summary(db, group="vehicle", **kw)),
    "fuel_driver": ("Fleet", "Diesel summary – driver-wise", lambda db, **kw: fuel_summary(db, group="driver", **kw)),
    "maintenance_cost": ("Fleet", "Maintenance & workshop register", maintenance_cost),
    "tyre_history": ("Fleet", "Tyre & battery history", tyre_history),
    "toll_statement": ("Fleet", "Vehicle-wise toll statement", toll_statement),
    "toll_reconciliation": ("Fleet", "Toll reconciliation", toll_reconciliation),
    "customer_outstanding": ("Finance", "Customer outstanding – ageing", lambda db, **kw: outstanding(db, "customer", kw.get("end"))),
    "customer_bills": ("Finance", "Customer bill-wise outstanding", lambda db, **kw: outstanding_bills(db, "customer", kw.get("end"))),
    "supplier_outstanding": ("Finance", "Supplier outstanding – ageing", lambda db, **kw: outstanding(db, "supplier", kw.get("end"))),
    "supplier_bills": ("Finance", "Supplier bill-wise outstanding", lambda db, **kw: outstanding_bills(db, "supplier", kw.get("end"))),
    "customer_statement": ("Finance", "Customer statement", customer_statement),
    "sales_register": ("GST", "Sales register", sales_register),
    "gst_summary": ("GST", "GST / HSN-SAC summary", gst_summary),
    "purchase_register": ("GST", "Purchase register", purchase_register),
    "trial_balance": ("Accounts", "Trial balance", trial_balance_report),
    "profit_loss": ("Accounts", "Profit & loss", pnl_report),
    "balance_sheet": ("Accounts", "Balance sheet", balance_sheet_report),
    "cash_flow": ("Accounts", "Cash flow statement", cash_flow_report),
    "day_book": ("Accounts", "Day book", day_book_report),
    "cash_book": ("Accounts", "Cash book", lambda db, **kw: day_book_report(db, ledger_type="cash", **kw)),
    "bank_book": ("Accounts", "Bank book", lambda db, **kw: day_book_report(db, ledger_type="bank", **kw)),
    "ledger": ("Accounts", "General ledger", ledger_report),
    "monthly_comparison": ("Management", "Monthly comparison", monthly_comparison),
    "yearly_comparison": ("Management", "Yearly comparison", yearly_comparison),
    "stock_register": ("Warehouse", "Stock register", stock_register),
    "stock_movements": ("Warehouse", "Inward / outward register", stock_movements),
    "payroll_register": ("HR", "Payroll register", payroll_register),
    "expiry": ("Compliance", "Alerts & expiring documents", expiry_report),
}


def run(db: Session, key: str, params: dict) -> dict:
    if key not in REPORTS:
        raise AppError("Unknown report", 404)
    today = date.today()
    fy_start, _ = fy_bounds(financial_year(today))
    start = date.fromisoformat(params["start"]) if params.get("start") else fy_start
    end = date.fromisoformat(params["end"]) if params.get("end") else today
    if end < start:
        raise AppError("End date is before start date")
    kw = {k: v for k, v in params.items() if k not in ("start", "end", "format") and v not in (None, "")}
    return REPORTS[key][2](db, start=start, end=end, **kw)
