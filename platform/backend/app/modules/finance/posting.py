"""Double-entry posting engine. Every financial event becomes a balanced voucher; posted vouchers are
never edited - corrections are made by reversal vouchers."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import money
from app.core.errors import AppError, Conflict
from app.core.services import financial_year, next_number
from app.modules.finance.models import Account, Voucher, VoucherLine

CHART = [
    # code, name, nature, group, control
    ("1000", "Cash in Hand", "asset", "Cash-in-Hand", False),
    ("1010", "Bank - Primary Current Account", "asset", "Bank Accounts", False),
    ("1100", "Sundry Debtors", "asset", "Sundry Debtors", True),
    ("1150", "Advances to Vehicle Owners", "asset", "Loans & Advances (Asset)", True),
    ("1160", "Advances to Drivers", "asset", "Loans & Advances (Asset)", True),
    ("1170", "Advances to Vendors", "asset", "Loans & Advances (Asset)", True),
    ("1200", "TDS Receivable", "asset", "Duties & Taxes (Asset)", False),
    ("1210", "GST Input Credit", "asset", "Duties & Taxes (Asset)", False),
    ("1250", "Reimbursable Expenses Recoverable", "asset", "Current Assets", False),
    ("1300", "Insurance Claims Receivable", "asset", "Current Assets", False),
    ("1400", "Stores & Spares Inventory", "asset", "Stock-in-Hand", False),
    ("1500", "Vehicles (Fixed Assets)", "asset", "Fixed Assets", False),
    ("1590", "Suspense - Unidentified Receipts", "liability", "Suspense", False),
    ("2000", "Creditors - Vehicle Owners", "liability", "Sundry Creditors", True),
    ("2010", "Creditors - Vendors", "liability", "Sundry Creditors", True),
    ("2020", "Driver Remuneration Payable", "liability", "Current Liabilities", True),
    ("2030", "Salaries Payable", "liability", "Current Liabilities", True),
    ("2101", "CGST Output", "liability", "Duties & Taxes", False),
    ("2102", "SGST Output", "liability", "Duties & Taxes", False),
    ("2103", "IGST Output", "liability", "Duties & Taxes", False),
    ("2110", "TDS Payable", "liability", "Duties & Taxes", False),
    ("2120", "Statutory Payroll Payable (PF/ESI/PT)", "liability", "Duties & Taxes", False),
    ("2200", "Customer Advances", "liability", "Current Liabilities", True),
    ("2300", "Vehicle Loans", "liability", "Secured Loans", False),
    ("3000", "Capital Account", "equity", "Capital Account", False),
    ("3100", "Opening Balance Equity", "equity", "Reserves & Surplus", False),
    ("4000", "Freight Income - FTL Own Fleet", "income", "Direct Income", False),
    ("4010", "Freight Income - FTL Attached", "income", "Direct Income", False),
    ("4020", "Freight Income - PTL", "income", "Direct Income", False),
    ("4030", "Handling & Service Income", "income", "Direct Income", False),
    ("4040", "Godown & Storage Income", "income", "Direct Income", False),
    ("4050", "Detention & Other Charges", "income", "Direct Income", False),
    ("4900", "Other Income", "income", "Indirect Income", False),
    ("5000", "Vehicle Hire - Attached", "expense", "Direct Expenses", False),
    ("5010", "Fuel & AdBlue", "expense", "Direct Expenses", False),
    ("5020", "Toll & Parking", "expense", "Direct Expenses", False),
    ("5030", "Repairs & Maintenance", "expense", "Direct Expenses", False),
    ("5040", "Tyres & Batteries", "expense", "Direct Expenses", False),
    ("5050", "Driver Remuneration & Allowances", "expense", "Direct Expenses", False),
    ("5060", "Loading / Unloading / Hamali", "expense", "Direct Expenses", False),
    ("5070", "Crane / Hydra Hire", "expense", "Direct Expenses", False),
    ("5080", "Permits & Compliance", "expense", "Direct Expenses", False),
    ("5090", "Insurance", "expense", "Indirect Expenses", False),
    ("5100", "Godown & Handling Vendor Costs", "expense", "Direct Expenses", False),
    ("5200", "Salaries & Wages", "expense", "Indirect Expenses", False),
    ("5300", "Office Overheads", "expense", "Indirect Expenses", False),
    ("5400", "Marketing", "expense", "Indirect Expenses", False),
    ("5500", "Bank Charges", "expense", "Indirect Expenses", False),
    ("5600", "Claims & Compensation", "expense", "Indirect Expenses", False),
    ("5700", "Depreciation", "expense", "Indirect Expenses", False),
    ("5800", "Interest on Loans", "expense", "Indirect Expenses", False),
    ("5900", "Other Expenses", "expense", "Indirect Expenses", False),
]

EXPENSE_ACCOUNT = {
    "fuel": "5010", "toll": "5020", "parking": "5020", "repair": "5030", "tyre": "5040", "allowance": "5050",
    "hamali": "5060", "loading": "5060", "crane": "5070", "permit": "5080", "compliance": "5080", "insurance": "5090",
    "godown": "5100", "overhead": "5300", "marketing": "5400", "bank_charges": "5500", "other": "5900",
}


def seed_chart(db: Session):
    have = set(db.execute(select(Account.code)).scalars())
    for code, name, nature, group, ctrl in CHART:
        if code not in have:
            db.add(Account(code=code, name=name, nature=nature, group=group, is_control=ctrl))
    db.flush()


def acct(db: Session, code: str) -> Account:
    a = db.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if not a:
        raise AppError("ledger_missing", f"Ledger {code} missing - run setup")
    return a


def post_voucher(db: Session, actor, *, vtype: str, vdate: date, narration: str, lines: list[dict],
                 source_entity: str | None = None, source_id=None, external_ref: str | None = None,
                 approved_by=None) -> Voucher:
    """lines: [{account: code, debit|credit, party_type?, party_id?, cost_centre?, trip_id?, booking_id?, vehicle_id?, narration?}]"""
    clean = []
    for l in lines:
        dr, cr = money(l.get("debit", 0)), money(l.get("credit", 0))
        if dr == 0 and cr == 0:
            continue
        if dr < 0 or cr < 0:
            raise AppError("negative_amount", "Voucher lines cannot have negative amounts")
        clean.append({**l, "debit": dr, "credit": cr})
    td = sum((l["debit"] for l in clean), Decimal("0"))
    tc = sum((l["credit"] for l in clean), Decimal("0"))
    if td != tc:
        raise AppError("unbalanced", f"Voucher does not balance: debit {td} vs credit {tc}")
    if td == 0:
        raise AppError("empty_voucher", "Voucher has no amounts")
    v = Voucher(number=next_number(db, f"V-{vtype}", f"{vtype[:3].upper()}", when=vdate), vtype=vtype, vdate=vdate,
                fy=financial_year(vdate), narration=narration, source_entity=source_entity,
                source_id=str(source_id) if source_id else None, created_by=getattr(actor, "user_id", None),
                approved_by=approved_by, total=td, external_ref=external_ref)
    db.add(v)
    db.flush()
    for l in clean:
        db.add(VoucherLine(voucher_id=v.id, account_id=acct(db, l["account"]).id, debit=l["debit"], credit=l["credit"],
                           party_type=l.get("party_type"), party_id=l.get("party_id"), cost_centre=l.get("cost_centre"),
                           trip_id=l.get("trip_id"), booking_id=l.get("booking_id"), vehicle_id=l.get("vehicle_id"),
                           line_narration=l.get("narration")))
    db.flush()
    write_audit(db, actor=actor, action="voucher.post", entity="voucher", entity_id=v.id,
                after={"number": v.number, "type": vtype, "total": td, "source": source_entity})
    return v


def reverse_voucher(db: Session, actor, voucher_id: uuid.UUID, reason: str, on: date | None = None) -> Voucher:
    v = db.execute(select(Voucher).where(Voucher.id == voucher_id).with_for_update()).scalar_one()
    if v.status == "reversed":
        raise Conflict("already_reversed", "Voucher already reversed")
    lines = db.execute(select(VoucherLine).where(VoucherLine.voucher_id == v.id)).scalars().all()
    rl = []
    for l in lines:
        a = db.get(Account, l.account_id)
        rl.append({"account": a.code, "debit": l.credit, "credit": l.debit, "party_type": l.party_type, "party_id": l.party_id,
                   "cost_centre": l.cost_centre, "trip_id": l.trip_id, "booking_id": l.booking_id, "vehicle_id": l.vehicle_id})
    r = post_voucher(db, actor, vtype="journal", vdate=on or date.today(), narration=f"Reversal of {v.number}: {reason}",
                     lines=rl, source_entity="reversal", source_id=v.id)
    r.reversal_of = v.id
    v.status, v.reversed_by = "reversed", r.id
    write_audit(db, actor=actor, action="voucher.reverse", entity="voucher", entity_id=v.id, reason=reason)
    return r


def bank_ledger(db: Session, company_bank_id) -> str:
    from app.modules.masters.models import CompanyBankAccount
    if not company_bank_id:
        return "1010"
    cb = db.get(CompanyBankAccount, company_bank_id)
    return cb.ledger_code if cb else "1010"


# ------------------------------------------------------------------ domain postings
def post_expense(db: Session, actor, exp) -> Voucher:
    if exp.voucher_id:
        return db.get(Voucher, exp.voucher_id)
    from app.modules.fleet.models import Vehicle
    cc = None
    if exp.vehicle_id:
        v = db.get(Vehicle, exp.vehicle_id)
        cc = f"VEH:{v.registration}" if v else None
    dr_acct = "1250" if exp.rebillable else EXPENSE_ACCOUNT.get(exp.category, "5900")
    lines = [{"account": dr_acct, "debit": exp.amount, "cost_centre": cc, "trip_id": exp.trip_id, "vehicle_id": exp.vehicle_id,
              "booking_id": exp.booking_id, "narration": f"{exp.category} {exp.vendor_name or ''}"}]
    if exp.tax_amount:
        lines.append({"account": "1210", "debit": exp.tax_amount})
    total = money(Decimal(exp.amount) + Decimal(exp.tax_amount or 0))
    if exp.paid_by == "driver_cash":
        lines.append({"account": "2020", "credit": total, "party_type": "driver", "party_id": exp.driver_id})
    elif exp.paid_by == "driver_advance":
        lines.append({"account": "1160", "credit": total, "party_type": "driver", "party_id": exp.driver_id})
    elif exp.payment_mode == "cash":
        lines.append({"account": "1000", "credit": total})
    else:
        lines.append({"account": "2010", "credit": total, "party_type": "vendor", "party_id": exp.vendor_id})
    v = post_voucher(db, actor, vtype="expense", vdate=exp.expense_date, narration=f"Expense {exp.code}", lines=lines,
                     source_entity="expense", source_id=exp.id, approved_by=exp.approved_by)
    exp.voucher_id, exp.status = v.id, "posted"
    return v
