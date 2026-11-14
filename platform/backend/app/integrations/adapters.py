"""Provider adapters. Every adapter declares its MODE honestly: MOCK, SANDBOX or LIVE.

Only MOCK adapters are implemented with behaviour in this codebase. LIVE adapters require credentials,
provider documentation and authorisation (see INTEGRATIONS.md and BLOCKERS.md) and must never be
reported as live until an authenticated connection has been tested.
"""
from __future__ import annotations

import hashlib
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.db import utcnow


@dataclass
class AdapterResult:
    ok: bool
    mode: str
    data: dict
    error: str | None = None


class Adapter:
    kind = "base"
    name = "base"
    mode = "MOCK"


# ------------------------------------------------------------------ messaging
class MockMessaging(Adapter):
    """Records the message as 'sent (MOCK)'. Nothing leaves the system."""

    mode = "MOCK"

    def __init__(self, kind: str):
        self.kind = kind
        self.name = f"mock_{kind}"

    def send(self, recipient: str, body: str, subject: str | None = None) -> AdapterResult:
        ref = "MOCK-" + secrets.token_hex(6)
        return AdapterResult(True, self.mode, {"provider_ref": ref, "recipient": recipient})


# ------------------------------------------------------------------ GST / e-invoice / e-way
_GSTIN_RE = re.compile(r"^[0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum_ok(gstin: str) -> bool:
    """Offline structural + check-digit validation. This is NOT official GST portal verification."""
    gstin = (gstin or "").upper().strip()
    if not _GSTIN_RE.match(gstin):
        return False
    total = 0
    for i, ch in enumerate(gstin[:14]):
        v = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _CHARS[(36 - total % 36) % 36] == gstin[14]


class MockGst(Adapter):
    kind = "gst"
    name = "mock_gsp"

    def validate_gstin(self, gstin: str) -> AdapterResult:
        ok = gstin_checksum_ok(gstin)
        return AdapterResult(ok, self.mode, {"gstin": gstin, "format_valid": ok,
                                              "official_status": "NOT VERIFIED (MOCK - no GSP connection)"})

    def generate_irn(self, invoice_payload: dict) -> AdapterResult:
        irn = hashlib.sha256(repr(sorted(invoice_payload.items())).encode()).hexdigest()
        return AdapterResult(True, self.mode, {"irn": "MOCK-" + irn[:40], "ack_no": "MOCK", "signed_qr": None})


class MockEway(Adapter):
    kind = "eway"
    name = "mock_eway"

    def generate(self, booking_payload: dict, km: float) -> AdapterResult:
        # Validity rule is configurable in reality (distance-based); MOCK uses 1 day per 200 km.
        days = max(1, math.ceil(km / 200))
        now = utcnow()
        return AdapterResult(True, self.mode, {"number": "MOCK" + str(secrets.randbelow(10**8)).zfill(8),
                                               "valid_from": now.isoformat(),
                                               "valid_until": (now + timedelta(days=days)).isoformat()})


# ------------------------------------------------------------------ maps / GPS / camera
def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class MockMaps(Adapter):
    """Straight-line distance × road factor. Labelled ESTIMATED - not a routing engine."""

    kind = "maps"
    name = "haversine_estimate"
    ROAD_FACTOR = 1.25

    def distance(self, a: tuple[float, float], b: tuple[float, float]) -> AdapterResult:
        km = haversine_km(*a, *b) * self.ROAD_FACTOR
        return AdapterResult(True, self.mode, {"km": round(km, 1), "basis": "ESTIMATED straight-line x1.25"})


class MockCamera(Adapter):
    """Issues a short-lived signed token for a simulated stream. Never returns DVR passwords/URLs."""

    kind = "camera"
    name = "mock_dvr_gateway"

    def live_stream(self, dvr_device_id: str, channel: int, ttl_seconds: int = 120) -> AdapterResult:
        token = secrets.token_urlsafe(24)
        return AdapterResult(True, self.mode, {
            "stream_url": f"/simulated-stream/{dvr_device_id}/{channel}?t={token}",
            "expires_at": (utcnow() + timedelta(seconds=ttl_seconds)).isoformat(),
            "label": "SIMULATED STREAM - no DVR hardware connected",
        })


# ------------------------------------------------------------------ bank
class MockBank(Adapter):
    kind = "bank"
    name = "mock_bank"

    def execute_payment(self, payment: dict) -> AdapterResult:
        # Deterministic on idempotency key so retries never double-pay.
        ref = "MOCKUTR" + hashlib.sha256(payment["idempotency_key"].encode()).hexdigest()[:12].upper()
        return AdapterResult(True, self.mode, {"bank_reference": ref, "status": "executed_simulated"})

    def verify_account(self, account_number: str, ifsc: str) -> AdapterResult:
        ok = bool(re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc or "")) and 6 <= len(account_number or "") <= 20
        return AdapterResult(ok, self.mode, {"name_at_bank": None, "note": "MOCK - IFSC format check only"})


class MockPaymentGateway(Adapter):
    kind = "payment_gateway"
    name = "mock_gateway"

    def create_order(self, amount: Decimal, ref: str) -> AdapterResult:
        return AdapterResult(True, self.mode, {"order_id": "MOCKORD-" + secrets.token_hex(6), "amount": str(amount)})


# ------------------------------------------------------------------ OCR
class MockOcr(Adapter):
    """Pattern-based extraction from text. Output is always labelled 'EXTRACTED - NOT VERIFIED'."""

    kind = "ocr"
    name = "mock_ocr_regex"

    def extract(self, text: str) -> AdapterResult:
        amt = re.findall(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", text or "", re.I)
        dt = re.findall(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text or "")
        gst = re.findall(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", (text or "").upper())
        bill = re.findall(r"(?:bill|invoice)\s*(?:no\.?|#)\s*[:\-]?\s*([A-Z0-9/-]+)", text or "", re.I)
        litres = re.findall(r"([\d.]+)\s*(?:L|ltr|litres?)\b", text or "", re.I)
        return AdapterResult(True, self.mode, {
            "label": "EXTRACTED - NOT VERIFIED",
            "amount": amt[-1].replace(",", "") if amt else None,
            "date": dt[0] if dt else None,
            "gstin": gst[0] if gst else None,
            "bill_number": bill[0] if bill else None,
            "litres": litres[0] if litres else None,
        })


REGISTRY: dict[str, Adapter] = {
    "sms": MockMessaging("sms"),
    "whatsapp": MockMessaging("whatsapp"),
    "email": MockMessaging("email"),
    "gst": MockGst(),
    "eway": MockEway(),
    "maps": MockMaps(),
    "camera": MockCamera(),
    "bank": MockBank(),
    "payment_gateway": MockPaymentGateway(),
    "ocr": MockOcr(),
}

# kinds that exist only as documented interfaces (no mock behaviour needed beyond status)
STATUS_ONLY = {
    "gps_tracker": "Tracker pings are accepted at POST /api/v1/gps/tracker-webhook (MOCK until vendor API verified)",
    "income_tax": "No integration - manual/CA workflow; ERI access needs eligibility",
    "tally": "XML/CSV import-export implemented (file based). No live Tally connection",
    "ai": "Mock provider active; Anthropic/OpenAI adapters activate only when API keys are configured",
    "social": "Publishing queue implemented; platform APIs not connected (MOCK publish)",
    "object_storage": "Encrypted local storage (dev). S3-compatible storage needs account + credentials",
}


def get_adapter(kind: str) -> Adapter:
    return REGISTRY[kind]


def now_label() -> str:
    return datetime.now().isoformat()
