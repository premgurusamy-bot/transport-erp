"""Report export to CSV, Excel (.xlsx) and PDF (simple text-layout PDF, no external dependency)."""
from __future__ import annotations

import csv
import io
from datetime import date

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.finance import reports as rpt


def _rows(db: Session, name: str, frm: date, to: date) -> tuple[list[str], list[list]]:
    if name == "trial-balance":
        r = rpt.trial_balance(db, to)
        return ["Code", "Ledger", "Debit", "Credit"], [[x["code"], x["name"], x["debit"], x["credit"]] for x in r["rows"]]
    if name == "pnl":
        r = rpt.profit_and_loss(db, frm, to)
        return ["Type", "Code", "Ledger", "Amount"], ([["Income", x["code"], x["name"], x["amount"]] for x in r["income"]]
                                                     + [["Expense", x["code"], x["name"], x["amount"]] for x in r["expenses"]]
                                                     + [["", "", "Net profit", r["net_profit"]]])
    if name == "ageing":
        r = rpt.ageing(db, "receivable")
        return ["Customer", *r["buckets"], "Total"], [[x["party"], *[x[b] for b in r["buckets"]], x["total"]] for x in r["rows"]]
    if name == "gst":
        r = rpt.gst_register(db, frm, to)
        return ["Invoice", "Date", "Customer", "GSTIN", "Mode", "Taxable", "CGST", "SGST", "IGST"], [
            [x["invoice"], x["date"], x["customer"], x["gstin"], x["mode"], x["taxable"], x["cgst"], x["sgst"], x["igst"]] for x in r["rows"]]
    raise AppError("unknown_report", f"Unknown report {name}")


def _pdf(title: str, header: list[str], rows: list[list]) -> bytes:
    lines = [title, "", " | ".join(header)] + [" | ".join(str(c) for c in r) for r in rows]
    pages = [lines[i:i + 50] for i in range(0, len(lines), 50)] or [[title]]
    objs = []
    kids = []
    for pg in pages:
        text = "BT /F1 9 Tf 36 800 Td 12 TL " + " ".join(
            "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:150] + ") '" for l in pg) + " ET"
        stream = text.encode("latin-1", "replace")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(len(objs))
        objs.append(None)  # placeholder for page
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    # objects: 1 catalog, 2 pages, 3 font, then content/page pairs
    final = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    page_refs = []
    for i in range(0, len(objs), 2):
        final.append(objs[i])
        content_no = len(final)
        final.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_no)
        page_refs.append(len(final))
    final[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % r for r in page_refs) + b"] /Count %d >>" % len(page_refs)
    offsets = []
    for n, o in enumerate(final, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % n + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(final) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(final) + 1, xref))
    return out.getvalue()


def export_report(db: Session, name: str, fmt: str, frm: date, to: date) -> tuple[bytes, str, str]:
    header, rows = _rows(db, name, frm, to)
    base = f"GRL_{name}_{frm}_{to}"
    if fmt == "csv":
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(header)
        w.writerows(rows)
        return s.getvalue().encode("utf-8-sig"), "text/csv", base + ".csv"
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = name[:30]
        ws.append(header)
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        b = io.BytesIO()
        wb.save(b)
        return b.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", base + ".xlsx"
    if fmt == "pdf":
        return _pdf(f"G ROAD LINES - {name} {frm} to {to}", header, rows), "application/pdf", base + ".pdf"
    raise AppError("format", "Format must be csv, xlsx or pdf")
