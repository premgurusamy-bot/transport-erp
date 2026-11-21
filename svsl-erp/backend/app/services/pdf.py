"""PDF generation (ReportLab): LR (A4 + 80 mm thermal), GST invoice, generic report tables."""
from __future__ import annotations

import io
import os
from decimal import Decimal
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import get_settings
from ..core.money import D, amount_in_words, fmt_date, inr
from ..core.security import sign

_FONT, _FONT_B, _RUPEE = "Helvetica", "Helvetica-Bold", "Rs."


def _fonts() -> None:
    global _FONT, _FONT_B, _RUPEE
    if _FONT != "Helvetica":
        return
    win = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    candidates = [(d, "DejaVuSans.ttf", "DejaVuSans-Bold.ttf") for d in (os.environ.get("PDF_FONT_DIR", ""), "/usr/share/fonts/truetype/dejavu", win, str(Path(__file__).parent / "fonts"))]
    candidates.append((win, "segoeui.ttf", "segoeuib.ttf"))  # Windows 8+: has the ₹ glyph
    for d, r, b in candidates:
        reg, bold = Path(d) / r, Path(d) / b
        if d and reg.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("ErpSans", str(reg)))
            pdfmetrics.registerFont(TTFont("ErpSans-Bold", str(bold)))
            _FONT, _FONT_B, _RUPEE = "ErpSans", "ErpSans-Bold", "₹"
            return


def money(v) -> str:
    return inr(v, symbol=False)


def rs(v) -> str:
    return f"{_RUPEE} {inr(v, symbol=False)}"


def styles(size: float = 8.5):
    _fonts()
    return {
        "n": ParagraphStyle("n", fontName=_FONT, fontSize=size, leading=size * 1.25),
        "b": ParagraphStyle("b", fontName=_FONT_B, fontSize=size, leading=size * 1.25),
        "s": ParagraphStyle("s", fontName=_FONT, fontSize=size - 1.5, leading=(size - 1.5) * 1.25, textColor=colors.HexColor("#444444")),
        "h": ParagraphStyle("h", fontName=_FONT_B, fontSize=size + 6, leading=(size + 6) * 1.2, textColor=colors.HexColor("#0f4c81")),
        "t": ParagraphStyle("t", fontName=_FONT_B, fontSize=size + 3, leading=(size + 3) * 1.2, alignment=TA_CENTER),
        "r": ParagraphStyle("r", fontName=_FONT, fontSize=size, leading=size * 1.25, alignment=TA_RIGHT),
        "rb": ParagraphStyle("rb", fontName=_FONT_B, fontSize=size, leading=size * 1.25, alignment=TA_RIGHT),
        "c": ParagraphStyle("c", fontName=_FONT, fontSize=size, leading=size * 1.25, alignment=TA_CENTER),
    }


def P(text, style) -> Paragraph:
    from xml.sax.saxutils import escape

    return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)


def qr_image(data: str, size_mm: float = 24) -> Image:
    img = qrcode.make(data, box_size=4, border=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Image(buf, width=size_mm * mm, height=size_mm * mm)


def logo(company, h_mm: float = 16):
    if company.logo_path:
        p = get_settings().storage_dir / company.logo_path
        if p.exists():
            try:
                return Image(str(p), width=h_mm * mm * 1.6, height=h_mm * mm, kind="proportional")
            except Exception:  # noqa: BLE001
                return None
    return None


def company_block(company, st, title: str) -> Table:
    name = company.trade_name or company.legal_name
    lines = [P(name, st["h"])]
    if company.trade_name and company.legal_name and company.trade_name != company.legal_name:
        lines.append(P(company.legal_name, st["s"]))
    addr = ", ".join(filter(None, [company.address, company.city, company.state, company.pincode]))
    lines.append(P(addr, st["n"]))
    ids = " | ".join(filter(None, [f"GSTIN: {company.gstin}" if company.gstin else "GSTIN: (not configured)", f"PAN: {company.pan}" if company.pan else None, f"CIN: {company.cin}" if company.cin else None]))
    lines.append(P(ids, st["n"]))
    lines.append(P(" | ".join(filter(None, [company.phone, company.email])), st["n"]))
    lg = logo(company)
    data = [[lg, lines, P(title, st["t"])]] if lg else [[lines, P(title, st["t"])]]
    widths = [30 * mm, 110 * mm, 46 * mm] if lg else [135 * mm, 51 * mm]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#0f4c81"))]))
    return t


GRID = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#888888")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)])


def _doc(buf, pagesize=A4, margins=10):
    return SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=margins * mm, rightMargin=margins * mm, topMargin=margins * mm, bottomMargin=margins * mm)


