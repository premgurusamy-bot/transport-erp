"""PDF generation (ReportLab): LR (A4 + 80 mm thermal), GST invoice, generic report tables."""
from __future__ import annotations

import io
import os
from decimal import Decimal
from pathlib import Path

import qrcode
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, A5, landscape, legal, letter
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


def styles(size: float = 8.5, accent=None):
    _fonts()
    accent = accent or colors.HexColor("#0f4c81")
    return {
        "n": ParagraphStyle("n", fontName=_FONT, fontSize=size, leading=size * 1.25),
        "b": ParagraphStyle("b", fontName=_FONT_B, fontSize=size, leading=size * 1.25),
        "s": ParagraphStyle("s", fontName=_FONT, fontSize=size - 1.5, leading=(size - 1.5) * 1.25, textColor=colors.HexColor("#444444")),
        "h": ParagraphStyle("h", fontName=_FONT_B, fontSize=size + 6, leading=(size + 6) * 1.2, textColor=accent),
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
    return _image(company.logo_path, h_mm * 1.6, h_mm)


def _image(name: str | None, w_mm: float, h_mm: float):
    if name:
        p = get_settings().storage_dir / name
        if p.exists():
            try:
                return Image(str(p), width=w_mm * mm, height=h_mm * mm, kind="proportional")
            except Exception:  # noqa: BLE001
                return None
    return None


# ------------------------------------------------------------------ layout helpers

PAPER_SIZES = {"A4": A4, "A5": A5, "Letter": letter, "Legal": legal}


def _defaults(doc: str) -> dict:
    from .layouts import DEFAULTS

    return {**DEFAULTS[doc], "_assets": {}}


class Ctx:
    """Page geometry, colours and styles derived from a layout."""

    def __init__(self, L: dict, wide: bool = False):
        self.L = L
        size = PAPER_SIZES.get(L.get("paper", "A4"), A4)
        orient = L.get("orientation", "portrait")
        if orient == "landscape" or (orient == "auto" and wide):
            size = landscape(size)
        self.size = size
        self.margin = float(L.get("margin_mm", 10)) * mm
        self.avail = size[0] - 2 * self.margin
        self.accent = colors.HexColor(L.get("accent_color", "#0f4c81"))
        self.border = colors.HexColor(L.get("border_color", "#888888"))
        self.fill = colors.HexColor(L.get("header_fill", "#e8eef5"))
        self.st = styles(float(L.get("font_size", 8.5)), self.accent)
        self.grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, self.border), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)])
        self.head_grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.4, self.border), ("BACKGROUND", (0, 0), (-1, 0), self.fill), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)])
        self.watermark: str | None = None

    def w(self, *fractions) -> list:
        tot = sum(fractions)
        return [self.avail * f / tot for f in fractions]

    def doc(self, buf):
        return SimpleDocTemplate(buf, pagesize=self.size, leftMargin=self.margin, rightMargin=self.margin, topMargin=self.margin, bottomMargin=self.margin + (5 * mm if self.L.get("footer_text") or self.L.get("page_numbers") else 0))

    def on_page(self, canvas, doc):
        canvas.saveState()
        f = _FONT
        if self.watermark:
            canvas.setFont(_FONT_B, 70)
            canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.12))
            canvas.translate(self.size[0] / 2, self.size[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, -20, self.watermark)
            canvas.rotate(-35)
            canvas.translate(-self.size[0] / 2, -self.size[1] / 2)
        canvas.setFont(f, 7)
        canvas.setFillColor(colors.HexColor("#555555"))
        y = self.margin - 2 * mm + (5 * mm if self.L.get("footer_text") or self.L.get("page_numbers") else 0) - 4 * mm
        if self.L.get("footer_text"):
            canvas.drawCentredString(self.size[0] / 2, y, str(self.L["footer_text"])[:180])
        if self.L.get("page_numbers"):
            canvas.drawRightString(self.size[0] - self.margin, y, f"Page {doc.page}")
        canvas.restoreState()

    def build(self, buf, story):
        d = self.doc(buf)
        d.build(story, onFirstPage=self.on_page, onLaterPages=self.on_page)


def company_block(company, ctx: Ctx, title: str, copy_label: str | None = None) -> Table:
    L, st = ctx.L, ctx.st
    name = company.trade_name or company.legal_name
    lines = [P(name, st["h"])]
    if L.get("show_legal_name", True) and company.trade_name and company.legal_name and company.trade_name != company.legal_name:
        lines.append(P(company.legal_name, st["s"]))
    if L.get("show_address", True):
        addr = ", ".join(filter(None, [company.address, company.city, company.state, company.pincode]))
        if addr:
            lines.append(P(addr, st["n"]))
    ids = []
    if L.get("show_gstin", True):
        ids.append(f"GSTIN: {company.gstin}" if company.gstin else "GSTIN: (not configured)")
    if L.get("show_pan", True) and company.pan:
        ids.append(f"PAN: {company.pan}")
    if L.get("show_cin") and company.cin:
        ids.append(f"CIN: {company.cin}")
    if ids:
        lines.append(P(" | ".join(ids), st["n"]))
    if L.get("show_contact", True):
        contact = " | ".join(filter(None, [company.phone, company.email, company.website]))
        if contact:
            lines.append(P(contact, st["n"]))
    if L.get("header_lines"):
        lines.append(P(L["header_lines"], st["s"]))
    right = [P(title, st["t"])] + ([P(copy_label, st["rb"])] if copy_label else [])
    pos = L.get("logo_position", "left")
    lg = logo(company, float(L.get("logo_height_mm", 16))) if pos != "none" else None
    if lg and pos == "center":
        lines = [lg] + lines
        for x in lines[1:]:
            if isinstance(x, Paragraph):
                x.style = ParagraphStyle(x.style.name + "c", parent=x.style, alignment=TA_CENTER)
        data, widths = [[lines], [right]], [ctx.avail]
        t = Table(data, colWidths=widths)
    elif lg:
        lw = float(L.get("logo_height_mm", 16)) * 1.6 * mm + 4 * mm
        row = [lg, lines, right] if pos == "left" else [lines, lg, right]
        w = [lw, ctx.avail - lw - ctx.avail * 0.32, ctx.avail * 0.32] if pos == "left" else [ctx.avail - lw - ctx.avail * 0.32, lw, ctx.avail * 0.32]
        t = Table([row], colWidths=w)
    else:
        t = Table([[lines, right]], colWidths=ctx.w(68, 32))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, -1), (-1, -1), 1.2, ctx.accent)]))
    return t


