"""Double-entry accounting: chart of accounts, posting, reversal, books and financial statements."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..core.audit import log
from ..core.deps import AppError
from ..core.money import D, ZERO, r2
from ..core.numbering import next_number
from ..models import AccountGroup, BillAllocation, Invoice, Ledger, Vendor, VendorBill, Voucher, VoucherEntry

GROUPS = [
    # name, parent, nature, cash_flow
    ("Capital Account", None, "Equity", "financing"),
    ("Reserves & Surplus", None, "Equity", "financing"),
    ("Loans (Liability)", None, "Liability", "financing"),
    ("Secured Loans", "Loans (Liability)", "Liability", "financing"),
    ("Unsecured Loans", "Loans (Liability)", "Liability", "financing"),
    ("Current Liabilities", None, "Liability", "operating"),
    ("Duties & Taxes", "Current Liabilities", "Liability", "operating"),
    ("Sundry Creditors", "Current Liabilities", "Liability", "operating"),
    ("Provisions", "Current Liabilities", "Liability", "operating"),
    ("Suspense Account", None, "Liability", "operating"),
    ("Fixed Assets", None, "Asset", "investing"),
    ("Current Assets", None, "Asset", "operating"),
    ("Bank Accounts", "Current Assets", "Asset", "cash"),
    ("Cash-in-Hand", "Current Assets", "Asset", "cash"),
    ("Sundry Debtors", "Current Assets", "Asset", "operating"),
    ("Loans & Advances (Asset)", "Current Assets", "Asset", "operating"),
    ("Driver Advances", "Loans & Advances (Asset)", "Asset", "operating"),
    ("Deposits (Asset)", "Current Assets", "Asset", "operating"),
    ("Direct Incomes", None, "Income", "operating"),
    ("Indirect Incomes", None, "Income", "operating"),
    ("Direct Expenses", None, "Expense", "operating"),
    ("Indirect Expenses", None, "Expense", "operating"),
]

SYSTEM_LEDGERS = [
    # key, name, group
    ("CASH", "Cash", "Cash-in-Hand"),
    ("CAPITAL", "Capital Account", "Capital Account"),
    ("FREIGHT_INCOME", "Freight Income", "Direct Incomes"),
    ("WAREHOUSE_INCOME", "Warehouse Storage & Handling Income", "Direct Incomes"),
    ("OTHER_INCOME", "Other Income", "Indirect Incomes"),
    ("ASSET_SALE_PL", "Profit / Loss on Sale of Assets", "Indirect Incomes"),
    ("CGST_OUTPUT", "Output CGST", "Duties & Taxes"),
    ("SGST_OUTPUT", "Output SGST", "Duties & Taxes"),
    ("IGST_OUTPUT", "Output IGST", "Duties & Taxes"),
    ("CGST_INPUT", "Input CGST", "Duties & Taxes"),
    ("SGST_INPUT", "Input SGST", "Duties & Taxes"),
    ("IGST_INPUT", "Input IGST", "Duties & Taxes"),
    ("RCM_PAYABLE", "GST Payable under RCM", "Duties & Taxes"),
    ("TDS_PAYABLE", "TDS Payable", "Duties & Taxes"),
    ("TDS_RECEIVABLE", "TDS Receivable (deducted by customers)", "Loans & Advances (Asset)"),
    ("PF_PAYABLE", "EPF Payable", "Duties & Taxes"),
    ("ESI_PAYABLE", "ESI Payable", "Duties & Taxes"),
    ("PT_PAYABLE", "Professional Tax Payable", "Duties & Taxes"),
    ("SALARY_PAYABLE", "Salary Payable", "Provisions"),
    ("DRIVER_PAYABLE", "Driver Settlements Payable", "Provisions"),
    ("EMPLOYEE_ADVANCES", "Employee Salary Advances", "Loans & Advances (Asset)"),
    ("FASTAG_WALLET", "FASTag Wallet", "Loans & Advances (Asset)"),
    ("FUEL_CARD", "Fuel Card Balance", "Loans & Advances (Asset)"),
    ("VEHICLES", "Vehicles", "Fixed Assets"),
    ("VEHICLE_LOANS", "Vehicle Loans", "Secured Loans"),
    ("DIESEL_EXP", "Diesel Expenses", "Direct Expenses"),
    ("TOLL_EXP", "Toll Expenses", "Direct Expenses"),
    ("PARKING_EXP", "Parking Expenses", "Direct Expenses"),
    ("RTO_EXP", "RTO / Check Post Expenses", "Direct Expenses"),
    ("LOADING_EXP", "Loading & Unloading Expenses", "Direct Expenses"),
    ("DRIVER_BATA_EXP", "Driver Bata & Allowances", "Direct Expenses"),
    ("TRIP_OTHER_EXP", "Other Trip Expenses", "Direct Expenses"),
    ("MAINT_EXP", "Vehicle Maintenance", "Direct Expenses"),
    ("TYRE_EXP", "Tyres & Batteries", "Direct Expenses"),
    ("VEHICLE_HIRE_EXP", "Vehicle Hire Charges", "Direct Expenses"),
    ("INSURANCE_EXP", "Vehicle Insurance", "Indirect Expenses"),
    ("ROAD_TAX_EXP", "Road Tax & Permits", "Indirect Expenses"),
    ("EMI_INTEREST", "Interest on Vehicle Loans", "Indirect Expenses"),
    ("SALARY_EXP", "Salaries & Wages", "Indirect Expenses"),
    ("PF_EMPLOYER_EXP", "Employer EPF Contribution", "Indirect Expenses"),
    ("ESI_EMPLOYER_EXP", "Employer ESI Contribution", "Indirect Expenses"),
    ("OFFICE_EXP", "Office Expenses", "Indirect Expenses"),
    ("FINES_EXP", "Fines & Penalties", "Indirect Expenses"),
    ("BANK_CHARGES", "Bank Charges", "Indirect Expenses"),
    ("ROUND_OFF", "Round Off", "Indirect Expenses"),
    ("SUSPENSE", "Suspense", "Suspense Account"),
]

EXPENSE_LEDGER_FOR = {
    "Diesel": "DIESEL_EXP", "Toll": "TOLL_EXP", "Parking": "PARKING_EXP", "RTO / Check Post": "RTO_EXP",
    "Loading": "LOADING_EXP", "Unloading": "LOADING_EXP", "Driver Bata": "DRIVER_BATA_EXP", "Food": "DRIVER_BATA_EXP",
    "Police / Fine": "FINES_EXP", "Repair on Road": "MAINT_EXP", "Tyre Puncture": "MAINT_EXP",
}

VENDOR_CATEGORY_LEDGER = {
    "Diesel / Fuel": "DIESEL_EXP", "Spare Parts": "MAINT_EXP", "Tyres": "TYRE_EXP", "Batteries": "TYRE_EXP",
    "Workshop / Repairs": "MAINT_EXP", "Vehicle Dealer": "VEHICLES", "Insurance": "INSURANCE_EXP", "Office": "OFFICE_EXP",
    "Vehicle Owner (Attached)": "VEHICLE_HIRE_EXP", "Transporter": "VEHICLE_HIRE_EXP", "Other": "OFFICE_EXP",
}


def ensure_chart(db: Session) -> None:
    existing = {g.name: g for g in db.execute(select(AccountGroup)).scalars()}
    for name, parent, nature, cf in GROUPS:
        if name not in existing:
            g = AccountGroup(name=name, parent_id=existing[parent].id if parent else None, nature=nature, cash_flow=cf)
            db.add(g)
            db.flush()
            existing[name] = g
    have = {l.system_key for l in db.execute(select(Ledger).where(Ledger.system_key.is_not(None))).scalars()}
    for key, name, group in SYSTEM_LEDGERS:
        if key not in have:
            db.add(Ledger(name=name, code=key, group_id=existing[group].id, system_key=key))
    db.flush()


def group_id(db: Session, name: str) -> int:
    gid = db.execute(select(AccountGroup.id).where(AccountGroup.name == name)).scalar_one_or_none()
    if gid is None:
        ensure_chart(db)
        gid = db.execute(select(AccountGroup.id).where(AccountGroup.name == name)).scalar_one()
    return gid


def sys_ledger(db: Session, key: str) -> int:
    lid = db.execute(select(Ledger.id).where(Ledger.system_key == key)).scalar_one_or_none()
    if lid is None:
        ensure_chart(db)
        lid = db.execute(select(Ledger.id).where(Ledger.system_key == key)).scalar_one()
    return lid


def party_ledger(db: Session, party_type: str, party_id: int, name: str, gstin: str | None = None) -> int:
    lid = db.execute(select(Ledger.id).where(Ledger.party_type == party_type, Ledger.party_id == party_id)).scalar_one_or_none()
    if lid:
        return lid
    group = {"customer": "Sundry Debtors", "vendor": "Sundry Creditors", "driver": "Driver Advances", "bank": "Bank Accounts", "employee": "Loans & Advances (Asset)"}[party_type]
    base = name if party_type in ("customer", "bank") else f"{name} ({party_type.title()})"
    final, n = base, 2
    while db.execute(select(Ledger.id).where(Ledger.name == final)).scalar_one_or_none():
        final = f"{base} #{n}"
        n += 1
    led = Ledger(name=final, group_id=group_id(db, group), party_type=party_type, party_id=party_id, gstin=gstin, is_bank=party_type == "bank")
    db.add(led)
    db.flush()
    return led.id


def check_period_open(db: Session, on: date) -> None:
    from . import settings as app_settings

    lock = app_settings.get(db, "accounts").get("lock_before")
    if lock and on < date.fromisoformat(str(lock)[:10]):
        raise AppError(f"Books are locked for dates before {lock}. Ask an administrator to change the lock date.")


def post(
    db: Session,
    user,
    voucher_type: str,
    on: date,
    lines: list[dict],
    narration: str = "",
    source_type: str | None = None,
    source_id: int | None = None,
    reference: str | None = None,
    branch_id: int | None = None,
) -> Voucher:
    """lines: [{ledger_id, debit, credit, narration?, vehicle_id?, trip_id?, instrument_no?}] – must balance."""
    check_period_open(db, on)
    clean = []
    for ln in lines:
        dr, cr = r2(ln.get("debit")), r2(ln.get("credit"))
        if dr == 0 and cr == 0:
            continue
        net = dr - cr
        dr, cr = (net, ZERO) if net > 0 else (ZERO, -net)
        if dr == 0 and cr == 0:
            continue
        if not ln.get("ledger_id"):
            raise AppError("Every voucher line needs a ledger")
        clean.append({**ln, "debit": dr, "credit": cr})
    total_dr = sum((l["debit"] for l in clean), ZERO)
    total_cr = sum((l["credit"] for l in clean), ZERO)
    if len(clean) < 2:
        raise AppError("A voucher needs at least one debit and one credit line")
    if total_dr != total_cr:
        raise AppError(f"Voucher does not balance: debit {total_dr} ≠ credit {total_cr}")
    for l in clean:
        led = db.get(Ledger, l["ledger_id"])
        if not led or not led.is_active:
            raise AppError(f"Ledger {l['ledger_id']} not found or inactive")
    v = Voucher(
        voucher_no=next_number(db, f"VOUCHER_{voucher_type.upper()}", on),
        voucher_type=voucher_type,
        voucher_date=on,
        narration=narration,
        reference=reference,
        source_type=source_type,
        source_id=source_id,
        total=total_dr,
        created_by=getattr(user, "id", None),
        branch_id=branch_id,
    )
    db.add(v)
    db.flush()
    for l in clean:
        db.add(
            VoucherEntry(
                voucher_id=v.id,
                ledger_id=l["ledger_id"],
                debit=l["debit"],
                credit=l["credit"],
                narration=l.get("narration"),
                cost_vehicle_id=l.get("vehicle_id"),
                cost_trip_id=l.get("trip_id"),
                instrument_no=l.get("instrument_no"),
            )
        )
    db.flush()
    log(db, user, "post", "vouchers", v.id, None, {"voucher_no": v.voucher_no, "type": voucher_type, "total": str(total_dr), "source": f"{source_type}:{source_id}"})
    return v


def reverse(db: Session, user, voucher_id: int, reason: str, on: date | None = None) -> Voucher:
    """Cancel by posting an exact reversal. Nothing is ever deleted."""
    v = db.get(Voucher, voucher_id)
    if not v:
        raise AppError("Voucher not found", 404)
    if v.status != "Posted":
        raise AppError(f"Voucher {v.voucher_no} is already {v.status.lower()}")
    if not reason or len(reason.strip()) < 3:
        raise AppError("A reason is required to cancel a voucher")
    entries = db.execute(select(VoucherEntry).where(VoucherEntry.voucher_id == v.id)).scalars().all()
    rev = Voucher(
        voucher_no=next_number(db, "VOUCHER_JOURNAL", on or date.today()),
        voucher_type="Journal",
        voucher_date=on or date.today(),
        narration=f"Reversal of {v.voucher_no}: {reason}",
        reference=v.voucher_no,
        source_type=v.source_type,
        source_id=v.source_id,
        status="Reversal",
        reversal_of_id=v.id,
        total=v.total,
        created_by=getattr(user, "id", None),
    )
    db.add(rev)
    db.flush()
    for e in entries:
        db.add(VoucherEntry(voucher_id=rev.id, ledger_id=e.ledger_id, debit=e.credit, credit=e.debit, narration="Reversal", cost_vehicle_id=e.cost_vehicle_id, cost_trip_id=e.cost_trip_id))
    v.status = "Cancelled"
    v.reversed_by_id = rev.id
    v.cancel_reason = reason
    # release bill allocations made by this voucher
    for a in db.execute(select(BillAllocation).where(BillAllocation.voucher_id == v.id, BillAllocation.reversed.is_(False))).scalars():
        a.reversed = True
        if a.invoice_id:
            inv = db.get(Invoice, a.invoice_id)
            inv.amount_received = r2(D(inv.amount_received) - D(a.amount) - D(a.tds_amount))
            refresh_invoice_status(inv)
        if a.vendor_bill_id:
            bill = db.get(VendorBill, a.vendor_bill_id)
            bill.amount_paid = r2(D(bill.amount_paid) - D(a.amount) - D(a.tds_amount))
            refresh_bill_status(bill)
    db.flush()
    log(db, user, "cancel", "vouchers", v.id, {"status": "Posted"}, {"status": "Cancelled", "reversal": rev.voucher_no}, reason)
    return rev


def refresh_invoice_status(inv: Invoice) -> None:
    if inv.status in ("Cancelled", "Draft") or inv.doc_type in ("proforma",):
        return
    rec, total = D(inv.amount_received), D(inv.total)
    inv.status = "Paid" if rec >= total and total > 0 else ("Partly Paid" if rec > 0 else "Issued")


def refresh_bill_status(bill: VendorBill) -> None:
    if bill.status == "Cancelled":
        return
    paid, total = D(bill.amount_paid), D(bill.total) - D(bill.tds_amount)
    bill.status = "Paid" if paid >= total and total > 0 else ("Partly Paid" if paid > 0 else "Unpaid")


# ---------------------------------------------------------------- reports


def _signed_opening(led: Ledger) -> Decimal:
    ob = D(led.opening_balance)
    return ob if (led.opening_type or "Dr") == "Dr" else -ob


def ledger_balances(db: Session, upto: date | None = None, start: date | None = None) -> dict[int, dict]:
    """Per ledger: opening (incl. movement before start), debit, credit, closing (Dr positive)."""
    out: dict[int, dict] = {}
    for led in db.execute(select(Ledger)).scalars():
        out[led.id] = {"ledger": led, "opening": _signed_opening(led), "debit": ZERO, "credit": ZERO}
    q = select(VoucherEntry.ledger_id, Voucher.voucher_date, func.sum(VoucherEntry.debit), func.sum(VoucherEntry.credit)).join(
        Voucher, Voucher.id == VoucherEntry.voucher_id
    )
    if upto:
        q = q.where(Voucher.voucher_date <= upto)
    q = q.group_by(VoucherEntry.ledger_id, Voucher.voucher_date)
    for lid, vdate, dr, cr in db.execute(q):
        row = out.get(lid)
        if row is None:
            continue
        if start and vdate < start:
            row["opening"] += D(dr) - D(cr)
        else:
            row["debit"] += D(dr)
            row["credit"] += D(cr)
    for row in out.values():
        row["closing"] = row["opening"] + row["debit"] - row["credit"]
    return out


def ledger_balance(db: Session, ledger_id: int, upto: date | None = None) -> Decimal:
    led = db.get(Ledger, ledger_id)
    q = select(func.coalesce(func.sum(VoucherEntry.debit), 0) - func.coalesce(func.sum(VoucherEntry.credit), 0)).join(Voucher, Voucher.id == VoucherEntry.voucher_id).where(VoucherEntry.ledger_id == ledger_id)
    if upto:
        q = q.where(Voucher.voucher_date <= upto)
    return _signed_opening(led) + D(db.execute(q).scalar())


def groups_map(db: Session) -> dict[int, AccountGroup]:
    return {g.id: g for g in db.execute(select(AccountGroup)).scalars()}


def top_group(groups: dict[int, AccountGroup], gid: int) -> AccountGroup:
    g = groups[gid]
    while g.parent_id:
        g = groups[g.parent_id]
    return g


def trial_balance(db: Session, start: date, end: date) -> dict:
    bal = ledger_balances(db, upto=end, start=start)
    groups = groups_map(db)
    rows, tdr, tcr = [], ZERO, ZERO
    for lid, b in sorted(bal.items(), key=lambda kv: (groups[kv[1]["ledger"].group_id].name, kv[1]["ledger"].name)):
        if b["opening"] == 0 and b["debit"] == 0 and b["credit"] == 0:
            continue
        closing = b["closing"]
        dr, cr = (closing, ZERO) if closing >= 0 else (ZERO, -closing)
        tdr += dr
        tcr += cr
        rows.append({
            "ledger_id": lid, "ledger": b["ledger"].name, "group": groups[b["ledger"].group_id].name,
            "opening": r2(b["opening"]), "debit": r2(b["debit"]), "credit": r2(b["credit"]),
            "closing_dr": r2(dr), "closing_cr": r2(cr),
        })
    return {"rows": rows, "total_dr": r2(tdr), "total_cr": r2(tcr), "balanced": r2(tdr) == r2(tcr)}


def profit_and_loss(db: Session, start: date, end: date) -> dict:
    bal = ledger_balances(db, upto=end, start=start)
    groups = groups_map(db)
    sections = {"Direct Incomes": [], "Indirect Incomes": [], "Direct Expenses": [], "Indirect Expenses": []}
    for b in bal.values():
        led = b["ledger"]
        tg = top_group(groups, led.group_id)
        if tg.nature not in ("Income", "Expense"):
            continue
        movement = b["debit"] - b["credit"]  # P&L uses only the period movement
        if movement == 0:
            continue
        amount = -movement if tg.nature == "Income" else movement
        sections.setdefault(tg.name, []).append({"ledger_id": led.id, "ledger": led.name, "amount": r2(amount)})
    tot = {k: r2(sum((x["amount"] for x in v), ZERO)) for k, v in sections.items()}
    gross = tot["Direct Incomes"] - tot["Direct Expenses"]
    net = gross + tot["Indirect Incomes"] - tot["Indirect Expenses"]
    return {"sections": sections, "totals": tot, "gross_profit": r2(gross), "net_profit": r2(net), "from": start, "to": end}


def balance_sheet(db: Session, on: date, fy_start: date) -> dict:
    bal = ledger_balances(db, upto=on)
    groups = groups_map(db)
    assets: dict[str, list] = defaultdict(list)
    liabilities: dict[str, list] = defaultdict(list)
    pl_total = ZERO
    for b in bal.values():
        led = b["ledger"]
        tg = top_group(groups, led.group_id)
        closing = b["closing"]
        if tg.nature in ("Income", "Expense"):
            pl_total += -closing
            continue
        if closing == 0:
            continue
        g = groups[led.group_id].name
        if tg.nature == "Asset":
            assets[g].append({"ledger": led.name, "amount": r2(closing)})
        else:
            liabilities[g].append({"ledger": led.name, "amount": r2(-closing)})
    liabilities["Profit & Loss Account"].append({"ledger": "Accumulated profit / (loss)", "amount": r2(pl_total)})
    ta = r2(sum((x["amount"] for v in assets.values() for x in v), ZERO))
    tl = r2(sum((x["amount"] for v in liabilities.values() for x in v), ZERO))
    return {"as_on": on, "assets": dict(assets), "liabilities": dict(liabilities), "total_assets": ta, "total_liabilities": tl, "difference": r2(ta - tl)}


def cash_flow(db: Session, start: date, end: date) -> dict:
    """Direct method: every movement in cash/bank ledgers classified by the counter-ledger's group."""
    groups = groups_map(db)
    ledgers = {l.id: l for l in db.execute(select(Ledger)).scalars()}
    cash_ids = {lid for lid, l in ledgers.items() if groups[l.group_id].cash_flow == "cash"}
    buckets: dict[str, dict[str, Decimal]] = {"operating": defaultdict(lambda: ZERO), "investing": defaultdict(lambda: ZERO), "financing": defaultdict(lambda: ZERO)}
    vouchers = db.execute(select(Voucher.id).where(Voucher.voucher_date.between(start, end))).scalars().all()
    entries_by_v: dict[int, list[VoucherEntry]] = defaultdict(list)
    if vouchers:
        for e in db.execute(select(VoucherEntry).where(VoucherEntry.voucher_id.in_(vouchers))).scalars():
            entries_by_v[e.voucher_id].append(e)
    for vid, entries in entries_by_v.items():
        cash_net = sum((D(e.debit) - D(e.credit) for e in entries if e.ledger_id in cash_ids), ZERO)
        if cash_net == 0:
            continue
        others = [e for e in entries if e.ledger_id not in cash_ids]
        other_total = sum((abs(D(e.debit) - D(e.credit)) for e in others), ZERO)
        for e in others:
            share = abs(D(e.debit) - D(e.credit)) / other_total * cash_net if other_total else ZERO
            led = ledgers[e.ledger_id]
            tg = groups[led.group_id]
            bucket = tg.cash_flow if tg.cash_flow in buckets else top_group(groups, led.group_id).cash_flow
            bucket = bucket if bucket in buckets else "operating"
            buckets[bucket][groups[led.group_id].name] += share
    opening = sum((ledger_balance(db, lid, start - timedelta(days=1)) for lid in cash_ids), ZERO)
    closing = sum((ledger_balance(db, lid, end) for lid in cash_ids), ZERO)
    out = {k: [{"head": h, "amount": r2(a)} for h, a in v.items()] for k, v in buckets.items()}
    totals = {k: r2(sum((x["amount"] for x in v), ZERO)) for k, v in out.items()}
    return {"sections": out, "totals": totals, "net_change": r2(sum(totals.values(), ZERO)), "opening_cash": r2(opening), "closing_cash": r2(closing)}