def verify_url(kind: str, number: str, token: str | None) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/public/verify/{kind}/{number.replace('/', '~')}?s={sign(kind + number + (token or ''))}"


# ------------------------------------------------------------------ LR


def lr_pdf(lr, company, customer, items, points, copies: list[str], fmt: str = "A4") -> bytes:
    if fmt == "thermal":
        return lr_thermal(lr, company, items)
    st = styles(8.5)
    buf = io.BytesIO()
    doc = _doc(buf)
    story = []
    url = verify_url("lr", lr.lr_no, lr.verify_token)
    for idx, copy in enumerate(copies or ["Original"]):
        if idx:
            story.append(PageBreak())
        story.append(company_block(company, st, "LORRY RECEIPT\n(Consignment Note)"))
        story.append(Spacer(1, 3 * mm))
        hdr = Table([[
            [P(f"LR No: {lr.lr_no}", st["b"]), P(f"Date: {fmt_date(lr.lr_date)}", st["n"]), P(f"{lr.load_type} {'• RETURN LR' if lr.is_return else ''}", st["n"])],
            [P(f"From: {lr.from_place}", st["b"]), P(f"To: {lr.to_place}", st["b"]), P(f"Distance: {lr.distance_km or '-'} km", st["n"])],
            [P(f"Vehicle: {lr.vehicle_no or '-'}", st["b"]), P(f"Driver: {lr.driver_name or '-'} {lr.driver_mobile or ''}", st["n"]), P(f"DL: {lr.driver_licence or '-'}", st["s"])],
            [P(copy.upper(), st["rb"]), qr_image(url, 20)],
        ]], colWidths=[52 * mm, 52 * mm, 50 * mm, 32 * mm])
        hdr.setStyle(GRID)
        story.append(hdr)
        parties = Table([[
            [P("CONSIGNOR", st["b"]), P(lr.consignor_name, st["n"]), P(lr.consignor_address, st["s"]), P(f"GSTIN: {lr.consignor_gstin or '-'}   Ph: {lr.consignor_phone or '-'}", st["s"])],
            [P("CONSIGNEE", st["b"]), P(lr.consignee_name, st["n"]), P(lr.consignee_address, st["s"]), P(f"GSTIN: {lr.consignee_gstin or '-'}   Ph: {lr.consignee_phone or '-'}", st["s"])],
        ], [
            [P("Loading at", st["b"]), P(lr.loading_address or lr.consignor_address, st["s"])],
            [P("Delivery at", st["b"]), P(lr.delivery_address or lr.consignee_address, st["s"])],
        ]], colWidths=[93 * mm, 93 * mm])
        parties.setStyle(GRID)
        story.append(parties)
        rows = [[P(h, st["b"]) for h in ("#", "Description of goods", "HSN", "Pkgs", "Qty", "Weight (kg)", "Value")]]
        for i, it in enumerate(items, 1):
            rows.append([P(i, st["n"]), P(it.description, st["n"]), P(it.hsn or "", st["n"]), P(f"{it.packages} {it.package_type or ''}", st["n"]), P(f"{D(it.quantity):g} {it.uom}", st["n"]), P(f"{D(it.weight_kg):g}", st["r"]), P(money(it.value), st["r"])])
        if not items:
            rows.append(["", P("As per invoice", st["n"]), "", P(lr.packages, st["n"]), P(f"{D(lr.quantity):g}", st["n"]), P(f"{D(lr.weight_kg):g}", st["r"]), P(money(lr.goods_value), st["r"])])
        rows.append(["", P(f"Total   (Charged weight: {D(lr.charged_weight_kg):g} kg)", st["b"]), "", P(lr.packages, st["b"]), P(f"{D(lr.quantity):g}", st["b"]), P(f"{D(lr.weight_kg):g}", st["rb"]), P(money(lr.goods_value), st["rb"])])
        gt = Table(rows, colWidths=[8 * mm, 70 * mm, 16 * mm, 22 * mm, 22 * mm, 22 * mm, 26 * mm], repeatRows=1)
        gt.setStyle(GRID)
        story.append(gt)
        docs = [
            [P("Customer invoice", st["b"]), P(f"{lr.customer_invoice_no or '-'} {('dt ' + fmt_date(lr.customer_invoice_date)) if lr.customer_invoice_date else ''}", st["n"]), P("E-way bill", st["b"]), P(f"{lr.eway_bill_no or '-'} {('valid till ' + fmt_date(lr.eway_valid_until)) if lr.eway_valid_until else ''}", st["n"])],
            [P("Payment terms", st["b"]), P(lr.payment_terms, st["n"]), P("GST payable by", st["b"]), P(lr.gst_paid_by, st["n"])],
            [P("Risk", st["b"]), P(lr.risk, st["n"]), P("E-invoice ref", st["b"]), P(lr.einvoice_ref or "-", st["n"])],
        ]
        dt = Table(docs, colWidths=[30 * mm, 63 * mm, 30 * mm, 63 * mm])
        dt.setStyle(GRID)
        story.append(dt)
        if points:
            pr = [[P("Delivery points", st["b"]), P("Consignee", st["b"]), P("Address", st["b"]), P("Pkgs", st["b"])]]
            for p in points:
                pr.append([P(p.sequence, st["n"]), P(p.consignee_name or "", st["n"]), P(p.address, st["s"]), P(p.packages, st["n"])])
            ptab = Table(pr, colWidths=[24 * mm, 50 * mm, 92 * mm, 20 * mm])
            ptab.setStyle(GRID)
            story.append(ptab)
        fr = [[P("Freight", st["b"]), P("Amount", st["rb"])]]
        show_freight = lr.payment_terms != "To Be Billed" or True
        for label, val in (("Basic freight", lr.basic_freight), ("Loading charges", lr.loading_charges), ("Unloading charges", lr.unloading_charges), ("Waiting charges", lr.waiting_charges), ("Detention charges", lr.detention_charges), ("Additional stop charges", lr.extra_stop_charges), (f"Other charges {lr.other_charges_note or ''}", lr.other_charges)):
            if D(val):
                fr.append([P(label, st["n"]), P(money(val), st["r"])])
        fr += [[P("Total freight", st["b"]), P(rs(lr.total_freight), st["rb"])], [P("Advance", st["n"]), P(money(lr.advance_freight), st["r"])], [P("Balance", st["b"]), P(rs(lr.balance_freight), st["rb"])]]
        basis = (lr.freight_breakdown or {}).get("lines") or []
        basis_txt = "; ".join(b["label"] for b in basis[:3])
        ftab = Table([[Table(fr, colWidths=[50 * mm, 30 * mm]) if show_freight else "", [P("Freight basis", st["b"]), P(basis_txt or lr.freight_basis or "-", st["s"]), Spacer(1, 2 * mm), P("Remarks", st["b"]), P(lr.remarks or "-", st["s"]), P(f"Customer authorisation: {lr.customer_authorization or '-'}", st["s"])]]], colWidths=[86 * mm, 100 * mm])
        ftab.setStyle(GRID)
        story.append(ftab)
        decl = company.lr_print_declaration or (
            "Goods are carried at owner's risk unless otherwise agreed in writing. The consignor declares that the description, weight and value "
            "of goods are correct and that the goods are not prohibited or hazardous. The carrier is not responsible for leakage, breakage or "
            "damage due to improper packing. Delivery will be made only to the consignee or his authorised representative against this LR. "
            "Subject to Coimbatore jurisdiction."
        )
        terms = company.terms_lr or ""
        story.append(Spacer(1, 2 * mm))
        story.append(P("Declaration: " + decl, st["s"]))
        if terms:
            story.append(P("Terms: " + terms, st["s"]))
        if lr.status == "Cancelled":
            story.append(P(f"*** CANCELLED on {fmt_date(lr.cancelled_at)}: {lr.cancel_reason} ***", st["t"]))
        if lr.revision:
            story.append(P(f"Revision {lr.revision} (amended – see audit trail)", st["s"]))
        sig = Table([[P("Signature of consignor", st["c"]), P("Received in good condition – consignee signature & seal", st["c"]), P(f"For {company.trade_name or company.legal_name}\n\n\n{company.authorized_signatory or 'Authorised signatory'}", st["c"])]], colWidths=[62 * mm] * 3, rowHeights=[22 * mm])
        sig.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        story.append(Spacer(1, 2 * mm))
        story.append(sig)
        story.append(P(f"Verify this LR: scan the QR code. Printed from SVL ERP.", st["s"]))
    doc.build(story)
    return buf.getvalue()