def signature_cell(ctx: Ctx, company, label: str) -> list:
    """'For <company>' + optional signature / stamp images + signatory name."""
    L, assets = ctx.L, ctx.L.get("_assets") or {}
    parts = [P(f"For {company.trade_name or company.legal_name}", ctx.st["c"])]
    imgs = []
    if L.get("show_signature_image", True):
        im = _image(assets.get("signature"), 34, 12)
        if im:
            imgs.append(im)
    if L.get("show_stamp_image", True):
        im = _image(assets.get("stamp"), 18, 18)
        if im:
            imgs.append(im)
    if imgs:
        parts.append(Table([imgs], hAlign="CENTER"))
    else:
        parts.append(Spacer(1, 10 * mm))
    name = company.authorized_signatory or ""
    if company.signatory_designation:
        name += f" ({company.signatory_designation})"
    parts.append(P(f"{name}\n{label}" if name else label, ctx.st["c"]))
    return parts


def _cols(ctx: Ctx, defs: list[dict]) -> tuple[list[dict], list[float]]:
    shown = [c for c in defs if c.get("show", True)]
    return shown, ctx.w(*[float(c.get("width") or 1) for c in shown])


def verify_url(kind: str, number: str, token: str | None) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/public/verify/{kind}/{number.replace('/', '~')}?s={sign(kind + number + (token or ''))}"


# ------------------------------------------------------------------ LR


