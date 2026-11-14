"""Bank statement import (CSV), normalisation, de-duplication and matching.

Never treats an unmatched bank credit as a confirmed customer payment. Auto-confirmation only for exact
matches under the configured rule; everything else goes to the Accounts exception queue."""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import money
from app.core.errors import AppError, Conflict
from app.modules.finance.models import BankStatementImport, BankTransaction, Invoice, Payment, Receipt
from app.modules.masters.models import Customer

HEADER_ALIASES = {
    "date": ["date", "txn date", "transaction date", "tran date", "value date"],
    "description": ["description", "narration", "particulars", "remarks", "details"],
    "reference": ["reference", "ref no", "ref", "chq/ref no", "cheque no", "utr", "ref no./cheque no."],
    "debit": ["debit", "withdrawal", "withdrawal amt", "dr", "withdrawals"],
    "credit": ["credit", "deposit", "deposit amt", "cr", "deposits"],
    "balance": ["balance", "closing balance", "bal"],
}


def _amt(s) -> Decimal:
    s = str(s or "").replace(",", "").replace("₹", "").replace("Rs", "").strip()
    if not s or s in ("-", "0", "0.00"):
        return Decimal("0")
    try:
        return money(Decimal(s))
    except InvalidOperation:
        raise AppError("bad_amount", f"Unreadable amount '{s}'")


def _date(s) -> date:
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise AppError("bad_date", f"Unreadable date '{s}'")


def detect_mode(desc: str) -> str:
    d = desc.upper()
    for key, mode in (("UPI", "upi"), ("NEFT", "neft"), ("RTGS", "rtgs"), ("IMPS", "imps"), ("CHQ", "cheque"), ("CHEQUE", "cheque"),
                      ("CHARGES", "charges"), ("CHRG", "charges"), ("GST ON", "charges"), ("INT.PD", "interest"), ("INTEREST", "interest"),
                      ("EMI", "emi"), ("LOAN", "emi"), ("TRF", "transfer"), ("TRANSFER", "transfer")):
        if key in d:
            return mode
    return "other"


def parse_csv(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text)))
    hdr_idx = None
    for i, r in enumerate(rows[:20]):
        low = [c.strip().lower() for c in r]
        if any(a in low for a in HEADER_ALIASES["date"]) and (any(a in low for a in HEADER_ALIASES["credit"]) or any(a in low for a in HEADER_ALIASES["debit"])):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise AppError("no_header", "Could not find a header row with Date and Debit/Credit columns")
    hdr = [c.strip().lower() for c in rows[hdr_idx]]
    col = {}
    for k, aliases in HEADER_ALIASES.items():
        for a in aliases:
            if a in hdr:
                col[k] = hdr.index(a)
                break
    out = []
    for n, r in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
        if not r or not any(c.strip() for c in r):
            continue
        try:
            d = _date(r[col["date"]])
        except (AppError, IndexError):
            continue  # footer/summary lines
        desc = r[col["description"]].strip() if "description" in col else ""
        out.append({"line": n, "txn_date": d, "description": desc,
                    "reference": r[col["reference"]].strip() if "reference" in col and r[col["reference"]].strip() else None,
                    "debit": _amt(r[col["debit"]]) if "debit" in col else Decimal("0"),
                    "credit": _amt(r[col["credit"]]) if "credit" in col else Decimal("0"),
                    "balance": _amt(r[col["balance"]]) if "balance" in col and r[col["balance"]].strip() else None})
    return out


def dedupe_hash(bank_id, row) -> str:
    key = f"{bank_id}|{row['txn_date']}|{row['debit']}|{row['credit']}|{(row['reference'] or '').upper()}|{re.sub(r'\\s+', ' ', row['description'].upper())}|{row['balance']}"
    return hashlib.sha256(key.encode()).hexdigest()


