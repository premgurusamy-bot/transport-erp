"""Excel / CSV import with column mapping.

Workflow: upload → pick sheet & header row → map *your* column headings to ERP fields (suggested
automatically, saved as reusable templates) → validate (a full dry run inside a transaction that is rolled
back) → import (one transaction; nothing is saved if any row fails unless "skip invalid rows" is chosen).

Masters go through exactly the same validation, hooks (ledger creation, etc.) and audit trail as manual entry.
"""
from __future__ import annotations

import io
import json
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.audit import log
from ..core.deps import AppError
from ..core.money import D, r2
from ..models import AccountGroup, AppSetting, Ledger

MAX_ROWS = 20000

# extra words people commonly use as headings, per ERP field
ALIASES = {
    "registration_no": ["vehicle no", "vehicle number", "reg no", "regn no", "lorry no", "truck no", "vehicle"],
    "name": ["party name", "customer name", "vendor name", "supplier name", "driver name", "employee name", "item name", "description"],
    "code": ["party code", "customer code", "vendor code", "id", "emp code", "driver code"],
    "gstin": ["gst no", "gst number", "gstin no", "gst"],
    "mobile": ["phone", "mobile no", "cell", "contact no", "phone no", "whatsapp"],
    "billing_address": ["address", "billing address"],
    "insurance_expiry": ["insurance", "insurance due", "insurance valid", "insurance date"],
    "fc_expiry": ["fc", "fc due", "fitness", "fc date", "fitness expiry"],
    "puc_expiry": ["pollution", "puc", "emission", "pollution due"],
    "national_permit_expiry": ["np", "national permit", "np due", "permit"],
    "state_permit_expiry": ["state permit", "sp due"],
    "road_tax_expiry": ["tax", "road tax", "tax due", "quarterly tax"],
    "licence_no": ["dl no", "license no", "licence", "driving licence", "dl number"],
    "licence_expiry": ["dl expiry", "license expiry", "dl valid", "licence valid"],
    "credit_limit": ["limit"],
    "credit_days": ["credit period", "days"],
    "chassis_no": ["chassis"],
    "engine_no": ["engine"],
    "vehicle_type": ["type", "body type"],
    "opening_balance": ["opening", "op balance", "opening bal", "balance", "amount"],
    "ledger": ["ledger name", "account", "account name", "particulars", "ledger"],
    "debit": ["dr", "debit amount", "dr amount"],
    "credit": ["cr", "credit amount", "cr amount"],
    "voucher_ref": ["voucher no", "vch no", "voucher number", "ref", "reference", "bill no"],
    "voucher_date": ["date", "vch date", "voucher date", "txn date"],
    "narration": ["remarks", "description", "particulars details"],
    "dr_cr": ["dr/cr", "type", "drcr"],
    "group": ["under", "group", "parent"],
}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


# ------------------------------------------------------------------ target definitions

def _crud_targets() -> dict:
    from ..api.crud import REGISTRY

    keys = {"customers": "code", "vehicles": "registration_no", "drivers": "code", "vendors": "code", "routes": "code", "toll_plazas": "name",
            "fuel_stations": "name", "items": "sku", "warehouses": "code", "employees": "code", "branches": "code", "departments": "name", "rate_contracts": None,
            "tyres": "serial_no", "ledgers": "name"}
    out = {}
    for name, match in keys.items():
        res = REGISTRY.get(name)
        if not res:
            continue
        fields = []
        for col in res.model.__table__.columns:
            info = col.info or {}
            if not info.get("label") or info.get("readonly") or info.get("hidden") or col.name in ("id",):
                continue
            from ..api.crud import _ftype

            fields.append({"key": col.name, "label": info["label"], "required": bool(info.get("required")) and col.default is None, "type": _ftype(col),
                           "options": [o for o in (info.get("options") or []) if o], "ref": info.get("ref"), "secret": bool(info.get("secret")), "validator": info.get("validator")})
        out[name] = {"title": res.title or name.title(), "perm": res.write_perm or f"{res.perm}:write", "match": match, "fields": fields, "kind": "crud"}
    return out