def lr_pdf(lr, company, customer, items, points, copies: list[str] | None, fmt: str = "A4", layout: dict | None = None, thermal_layout: dict | None = None) -> bytes:
    if fmt == "thermal":
        return lr_thermal(lr, company, items, thermal_layout or _defaults("thermal"))
    L = layout or _defaults("lr")
    ctx = Ctx(L)
    st = ctx.st
    buf = io.BytesIO()
    story = []
    url = verify_url("lr", lr.lr_no, lr.verify_token)
    if lr.status == "Cancelled" and L.get("watermark_cancelled"):
        ctx.watermark = L["watermark_cancelled"]
    for idx, copy_name in enumerate(copies or L.get("copies") or ["Original"]):
        if idx:
            story.append(PageBreak())
        story.append(company_block(company, ctx, "\n".join(filter(None, [L.get("title"), L.get("subtitle")])), copy_name.upper()))
        story.append(Spacer(1, 3 * mm))
        c1 = [P(f"LR No: {lr.lr_no}", st["b"]), P(f"Date: {fmt_date(lr.lr_date)}", st["n"]), P(f"{lr.load_type} {'• RETURN LR' if lr.is_return else ''}", st["n"])]
        c2 = [P(f"From: {lr.from_place}", st["b"]), P(f"To: {lr.to_place}", st["b"])] + ([P(f"Distance: {lr.distance_km or '-'} km", st["n"])] if L.get("show_distance", True) else [])
        c3 = [P(f"Vehicle: {lr.vehicle_no or '-'}", st["b"])] + ([P(f"Driver: {lr.driver_name or '-'} {lr.driver_mobile or ''}", st["n"]), P(f"DL: {lr.driver_licence or '-'}", st["s"])] if L.get("show_driver", True) else [])
        row = [c1, c2, c3] + ([qr_image(url, 20)] if L.get("show_qr", True) else [])
        hdr = Table([row], colWidths=ctx.w(28, 28, 27, 17) if L.get("show_qr", True) else ctx.w(34, 33, 33))
        hdr.setStyle(ctx.grid)
        story.append(hdr)
        parties = Table([[
            [P("CONSIGNOR", st["b"]), P(lr.consignor_name, st["n"]), P(lr.consignor_address, st["s"]), P(f"GSTIN: {lr.consignor_gstin or '-'}   Ph: {lr.consignor_phone or '-'}", st["s"])],
            [P("CONSIGNEE", st["b"]), P(lr.consignee_name, st["n"]), P(lr.consignee_address, st["s"]), P(f"GSTIN: {lr.consignee_gstin or '-'}   Ph: {lr.consignee_phone or '-'}", st["s"])],
        ], [
            [P("Loading at", st["b"]), P(lr.loading_address or lr.consignor_address, st["s"])],
            [P("Delivery at", st["b"]), P(lr.delivery_address or lr.consignee_address, st["s"])],
        ]], colWidths=ctx.w(1, 1))
        parties.setStyle(ctx.grid)
        story.append(parties)
        cols, widths = _cols(ctx, L.get("columns") or _defaults("lr")["columns"])
        right = {"weight", "value"}

        def cellv(key, it, i):
            return {"line_no": i, "description": it.description, "hsn": it.hsn or "", "packages": f"{it.packages} {it.package_type or ''}",
                    "quantity": f"{D(it.quantity):g} {it.uom}", "weight": f"{D(it.weight_kg):g}", "value": money(it.value)}[key]

        rows = [[P(c["label"], st["b"]) for c in cols]]
        for i, it in enumerate(items, 1):
            rows.append([P(cellv(c["key"], it, i), st["r"] if c["key"] in right else st["n"]) for c in cols])
        if not items:
            fallback = {"line_no": "", "description": "As per invoice", "hsn": "", "packages": lr.packages, "quantity": f"{D(lr.quantity):g}", "weight": f"{D(lr.weight_kg):g}", "value": money(lr.goods_value)}
            rows.append([P(fallback[c["key"]], st["r"] if c["key"] in right else st["n"]) for c in cols])
        tot = {"line_no": "", "description": f"Total   (Charged weight: {D(lr.charged_weight_kg):g} kg)", "hsn": "", "packages": lr.packages, "quantity": f"{D(lr.quantity):g}", "weight": f"{D(lr.weight_kg):g}", "value": money(lr.goods_value)}
        rows.append([P(tot[c["key"]], st["rb"] if c["key"] in right else st["b"]) for c in cols])
        gt = Table(rows, colWidths=widths, repeatRows=1)
        gt.setStyle(ctx.head_grid)
        story.append(gt)
        if L.get("show_documents", True):
            docs = [
                [P("Customer invoice", st["b"]), P(f"{lr.customer_invoice_no or '-'} {('dt ' + fmt_date(lr.customer_invoice_date)) if lr.customer_invoice_date else ''}", st["n"]), P("E-way bill", st["b"]), P(f"{lr.eway_bill_no or '-'} {('valid till ' + fmt_date(lr.eway_valid_until)) if lr.eway_valid_until else ''}", st["n"])],
                [P("Payment terms", st["b"]), P(lr.payment_terms, st["n"]), P("GST payable by", st["b"]), P(lr.gst_paid_by, st["n"])],
                [P("Risk", st["b"]), P(lr.risk, st["n"]), P("E-invoice ref", st["b"]), P(lr.einvoice_ref or "-", st["n"])],
            ]
            dtab = Table(docs, colWidths=ctx.w(16, 34, 16, 34))
            dtab.setStyle(ctx.grid)
            story.append(dtab)
        if points and L.get("show_delivery_points", True):
            pr = [[P("Delivery points", st["b"]), P("Consignee", st["b"]), P("Address", st["b"]), P("Pkgs", st["b"])]]
            for p in points:
                pr.append([P(p.sequence, st["n"]), P(p.consignee_name or "", st["n"]), P(p.address, st["s"]), P(p.packages, st["n"])])
            ptab = Table(pr, colWidths=ctx.w(13, 27, 49, 11))
            ptab.setStyle(ctx.head_grid)
            story.append(ptab)
        show_freight = L.get("show_freight", True) and copy_name not in (L.get("hide_freight_on_copies") or [])
        info = []
        if L.get("show_freight_basis", True):
            basis = (lr.freight_breakdown or {}).get("lines") or []
            info += [P("Freight basis", st["b"]), P("; ".join(b["label"] for b in basis[:3]) or lr.freight_basis or "-", st["s"]), Spacer(1, 2 * mm)]
        info += [P("Remarks", st["b"]), P(lr.remarks or "-", st["s"]), P(f"Customer authorisation: {lr.customer_authorization or '-'}", st["s"])]
        if show_freight:
            fr = [[P("Freight", st["b"]), P("Amount", st["rb"])]]
            for label, val in (("Basic freight", lr.basic_freight), ("Loading charges", lr.loading_charges), ("Unloading charges", lr.unloading_charges), ("Waiting charges", lr.waiting_charges), ("Detention charges", lr.detention_charges), ("Additional stop charges", lr.extra_stop_charges), (f"Other charges {lr.other_charges_note or ''}", lr.other_charges)):
                if D(val):
                    fr.append([P(label, st["n"]), P(money(val), st["r"])])
            fr += [[P("Total freight", st["b"]), P(rs(lr.total_freight), st["rb"])], [P("Advance", st["n"]), P(money(lr.advance_freight), st["r"])], [P("Balance", st["b"]), P(rs(lr.balance_freight), st["rb"])]]
            fw = ctx.w(46, 54)
            ftab = Table([[Table(fr, colWidths=[fw[0] * 0.62, fw[0] * 0.34]), info]], colWidths=fw)
        else:
            ftab = Table([[info]], colWidths=[ctx.avail])
        ftab.setStyle(ctx.grid)
        story.append(ftab)
        story.append(Spacer(1, 2 * mm))
        if L.get("show_declaration", True):
            decl = company.lr_print_declaration or (
                "Goods are carried at owner's risk unless otherwise agreed in writing. The consignor declares that the description, weight and value "
                "of goods are correct and that the goods are not prohibited or hazardous. The carrier is not responsible for leakage, breakage or "
                "damage due to improper packing. Delivery will be made only to the consignee or his authorised representative against this LR. "
                "Subject to Coimbatore jurisdiction."
            )
            story.append(P("Declaration: " + decl, st["s"]))
        if L.get("show_terms", True) and company.terms_lr:
            story.append(P("Terms: " + company.terms_lr, st["s"]))
        if lr.status == "Cancelled":
            story.append(P(f"*** CANCELLED on {fmt_date(lr.cancelled_at)}: {lr.cancel_reason} ***", st["t"]))
        if lr.revision:
            story.append(P(f"Revision {lr.revision} (amended – see audit trail)", st["s"]))
        labels = (L.get("signature_labels") or []) + _defaults("lr")["signature_labels"]
        sig = Table([[[Spacer(1, 18 * mm), P(labels[0], st["c"])], [Spacer(1, 18 * mm), P(labels[1], st["c"])], signature_cell(ctx, company, labels[2])]], colWidths=ctx.w(1, 1, 1))
        sig.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, ctx.border), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        story.append(Spacer(1, 2 * mm))
        story.append(KeepTogether(sig))
        if L.get("show_qr", True):
            story.append(P("Verify this LR: scan the QR code.", st["s"]))
    ctx.build(buf, story)
    return buf.getvalue()


