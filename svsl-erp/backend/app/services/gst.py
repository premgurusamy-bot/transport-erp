"""GST computation driven by the configured treatment of each transaction.

The engine never decides legal eligibility by itself: the user (or customer/contract default)
selects a GST treatment (FCM / RCM / EXEMPT / NIL with rate and SAC) and the engine applies it.
"""
from __future__ import annotations

from decimal import Decimal

from ..core.money import D, ZERO, r2
from ..core.validators import state_code_from_gstin


def place_of_supply(customer_gstin: str | None, customer_state_code: str | None, loading_state_code: str | None) -> str | None:
    """Sec. 12(8) IGST Act for transport of goods:
    registered recipient -> recipient's location; otherwise -> where goods are handed over for transport."""
    gst_state = state_code_from_gstin(customer_gstin)
    if gst_state:
        return gst_state
    return loading_state_code or customer_state_code


def compute(taxable, rate, mechanism: str, supplier_state: str, pos: str) -> dict:
    taxable = r2(taxable)
    rate = D(rate)
    interstate = (supplier_state or "") != (pos or "")
    out = {"taxable": taxable, "cgst": ZERO, "sgst": ZERO, "igst": ZERO, "rcm_tax": ZERO, "interstate": interstate}
    if mechanism in ("EXEMPT", "NIL") or rate <= 0:
        return out
    if mechanism == "RCM":
        out["rcm_tax"] = r2(taxable * rate / Decimal(100))
        return out
    if interstate:
        out["igst"] = r2(taxable * rate / Decimal(100))
    else:
        half = r2(taxable * rate / Decimal(200))
        out["cgst"] = half
        out["sgst"] = half
    return out


def round_total(amount) -> tuple[Decimal, Decimal]:
    total = D(amount)
    rounded = total.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
    return rounded, r2(rounded - total)
