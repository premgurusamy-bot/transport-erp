"""Customisable print layouts for invoices, LRs (A4 + thermal) and reports/statements.

Stored in app_settings["layouts"] as overrides on top of DEFAULTS (deep merge), so new options added in
later versions get sensible defaults automatically. Edited in Settings → Document layouts.
"""
from __future__ import annotations

import copy
import re

from sqlalchemy.orm import Session

from ..core.deps import AppError
from ..models import AppSetting

KEY = "layouts"

COMMON = {
    "paper": "A4",                 # A4 / A5 / Letter / Legal
    "orientation": "portrait",     # portrait / landscape
    "margin_mm": 10,
    "font_size": 8.5,
    "accent_color": "#0f4c81",     # company name, header line
    "border_color": "#888888",
    "header_fill": "#e8eef5",      # table header background
    "logo_position": "left",       # left / right / center / none
    "logo_height_mm": 16,
    "show_legal_name": True,
    "show_address": True,
    "show_gstin": True,
    "show_pan": True,
    "show_cin": False,
    "show_contact": True,
    "header_lines": "",            # extra lines under the company details (e.g. "ISO 9001:2015 certified")
    "footer_text": "",             # printed at the bottom of every page
    "page_numbers": True,
    "show_signature_image": True,
    "show_stamp_image": True,
}

DEFAULTS: dict[str, dict] = {
    "invoice": {
        **COMMON,
        "titles": {"tax_invoice": "TAX INVOICE", "proforma": "PROFORMA INVOICE", "debit_note": "DEBIT NOTE", "credit_note": "CREDIT NOTE",
                   "bill_of_supply": "BILL OF SUPPLY", "advance_receipt": "RECEIPT VOUCHER (ADVANCE)"},
        "copies": ["ORIGINAL FOR RECIPIENT"],
        "columns": [
            {"key": "line_no", "label": "#", "show": True, "width": 4},
            {"key": "description", "label": "Description", "show": True, "width": 50},
            {"key": "sac", "label": "SAC", "show": True, "width": 9},
            {"key": "quantity", "label": "Qty", "show": True, "width": 7},
            {"key": "rate", "label": "Rate", "show": True, "width": 12},
            {"key": "amount", "label": "Taxable value", "show": True, "width": 14},
        ],
        "show_qr": True,
        "show_due_date": True,
        "show_po": True,
        "show_place_of_supply": True,
        "show_amount_in_words": True,
        "show_bank": True,
        "show_tax_summary": True,
        "show_terms": True,
        "show_customer_ack": True,
        "customer_ack_label": "Customer acknowledgement",
        "signatory_label": "Authorised signatory",
        "extra_note": "",
        "watermark_proforma": "PROFORMA",
        "watermark_cancelled": "CANCELLED",
    },
    "lr": {
        **COMMON,
        "title": "LORRY RECEIPT",
        "subtitle": "(Consignment Note)",
        "copies": ["Consignor Copy", "Consignee Copy", "Driver Copy", "Office Copy"],
        "columns": [
            {"key": "line_no", "label": "#", "show": True, "width": 4},
            {"key": "description", "label": "Description of goods", "show": True, "width": 38},
            {"key": "hsn", "label": "HSN", "show": True, "width": 9},
            {"key": "packages", "label": "Pkgs", "show": True, "width": 12},
            {"key": "quantity", "label": "Qty", "show": True, "width": 12},
            {"key": "weight", "label": "Weight (kg)", "show": True, "width": 12},
            {"key": "value", "label": "Value", "show": True, "width": 13},
        ],
        "show_qr": True,
        "show_driver": True,
        "show_distance": True,
        "show_documents": True,
        "show_delivery_points": True,
        "show_freight": True,
        "hide_freight_on_copies": [],   # e.g. ["Consignee Copy"] for "To Be Billed" customers
        "show_freight_basis": True,
        "show_declaration": True,
        "show_terms": True,
        "signature_labels": ["Signature of consignor", "Received in good condition – consignee signature & seal", "Authorised signatory"],
        "watermark_cancelled": "CANCELLED",
    },
    "thermal": {
        "width_mm": 80,                 # 80 or 58 mm roll
        "font_size": 7,
        "show_gstin": True,
        "show_items": True,
        "show_freight": True,
        "show_qr": True,
        "footer_text": "Consignee signature: ____________",
    },
    "report": {
        **COMMON,
        "orientation": "auto",          # auto (landscape for wide reports) / portrait / landscape
        "margin_mm": 8,
        "font_size": 8.5,
        "logo_position": "none",
        "show_gstin": False,
        "show_pan": False,
        "show_contact": False,
        "show_address": False,
        "zebra_rows": False,
    },
}