def ledger_statement(db: Session, ledger_id: int, start: date, end: date) -> dict:
    led = db.get(Ledger, ledger_id)
    if not led:
        raise AppError("Ledger not found", 404)
    opening = ledger_balance(db, ledger_id, start - timedelta(days=1))
    q = (
        select(VoucherEntry, Voucher)
        .join(Voucher, Voucher.id == VoucherEntry.voucher_id)
        .where(VoucherEntry.ledger_id == ledger_id, Voucher.voucher_date.between(start, end))
        .order_by(Voucher.voucher_date, Voucher.id)
    )
    running = opening
    rows = []
    for e, v in db.execute(q):
        running += D(e.debit) - D(e.credit)
        rows.append({
            "date": v.voucher_date, "voucher_no": v.voucher_no, "type": v.voucher_type, "narration": v.narration or e.narration,
            "reference": v.reference, "debit": r2(e.debit), "credit": r2(e.credit), "balance": r2(running), "status": v.status,
            "voucher_id": v.id,
        })
    return {"ledger": led.name, "ledger_id": led.id, "opening": r2(opening), "closing": r2(running), "rows": rows}


def day_book(db: Session, start: date, end: date, ledger_ids: set[int] | None = None) -> list[dict]:
    q = select(Voucher).where(Voucher.voucher_date.between(start, end)).order_by(Voucher.voucher_date, Voucher.id)
    ledgers = {l.id: l.name for l in db.execute(select(Ledger)).scalars()}
    out = []
    for v in db.execute(q).scalars():
        entries = db.execute(select(VoucherEntry).where(VoucherEntry.voucher_id == v.id)).scalars().all()
        if ledger_ids and not any(e.ledger_id in ledger_ids for e in entries):
            continue
        out.append({
            "voucher_id": v.id, "date": v.voucher_date, "voucher_no": v.voucher_no, "type": v.voucher_type, "status": v.status,
            "narration": v.narration, "total": r2(v.total),
            "entries": [{"ledger": ledgers.get(e.ledger_id), "debit": r2(e.debit), "credit": r2(e.credit)} for e in entries],
        })
    return out