def import_statement(db: Session, actor, *, company_bank_id, text: str, filename: str, source: str = "csv_upload") -> BankStatementImport:
    checksum = hashlib.sha256(text.encode()).hexdigest()
    if db.execute(select(BankStatementImport).where(BankStatementImport.checksum == checksum,
                                                    BankStatementImport.company_bank_id == company_bank_id)).first():
        raise Conflict("same_file", "This exact statement file was already imported")
    rows = parse_csv(text)
    imp = BankStatementImport(company_bank_id=company_bank_id, source=source, filename=filename, checksum=checksum,
                              rows_total=len(rows), imported_by=actor.user_id)
    db.add(imp)
    db.flush()
    new = dup = 0
    for r in rows:
        h = dedupe_hash(company_bank_id, r)
        if db.execute(select(BankTransaction.id).where(BankTransaction.dedupe_hash == h)).first():
            dup += 1
            continue
        db.add(BankTransaction(company_bank_id=company_bank_id, import_id=imp.id, txn_date=r["txn_date"], description=r["description"],
                               reference=r["reference"], debit=r["debit"], credit=r["credit"], balance=r["balance"],
                               mode=detect_mode(r["description"]), dedupe_hash=h))
        new += 1
    imp.rows_new, imp.rows_duplicate = new, dup
    if rows:
        imp.statement_from, imp.statement_to = min(r["txn_date"] for r in rows), max(r["txn_date"] for r in rows)
        last = [r for r in rows if r["balance"] is not None]
        imp.closing_balance = last[-1]["balance"] if last else None
    db.flush()
    write_audit(db, actor=actor, action="bank.import", entity="bank_import", entity_id=imp.id,
                after={"file": filename, "rows": len(rows), "new": new, "duplicates": dup})
    return imp