SPECIAL = {
    "opening_balances": {
        "title": "Opening balances (ledgers)", "perm": "accounts:cancel", "match": "ledger", "kind": "opening",
        "fields": [
            {"key": "ledger", "label": "Ledger / party name", "required": True, "type": "string"},
            {"key": "opening_balance", "label": "Amount (or signed: + Dr, − Cr)", "required": True, "type": "number"},
            {"key": "dr_cr", "label": "Dr / Cr (blank = sign of amount)", "required": False, "type": "string"},
            {"key": "debit", "label": "Debit column (instead of amount)", "required": False, "type": "number"},
            {"key": "credit", "label": "Credit column (instead of amount)", "required": False, "type": "number"},
            {"key": "group", "label": "Group for new ledgers (e.g. Sundry Debtors)", "required": False, "type": "string"},
        ],
    },
    "vouchers": {
        "title": "Accounting vouchers (journal entries)", "perm": "accounts:write", "match": None, "kind": "vouchers",
        "fields": [
            {"key": "voucher_date", "label": "Date", "required": True, "type": "date"},
            {"key": "voucher_ref", "label": "Voucher no / reference (rows with the same value form one voucher)", "required": True, "type": "string"},
            {"key": "ledger", "label": "Ledger name", "required": True, "type": "string"},
            {"key": "debit", "label": "Debit", "required": False, "type": "number"},
            {"key": "credit", "label": "Credit", "required": False, "type": "number"},
            {"key": "amount", "label": "Amount (with Dr/Cr column)", "required": False, "type": "number"},
            {"key": "dr_cr", "label": "Dr / Cr", "required": False, "type": "string"},
            {"key": "narration", "label": "Narration", "required": False, "type": "string"},
        ],
    },
}


def targets() -> dict:
    return {**_crud_targets(), **SPECIAL}


# ------------------------------------------------------------------ file handling

def _dir() -> Path:
    p = get_settings().storage_dir / "imports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.hour == v.minute == v.second == 0 else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_upload(filename: str, content: bytes) -> dict:
    name = filename.lower()
    sheets: dict[str, list[list[str]]] = {}
    if name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except Exception as exc:  # noqa: BLE001
            raise AppError(f"Cannot read the Excel file: {exc}")
        for ws in wb.worksheets:
            rows = []
            for r in ws.iter_rows(values_only=True):
                rows.append([_cell(v) for v in r])
                if len(rows) > MAX_ROWS + 50:
                    raise AppError(f"Sheet '{ws.title}' has more than {MAX_ROWS} rows – split the file")
            while rows and not any(rows[-1]):
                rows.pop()
            sheets[ws.title] = rows
    elif name.endswith((".csv", ".txt")):
        import csv

        text = content.decode("utf-8-sig", errors="replace")
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t|") if text.strip() else csv.excel
        sheets["CSV"] = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]
    elif name.endswith(".xls"):
        raise AppError("Old .xls files: open in Excel and 'Save As' .xlsx, then upload")
    else:
        raise AppError("Upload an Excel (.xlsx) or CSV file")
    if not any(any(r) for rows in sheets.values() for r in rows):
        raise AppError("The file is empty")
    fid = secrets.token_hex(12)
    (_dir() / f"{fid}.json").write_text(json.dumps({"filename": filename, "sheets": sheets}))
    return {"file_id": fid, "filename": filename, "sheets": [{"name": n, "rows": len(r), "header_row": guess_header_row(r)} for n, r in sheets.items()]}


def guess_header_row(rows: list[list[str]]) -> int:
    """First row (1-based) in the top 15 with at least 2 text cells and mostly non-numeric values."""
    for i, r in enumerate(rows[:15]):
        cells = [c for c in r if c]
        if len(cells) >= 2 and sum(1 for c in cells if not re.fullmatch(r"[\d.,/\- :]+", c)) >= max(2, len(cells) * 0.6):
            return i + 1
    return 1