def ageing(db: Session, kind: str, on: date) -> list[dict]:
    """Bill-wise outstanding with 0-30 / 31-60 / 61-90 / 90+ buckets (by due date)."""
    rows = []
    if kind == "customer":
        from ..models import Customer

        names = {c.id: c.name for c in db.execute(select(Customer)).scalars()}
        q = select(Invoice).where(Invoice.status.in_(["Issued", "Partly Paid"]), Invoice.doc_type.in_(["tax_invoice", "bill_of_supply", "debit_note"]), Invoice.invoice_date <= on)
        for inv in db.execute(q).scalars():
            bal = D(inv.total) - D(inv.amount_received)
            if bal <= 0:
                continue
            rows.append({"party_id": inv.customer_id, "party": names.get(inv.customer_id), "doc_no": inv.invoice_no, "doc_date": inv.invoice_date, "due_date": inv.due_date or inv.invoice_date, "amount": r2(inv.total), "balance": r2(bal)})
        # unadjusted credit notes reduce the party balance
        q2 = select(Invoice).where(Invoice.doc_type == "credit_note", Invoice.status != "Cancelled", Invoice.invoice_date <= on)
        for cn in db.execute(q2).scalars():
            rows.append({"party_id": cn.customer_id, "party": names.get(cn.customer_id), "doc_no": cn.invoice_no, "doc_date": cn.invoice_date, "due_date": cn.invoice_date, "amount": -r2(cn.total), "balance": -r2(D(cn.total) - D(cn.amount_received))})
    else:
        names = {v.id: v.name for v in db.execute(select(Vendor)).scalars()}
        q = select(VendorBill).where(VendorBill.status.in_(["Unpaid", "Partly Paid"]), VendorBill.bill_date <= on)
        for b in db.execute(q).scalars():
            bal = D(b.total) - D(b.tds_amount) - D(b.amount_paid)
            if bal <= 0:
                continue
            rows.append({"party_id": b.vendor_id, "party": names.get(b.vendor_id), "doc_no": f"{b.entry_no} / {b.bill_no}", "doc_date": b.bill_date, "due_date": b.due_date or b.bill_date, "amount": r2(b.total), "balance": r2(bal)})
    for r in rows:
        days = (on - r["due_date"]).days
        r["days_overdue"] = max(0, days)
        r["bucket"] = "Not due" if days < 0 else "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
    return sorted(rows, key=lambda r: (r["party"] or "", r["doc_date"]))


