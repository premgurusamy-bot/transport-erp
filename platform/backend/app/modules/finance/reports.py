"""Financial statements, registers, ageing, profitability and cash-flow forecast.

Every figure states whether it is ACTUAL (posted), ESTIMATED, FORECAST or UNRECONCILED."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.db import money, utcnow
from app.core.services import get_config
from app.modules.commercial.models import Booking
from app.modules.finance.models import (
    Account, Expense, Invoice, InvoiceLine, Payment, Settlement, Voucher, VoucherLine,
)
from app.modules.fleet.models import DriverEarning, Vehicle
from app.modules.masters.models import Customer, Location
from app.modules.operations.models import Trip, TripLoad


def _bal_query(db: Session, upto: date | None = None, frm: date | None = None):
    q = (select(Account.code, Account.name, Account.nature, Account.group,
                func.coalesce(func.sum(VoucherLine.debit), 0), func.coalesce(func.sum(VoucherLine.credit), 0))
         .join(VoucherLine, VoucherLine.account_id == Account.id).join(Voucher, Voucher.id == VoucherLine.voucher_id))
    if upto:
        q = q.where(Voucher.vdate <= upto)
    if frm:
        q = q.where(Voucher.vdate >= frm)
    return db.execute(q.group_by(Account.code, Account.name, Account.nature, Account.group).order_by(Account.code)).all()


def trial_balance(db: Session, upto: date | None = None) -> dict:
    rows = []
    td = tc = Decimal("0")
    for code, name, nature, group, dr, cr in _bal_query(db, upto):
        net = Decimal(dr) - Decimal(cr)
        rows.append({"code": code, "name": name, "nature": nature, "group": group,
                     "debit": str(net if net > 0 else 0), "credit": str(-net if net < 0 else 0)})
        td += max(net, 0)
        tc += max(-net, 0)
    return {"as_of": str(upto or date.today()), "rows": rows, "total_debit": str(td), "total_credit": str(tc),
            "balanced": td == tc, "basis": "ACTUAL - posted vouchers"}


def profit_and_loss(db: Session, frm: date, to: date) -> dict:
    inc, exp = [], []
    ti = te = Decimal("0")
    for code, name, nature, group, dr, cr in _bal_query(db, to, frm):
        if nature == "income":
            v = Decimal(cr) - Decimal(dr)
            inc.append({"code": code, "name": name, "group": group, "amount": str(v)})
            ti += v
        elif nature == "expense":
            v = Decimal(dr) - Decimal(cr)
            exp.append({"code": code, "name": name, "group": group, "amount": str(v)})
            te += v
    direct_exp = sum((Decimal(e["amount"]) for e in exp if e["group"] == "Direct Expenses"), Decimal("0"))
    direct_inc = sum((Decimal(i["amount"]) for i in inc if i["group"] == "Direct Income"), Decimal("0"))
    return {"from": str(frm), "to": str(to), "income": inc, "expenses": exp, "total_income": str(ti), "total_expenses": str(te),
            "gross_contribution": str(direct_inc - direct_exp), "net_profit": str(ti - te), "basis": "ACTUAL - posted vouchers"}


def balance_sheet(db: Session, as_of: date) -> dict:
    sections = defaultdict(list)
    totals = defaultdict(Decimal)
    profit = Decimal("0")
    for code, name, nature, group, dr, cr in _bal_query(db, as_of):
        net = Decimal(dr) - Decimal(cr)
        if nature == "asset":
            sections["assets"].append({"code": code, "name": name, "amount": str(net)})
            totals["assets"] += net
        elif nature in ("liability", "equity"):
            sections[nature].append({"code": code, "name": name, "amount": str(-net)})
            totals[nature] += -net
        elif nature == "income":
            profit += -net
        else:
            profit -= net
    totals["equity"] += profit
    sections["equity"].append({"code": "P&L", "name": "Profit & Loss (current)", "amount": str(profit)})
    return {"as_of": str(as_of), "sections": sections, "total_assets": str(totals["assets"]),
            "total_liabilities_equity": str(totals["liability"] + totals["equity"]),
            "balanced": totals["assets"] == totals["liability"] + totals["equity"], "basis": "ACTUAL - posted vouchers"}


def ledger(db: Session, code: str, frm: date | None = None, to: date | None = None, party_id=None, cost_centre=None) -> dict:
    acc = db.execute(select(Account).where(Account.code == code)).scalar_one()
    q = (select(Voucher.vdate, Voucher.number, Voucher.narration, VoucherLine.debit, VoucherLine.credit, VoucherLine.party_type,
                VoucherLine.party_id, VoucherLine.cost_centre, Voucher.status)
         .join(Voucher, Voucher.id == VoucherLine.voucher_id).where(VoucherLine.account_id == acc.id))
    if frm:
        q = q.where(Voucher.vdate >= frm)
    if to:
        q = q.where(Voucher.vdate <= to)
    if party_id:
        q = q.where(VoucherLine.party_id == party_id)
    if cost_centre:
        q = q.where(VoucherLine.cost_centre == cost_centre)
    bal = Decimal("0")
    rows = []
    for d, num, narr, dr, cr, pt, pid, cc, st in db.execute(q.order_by(Voucher.vdate, Voucher.number)).all():
        bal += Decimal(dr) - Decimal(cr)
        rows.append({"date": str(d), "voucher": num, "narration": narr, "debit": str(dr), "credit": str(cr), "balance": str(bal),
                     "party_type": pt, "party_id": str(pid) if pid else None, "cost_centre": cc, "status": st})
    return {"account": {"code": acc.code, "name": acc.name}, "rows": rows, "closing": str(bal)}


def day_book(db: Session, day: date) -> list[dict]:
    out = []
    for v in db.execute(select(Voucher).where(Voucher.vdate == day).order_by(Voucher.number)).scalars():
        out.append({"number": v.number, "type": v.vtype, "narration": v.narration, "total": str(v.total), "status": v.status})
    return out


def ageing(db: Session, side: str = "receivable") -> dict:
    today = date.today()
    buckets = ["not_due", "0-30", "31-60", "61-90", "90+"]
    rows = []
    if side == "receivable":
        per = defaultdict(lambda: defaultdict(Decimal))
        for inv in db.execute(select(Invoice).where(Invoice.status.in_(("issued", "part_paid", "disputed")))).scalars():
            bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
            if bal <= 0:
                continue
            days = (today - inv.due_date).days
            b = "not_due" if days < 0 else "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
            per[inv.customer_id][b] += bal
            per[inv.customer_id]["total"] += bal
        for cid, v in per.items():
            c = db.get(Customer, cid)
            rows.append({"party": c.name, "party_id": str(cid), **{k: str(v[k]) for k in buckets}, "total": str(v["total"])})
    else:
        for s in db.execute(select(Settlement).where(Settlement.status.in_(("approved", "part_paid")))).scalars():
            bal = Decimal(s.net_payable) - Decimal(s.paid)
            days = (today - s.created_at.date()).days
            b = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
            rows.append({"party": f"{s.party_type}:{s.code}", "party_id": str(s.party_id), **{k: "0" for k in buckets}, b: str(bal), "total": str(bal)})
    return {"side": side, "buckets": buckets, "rows": sorted(rows, key=lambda r: -Decimal(r["total"]))}


def gst_register(db: Session, frm: date, to: date) -> dict:
    rows = []
    for inv in db.execute(select(Invoice).where(Invoice.invoice_date.between(frm, to), Invoice.status != "cancelled")
                          .order_by(Invoice.invoice_date)).scalars():
        c = db.get(Customer, inv.customer_id)
        rows.append({"invoice": inv.number, "date": str(inv.invoice_date), "customer": c.name, "gstin": c.gstin,
                     "place_of_supply": inv.place_of_supply, "mode": inv.gst_mode, "taxable": str(inv.taxable_value),
                     "cgst": str(inv.cgst), "sgst": str(inv.sgst), "igst": str(inv.igst), "irn_status": inv.irn_status})
    return {"rows": rows, "note": "Prepared data for review - filing requires authorised human submission (GSTR-1/3B).",
            "totals": {k: str(sum((Decimal(r[k]) for r in rows), Decimal("0"))) for k in ("taxable", "cgst", "sgst", "igst")}}


def tds_register(db: Session, frm: date, to: date) -> dict:
    rows = []
    for s in db.execute(select(Settlement).where(Settlement.tds > 0, Settlement.status.in_(("approved", "part_paid", "paid")))).scalars():
        if frm <= s.created_at.date() <= to:
            rows.append({"settlement": s.code, "party_type": s.party_type, "party_id": str(s.party_id), "gross": str(s.gross),
                         "tds": str(s.tds), "section": "194C"})
    return {"rows": rows, "note": "TDS deducted (payable). Deposit/returns require CA review and authorised filing."}


# ------------------------------------------------------------------ profitability
def trip_profitability(db: Session, trip: Trip) -> dict:
    loads = list(db.execute(select(TripLoad).where(TripLoad.trip_id == trip.id, TripLoad.status != "removed")).scalars())
    revenue = Decimal("0")
    revenue_basis = "ACTUAL (invoiced)"
    per_booking = []
    for tl in loads:
        b = db.get(Booking, tl.booking_id)
        inv_amt = db.execute(select(func.coalesce(func.sum(InvoiceLine.amount), 0)).where(
            InvoiceLine.booking_id == b.id, InvoiceLine.active.is_(True), InvoiceLine.is_pass_through.is_(False))).scalar()
        if Decimal(inv_amt) == 0:
            inv_amt = Decimal(b.freight_amount)
            revenue_basis = "ESTIMATED (includes unbilled booking value)"
        revenue += Decimal(inv_amt)
        per_booking.append({"booking": b.code, "revenue": str(inv_amt), "share": (tl.allocation_basis or {}).get("normalised_share", 1.0)})
    costs = defaultdict(Decimal)
    for e in db.execute(select(Expense).where(Expense.trip_id == trip.id, Expense.status.in_(("approved", "posted")),
                                              Expense.rebillable.is_(False))).scalars():
        costs[e.category] += Decimal(e.amount)
    if trip.fleet_type == "attached":
        costs["owner_hire"] += Decimal(trip.owner_hire_amount)
    de = db.execute(select(func.coalesce(func.sum(DriverEarning.gross), 0)).where(DriverEarning.trip_id == trip.id)).scalar()
    costs["driver_remuneration"] += Decimal(de)
    direct = sum(costs.values(), Decimal("0"))
    contribution = revenue - direct
    fixed = Decimal("0")
    if trip.fleet_type == "own":  # never allocate own-fleet fixed costs to attached vehicles
        days = max(1, ((trip.actual_end or utcnow()) - (trip.actual_start or trip.planned_start)).days + 1) if trip.actual_start else 1
        fixed = money(Decimal(days) * Decimal(str(get_config(db, "pricing.cost_rates")["own_fixed_per_day"])))
    for pb in per_booking:  # PTL actual allocation of direct cost by the versioned formula
        pb["allocated_direct_cost"] = str(money(direct * Decimal(str(pb["share"]))))
    for tl in loads:
        share = Decimal(str((tl.allocation_basis or {}).get("normalised_share", 1.0)))
        tl.allocated_cost_actual = money(direct * share)
    km = Decimal(str((trip.end_odometer or 0) - (trip.start_odometer or 0))) if trip.end_odometer and trip.start_odometer else Decimal(trip.planned_km or 0)
    return {"trip": trip.code, "mode": trip.trip_mode, "fleet": trip.fleet_type, "revenue": str(money(revenue)), "revenue_basis": revenue_basis,
            "direct_costs": {k: str(money(v)) for k, v in costs.items()}, "total_direct": str(money(direct)),
            "gross_contribution": str(money(contribution)),
            "allocated_fixed": str(fixed), "allocated_fixed_basis": "ESTIMATED (configured own fixed cost per day)" if fixed else "n/a (attached)",
            "fully_allocated_profit": str(money(contribution - fixed)), "km": str(km),
            "revenue_per_km": str(money(revenue / km)) if km else None, "cost_per_km": str(money(direct / km)) if km else None,
            "bookings": per_booking}


def profitability_summary(db: Session, frm: date, to: date) -> dict:
    groups = defaultdict(lambda: defaultdict(Decimal))
    lanes = defaultdict(lambda: defaultdict(Decimal))
    customers = defaultdict(lambda: defaultdict(Decimal))
    vehicles = defaultdict(lambda: defaultdict(Decimal))
    for t in db.execute(select(Trip).where(Trip.status.in_(("delivered", "closed")), Trip.actual_start.isnot(None))).scalars():
        if not (frm <= t.actual_start.date() <= to):
            continue
        p = trip_profitability(db, t)
        key = f"{t.trip_mode}/{t.fleet_type}"
        for g, k in ((groups, key),):
            g[k]["revenue"] += Decimal(p["revenue"])
            g[k]["direct"] += Decimal(p["total_direct"])
            g[k]["contribution"] += Decimal(p["gross_contribution"])
            g[k]["fixed"] += Decimal(p["allocated_fixed"])
            g[k]["trips"] += 1
        v = db.get(Vehicle, t.vehicle_id)
        vehicles[v.registration]["revenue"] += Decimal(p["revenue"])
        vehicles[v.registration]["contribution"] += Decimal(p["gross_contribution"])
        vehicles[v.registration]["km"] += Decimal(p["km"])
        for pb, tl in zip(p["bookings"], db.execute(select(TripLoad).where(TripLoad.trip_id == t.id, TripLoad.status != "removed")).scalars()):
            b = db.get(Booking, tl.booking_id)
            o, d = db.get(Location, b.origin_id), db.get(Location, b.destination_id)
            lane = f"{o.city} → {d.city}"
            rev = Decimal(pb["revenue"])
            cost = Decimal(pb["allocated_direct_cost"])
            lanes[lane]["revenue"] += rev
            lanes[lane]["contribution"] += rev - cost
            c = db.get(Customer, b.customer_id)
            customers[c.name]["revenue"] += rev
            customers[c.name]["contribution"] += rev - cost

    def fmt(d):
        return [{"key": k, **{m: str(money(v)) for m, v in vals.items()}} for k, vals in d.items()]
    return {"from": str(frm), "to": str(to), "by_service": fmt(groups), "by_vehicle": fmt(vehicles), "by_lane": fmt(lanes),
            "by_customer": fmt(customers),
            "note": "Gross contribution = revenue − direct trip costs. Fully allocated adds estimated own-fleet fixed costs only."}


def cashflow_forecast(db: Session, weeks: int = 8) -> dict:
    today = date.today()
    start = today - timedelta(days=today.weekday())
    buckets = [{"week_start": str(start + timedelta(weeks=i)), "inflow": Decimal("0"), "outflow": Decimal("0"), "items": []} for i in range(weeks)]

    def put(d: date, amt: Decimal, kind: str, label: str):
        idx = max(0, (d - start).days // 7)
        if idx < weeks:
            buckets[idx]["inflow" if kind == "in" else "outflow"] += amt
            buckets[idx]["items"].append({"kind": kind, "label": label, "amount": str(amt)})
    for inv in db.execute(select(Invoice).where(Invoice.status.in_(("issued", "part_paid")))).scalars():
        bal = Decimal(inv.total) - Decimal(inv.amount_received) - Decimal(inv.tds_received)
        overdue_hist = db.execute(select(func.count()).select_from(Invoice).where(
            Invoice.customer_id == inv.customer_id, Invoice.due_date < today, Invoice.status.in_(("issued", "part_paid")))).scalar()
        expected = max(inv.due_date, today) + timedelta(days=15 if overdue_hist > 1 else 0)
        put(expected, bal, "in", f"Collection {inv.number}" + (" (delayed - customer has overdue history)" if overdue_hist > 1 else ""))
    for s in db.execute(select(Settlement).where(Settlement.status.in_(("approved", "part_paid")))).scalars():
        put(today + timedelta(days=3), Decimal(s.net_payable) - Decimal(s.paid), "out", f"Settlement {s.code}")
    for pmt in db.execute(select(Payment).where(Payment.status.in_(("approved", "pending_approval")))).scalars():
        put(today + timedelta(days=1), Decimal(pmt.amount), "out", f"Payment {pmt.code}")
    for v in db.execute(select(Vehicle).where(Vehicle.ownership == "own")).scalars():
        f = v.finance or {}
        if f.get("emi"):
            for m in range(0, 3):
                due = date(today.year + (today.month - 1 + m) // 12, (today.month - 1 + m) % 12 + 1, min(int(f.get("due_day", 5)), 28))
                if due >= today:
                    put(due, Decimal(str(f["emi"])), "out", f"EMI {v.registration}")
    from app.modules.fleet.models import ComplianceItem
    for it in db.execute(select(ComplianceItem).where(ComplianceItem.status == "current", ComplianceItem.valid_to.isnot(None),
                                                      ComplianceItem.valid_to <= today + timedelta(weeks=weeks))).scalars():
        est = Decimal(str((it.meta or {}).get("renewal_estimate", 0)))
        if est:
            put(max(it.valid_to - timedelta(days=7), today), est, "out", f"Renewal {it.kind}")
    gst_out = db.execute(select(func.coalesce(func.sum(Invoice.cgst + Invoice.sgst + Invoice.igst), 0)).where(
        Invoice.invoice_date >= date(today.year, today.month, 1), Invoice.status != "cancelled")).scalar()
    if gst_out:
        nm = date(today.year + today.month // 12, today.month % 12 + 1, 20)
        put(nm, Decimal(gst_out), "out", "GST payable (estimate, month to date)")
    running = Decimal("0")
    for b in buckets:
        running += b["inflow"] - b["outflow"]
        b["net"], b["cumulative_net"] = str(b["inflow"] - b["outflow"]), str(running)
        b["inflow"], b["outflow"] = str(b["inflow"]), str(b["outflow"])
    return {"weeks": buckets, "label": "FORECAST", "confidence": "medium",
            "assumptions": ["Collections expected at due date; +15 days for customers with >1 overdue invoice",
                            "Approved settlements/payments paid within 1-3 days", "EMIs from vehicle finance records",
                            "GST estimate = output tax month to date (verify with CA)"]}