DOCS = {"invoice": "Invoices & notes", "lr": "LR (A4)", "thermal": "LR (thermal roll)", "report": "Reports & statements"}
PAPERS = ("A4", "A5", "Letter", "Legal")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _stored(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    return row.value if row and isinstance(row.value, dict) else {}


def get(db: Session, doc: str | None = None) -> dict:
    stored = _stored(db)
    all_ = {d: _merge(DEFAULTS[d], stored.get(d, {})) for d in DEFAULTS}
    all_["_assets"] = stored.get("_assets", {})
    return all_[doc] | {"_assets": all_["_assets"]} if doc else all_


def validate(doc: str, data: dict) -> dict:
    if doc not in DEFAULTS:
        raise AppError("Unknown document type", 404)
    base = DEFAULTS[doc]
    clean: dict = {}
    for k, v in (data or {}).items():
        if k not in base:
            continue  # unknown keys are ignored
        d = base[k]
        label = k.replace("_", " ")
        if isinstance(d, bool):
            clean[k] = bool(v)
        elif isinstance(d, (int, float)):
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise AppError(f"{label}: enter a number")
            limits = {"margin_mm": (3, 40), "font_size": (6, 14), "logo_height_mm": (6, 40), "width_mm": (48, 110)}.get(k, (0, 1000))
            if not limits[0] <= n <= limits[1]:
                raise AppError(f"{label}: must be between {limits[0]} and {limits[1]}")
            clean[k] = n
        elif k.endswith("_color"):
            if not COLOR.match(str(v)):
                raise AppError(f"{label}: use a colour like #0f4c81")
            clean[k] = str(v)
        elif k == "paper":
            if v not in PAPERS:
                raise AppError(f"Paper must be one of {', '.join(PAPERS)}")
            clean[k] = v
        elif k == "orientation":
            if v not in (("auto", "portrait", "landscape") if doc == "report" else ("portrait", "landscape")):
                raise AppError("Invalid orientation")
            clean[k] = v
        elif k == "logo_position":
            if v not in ("left", "right", "center", "none"):
                raise AppError("Logo position must be left, right, center or none")
            clean[k] = v
        elif k == "columns":
            keys = {c["key"] for c in d}
            cols, seen = [], set()
            for c in v or []:
                if c.get("key") not in keys or c["key"] in seen:
                    raise AppError(f"Unknown or repeated column {c.get('key')}")
                seen.add(c["key"])
                w = float(c.get("width") or 1)
                if not 1 <= w <= 100:
                    raise AppError("Column width must be between 1 and 100")
                cols.append({"key": c["key"], "label": str(c.get("label") or "")[:40], "show": bool(c.get("show", True)), "width": w})
            if not any(c["show"] and c["key"] == "description" for c in cols):
                raise AppError("The description column must be shown")
            cols += [{**c, "show": False} for c in d if c["key"] not in seen]  # omitted columns are kept, hidden
            clean[k] = cols
        elif k == "titles":
            clean[k] = {t: str((v or {}).get(t) or d[t])[:60] for t in d}
        elif isinstance(d, list):
            items = [str(x).strip()[:60] for x in (v or []) if str(x).strip()]
            if k == "copies" and not items:
                raise AppError("At least one copy is required")
            if k == "copies" and len(items) > 6:
                raise AppError("At most 6 copies")
            if k == "signature_labels":
                items = (items + d)[: len(d)]
            clean[k] = items
        else:
            clean[k] = str(v or "")[:1500]
    return clean


def save(db: Session, doc: str, data: dict, user_id: int | None) -> dict:
    clean = validate(doc, data)
    stored = copy.deepcopy(_stored(db))
    stored[doc] = clean
    _put(db, stored, user_id)
    return get(db, doc)


def reset(db: Session, doc: str, user_id: int | None) -> dict:
    stored = copy.deepcopy(_stored(db))
    stored.pop(doc, None)
    _put(db, stored, user_id)
    return get(db, doc)


def set_asset(db: Session, name: str, filename: str | None, user_id: int | None) -> None:
    stored = copy.deepcopy(_stored(db))
    assets = stored.setdefault("_assets", {})
    if filename:
        assets[name] = filename
    else:
        assets.pop(name, None)
    _put(db, stored, user_id)


def _put(db: Session, value: dict, user_id: int | None) -> None:
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value, updated_by=user_id))
    else:
        row.value = value
        row.updated_by = user_id
    db.flush()