def load(file_id: str, sheet: str | None, header_row: int) -> tuple[list[str], list[dict]]:
    if not re.fullmatch(r"[0-9a-f]{24}", file_id or ""):
        raise AppError("Invalid file reference")
    path = _dir() / f"{file_id}.json"
    if not path.exists():
        raise AppError("Uploaded file expired – upload it again", 404)
    data = json.loads(path.read_text())
    sheets = data["sheets"]
    rows = sheets.get(sheet) if sheet else next(iter(sheets.values()))
    if rows is None:
        raise AppError("Sheet not found")
    hr = max(1, int(header_row or 1))
    header = rows[hr - 1] if len(rows) >= hr else []
    names, seen = [], {}
    for i, h in enumerate(header):
        h = h or f"Column {i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        names.append(h)
    out = []
    for idx, r in enumerate(rows[hr:], start=hr + 1):
        if not any(r):
            continue
        out.append({"_row": idx, **{names[i]: (r[i] if i < len(r) else "") for i in range(len(names))}})
    return names, out


def preview(file_id: str, sheet: str | None, header_row: int) -> dict:
    headers, rows = load(file_id, sheet, header_row)
    return {"headers": headers, "rows": rows[:15], "total": len(rows)}


def suggest(target: str, headers: list[str]) -> dict:
    t = targets().get(target)
    if not t:
        raise AppError("Unknown import type", 404)
    mapping, used = {}, set()
    scored = []
    for f in t["fields"]:
        cands = [_norm(f["label"]), _norm(f["key"])] + [_norm(a) for a in ALIASES.get(f["key"], [])]
        for h in headers:
            nh = _norm(h)
            if not nh:
                continue
            score = max((1.0 if nh == c else SequenceMatcher(None, nh, c).ratio()) for c in cands if c)
            if nh in cands:
                score = 1.0
            scored.append((score, f["key"], h))
    for score, key, h in sorted(scored, key=lambda x: -x[0]):
        if score < 0.72 or key in mapping or h in used:
            continue
        mapping[key] = h
        used.add(h)
    return mapping


# ------------------------------------------------------------------ value conversion

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S")