def lr_thermal(lr, company, items) -> bytes:
    st = styles(7)
    buf = io.BytesIO()
    width = 80 * mm
    height = max(140, 110 + 8 * len(items)) * mm
    doc = SimpleDocTemplate(buf, pagesize=(width, height), leftMargin=3 * mm, rightMargin=3 * mm, topMargin=3 * mm, bottomMargin=3 * mm)
    s = [P(company.trade_name or company.legal_name, st["t"]), P(", ".join(filter(None, [company.city, company.phone])), st["c"]), P(f"GSTIN: {company.gstin or '-'}", st["c"]),
         P("LORRY RECEIPT", st["t"]), P(f"LR: {lr.lr_no}", st["b"]), P(f"Date: {fmt_date(lr.lr_date)}   {lr.load_type}", st["n"]),
         P(f"{lr.from_place} → {lr.to_place}", st["b"]), P(f"Vehicle: {lr.vehicle_no or '-'}  Driver: {lr.driver_name or '-'}", st["n"]),
         P(f"Consignor: {lr.consignor_name}", st["n"]), P(f"Consignee: {lr.consignee_name}", st["n"]), Spacer(1, 2 * mm)]
    for it in items:
        s.append(P(f"• {it.description} – {it.packages} pkg, {D(it.weight_kg):g} kg", st["n"]))
    s += [Spacer(1, 2 * mm), P(f"Pkgs {lr.packages}  Wt {D(lr.weight_kg):g} kg", st["n"]), P(f"E-way bill: {lr.eway_bill_no or '-'}", st["n"]),
          P(f"Freight: {rs(lr.total_freight)}  Adv: {money(lr.advance_freight)}  Bal: {money(lr.balance_freight)}", st["b"]), P(f"Terms: {lr.payment_terms}", st["n"]),
          qr_image(verify_url("lr", lr.lr_no, lr.verify_token), 28), P("Consignee signature: ____________", st["n"])]
    doc.build(s)
    return buf.getvalue()