def _name_hit(desc: str, name: str) -> bool:
    words = [w for w in re.findall(r"[A-Z]{3,}", name.upper()) if w not in ("PVT", "LTD", "PRIVATE", "LIMITED", "AND", "THE", "CO")]
    d = desc.upper()
    return bool(words) and sum(1 for w in words if w in d) >= max(1, len(words) // 2)


def match_all(db: Session, actor, company_bank_id=None, auto_confirm: bool = True) -> dict:
    q = select(BankTransaction).where(BankTransaction.status.in_(("unmatched", "suggested")))
    if company_bank_id:
        q = q.where(BankTransaction.company_bank_id == company_bank_id)
    stats = {"exact": 0, "suggested": 0, "unmatched": 0, "auto_confirmed": 0}
    for t in db.execute(q).scalars():
        res = match_one(db, t)
        if res["confidence"] >= 1.0 and res["entity"] in ("receipt", "payment") and auto_confirm:
            confirm_match(db, actor, t, res["entity"], res["ids"], auto=True)
            stats["auto_confirmed"] += 1
            stats["exact"] += 1
        elif res["entity"]:
            t.status, t.match_entity, t.match_ids, t.match_confidence, t.match_reason = "suggested", res["entity"], res["ids"], Decimal(str(res["confidence"])), res["reason"]
            stats["suggested"] += 1
        else:
            t.status = "unmatched"
            t.match_reason = res["reason"]
            stats["unmatched"] += 1
    return stats


def match_one(db: Session, t: BankTransaction) -> dict:
    if t.credit > 0:
        amt = Decimal(t.credit)
        # 1. Recorded (unconfirmed) receipt with same reference and amount → exact
        if t.reference:
            r = db.execute(select(Receipt).where(Receipt.status == "unconfirmed", Receipt.amount == amt,
                                                 func.upper(Receipt.reference) == t.reference.upper())).scalars().first()
            if r:
                return {"entity": "receipt", "ids": [str(r.id)], "confidence": 1.0, "reason": "Reference and amount match recorded receipt"}
        r = db.execute(select(Receipt).where(Receipt.status == "unconfirmed", Receipt.amount == amt)).scalars().all()
        if len(r) == 1:
            return {"entity": "receipt", "ids": [str(r[0].id)], "confidence": 0.8, "reason": "Amount matches one unconfirmed receipt (reference differs)"}
        # 2. Open invoices of a customer named in the narration: single or combination
        for c in db.execute(select(Customer)).scalars():
            if not _name_hit(t.description, c.name):
                continue
            invs = list(db.execute(select(Invoice).where(Invoice.customer_id == c.id, Invoice.status.in_(("issued", "part_paid")))
                                   .order_by(Invoice.due_date)).scalars())
            bal = {i.id: Decimal(i.total) - Decimal(i.amount_received) - Decimal(i.tds_received) for i in invs}
            for i in invs:
                if bal[i.id] == amt:
                    return {"entity": "invoice", "ids": [str(i.id)], "confidence": 0.9, "reason": f"Customer {c.name} named; exact invoice balance"}
            for n in range(2, min(5, len(invs)) + 1):
                for combo in itertools.combinations(invs[:10], n):
                    if sum(bal[i.id] for i in combo) == amt:
                        return {"entity": "invoice", "ids": [str(i.id) for i in combo], "confidence": 0.75,
                                "reason": f"Customer {c.name}; {n} invoices sum to amount"}
            return {"entity": "customer", "ids": [str(c.id)], "confidence": 0.5, "reason": f"Customer {c.name} named but amount does not match open invoices (part/advance?)"}
        if t.mode == "interest":
            return {"entity": "interest", "ids": [], "confidence": 0.7, "reason": "Interest credit"}
        return {"entity": None, "ids": [], "confidence": 0, "reason": "No matching receipt/invoice - unidentified credit (NOT a confirmed payment)"}
    amt = Decimal(t.debit)
    if t.reference:
        pmt = db.execute(select(Payment).where(Payment.status == "executed", Payment.amount == amt,
                                               func.upper(Payment.bank_reference) == t.reference.upper())).scalars().first()
        if pmt:
            return {"entity": "payment", "ids": [str(pmt.id)], "confidence": 1.0, "reason": "UTR and amount match executed payment"}
    pm = db.execute(select(Payment).where(Payment.status == "executed", Payment.amount == amt)).scalars().all()
    if len(pm) == 1:
        return {"entity": "payment", "ids": [str(pm[0].id)], "confidence": 0.8, "reason": "Amount matches one executed payment"}
    if t.mode in ("charges", "emi", "interest"):
        return {"entity": t.mode, "ids": [], "confidence": 0.7, "reason": f"Bank {t.mode} - post with review"}
    return {"entity": None, "ids": [], "confidence": 0, "reason": "No matching payment"}


def confirm_match(db: Session, actor, t: BankTransaction, entity: str, ids: list, auto: bool = False, customer_id=None,
                  tds_amount: Decimal = Decimal("0")):
    from app.modules.finance.billing import confirm_receipt, record_receipt
    from app.modules.finance.posting import bank_ledger, post_voucher
    if t.status == "matched":
        raise Conflict("matched", "Transaction already matched")
    if entity == "receipt":
        r = db.get(Receipt, uuid.UUID(str(ids[0])))
        if Decimal(r.amount) != Decimal(t.credit):
            raise AppError("amount_mismatch", "Receipt amount differs from bank credit")
        r.bank_txn_id, r.company_bank_id = t.id, t.company_bank_id
        confirm_receipt(db, actor, r, [{**a, "amount": Decimal(a["amount"]), "tds_amount": Decimal(a.get("tds_amount", "0"))}
                                       for a in (r.planned_allocations or [])])
    elif entity == "invoice":
        invs = [db.get(Invoice, uuid.UUID(str(i))) for i in ids]
        cust = invs[0].customer_id
        r = record_receipt(db, actor, customer_id=cust, amount=Decimal(t.credit), tds_amount=tds_amount, mode=t.mode or "neft",
                           reference=t.reference or f"BANK-{t.id.hex[:8]}", receipt_date=t.txn_date, company_bank_id=t.company_bank_id,
                           allocations=[{"invoice_id": i.id} for i in invs], confirmed=True, bank_txn_id=t.id)
        ids = [str(r.id)]
        entity = "receipt"
    elif entity in ("customer", "advance"):
        if not customer_id and entity == "customer":
            customer_id = uuid.UUID(str(ids[0]))
        r = record_receipt(db, actor, customer_id=customer_id, amount=Decimal(t.credit), tds_amount=tds_amount, mode=t.mode or "neft",
                           reference=t.reference or f"BANK-{t.id.hex[:8]}", receipt_date=t.txn_date, company_bank_id=t.company_bank_id,
                           confirmed=True, bank_txn_id=t.id, is_advance=entity == "advance")
        ids, entity = [str(r.id)], "receipt"
    elif entity == "payment":
        p = db.get(Payment, uuid.UUID(str(ids[0])))
        if Decimal(p.amount) != Decimal(t.debit):
            raise AppError("amount_mismatch", "Payment amount differs from bank debit")
        p.status, p.bank_txn_id = "confirmed", t.id
    elif entity in ("charges", "interest", "emi"):
        acct = {"charges": "5500", "interest": "4900" if t.credit else "5800", "emi": "2300"}[entity]
        amt = Decimal(t.credit or t.debit)
        bank = bank_ledger(db, t.company_bank_id)
        lines = ([{"account": bank, "debit": amt}, {"account": acct, "credit": amt}] if t.credit
                 else [{"account": acct, "debit": amt}, {"account": bank, "credit": amt}])
        v = post_voucher(db, actor, vtype="journal", vdate=t.txn_date, narration=f"Bank {entity}: {t.description[:80]}", lines=lines,
                         source_entity="bank_txn", source_id=t.id)
        ids = [str(v.id)]
    else:
        raise AppError("bad_entity", "Unsupported match type")
    t.status, t.match_entity, t.match_ids, t.matched_by, t.auto_matched = "matched", entity, ids, actor.user_id, auto
    t.match_confidence = t.match_confidence or Decimal("1.0")
    write_audit(db, actor=actor, action="bank.match", entity="bank_txn", entity_id=t.id,
                after={"entity": entity, "ids": ids, "auto": auto})


def reconciliation_summary(db: Session, company_bank_id) -> dict:
    from app.modules.finance.models import Account, VoucherLine
    from app.modules.finance.posting import bank_ledger
    from app.modules.masters.models import CompanyBankAccount
    cb = db.get(CompanyBankAccount, company_bank_id)
    acc = db.execute(select(Account).where(Account.code == bank_ledger(db, company_bank_id))).scalar_one()
    book = db.execute(select(func.coalesce(func.sum(VoucherLine.debit - VoucherLine.credit), 0)).where(VoucherLine.account_id == acc.id)).scalar()
    book = Decimal(book) + Decimal(cb.opening_balance or 0)
    last = db.execute(select(BankStatementImport).where(BankStatementImport.company_bank_id == company_bank_id)
                      .order_by(BankStatementImport.created_at.desc())).scalars().first()
    unrec = list(db.execute(select(BankTransaction).where(BankTransaction.company_bank_id == company_bank_id,
                                                          BankTransaction.status != "matched", BankTransaction.status != "ignored")).scalars())
    today = date.today()
    return {
        "bank": cb.name, "book_balance": str(money(book)),
        "statement_balance": str(last.closing_balance) if last and last.closing_balance is not None else None,
        "last_import_at": last.created_at if last else None, "last_import_source": last.source if last else None,
        "statement_to": last.statement_to if last else None,
        "sync_status": "MOCK/manual import - no live bank connection" if last else "No statement imported",
        "missing_statement": (not last) or (last.statement_to and (today - last.statement_to).days > 1),
        "unreconciled_count": len(unrec),
        "unreconciled_credits": str(sum((Decimal(t.credit) for t in unrec), Decimal("0"))),
        "unreconciled_debits": str(sum((Decimal(t.debit) for t in unrec), Decimal("0"))),
        "oldest_unreconciled_days": max(((today - t.txn_date).days for t in unrec), default=0),
    }
