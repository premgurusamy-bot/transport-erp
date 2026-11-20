"""Warehouse stock, purchase & vendor bills, maintenance & tyres, vehicle purchase/sale/transfer."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.audit import log, snapshot
from ..core.deps import AppError
from ..core.money import D, ZERO, r2
from ..core.numbering import next_number
from ..models import (
    GoodsReceipt, Item, MaintenanceJob, MaintenanceSchedule, PurchaseOrder, StockDoc, StockMovement, Tyre, TyreEvent,
    Vehicle, VehicleEvent, Vendor, VendorBill, Warehouse, WarehouseRateCard,
)
from . import accounting as acc
from .operations import _credit_ledger_for, parse_date

# ------------------------------------------------------------------ warehouse

STOCK_SERIES = {"Inward": "STOCK_INWARD", "Outward": "STOCK_OUTWARD"}


def stock_balance(db: Session, warehouse_id: int | None = None, item_id: int | None = None, batch_no: str | None = None, customer_id: int | None = None, on: date | None = None) -> list[dict]:
    q = select(StockMovement.warehouse_id, StockMovement.item_id, StockMovement.batch_no, StockMovement.customer_id,
               func.sum(StockMovement.qty_in), func.sum(StockMovement.qty_out), func.sum(func.coalesce(StockMovement.packages, 0)))
    if warehouse_id:
        q = q.where(StockMovement.warehouse_id == warehouse_id)
    if item_id:
        q = q.where(StockMovement.item_id == item_id)
    if batch_no is not None:
        q = q.where(StockMovement.batch_no == batch_no)
    if customer_id:
        q = q.where(StockMovement.customer_id == customer_id)
    if on:
        q = q.where(StockMovement.at <= on)
    q = q.group_by(StockMovement.warehouse_id, StockMovement.item_id, StockMovement.batch_no, StockMovement.customer_id)
    items = {i.id: i for i in db.execute(select(Item)).scalars()}
    whs = {w.id: w.name for w in db.execute(select(Warehouse)).scalars()}
    rows = []
    for wid, iid, batch, cid, qin, qout, pk in db.execute(q):
        bal = D(qin) - D(qout)
        it = items.get(iid)
        rows.append({"warehouse_id": wid, "warehouse": whs.get(wid), "item_id": iid, "sku": it.sku if it else None, "item": it.name if it else None, "uom": it.uom if it else None,
                     "batch_no": batch, "customer_id": cid, "qty_in": D(qin), "qty_out": D(qout), "balance": bal})
    return rows


def post_stock_doc(db: Session, user, data: dict) -> StockDoc:
    doc_type = data.get("doc_type")
    if doc_type not in ("Inward", "Outward", "Transfer", "Adjustment", "Damage", "Shortage", "Count"):
        raise AppError("Invalid stock document type")
    wh = db.get(Warehouse, int(data.get("warehouse_id") or 0))
    if not wh or not wh.is_active:
        raise AppError("Select a godown")
    lines = data.get("lines") or []
    if not lines:
        raise AppError("Add at least one item line")
    on = parse_date(data.get("doc_date")) or date.today()
    doc = StockDoc(doc_no=next_number(db, STOCK_SERIES.get(doc_type, "STOCK_OTHER"), on), doc_type=doc_type, doc_date=on, warehouse_id=wh.id,
                   to_warehouse_id=int(data["to_warehouse_id"]) if data.get("to_warehouse_id") else None,
                   customer_id=int(data["customer_id"]) if data.get("customer_id") else None, vehicle_no=data.get("vehicle_no"),
                   consignment_id=int(data["consignment_id"]) if data.get("consignment_id") else None, party_doc_no=data.get("party_doc_no"),
                   loaded_by=data.get("loaded_by"), remarks=data.get("remarks"), created_by=user.id)
    if doc_type == "Transfer" and (not doc.to_warehouse_id or doc.to_warehouse_id == wh.id):
        raise AppError("Select a different destination godown for transfers")
    db.add(doc)
    db.flush()
    units = ZERO
    for ln in lines:
        item = db.get(Item, int(ln.get("item_id") or 0))
        if not item:
            raise AppError("Unknown item in line")
        qty = D(ln.get("qty"))
        batch = (ln.get("batch_no") or "").strip()
        if item.batch_tracked and not batch:
            raise AppError(f"Batch number is required for {item.name}")
        owner = doc.customer_id or item.customer_id
        base = dict(doc_id=doc.id, at=on, item_id=item.id, customer_id=owner, batch_no=batch, packages=int(ln.get("packages") or 0), location_bin=ln.get("location_bin"), remarks=ln.get("remarks"), user_id=user.id, created_at=datetime.now(timezone.utc))
        if doc_type == "Count":
            current = sum((r["balance"] for r in stock_balance(db, wh.id, item.id, batch, owner)), ZERO)
            diff = qty - current
            if diff:
                db.add(StockMovement(warehouse_id=wh.id, qty_in=diff if diff > 0 else 0, qty_out=-diff if diff < 0 else 0, reason="Adjustment", **base))
            continue
        if qty <= 0:
            raise AppError("Quantity must be greater than zero")
        units += qty
        if doc_type in ("Inward",):
            db.add(StockMovement(warehouse_id=wh.id, qty_in=qty, qty_out=0, reason=doc_type, **base))
        elif doc_type == "Adjustment" and ln.get("direction") == "in":
            db.add(StockMovement(warehouse_id=wh.id, qty_in=qty, qty_out=0, reason="Adjustment", **base))
        else:
            available = sum((r["balance"] for r in stock_balance(db, wh.id, item.id, batch, owner)), ZERO)
            if qty > available:
                raise AppError(f"Only {available:g} {item.uom} of {item.name}{' batch ' + batch if batch else ''} available in {wh.name}")
            db.add(StockMovement(warehouse_id=wh.id, qty_in=0, qty_out=qty, reason=doc_type, **base))
            if doc_type == "Transfer":
                db.add(StockMovement(warehouse_id=doc.to_warehouse_id, qty_in=qty, qty_out=0, reason="Transfer", **base))
        db.flush()
    doc.handling_units = units
    log(db, user, "create", "stock_docs", doc.id, None, {"doc_no": doc.doc_no, "type": doc_type, "lines": lines})
    return doc


def warehouse_bill_lines(db: Session, customer_id: int, start: date, end: date) -> list[dict]:
    cards = db.query(WarehouseRateCard).filter(WarehouseRateCard.customer_id == customer_id, WarehouseRateCard.is_active.is_(True), WarehouseRateCard.effective_from <= end).all()
    cards = [c for c in cards if not c.effective_to or c.effective_to >= start]
    if not cards:
        raise AppError("No warehouse rate card for this customer in the period")
    lines = []
    days = (end - start).days + 1
    months = Decimal(days) / Decimal(calendar.monthrange(start.year, start.month)[1])
    for card in cards:
        wh_filter = card.warehouse_id
        if card.storage_basis == "fixed_monthly":
            amt = D(card.storage_rate) * months
            desc = f"Storage charges (fixed) {start:%d-%m-%Y} to {end:%d-%m-%Y}"
        elif card.storage_basis == "per_sqft_month":
            amt = D(card.storage_rate) * D(card.area_sqft) * months
            desc = f"Storage {D(card.area_sqft):g} sq.ft × ₹{card.storage_rate}/sq.ft/month, {start:%d-%m-%Y} to {end:%d-%m-%Y}"
        else:
            unit_days = ZERO
            d = start
            while d <= end:
                bal = sum((max(ZERO, r["balance"]) for r in stock_balance(db, wh_filter, customer_id=customer_id, on=d)), ZERO)
                unit_days += bal
                d += timedelta(days=1)
            amt = D(card.storage_rate) * unit_days
            desc = f"Storage {unit_days:g} {'pallet' if card.storage_basis == 'per_pallet_day' else 'unit'}-days × ₹{card.storage_rate}"
        amt = max(r2(amt), r2(D(card.min_monthly) * months))
        if amt > 0:
            lines.append({"description": desc, "amount": amt, "quantity": 1, "rate": amt, "sac": "996729"})
        q = select(StockMovement.reason, func.sum(StockMovement.qty_in), func.sum(StockMovement.qty_out)).where(StockMovement.customer_id == customer_id, StockMovement.at.between(start, end), StockMovement.reason.in_(["Inward", "Outward"]))
        if wh_filter:
            q = q.where(StockMovement.warehouse_id == wh_filter)
        for reason, qin, qout in db.execute(q.group_by(StockMovement.reason)):
            if reason == "Inward" and D(card.handling_in_rate) and D(qin):
                lines.append({"description": f"Handling – inward {D(qin):g} units × ₹{card.handling_in_rate}", "amount": r2(D(qin) * D(card.handling_in_rate)), "quantity": D(qin), "rate": card.handling_in_rate, "sac": "996719"})
            if reason == "Outward" and D(card.handling_out_rate) and D(qout):
                lines.append({"description": f"Handling – outward {D(qout):g} units × ₹{card.handling_out_rate}", "amount": r2(D(qout) * D(card.handling_out_rate)), "quantity": D(qout), "rate": card.handling_out_rate, "sac": "996719"})
    return lines


# ------------------------------------------------------------------ purchase


def _po_totals(lines: list[dict]) -> tuple[list[dict], Decimal, Decimal]:
    out, sub, tax = [], ZERO, ZERO
    for ln in lines:
        qty, rate, gr = D(ln.get("qty")), D(ln.get("rate")), D(ln.get("gst_rate"))
        if not ln.get("description") or qty <= 0:
            raise AppError("Each PO line needs a description and quantity")
        amt = r2(qty * rate)
        out.append({"description": ln["description"], "qty": str(qty), "uom": ln.get("uom") or "NOS", "rate": str(rate), "gst_rate": str(gr), "amount": str(amt), "received_qty": str(D(ln.get("received_qty")))})
        sub += amt
        tax += r2(amt * gr / 100)
    return out, sub, tax


def create_po(db: Session, user, data: dict) -> PurchaseOrder:
    vendor = db.get(Vendor, int(data.get("vendor_id") or 0))
    if not vendor:
        raise AppError("Select a vendor")
    on = parse_date(data.get("po_date")) or date.today()
    lines, sub, tax = _po_totals(data.get("lines") or [])
    if not lines:
        raise AppError("Add at least one line")
    po = PurchaseOrder(po_no=next_number(db, "PO", on), po_date=on, vendor_id=vendor.id, category=data.get("category") or vendor.category, vehicle_id=data.get("vehicle_id") or None,
                       expected_date=parse_date(data.get("expected_date")), lines=lines, subtotal=sub, gst_amount=tax, total=r2(sub + tax), terms=data.get("terms"), remarks=data.get("remarks"), created_by=user.id)
    db.add(po)
    db.flush()
    log(db, user, "create", "purchase_orders", po.id, None, snapshot(po))
    return po


def receive_po(db: Session, user, po_id: int, data: dict) -> GoodsReceipt:
    po = db.get(PurchaseOrder, po_id)
    if not po or po.status in ("Cancelled", "Closed", "Received"):
        raise AppError("Purchase order is not open")
    lines = [dict(l) for l in po.lines]
    received = []
    for r in data.get("lines") or []:
        idx, qty = int(r["po_line"]), D(r.get("qty"))
        if idx < 0 or idx >= len(lines) or qty <= 0:
            continue
        pending = D(lines[idx]["qty"]) - D(lines[idx].get("received_qty"))
        if qty > pending:
            raise AppError(f"Line {idx + 1}: only {pending} pending")
        lines[idx]["received_qty"] = str(D(lines[idx].get("received_qty")) + qty)
        received.append({"po_line": idx, "description": lines[idx]["description"], "qty": str(qty)})
    if not received:
        raise AppError("Enter received quantities")
    on = parse_date(data.get("grn_date")) or date.today()
    grn = GoodsReceipt(grn_no=next_number(db, "GRN", on), grn_date=on, po_id=po.id, vendor_id=po.vendor_id, lines=received, challan_no=data.get("challan_no"), remarks=data.get("remarks"), created_by=user.id)
    db.add(grn)
    po.lines = lines
    po.status = "Received" if all(D(l["received_qty"]) >= D(l["qty"]) for l in lines) else "Partly Received"
    db.flush()
    log(db, user, "create", "goods_receipts", grn.id, None, {"grn_no": grn.grn_no, "po": po.po_no})
    return grn


def create_vendor_bill(db: Session, user, data: dict) -> VendorBill:
    vendor = db.get(Vendor, int(data.get("vendor_id") or 0))
    if not vendor:
        raise AppError("Select a vendor")
    if not (data.get("bill_no") or "").strip():
        raise AppError("Vendor bill number is required")
    if db.execute(select(VendorBill).where(VendorBill.vendor_id == vendor.id, VendorBill.bill_no == data["bill_no"].strip(), VendorBill.status != "Cancelled")).scalars().first():
        raise AppError("This vendor bill number is already entered")
    on = parse_date(data.get("bill_date")) or date.today()
    from ..models import Company

    comp = db.query(Company).first()
    interstate = bool(vendor.state_code and comp and comp.state_code and vendor.state_code != comp.state_code)
    is_rcm = bool(data.get("is_rcm"))
    itc = bool(data.get("itc_eligible", True))
    default_ledger = acc.sys_ledger(db, acc.VENDOR_CATEGORY_LEDGER.get(data.get("category") or vendor.category, "OFFICE_EXP"))
    clean, taxable, cg, sg, ig = [], ZERO, ZERO, ZERO, ZERO
    for ln in data.get("lines") or []:
        amt = r2(ln.get("amount"))
        if amt <= 0 or not ln.get("description"):
            raise AppError("Each bill line needs a description and amount")
        gr = D(ln.get("gst_rate"))
        tax = r2(amt * gr / 100)
        if interstate:
            ig += tax
        else:
            cg += r2(tax / 2)
            sg += tax - r2(tax / 2)
        taxable += amt
        clean.append({"description": ln["description"], "expense_ledger_id": int(ln.get("expense_ledger_id") or default_ledger), "amount": str(amt), "gst_rate": str(gr), "vehicle_id": ln.get("vehicle_id") or data.get("vehicle_id")})
    if not clean:
        raise AppError("Add at least one line")
    gross = taxable + (ZERO if is_rcm else cg + sg + ig)
    from .gst import round_total

    total, ro = round_total(gross)
    tds = r2(data.get("tds_amount"))
    bill = VendorBill(entry_no=next_number(db, "VENDOR_BILL", on), vendor_id=vendor.id, bill_no=data["bill_no"].strip(), bill_date=on, category=data.get("category") or vendor.category,
                      po_id=data.get("po_id") or None, vehicle_id=data.get("vehicle_id") or None, lines=clean, taxable_value=taxable, cgst=cg, sgst=sg, igst=ig, is_rcm=is_rcm, itc_eligible=itc,
                      tds_amount=tds, round_off=ro, total=total, due_date=on + timedelta(days=vendor.credit_days or 0), source_type=data.get("source_type"), source_id=data.get("source_id"),
                      remarks=data.get("remarks"), created_by=user.id)
    db.add(bill)
    db.flush()
    vl = acc.party_ledger(db, "vendor", vendor.id, vendor.name, vendor.gstin)
    vendor.ledger_id = vl
    entries = [{"ledger_id": l["expense_ledger_id"], "debit": D(l["amount"]), "vehicle_id": l.get("vehicle_id")} for l in clean]
    if not is_rcm and itc and (cg + sg + ig) > 0:
        for key, amt in (("CGST_INPUT", cg), ("SGST_INPUT", sg), ("IGST_INPUT", ig)):
            if amt:
                entries.append({"ledger_id": acc.sys_ledger(db, key), "debit": amt})
    elif (cg + sg + ig) > 0 and not is_rcm:
        # ineligible ITC is added to cost of the first line
        entries[0]["debit"] = D(entries[0]["debit"]) + cg + sg + ig
    if is_rcm and (cg + sg + ig) > 0:
        entries.append({"ledger_id": acc.sys_ledger(db, "RCM_PAYABLE"), "credit": cg + sg + ig})
        if itc:
            for key, amt in (("CGST_INPUT", cg), ("SGST_INPUT", sg), ("IGST_INPUT", ig)):
                if amt:
                    entries.append({"ledger_id": acc.sys_ledger(db, key), "debit": amt})
        else:
            entries[0]["debit"] = D(entries[0]["debit"]) + cg + sg + ig
    if ro:
        entries.append({"ledger_id": acc.sys_ledger(db, "ROUND_OFF"), "debit": ro} if ro > 0 else {"ledger_id": acc.sys_ledger(db, "ROUND_OFF"), "credit": -ro})
    entries.append({"ledger_id": vl, "credit": total - tds})
    if tds > 0:
        entries.append({"ledger_id": acc.sys_ledger(db, "TDS_PAYABLE"), "credit": tds})
    v = acc.post(db, user, "Purchase", on, entries, f"Bill {bill.bill_no} – {vendor.name}", "vendor_bill", bill.id, bill.bill_no)
    bill.voucher_id = v.id
    log(db, user, "create", "vendor_bills", bill.id, None, snapshot(bill))
    return bill


def cancel_vendor_bill(db: Session, user, bill_id: int, reason: str) -> VendorBill:
    bill = db.get(VendorBill, bill_id)
    if not bill or bill.status == "Cancelled":
        raise AppError("Bill not found or already cancelled")
    if D(bill.amount_paid) > 0:
        raise AppError("Payments are allocated to this bill; cancel them first")
    if bill.voucher_id:
        acc.reverse(db, user, bill.voucher_id, f"Vendor bill {bill.bill_no} cancelled: {reason}")
    bill.status = "Cancelled"
    log(db, user, "cancel", "vendor_bills", bill.id, None, {"status": "Cancelled"}, reason)
    return bill


def pay_vendor(db: Session, user, data: dict):
    vendor = db.get(Vendor, int(data.get("vendor_id") or 0))
    if not vendor:
        raise AppError("Select a vendor")
    amount = r2(data.get("amount"))
    if amount <= 0:
        raise AppError("Amount must be greater than zero")
    on = parse_date(data.get("date")) or date.today()
    vl = acc.party_ledger(db, "vendor", vendor.id, vendor.name, vendor.gstin)
    vendor.ledger_id = vl
    cr = _credit_ledger_for(db, "Bank" if data.get("mode") == "Bank" else "Company Cash", None, None, data.get("bank_ledger_id"))
    v = acc.post(db, user, "Payment", on, [{"ledger_id": vl, "debit": amount}, {"ledger_id": cr, "credit": amount, "instrument_no": data.get("instrument_no")}], data.get("narration") or f"Payment to {vendor.name}", "vendor_payment", vendor.id, data.get("instrument_no"))
    allocations = data.get("allocations")
    if allocations is None:
        remaining, allocations = amount, []
        for b in db.query(VendorBill).filter(VendorBill.vendor_id == vendor.id, VendorBill.status.in_(["Unpaid", "Partly Paid"])).order_by(VendorBill.bill_date):
            if remaining <= 0:
                break
            take = min(D(b.total) - D(b.tds_amount) - D(b.amount_paid), remaining)
            if take > 0:
                allocations.append({"vendor_bill_id": b.id, "amount": take})
                remaining -= take
    acc.allocate_payment(db, v, allocations)
    return v


# ------------------------------------------------------------------ maintenance


def create_job(db: Session, user, data: dict) -> MaintenanceJob:
    v = db.get(Vehicle, int(data.get("vehicle_id") or 0))
    if not v:
        raise AppError("Select a vehicle")
    on = parse_date(data.get("date_in")) or date.today()
    job = MaintenanceJob(job_no=next_number(db, "MAINT_JOB", on), vehicle_id=v.id, category=data.get("category") or "Other", job_type=data.get("job_type") or "Breakdown",
                         vendor_id=int(data["vendor_id"]) if data.get("vendor_id") else None, workshop=data.get("workshop"), date_in=on, odometer=D(data.get("odometer")) or v.current_odometer,
                         complaint=data.get("complaint"), schedule_id=data.get("schedule_id") or None, status="Open", created_by=user.id)
    db.add(job)
    if data.get("vehicle_off_road", True) and v.status in ("Available",):
        v.status = "Maintenance"
    db.flush()
    log(db, user, "create", "maintenance_jobs", job.id, None, snapshot(job))
    return job


def complete_job(db: Session, user, job_id: int, data: dict) -> MaintenanceJob:
    job = db.get(MaintenanceJob, job_id)
    if not job or job.status != "Open":
        raise AppError("Job is not open")
    parts, parts_amt = [], ZERO
    for p in data.get("parts") or []:
        if not p.get("name"):
            continue
        qty, rate = D(p.get("qty") or 1), D(p.get("rate"))
        amt = r2(qty * rate)
        parts.append({"name": p["name"], "part_no": p.get("part_no"), "qty": str(qty), "rate": str(rate), "amount": str(amt)})
        parts_amt += amt
    labour = r2(data.get("labour_amount"))
    gst_amt = r2(data.get("gst_amount"))
    job.parts, job.parts_amount, job.labour_amount, job.gst_amount = parts, parts_amt, labour, gst_amt
    job.total_amount = r2(parts_amt + labour + gst_amt)
    job.work_done = data.get("work_done")
    job.date_out = parse_date(data.get("date_out")) or date.today()
    if job.date_out < job.date_in:
        raise AppError("Date out cannot be before date in")
    job.bill_no = data.get("bill_no")
    job.payment_mode = data.get("payment_mode") or "Vendor Credit"
    job.status = "Completed"
    v = db.get(Vehicle, job.vehicle_id)
    ledger_key = "TYRE_EXP" if job.category in ("Tyres", "Battery") else "MAINT_EXP"
    if job.total_amount > 0:
        if job.payment_mode == "Vendor Credit":
            if not job.vendor_id:
                raise AppError("Select the workshop vendor for credit bills")
            if not job.bill_no:
                raise AppError("Enter the workshop bill number")
            bill = create_vendor_bill(db, user, {"vendor_id": job.vendor_id, "bill_no": job.bill_no, "bill_date": job.date_out, "category": "Workshop / Repairs", "vehicle_id": job.vehicle_id,
                                                 "lines": [{"description": f"{job.category} – {job.job_no} {v.registration_no}", "amount": parts_amt + labour, "gst_rate": (gst_amt / (parts_amt + labour) * 100) if (parts_amt + labour) else 0, "expense_ledger_id": acc.sys_ledger(db, ledger_key), "vehicle_id": job.vehicle_id}],
                                                 "itc_eligible": bool(data.get("itc_eligible", False)), "source_type": "maintenance_job", "source_id": job.id})
            job.vendor_bill_id, job.voucher_id = bill.id, bill.voucher_id
        else:
            cr = _credit_ledger_for(db, "Bank" if job.payment_mode == "Bank" else "Company Cash", None, None, data.get("bank_ledger_id"))
            vch = acc.post(db, user, "Payment", job.date_out, [{"ledger_id": acc.sys_ledger(db, ledger_key), "debit": job.total_amount, "vehicle_id": job.vehicle_id}, {"ledger_id": cr, "credit": job.total_amount}], f"{job.category} {job.job_no} – {v.registration_no}", "maintenance_job", job.id, job.bill_no)
            job.voucher_id = vch.id
    if v.status in ("Maintenance", "Breakdown"):
        v.status = "Available"
    if job.schedule_id:
        s = db.get(MaintenanceSchedule, job.schedule_id)
        if s:
            s.last_done_date, s.last_done_km = job.date_out, job.odometer
    else:
        for s in db.query(MaintenanceSchedule).filter_by(vehicle_id=job.vehicle_id, task=job.category, is_active=True):
            s.last_done_date, s.last_done_km = job.date_out, job.odometer
    log(db, user, "complete", "maintenance_jobs", job.id, None, snapshot(job))
    return job


def maintenance_due(db: Session, on: date | None = None) -> list[dict]:
    on = on or date.today()
    out = []
    vehicles = {v.id: v for v in db.query(Vehicle)}
    for s in db.query(MaintenanceSchedule).filter_by(is_active=True):
        v = vehicles.get(s.vehicle_id)
        if not v or not v.is_active:
            continue
        due_date = (s.last_done_date + timedelta(days=s.interval_days)) if (s.interval_days and s.last_done_date) else None
        due_km = (D(s.last_done_km) + D(s.interval_km)) if (s.interval_km and s.last_done_km is not None) else None
        reasons = []
        if due_date and on >= due_date - timedelta(days=s.remind_before_days or 0):
            reasons.append(f"date {due_date:%d-%m-%Y}")
        if due_km is not None and D(v.current_odometer) >= due_km - D(s.remind_before_km or 0):
            reasons.append(f"{due_km:g} km (now {D(v.current_odometer):g})")
        if reasons:
            overdue = (due_date and on > due_date) or (due_km is not None and D(v.current_odometer) > due_km)
            out.append({"schedule_id": s.id, "vehicle_id": v.id, "vehicle": v.registration_no, "task": s.task, "due": " / ".join(reasons), "overdue": bool(overdue), "due_date": due_date, "due_km": due_km})
    return out


def tyre_action(db: Session, user, tyre_id: int, data: dict) -> Tyre:
    t = db.get(Tyre, tyre_id)
    if not t:
        raise AppError("Not found", 404)
    action = data.get("action")
    on = parse_date(data.get("date")) or date.today()
    odo = D(data.get("odometer"))
    ev = TyreEvent(tyre_id=t.id, at=on, event=action, odometer=odo or None, cost=r2(data.get("cost")), remarks=data.get("remarks"), user_id=user.id, created_at=datetime.now(timezone.utc))
    if action == "Fitted":
        if t.status == "Fitted":
            raise AppError("Remove the tyre from its current vehicle first")
        v = db.get(Vehicle, int(data.get("vehicle_id") or 0))
        if not v:
            raise AppError("Select the vehicle")
        clash = db.query(Tyre).filter(Tyre.vehicle_id == v.id, Tyre.position == data.get("position"), Tyre.status == "Fitted", Tyre.kind == t.kind).first()
        if clash and data.get("position"):
            raise AppError(f"Position {data.get('position')} on {v.registration_no} already has {clash.serial_no}")
        t.vehicle_id, t.position, t.fitted_date, t.fitted_km, t.status = v.id, data.get("position"), on, odo or v.current_odometer, "Fitted"
        ev.vehicle_id, ev.position = v.id, t.position
    elif action in ("Removed", "Scrapped", "Sold", "Retreading", "Rotated"):
        if t.status == "Fitted":
            run = max(ZERO, odo - D(t.fitted_km)) if odo else ZERO
            ev.km_run = run
            t.total_km = D(t.total_km) + run
            ev.vehicle_id, ev.position = t.vehicle_id, t.position
        if action == "Rotated":
            t.position = data.get("position")
            t.fitted_km = odo or t.fitted_km
        else:
            t.vehicle_id, t.position = None, None
            t.status = {"Removed": "In Stock", "Scrapped": "Scrapped", "Sold": "Sold", "Retreading": "Retreading"}[action]
    else:
        raise AppError("Unknown tyre action")
    db.add(ev)
    db.flush()
    return t


# ------------------------------------------------------------------ vehicle lifecycle


def vehicle_event(db: Session, user, vehicle_id: int, data: dict) -> VehicleEvent:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise AppError("Vehicle not found", 404)
    kind = data.get("event_type")
    on = parse_date(data.get("event_date")) or date.today()
    ev = VehicleEvent(vehicle_id=v.id, event_type=kind, event_date=on, amount=r2(data.get("amount")) or None, party=data.get("party"), odometer=D(data.get("odometer")) or None, remarks=data.get("remarks"), created_by=user.id)
    before = snapshot(v)
    if kind == "Transfer":
        to = int(data.get("to_branch_id") or 0)
        if not to or to == v.branch_id:
            raise AppError("Select a different branch")
        ev.from_branch_id, ev.to_branch_id = v.branch_id, to
        v.branch_id = to
    elif kind == "Sale":
        if v.status == "On Trip":
            raise AppError("Vehicle is on a trip")
        v.status, v.is_active = "Sold", False
        if ev.amount:
            mode = data.get("mode") or "Bank"
            dr = _credit_ledger_for(db, "Bank" if mode == "Bank" else "Company Cash", None, None, data.get("bank_ledger_id"))
            book = r2(data.get("book_value") if data.get("book_value") not in (None, "") else v.purchase_value or 0)
            lines = [{"ledger_id": dr, "debit": ev.amount}]
            if book:
                lines.append({"ledger_id": acc.sys_ledger(db, "VEHICLES"), "credit": book, "vehicle_id": v.id})
            diff = D(ev.amount) - book
            if diff:
                lines.append({"ledger_id": acc.sys_ledger(db, "ASSET_SALE_PL"), "credit": diff} if diff > 0 else {"ledger_id": acc.sys_ledger(db, "ASSET_SALE_PL"), "debit": -diff})
            vch = acc.post(db, user, "Receipt", on, lines, f"Sale of vehicle {v.registration_no} to {ev.party or ''}", "vehicle_sale", v.id)
            ev.voucher_id = vch.id
    elif kind == "Purchase":
        v.purchase_date = on
        v.purchase_value = ev.amount or v.purchase_value
        if ev.amount and data.get("post_accounts", True):
            mode = data.get("mode") or "Bank"
            if mode == "Vendor Credit":
                cr = _credit_ledger_for(db, "Vendor Credit", None, data.get("vendor_id"), None)
            elif mode == "Loan":
                cr = acc.sys_ledger(db, "VEHICLE_LOANS")
            else:
                cr = _credit_ledger_for(db, "Bank" if mode == "Bank" else "Company Cash", None, None, data.get("bank_ledger_id"))
            vch = acc.post(db, user, "Journal", on, [{"ledger_id": acc.sys_ledger(db, "VEHICLES"), "debit": ev.amount, "vehicle_id": v.id}, {"ledger_id": cr, "credit": ev.amount}], f"Purchase of vehicle {v.registration_no}", "vehicle_purchase", v.id)
            ev.voucher_id = vch.id
    elif kind == "Deactivation":
        if v.status == "On Trip":
            raise AppError("Vehicle is on a trip")
        v.status, v.is_active = "Inactive", False
    elif kind == "Reactivation":
        if v.status == "Sold":
            raise AppError("A sold vehicle cannot be reactivated")
        v.status, v.is_active = "Available", True
    else:
        raise AppError("Unknown event")
    db.add(ev)
    db.flush()
    log(db, user, kind.lower(), "vehicles", v.id, before, snapshot(v), data.get("remarks"))
    return ev