# ------------------------------------------------------------------ invoice

DOC_TITLES = {"tax_invoice": "TAX INVOICE", "proforma": "PROFORMA INVOICE", "debit_note": "DEBIT NOTE", "credit_note": "CREDIT NOTE", "bill_of_supply": "BILL OF SUPPLY", "advance_receipt": "RECEIPT VOUCHER (ADVANCE)"}


def invoice_pdf(inv, company, customer, lines, bank, treatment, ref_invoice=None) -> bytes:
    from ..core.validators import STATE_CODES

    st = styles(8.5)
    buf = io.BytesIO()
    doc = _doc(buf)
    story = [company_block(company, st, DOC_TITLES.get(inv.doc_type, "INVOICE") + ("\n(CANCELLED)" if inv.status == "Cancelled" else ""))]
    qr_data = inv.signed_qr if inv.signed_qr else verify_url("inv", inv.invoice_no, inv.verify_token)
    meta = Table([[
        [P(f"{DOC_TITLES.get(inv.doc_type, 'Invoice').title()} No: {inv.invoice_no}", st["b"]), P(f"Date: {fmt_date(inv.invoice_date)}", st["n"]), P(f"Due date: {fmt_date(inv.due_date)}", st["n"]),
         P(f"Place of supply: {inv.place_of_supply} – {STATE_CODES.get(inv.place_of_supply, '')}", st["n"]), P(f"Reverse charge: {'Yes' if inv.charge_mechanism == 'RCM' else 'No'}", st["b"]),
         P(f"Ref. invoice: {ref_invoice.invoice_no} dt {fmt_date(ref_invoice.invoice_date)}" if ref_invoice else (f"Period: {fmt_date(inv.period_from)} – {fmt_date(inv.period_to)}" if inv.period_from else ""), st["n"]),
         P(f"PO / Vendor code: {inv.po_number}" if inv.po_number else "", st["n"])],
        [P("Bill to", st["b"]), P(inv.billing_name, st["b"]), P(inv.billing_address, st["n"]), P(f"GSTIN: {inv.customer_gstin or 'Unregistered'}", st["n"]), P(f"State code: {customer.billing_state_code or (inv.customer_gstin or '')[:2]}", st["n"])],
        qr_image(qr_data, 26),
    ]], colWidths=[70 * mm, 86 * mm, 30 * mm])
    meta.setStyle(GRID)
    story.append(meta)
    if inv.irn:
        story.append(P(f"IRN: {inv.irn}   Ack No: {inv.ack_no}   Ack Date: {fmt_date(inv.ack_date)}", st["s"]))
    rows = [[P(h, st["b"]) for h in ("#", "Description", "SAC", "Qty", "Rate", "Taxable value")]]
    for ln in lines:
        rows.append([P(ln.line_no, st["n"]), P(ln.description, st["n"]), P(ln.sac or inv.sac, st["n"]), P(f"{D(ln.quantity):g}", st["r"]), P(money(ln.rate), st["r"]), P(money(ln.amount), st["r"])])
    t = Table(rows, colWidths=[8 * mm, 100 * mm, 16 * mm, 14 * mm, 22 * mm, 26 * mm], repeatRows=1)
    t.setStyle(GRID)
    story.append(t)
    half = D(inv.gst_rate) / 2
    tot = [[P("Taxable value", st["n"]), P(money(inv.taxable_value), st["r"])]]
    if inv.charge_mechanism == "FCM":
        if inv.is_interstate:
            tot.append([P(f"IGST @ {D(inv.gst_rate):g}%", st["n"]), P(money(inv.igst), st["r"])])
        else:
            tot += [[P(f"CGST @ {half:g}%", st["n"]), P(money(inv.cgst), st["r"])], [P(f"SGST @ {half:g}%", st["n"]), P(money(inv.sgst), st["r"])]]
    if D(inv.round_off):
        tot.append([P("Round off", st["n"]), P(money(inv.round_off), st["r"])])
    tot.append([P("TOTAL", st["b"]), P(rs(inv.total), st["rb"])])
    notes = [P(f"Amount in words: {amount_in_words(inv.total)}", st["b"])]
    if inv.charge_mechanism == "RCM":
        notes.append(P(f"GST of {rs(inv.rcm_tax)} ({'IGST' if inv.is_interstate else 'CGST + SGST'} @ {D(inv.gst_rate):g}%) is payable by the recipient under reverse charge.", st["n"]))
    if treatment and treatment.invoice_note:
        notes.append(P(treatment.invoice_note, st["s"]))
    if inv.reason:
        notes.append(P(f"Reason: {inv.reason}", st["n"]))
    if inv.notes:
        notes.append(P(inv.notes, st["s"]))
    if bank:
        notes.append(P(f"Bank: {bank.bank_name}, A/c {bank.account_no}, IFSC {bank.ifsc or '-'}{', UPI ' + bank.upi_id if bank.upi_id else ''}", st["n"]))
    tt = Table([[notes, Table(tot, colWidths=[38 * mm, 30 * mm])]], colWidths=[118 * mm, 68 * mm])
    tt.setStyle(GRID)
    story.append(tt)
    hsn = Table([[P(h, st["b"]) for h in ("SAC", "Taxable", "CGST", "SGST", "IGST", "RCM tax")], [P(inv.sac, st["n"]), P(money(inv.taxable_value), st["r"]), P(money(inv.cgst), st["r"]), P(money(inv.sgst), st["r"]), P(money(inv.igst), st["r"]), P(money(inv.rcm_tax), st["r"])]], colWidths=[31 * mm] * 6)
    hsn.setStyle(GRID)
    story.append(Spacer(1, 2 * mm))
    story.append(hsn)
    if company.terms_invoice:
        story.append(P("Terms: " + company.terms_invoice, st["s"]))
    story.append(Spacer(1, 4 * mm))
    sig = Table([[P("Customer acknowledgement", st["c"]), P(f"For {company.trade_name or company.legal_name}\n\n\n{company.authorized_signatory or 'Authorised signatory'} {('(' + company.signatory_designation + ')') if company.signatory_designation else ''}", st["c"])]], colWidths=[93 * mm, 93 * mm], rowHeights=[22 * mm])
    sig.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story.append(KeepTogether(sig))
    if inv.status == "Cancelled":
        story.append(P(f"CANCELLED on {fmt_date(inv.cancelled_at)} – {inv.cancel_reason}", st["t"]))
    if inv.einvoice_status in ("Pending", "Failed"):
        story.append(P("Note: IRN not yet obtained from the Invoice Registration Portal.", st["s"]))
    doc.build(story)
    return buf.getvalue()