def lr_thermal(lr, company, items, L: dict | None = None) -> bytes:
    L = L or _defaults("thermal")
    st = styles(float(L.get("font_size", 7)))
    buf = io.BytesIO()
    width = float(L.get("width_mm", 80)) * mm
    height = max(140, 110 + 8 * len(items)) * mm
    doc = SimpleDocTemplate(buf, pagesize=(width, height), leftMargin=3 * mm, rightMargin=3 * mm, topMargin=3 * mm, bottomMargin=3 * mm)
    s = [P(company.trade_name or company.legal_name, st["t"]), P(", ".join(filter(None, [company.city, company.phone])), st["c"])]
    if L.get("show_gstin", True):
        s.append(P(f"GSTIN: {company.gstin or '-'}", st["c"]))
    s += [P("LORRY RECEIPT", st["t"]), P(f"LR: {lr.lr_no}", st["b"]), P(f"Date: {fmt_date(lr.lr_date)}   {lr.load_type}", st["n"]),
          P(f"{lr.from_place} → {lr.to_place}", st["b"]), P(f"Vehicle: {lr.vehicle_no or '-'}  Driver: {lr.driver_name or '-'}", st["n"]),
          P(f"Consignor: {lr.consignor_name}", st["n"]), P(f"Consignee: {lr.consignee_name}", st["n"]), Spacer(1, 2 * mm)]
    if L.get("show_items", True):
        for it in items:
            s.append(P(f"• {it.description} – {it.packages} pkg, {D(it.weight_kg):g} kg", st["n"]))
    s += [Spacer(1, 2 * mm), P(f"Pkgs {lr.packages}  Wt {D(lr.weight_kg):g} kg", st["n"]), P(f"E-way bill: {lr.eway_bill_no or '-'}", st["n"])]
    if L.get("show_freight", True):
        s += [P(f"Freight: {rs(lr.total_freight)}  Adv: {money(lr.advance_freight)}  Bal: {money(lr.balance_freight)}", st["b"]), P(f"Terms: {lr.payment_terms}", st["n"])]
    if L.get("show_qr", True):
        s.append(qr_image(verify_url("lr", lr.lr_no, lr.verify_token), min(28, float(L.get("width_mm", 80)) * 0.4)))
    if L.get("footer_text"):
        s.append(P(L["footer_text"], st["n"]))
    doc.build(s)
    return buf.getvalue()


