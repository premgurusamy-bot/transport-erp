"""Duplicate-proof document numbering per financial year (row lock on number_series)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NumberSeries

DEFAULT_PREFIXES = {
    "LR": "SVL/LR/",
    "TRIP": "TRP/",
    "BOOKING": "BKG/",
    "INVOICE": "SVL/",
    "PROFORMA": "PRF/",
    "DEBIT_NOTE": "DN/",
    "CREDIT_NOTE": "CN/",
    "BILL_OF_SUPPLY": "BOS/",
    "ADVANCE_RECEIPT": "ARV/",
    "VOUCHER_JOURNAL": "JV/",
    "VOUCHER_PAYMENT": "PV/",
    "VOUCHER_RECEIPT": "RV/",
    "VOUCHER_CONTRA": "CV/",
    "VOUCHER_PURCHASE": "PUR/",
    "VOUCHER_SALES": "SV/",
    "VOUCHER_DEBIT NOTE": "DNV/",
    "VOUCHER_CREDIT NOTE": "CNV/",
    "DRIVER_SETTLEMENT": "DS/",
    "MAINT_JOB": "JOB/",
    "STOCK_INWARD": "GRN/",
    "STOCK_OUTWARD": "GDN/",
    "STOCK_OTHER": "STK/",
    "PO": "PO/",
    "GRN": "MRN/",
    "VENDOR_BILL": "VB/",
    "COMPLAINT": "CMP/",
    "RATE_CONTRACT": "RC/",
}


def financial_year(d: date, start_month: int = 4) -> str:
    start_year = d.year if d.month >= start_month else d.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def fy_bounds(fy: str, start_month: int = 4) -> tuple[date, date]:
    start_year = int(fy[:4])
    start = date(start_year, start_month, 1)
    end_year = start_year + 1 if start_month > 1 else start_year
    end_month = start_month - 1 if start_month > 1 else 12
    import calendar

    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return start, end


def next_number(db: Session, doc_type: str, on: date, branch_code: str = "") -> str:
    fy = financial_year(on)
    stmt = (
        select(NumberSeries)
        .where(NumberSeries.doc_type == doc_type, NumberSeries.fy == fy, NumberSeries.branch_code == branch_code)
        .with_for_update()
    )
    series = db.execute(stmt).scalar_one_or_none()
    if series is None:
        # Inherit prefix/padding from any earlier year's series so admin edits carry forward.
        prev = db.execute(
            select(NumberSeries).where(NumberSeries.doc_type == doc_type).order_by(NumberSeries.fy.desc()).limit(1)
        ).scalar_one_or_none()
        series = NumberSeries(
            doc_type=doc_type,
            fy=fy,
            branch_code=branch_code,
            prefix=prev.prefix if prev else DEFAULT_PREFIXES.get(doc_type, doc_type + "/"),
            padding=prev.padding if prev else 5,
            pattern=prev.pattern if prev else "{prefix}{fy}/{no}",
            next_no=1,
        )
        db.add(series)
        db.flush()
        series = db.execute(stmt).scalar_one()
    no = series.next_no
    series.next_no = no + 1
    db.flush()
    return series.pattern.format(
        prefix=series.prefix or "", fy=fy, branch=branch_code, no=str(no).zfill(series.padding or 1)
    )