def allocate_receipt(db: Session, voucher: Voucher, allocations: list[dict]) -> None:
    for a in allocations:
        inv = db.get(Invoice, int(a["invoice_id"]))
        amt, tds = r2(a.get("amount")), r2(a.get("tds_amount"))
        if not inv or inv.status in ("Cancelled", "Draft") or inv.doc_type == "proforma":
            raise AppError("Receipt can only be allocated to an issued invoice")
        bal = D(inv.total) - D(inv.amount_received)
        if amt + tds > bal + Decimal("0.01"):
            raise AppError(f"Allocation ₹{amt + tds} exceeds balance ₹{r2(bal)} of invoice {inv.invoice_no}")
        db.add(BillAllocation(voucher_id=voucher.id, invoice_id=inv.id, amount=amt, tds_amount=tds))
        inv.amount_received = r2(D(inv.amount_received) + amt + tds)
        refresh_invoice_status(inv)


def allocate_payment(db: Session, voucher: Voucher, allocations: list[dict]) -> None:
    for a in allocations:
        bill = db.get(VendorBill, int(a["vendor_bill_id"]))
        amt = r2(a.get("amount"))
        if not bill or bill.status == "Cancelled":
            raise AppError("Payment can only be allocated to an open vendor bill")
        bal = D(bill.total) - D(bill.tds_amount) - D(bill.amount_paid)
        if amt > bal + Decimal("0.01"):
            raise AppError(f"Allocation ₹{amt} exceeds balance ₹{r2(bal)} of bill {bill.bill_no}")
        db.add(BillAllocation(voucher_id=voucher.id, vendor_bill_id=bill.id, amount=amt))
        bill.amount_paid = r2(D(bill.amount_paid) + amt)
        refresh_bill_status(bill)
