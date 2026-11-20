"""Decimal money helpers, Indian number formatting and amount-in-words."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")


def D(value) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid number: {value!r}") from exc


def r2(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def r0(value) -> Decimal:
    return D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def inr(value, symbol: bool = True, decimals: int = 2) -> str:
    """Indian grouping: 12,34,567.89"""
    v = r2(value)
    neg = v < 0
    v = abs(v)
    whole, _, frac = f"{v:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    text = whole + ("." + frac if decimals else "")
    return ("-" if neg else "") + ("₹ " if symbol else "") + text


def fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return d
    if isinstance(d, datetime):
        return d.strftime("%d-%m-%Y %H:%M")
    return d.strftime("%d-%m-%Y")


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three(n: int) -> str:
    h, rest = divmod(n, 100)
    parts = []
    if h:
        parts.append(_ONES[h] + " Hundred")
    if rest:
        parts.append(_two(rest))
    return " ".join(parts)


def words_int(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(words_int(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts)


def amount_in_words(value) -> str:
    v = r2(value)
    rupees = int(abs(v))
    paise = int((abs(v) - rupees) * 100)
    text = "Rupees " + words_int(rupees)
    if paise:
        text += " and " + _two(paise) + " Paise"
    return ("Minus " if v < 0 else "") + text + " Only"