# ------------------------------------------------------------------ generic report


def _cell(v, typ):
    if v is None:
        return ""
    if typ == "money":
        return money(v)
    if typ == "date":
        return fmt_date(v)
    if typ == "number" and isinstance(v, (int, float, Decimal)):
        return f"{D(v):,.2f}".rstrip("0").rstrip(".") if D(v) % 1 else f"{int(D(v)):,}"
    return str(v)


def report_pdf(report: dict, company) -> bytes:
    cols = report["columns"]
    wide = len(cols) > 7
    st = styles(7.5 if wide else 8.5)
    buf = io.BytesIO()
    size = landscape(A4) if wide else A4
    doc = _doc(buf, size, 8)
    avail = size[0] - 16 * mm
    story = [P(company.trade_name or company.legal_name, st["h"]), P(report["title"], st["t"])]
    if report.get("subtitle"):
        story.append(P(report["subtitle"], st["c"]))
    story.append(Spacer(1, 3 * mm))
    head = [P(c["label"], st["b"]) for c in cols]
    body = [[P(_cell(r.get(c["key"]), c.get("type")), st["r"] if c.get("type") in ("money", "number") else st["n"]) for c in cols] for r in report["rows"]]
    data = [head] + body
    if report.get("totals"):
        data.append([P(_cell(report["totals"].get(c["key"]), c.get("type")) if c["key"] in report["totals"] else ("Total" if i == 0 else ""), st["rb"] if c.get("type") in ("money", "number") else st["b"]) for i, c in enumerate(cols)])
    weights = [c.get("w", 2 if c.get("type") in (None, "text") else 1.2) for c in cols]
    widths = [avail * w / sum(weights) for w in weights]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)
    if report.get("notes"):
        story.append(Spacer(1, 2 * mm))
        for n in report["notes"]:
            story.append(P(n, st["s"]))
    doc.build(story)
    return buf.getvalue()
