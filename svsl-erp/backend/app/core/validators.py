"""Indian identifiers: GSTIN (with check digit), PAN, IFSC, mobile, pincode, vehicle numbers, state codes."""
from __future__ import annotations

import re

STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura", "17": "Meghalaya",
    "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_MOBILE_RE = re.compile(r"^(\+91[\-\s]?)?[6-9][0-9]{9}$")
_PIN_RE = re.compile(r"^[1-9][0-9]{5}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# MH12AB1234, TN38BX1234, TN38X1234, 22BH1234AA (Bharat series), DL1CAB1234
_VEHICLE_RE = re.compile(r"^([A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}|[0-9]{2}BH[0-9]{4}[A-Z]{1,2})$")
_EWB_RE = re.compile(r"^[0-9]{12}$")

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        value = _CHARS.index(ch)
        product = value * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(value: str) -> str | None:
    """Return an error message, or None if the GSTIN is structurally valid (format + state + checksum)."""
    v = (value or "").strip().upper()
    if not _GSTIN_RE.match(v):
        return "GSTIN must be 15 characters: 2-digit state code, PAN, entity number, 'Z', check digit"
    if v[:2] not in STATE_CODES:
        return f"GSTIN state code {v[:2]} is not a valid GST state code"
    if gstin_check_digit(v[:14]) != v[14]:
        return "GSTIN check digit is wrong – please re-check the number"
    return None


def normalize(kind: str, value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if kind in ("gstin", "pan", "ifsc", "vehicle_no"):
            value = value.upper().replace(" ", "").replace("-", "") if kind == "vehicle_no" else value.upper()
        if kind == "mobile":
            value = re.sub(r"[\s\-]", "", value)
    return value


def validate(kind: str, value) -> str | None:
    if value in (None, ""):
        return None
    v = str(value)
    if kind == "gstin":
        return validate_gstin(v)
    if kind == "pan":
        return None if _PAN_RE.match(v) else "PAN must look like ABCDE1234F"
    if kind == "ifsc":
        return None if _IFSC_RE.match(v) else "IFSC must be 11 characters, e.g. SBIN0001234"
    if kind == "mobile":
        return None if _MOBILE_RE.match(v) else "Enter a valid 10-digit Indian mobile number"
    if kind == "pincode":
        return None if _PIN_RE.match(v) else "Pincode must be 6 digits"
    if kind == "email":
        return None if _EMAIL_RE.match(v) else "Enter a valid email address"
    if kind == "vehicle_no":
        return None if _VEHICLE_RE.match(v) else "Vehicle number must look like TN38AB1234"
    if kind == "ewb":
        return None if _EWB_RE.match(v) else "E-way bill number must be 12 digits"
    return None


def state_code_from_gstin(gstin: str | None) -> str | None:
    if gstin and len(gstin) >= 2 and gstin[:2] in STATE_CODES:
        return gstin[:2]
    return None