# ------------------------------------------------------------------ invoice

DOC_TITLES = {"tax_invoice": "TAX INVOICE", "proforma": "PROFORMA INVOICE", "debit_note": "DEBIT NOTE", "credit_note": "CREDIT NOTE", "bill_of_supply": "BILL OF SUPPLY", "advance_receipt": "RECEIPT VOUCHER (ADVANCE)"}


def invoice_pdf(inv, company, customer, lines, bank, treatment, ref_invoice=None, layout: dict | None = None) -> bytes:
    from ..core.validators import STATE_CODES

    L = layout or _defaults("invoice")
    ctx = Ctx(L)
    st = ctx.st
    buf = io.BytesIO()
    title = (L.get("titles") or {}).get(inv.doc_type) or DOC_TITLES.get(inv.doc_type, "INVOICE")
    if inv.status == "Cancelled" and L.get("watermark_cancelled"):
        ctx.watermark = L["watermark_cancelled"]
    elif inv.doc_type == "proforma" and L.get("watermark_proforma"):
        ctx.watermark = L["watermark_proforma"]
    story = []
    for idx, copy_name in enumerate(L.get("copies") or ["ORIGINAL"]):
        if idx:
            story.append(PageBreak())
        story += _invoice_page(inv, company, customer, lines, bank, treatment, ref_invoice, ctx, title + ("\n(CANCELLED)" if inv.status == "Cancelled" else ""), copy_name, STATE_CODES)
    ctx.build(buf, story)
    return buf.getvalue()