def to_date(v: str) -> date:
    s = str(v).strip()
    if re.fullmatch(r"\d{5}(\.0+)?", s):  # Excel serial number stored as text
        from datetime import timedelta

        return date(1899, 12, 30) + timedelta(days=int(float(s)))
    if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", s):
        s = s[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{v}' is not a date (use DD-MM-YYYY)")


def to_number(v: str) -> Decimal:
    s = str(v).strip().replace("₹", "").replace("Rs.", "").replace("Rs", "").replace(",", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if s.lower().endswith(("dr", "cr")):
        s = s[:-2]
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"'{v}' is not a number")
    return -d if neg else d


def to_bool(v: str) -> bool:
    s = str(v).strip().lower()
    if s in ("1", "y", "yes", "true", "t", "active", "✓", "x"):
        return True
    if s in ("0", "n", "no", "false", "f", "inactive", ""):
        return False
    raise ValueError(f"'{v}' is not yes/no")


class RefCache:
    def __init__(self, db: Session):
        self.db, self.cache = db, {}

    def resolve(self, ref: str, value: str) -> int:
        from ..api.crud import REGISTRY

        if ref not in self.cache:
            res = REGISTRY.get(ref)
            model = res.model if res else (AccountGroup if ref == "account_groups" else None)
            if model is None:
                raise ValueError(f"cannot look up {ref}")
            lookup = {}
            cols = {c.name for c in model.__table__.columns}
            for o in self.db.execute(select(model)).scalars():
                for f in ("name", "code", "registration_no", "label", "sku", "contract_no", "card_no", "serial_no", "ewb_no", "booking_no"):
                    if f in cols and getattr(o, f):
                        lookup.setdefault(_norm(getattr(o, f)), o.id)
                if res and res.label in cols and getattr(o, res.label):
                    lookup.setdefault(_norm(getattr(o, res.label)), o.id)
            self.cache[ref] = lookup
        if ref == "account_groups" and any(sep in str(value) for sep in ("›", ">", "/")):
            from . import accounting as acc

            try:  # a group path such as "Indirect Expenses › Salaries" – missing groups are created
                return acc.resolve_group_path(self.db, str(value))
            except AppError as exc:
                raise ValueError(exc.detail) from exc
        v = _norm(value)
        if v.isdigit() and int(v) in self.cache[ref].values() and v not in self.cache[ref]:
            return int(v)
        if v not in self.cache[ref]:
            raise ValueError(f"'{value}' not found in {ref.replace('_', ' ')}")
        return self.cache[ref][v]


def convert(field: dict, raw: str, refs: RefCache):
    if raw is None or str(raw).strip() == "":
        return None
    t = field.get("type")
    if field.get("ref"):
        return refs.resolve(field["ref"], raw)
    if field.get("options"):
        for o in field["options"]:
            if _norm(o) == _norm(raw):
                return o
        raise ValueError(f"'{raw}' must be one of: {', '.join(field['options'])}")
    if t == "date":
        return to_date(raw).isoformat()
    if t == "datetime":
        return to_date(raw).isoformat() + "T00:00:00"
    if t in ("number", "int"):
        n = to_number(raw)
        return int(n) if t == "int" else str(n)
    if t == "bool":
        return to_bool(raw)
    return str(raw).strip()


# ------------------------------------------------------------------ run


def run(db: Session, user, req: dict, commit: bool) -> dict:
    target = req.get("target")
    t = targets().get(target)
    if not t:
        raise AppError("Unknown import type", 404)
    if not user.can(t["perm"]):
        raise AppError(f"You do not have permission to import {t['title']} ({t['perm']})", 403)
    mapping = {k: v for k, v in (req.get("mapping") or {}).items() if v}
    constants = {k: v for k, v in (req.get("constants") or {}).items() if v not in (None, "")}
    fields = {f["key"]: f for f in t["fields"]}
    for k in list(mapping) + list(constants):
        if k not in fields:
            raise AppError(f"Unknown field {k}")
    headers, rows = load(req.get("file_id"), req.get("sheet"), int(req.get("header_row") or 1))
    for k, h in mapping.items():
        if h not in headers:
            raise AppError(f"Column '{h}' is not in the file")
    missing = [fields[k]["label"] for k, f in fields.items() if f["required"] and k not in mapping and k not in constants]
    mode_ = req.get("mode") or "create"
    if t["kind"] == "crud" and missing and mode_ == "create":
        raise AppError("Map the required fields: " + ", ".join(missing))
    mode = req.get("mode") or "create"  # create / update / upsert
    if mode not in ("create", "update", "upsert"):
        raise AppError("Mode must be create, update or upsert")
    refs = RefCache(db)
    results = []
    if t["kind"] == "crud":
        results = _run_crud(db, user, target, t, fields, mapping, constants, rows, mode, refs)
    elif t["kind"] == "opening":
        results = _run_opening(db, user, fields, mapping, constants, rows)
    else:
        results = _run_vouchers(db, user, fields, mapping, constants, rows)
    errors = [r for r in results if r["status"] == "error"]
    summary = {"total": len(results), "created": sum(r["status"] == "created" for r in results), "updated": sum(r["status"] == "updated" for r in results),
               "skipped": sum(r["status"] == "skipped" for r in results), "errors": len(errors)}
    can_commit = commit and (not errors or req.get("skip_invalid"))
    if can_commit:
        log(db, user, "import", target, None, None, {"file": req.get("file_id"), **summary, "mode": mode})
        db.commit()
    else:
        db.rollback()
    return {"committed": bool(can_commit), "summary": summary, "results": results[:2000],
            "message": None if can_commit or not commit else "Nothing was imported because some rows have errors. Fix them in Excel, or tick 'skip rows with errors'."}


def _row_values(row: dict, fields: dict, mapping: dict, constants: dict, refs: RefCache) -> tuple[dict, list[str]]:
    vals, errs = {}, []
    for k, h in mapping.items():
        try:
            v = convert(fields[k], row.get(h, ""), refs)
            if v is not None:
                vals[k] = v
        except ValueError as exc:
            errs.append(f"{fields[k]['label']}: {exc}")
    for k, v in constants.items():
        if k not in vals:
            try:
                vals[k] = convert(fields[k], v, refs)
            except ValueError as exc:
                errs.append(f"{fields[k]['label']}: {exc}")
    return vals, errs


def _run_crud(db, user, target, t, fields, mapping, constants, rows, mode, refs) -> list[dict]:
    from ..api.crud import REGISTRY, create_record, update_record

    res = REGISTRY[target]
    match = t["match"]
    if mode != "create" and (not match or match not in mapping):
        raise AppError(f"To update existing records, map the '{fields[match]['label'] if match else 'key'}' column")
    out = []
    seen_keys = set()
    for row in rows:
        vals, errs = _row_values(row, fields, mapping, constants, refs)
        key = vals.get(match) if match else None
        if key is not None and fields.get(match, {}).get("validator"):
            from ..core.validators import normalize

            key = normalize(fields[match]["validator"], key)
            vals[match] = key
        label = str(key or vals.get("name") or vals.get(res.label) or "")
        if errs:
            out.append({"row": row["_row"], "key": label, "status": "error", "message": "; ".join(errs)})
            continue
        if key is not None:
            nk = _norm(key)
            if nk in seen_keys:
                out.append({"row": row["_row"], "key": label, "status": "error", "message": f"Repeated in the file: {key}"})
                continue
            seen_keys.add(nk)
        existing = None
        if match and key is not None:
            col = getattr(res.model, match)
            existing = db.execute(select(res.model).where(func.lower(col) == str(key).lower())).scalars().first()
        try:
            with db.begin_nested():
                if existing is not None:
                    if mode == "create":
                        out.append({"row": row["_row"], "key": label, "status": "skipped", "message": "Already exists (choose 'update' or 'create & update' to change it)"})
                        continue
                    update_record(db, res, target, existing, vals, user, reason="Excel import")
                    out.append({"row": row["_row"], "key": label, "status": "updated", "message": ""})
                else:
                    if mode == "update":
                        out.append({"row": row["_row"], "key": label, "status": "skipped", "message": "Not found – not created in 'update only' mode"})
                        continue
                    create_record(db, res, target, vals, user)
                    out.append({"row": row["_row"], "key": label, "status": "created", "message": ""})
        except AppError as exc:
            out.append({"row": row["_row"], "key": label, "status": "error", "message": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001
            out.append({"row": row["_row"], "key": label, "status": "error", "message": str(exc)[:300]})
    return out


def _signed(vals: dict) -> Decimal:
    if vals.get("debit") or vals.get("credit"):
        return D(vals.get("debit")) - D(vals.get("credit"))
    amt = D(vals.get("opening_balance") if "opening_balance" in vals else vals.get("amount"))
    drcr = _norm(vals.get("dr_cr"))
    if drcr in ("cr", "credit", "c"):
        return -abs(amt)
    if drcr in ("dr", "debit", "d"):
        return abs(amt)
    return amt


def _run_opening(db, user, fields, mapping, constants, rows) -> list[dict]:
    from .accounting import group_id

    if "ledger" not in mapping:
        raise AppError("Map the ledger name column")
    if not ({"opening_balance", "debit", "credit"} & set(mapping)):
        raise AppError("Map the amount column (or the debit and credit columns)")
    groups = {_norm(g.name): g.id for g in db.query(AccountGroup)}
    out, total = [], Decimal(0)
    for row in rows:
        vals, errs = _row_values(row, fields, mapping, constants, RefCache(db))
        name = vals.get("ledger")
        if errs or not name:
            out.append({"row": row["_row"], "key": name or "", "status": "error", "message": "; ".join(errs) or "Ledger name is empty"})
            continue
        led = db.query(Ledger).filter(func.lower(Ledger.name) == name.lower()).first()
        amt = r2(_signed(vals))
        status = "updated"
        if not led:
            g = groups.get(_norm(vals.get("group") or ""))
            if not g and any(sep in str(vals.get("group") or "") for sep in ("›", ">", "/")):
                from . import accounting as acc

                try:
                    g = acc.resolve_group_path(db, str(vals["group"]))
                except AppError:
                    g = None
            if not g:
                out.append({"row": row["_row"], "key": name, "status": "error", "message": f"Ledger not found. Give a group (e.g. Sundry Debtors) to create it{' – unknown group ' + str(vals.get('group')) if vals.get('group') else ''}"})
                continue
            led = Ledger(name=name, group_id=g, created_by=user.id)
            db.add(led)
            status = "created"
        before = {"opening_balance": str(led.opening_balance or 0), "opening_type": led.opening_type}
        led.opening_balance, led.opening_type = abs(amt), ("Dr" if amt >= 0 else "Cr")
        db.flush()
        total += amt
        log(db, user, "opening_balance", "ledgers", led.id, before, {"opening_balance": str(abs(amt)), "opening_type": led.opening_type}, "Excel import")
        out.append({"row": row["_row"], "key": name, "status": status, "message": f"{abs(amt)} {led.opening_type}"})
    if out and not any(r["status"] == "error" for r in out):
        out.append({"row": 0, "key": "Total of imported openings", "status": "skipped", "message": f"Net {'Dr' if total >= 0 else 'Cr'} {abs(total)}" + (" – does not balance; the difference shows in the trial balance until corrected" if total else " – balanced")})
    return out


def _run_vouchers(db, user, fields, mapping, constants, rows) -> list[dict]:
    from . import accounting as acc

    for need in ("voucher_date", "voucher_ref", "ledger"):
        if need not in mapping and need not in constants:
            raise AppError(f"Map the '{fields[need]['label']}' column")
    ledgers = {_norm(l.name): l.id for l in db.query(Ledger)}
    groups: dict[str, list] = {}
    order: list[str] = []
    out = []
    for row in rows:
        vals, errs = _row_values(row, fields, mapping, constants, RefCache(db))
        ref = str(vals.get("voucher_ref") or "")
        if ref not in groups:
            groups[ref] = []
            order.append(ref)
        groups[ref].append((row["_row"], vals, errs))
    for ref in order:
        lines, errs, rownos, vdate, narr = [], [], [], None, None
        for rowno, vals, e in groups[ref]:
            rownos.append(rowno)
            errs += [f"row {rowno}: {x}" for x in e]
            lid = ledgers.get(_norm(vals.get("ledger")))
            if not lid:
                errs.append(f"row {rowno}: ledger '{vals.get('ledger')}' not found")
                continue
            amt = _signed(vals)
            lines.append({"ledger_id": lid, "debit": amt if amt > 0 else 0, "credit": -amt if amt < 0 else 0})
            vdate = vdate or vals.get("voucher_date")
            narr = narr or vals.get("narration")
        key = f"{ref} (rows {rownos[0]}–{rownos[-1]})"
        if not ref:
            errs.append("voucher number is empty")
        if errs:
            out.append({"row": rownos[0], "key": key, "status": "error", "message": "; ".join(errs)})
            continue
        try:
            with db.begin_nested():
                v = acc.post(db, user, "Journal", date.fromisoformat(vdate), lines, narr or f"Imported {ref}", "import", None, ref)
            out.append({"row": rownos[0], "key": key, "status": "created", "message": v.voucher_no})
        except AppError as exc:
            out.append({"row": rownos[0], "key": key, "status": "error", "message": str(exc.detail)})
    return out


# ------------------------------------------------------------------ templates

TEMPLATES_KEY = "import_templates"


def list_templates(db: Session) -> list[dict]:
    row = db.get(AppSetting, TEMPLATES_KEY)
    return list(row.value or []) if row else []


def save_template(db: Session, user, tpl: dict) -> list[dict]:
    name = str(tpl.get("name") or "").strip()[:80]
    if not name:
        raise AppError("Give the mapping a name")
    if tpl.get("target") not in targets():
        raise AppError("Unknown import type")
    items = [t for t in list_templates(db) if not (t["name"] == name and t["target"] == tpl["target"])]
    items.append({"name": name, "target": tpl["target"], "mapping": tpl.get("mapping") or {}, "constants": tpl.get("constants") or {}, "header_row": int(tpl.get("header_row") or 1), "mode": tpl.get("mode") or "create",
                  "saved_by": user.username, "saved_at": datetime.now().isoformat(timespec="seconds")})
    _put(db, items, user.id)
    return items


def delete_template(db: Session, user, target: str, name: str) -> list[dict]:
    items = [t for t in list_templates(db) if not (t["name"] == name and t["target"] == target)]
    _put(db, items, user.id)
    return items


def _put(db, items, uid):
    row = db.get(AppSetting, TEMPLATES_KEY)
    if row is None:
        db.add(AppSetting(key=TEMPLATES_KEY, value=items, updated_by=uid))
    else:
        row.value = items
        row.updated_by = uid
    db.flush()
