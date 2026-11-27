"""Excel / CSV exports of any report, Tally-compatible voucher & ledger exports, CSV imports."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..core.money import D


def _val(v, typ):
    if v is None:
        return None
    if typ == "money" or isinstance(v, Decimal):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    if typ == "date" and isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return v
    if isinstance(v, datetime) and v.tzinfo:
        return v.replace(tzinfo=None)
    if isinstance(v, (dict, list)):
        return str(v)
    return v


def report_xlsx(report: dict, company_name: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = report["title"][:31].replace("/", "-")
    ws.append([company_name])
    ws.append([report["title"]])
    if report.get("subtitle"):
        ws.append([report["subtitle"]])
    ws.append([])
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"].font = Font(bold=True, size=11)
    header_row = ws.max_row + 1
    cols = report["columns"]
    ws.append([c["label"] for c in cols])
    for i in range(1, len(cols) + 1):
        cell = ws.cell(row=header_row, column=i)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E8EEF5")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for r in report["rows"]:
        ws.append([_val(r.get(c["key"]), c.get("type")) for c in cols])
        if r.get("_bold"):  # group / section lines of grouped statements
            for i in range(1, len(cols) + 1):
                ws.cell(row=ws.max_row, column=i).font = Font(bold=True)
    if report.get("totals"):
        ws.append([_val(report["totals"].get(c["key"]), c.get("type")) if c["key"] in report["totals"] else ("Total" if i == 0 else None) for i, c in enumerate(cols)])
        for i in range(1, len(cols) + 1):
            ws.cell(row=ws.max_row, column=i).font = Font(bold=True)
    for i, c in enumerate(cols, 1):
        letter = get_column_letter(i)
        if c.get("type") == "money":
            for row in ws.iter_rows(min_row=header_row + 1, min_col=i, max_col=i):
                row[0].number_format = '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00'
        elif c.get("type") == "date":
            for row in ws.iter_rows(min_row=header_row + 1, min_col=i, max_col=i):
                row[0].number_format = "DD-MM-YYYY"
        ws.column_dimensions[letter].width = max(10, min(45, len(c["label"]) + 4, 14 if c.get("type") in ("money", "date", "number") else 45))
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_csv(report: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["label"] for c in report["columns"]])
    for r in report["rows"]:
        w.writerow(["" if r.get(c["key"]) is None else (r.get(c["key"]).strftime("%d-%m-%Y") if isinstance(r.get(c["key"]), date) else r.get(c["key"])) for c in report["columns"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")


TALLY_VOUCHER_COLUMNS = ["Date", "Voucher Type", "Voucher Number", "Ledger Name", "Dr/Cr", "Amount", "Narration", "Reference", "Cost Centre"]


def tally_vouchers(rows: list[dict]) -> dict:
    """rows prepared by the API: one row per voucher entry. Layout follows the common Tally Excel-import template."""
    return {
        "title": "Tally voucher export",
        "columns": [{"key": k, "label": k, "type": "money" if k == "Amount" else "date" if k == "Date" else None} for k in TALLY_VOUCHER_COLUMNS],
        "rows": rows,
    }


def read_table(filename: str, content: bytes) -> list[dict]:
    """Read CSV or XLSX into a list of dicts using the first non-empty row as header."""
    name = filename.lower()
    if name.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return [dict(r) for r in csv.DictReader(io.StringIO(text))]
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        rows = [r for r in rows if any(c not in (None, "") for c in r)]
        if not rows:
            return []
        header = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]
        return [dict(zip(header, r)) for r in rows[1:]]
    raise ValueError("Upload a .csv or .xlsx file")


def pick(row: dict, *names):
    """Case/space-insensitive column lookup for imports from different providers."""
    norm = {str(k).strip().lower().replace(" ", "").replace("_", ""): v for k, v in row.items()}
    for n in names:
        v = norm.get(n.lower().replace(" ", "").replace("_", ""))
        if v not in (None, ""):
            return v
    return None