def _invoice_page(inv, company, customer, lines, bank, treatment, ref_invoice, ctx: Ctx, title, copy_name, STATE_CODES) -> list:
    L, st = ctx.L, ctx.st
    story = [company_block(company, ctx, title, copy_name.upper() if copy_name else None)]
    left = [P(f"{title.split(chr(10))[0].title()} No: {inv.invoice_no}", st["b"]), P(f"Date: {fmt_date(inv.invoice_date)}", st["n"])]
    if L.get("show_due_date", True) and inv.due_date:
        left.append(P(f"Due date: {fmt_date(inv.due_date)}", st["n"]))
    if L.get("show_place_of_supply", True):
        left.append(P(f"Place of supply: {inv.place_of_supply} – {STATE_CODES.get(inv.place_of_supply, '')}", st["n"]))
    left.append(P(f"Reverse charge: {'Yes' if inv.charge_mechanism == 'RCM' else 'No'}", st["b"]))
    if ref_invoice:
        left.append(P(f"Ref. invoice: {ref_invoice.invoice_no} dt {fmt_date(ref_invoice.invoice_date)}", st["n"]))
    elif inv.period_from:
        left.append(P(f"Period: {fmt_date(inv.period_from)} – {fmt_date(inv.period_to)}", st["n"]))
    if L.get("show_po", True) and inv.po_number:
        left.append(P(f"PO / Vendor code: {inv.po_number}", st["n"]))
    bill = [P("Bill to", st["b"]), P(inv.billing_name, st["b"]), P(inv.billing_address, st["n"]), P(f"GSTIN: {inv.customer_gstin or 'Unregistered'}", st["n"]), P(f"State code: {customer.billing_state_code or (inv.customer_gstin or '')[:2]}", st["n"])]
    if L.get("show_qr", True):
        qr_data = inv.signed_qr if inv.signed_qr else verify_url("inv", inv.invoice_no, inv.verify_token)
        meta = Table([[left, bill, qr_image(qr_data, 26)]], colWidths=ctx.w(38, 46, 16))
    else:
        meta = Table([[left, bill]], colWidths=ctx.w(45, 55))
    meta.setStyle(ctx.grid)
    story.append(meta)
    if inv.irn:
        story.append(P(f"IRN: {inv.irn}   Ack No: {inv.ack_no}   Ack Date: {fmt_date(inv.ack_date)}", st["s"]))
    cols, widths = _cols(ctx, L.get("columns") or _defaults("invoice")["columns"])
    right = {"quantity", "rate", "amount"}
    rows = [[P(c["label"], st["b"]) for c in cols]]
    for ln in lines:
        v = {"line_no": ln.line_no, "description": ln.description, "sac": ln.sac or inv.sac, "quantity": f"{D(ln.quantity):g}", "rate": money(ln.rate), "amount": money(ln.amount)}
        rows.append([P(v[c["key"]], st["r"] if c["key"] in right else st["n"]) for c in cols])
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(ctx.head_grid)
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
    notes = []
    if L.get("show_amount_in_words", True):
        notes.append(P(f"Amount in words: {amount_in_words(inv.total)}", st["b"]))
    if inv.charge_mechanism == "RCM":  # legally required wording – always printed
        notes.append(P(f"GST of {rs(inv.rcm_tax)} ({'IGST' if inv.is_interstate else 'CGST + SGST'} @ {D(inv.gst_rate):g}%) is payable by the recipient under reverse charge.", st["n"]))
    if treatment and treatment.invoice_note:
        notes.append(P(treatment.invoice_note, st["s"]))
    if inv.reason:
        notes.append(P(f"Reason: {inv.reason}", st["n"]))
    if inv.notes:
        notes.append(P(inv.notes, st["s"]))
    if L.get("show_bank", True) and bank:
        notes.append(P(f"Bank: {bank.bank_name}, A/c {bank.account_no}, IFSC {bank.ifsc or '-'}{', UPI ' + bank.upi_id if bank.upi_id else ''}", st["n"]))
    if L.get("extra_note"):
        notes.append(P(L["extra_note"], st["s"]))
    tw = ctx.w(63, 37)
    tt = Table([[notes or "", Table(tot, colWidths=[tw[1] * 0.56, tw[1] * 0.42])]], colWidths=tw)
    tt.setStyle(ctx.grid)
    story.append(tt)
    if L.get("show_tax_summary", True):
        hsn = Table([[P(h, st["b"]) for h in ("SAC", "Taxable", "CGST", "SGST", "IGST", "RCM tax")], [P(inv.sac, st["n"]), P(money(inv.taxable_value), st["r"]), P(money(inv.cgst), st["r"]), P(money(inv.sgst), st["r"]), P(money(inv.igst), st["r"]), P(money(inv.rcm_tax), st["r"])]], colWidths=ctx.w(1, 1, 1, 1, 1, 1))
        hsn.setStyle(ctx.head_grid)
        story.append(Spacer(1, 2 * mm))
        story.append(hsn)
    if L.get("show_terms", True) and company.terms_invoice:
        story.append(P("Terms: " + company.terms_invoice, st["s"]))
    story.append(Spacer(1, 4 * mm))
    sign_cell = signature_cell(ctx, company, L.get("signatory_label") or "Authorised signatory")
    if L.get("show_customer_ack", True):
        sig = Table([[[Spacer(1, 18 * mm), P(L.get("customer_ack_label") or "Customer acknowledgement", st["c"])], sign_cell]], colWidths=ctx.w(1, 1))
    else:
        sig = Table([["", sign_cell]], colWidths=ctx.w(1, 1))
    sig.setStyle(TableStyle([("GRID", (0, 0), (-1, -1) if L.get("show_customer_ack", True) else (1, 0), 0.4, ctx.border), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story.append(KeepTogether(sig))
    if inv.status == "Cancelled":
        story.append(P(f"CANCELLED on {fmt_date(inv.cancelled_at)} – {inv.cancel_reason}", st["t"]))
    if inv.einvoice_status in ("Pending", "Failed"):
        story.append(P("Note: IRN not yet obtained from the Invoice Registration Portal.", st["s"]))
    return story


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


def report_pdf(report: dict, company, layout: dict | None = None) -> bytes:
    L = layout or _defaults("report")
    cols = report["columns"]
    ctx = Ctx(L, wide=len(cols) > 7)
    st = styles(float(L.get("font_size", 8.5)) - (1 if len(cols) > 7 else 0), ctx.accent)
    ctx.st = st
    buf = io.BytesIO()
    if L.get("logo_position", "none") != "none" or L.get("show_address") or L.get("show_gstin") or L.get("show_contact"):
        story = [company_block(company, ctx, report["title"])]
    else:
        story = [P(company.trade_name or company.legal_name, st["h"]), P(report["title"], st["t"])]
        if L.get("header_lines"):
            story.append(P(L["header_lines"], st["c"]))
    if report.get("subtitle"):
        story.append(P(report["subtitle"], st["c"]))
    story.append(Spacer(1, 3 * mm))
    head = [P(c["label"], st["b"]) for c in cols]
    body = [[P(_cell(r.get(c["key"]), c.get("type")), st["r"] if c.get("type") in ("money", "number") else st["n"]) for c in cols] for r in report["rows"]]
    data = [head] + body
    if report.get("totals"):
        data.append([P(_cell(report["totals"].get(c["key"]), c.get("type")) if c["key"] in report["totals"] else ("Total" if i == 0 else ""), st["rb"] if c.get("type") in ("money", "number") else st["b"]) for i, c in enumerate(cols)])
    weights = [c.get("w", 2 if c.get("type") in (None, "text") else 1.2) for c in cols]
    t = Table(data, colWidths=ctx.w(*weights), repeatRows=1)
    style = [("GRID", (0, 0), (-1, -1), 0.3, ctx.border), ("BACKGROUND", (0, 0), (-1, 0), ctx.fill), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    if L.get("zebra_rows"):
        style += [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f6f8fa")) for i in range(2, len(data), 2)]
    t.setStyle(TableStyle(style))
    story.append(t)
    if report.get("notes"):
        story.append(Spacer(1, 2 * mm))
        for n in report["notes"]:
            story.append(P(n, st["s"]))
    ctx.build(buf, story)
    return buf.getvalue()
