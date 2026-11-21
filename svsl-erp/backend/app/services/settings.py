"""Key/value system settings with defaults. Everything business-specific is editable in Settings."""
from __future__ import annotations

import copy

from sqlalchemy.orm import Session

from ..models import AppSetting, Company

DEFAULTS: dict[str, dict] = {
    "gst": {
        "default_treatment_code": "GTA_RCM_5",
        "einvoice_enabled": False,
        "einvoice_note": "E-invoicing applies when aggregate annual turnover exceeds the notified threshold. Enable only after confirming applicability and configuring an IRP/GSP.",
        "ewaybill_value_threshold": 50000,
        "freight_exempt_upto_per_consignment": 1500,
        "freight_exempt_upto_single_consignee": 750,
        "hsn_digits": 4,
    },
    "lr": {
        "default_print": "A4",
        "copies": ["Consignor Copy", "Consignee Copy", "Driver Copy", "Office Copy"],
        "require_eway_above_value": 50000,
        "allow_lr_without_vehicle": True,
    },
    "invoice": {"default_due_days": 30, "round_off": True, "show_bank_details": True, "show_lr_details": True},
    "accounts": {"lock_before": None, "cash_limit_alert": 200000},
    "alerts": {
        "expiry_days": [30, 15, 7, 1],
        "fuel_tolerance_pct": 15,
        "delay_grace_hours": 6,
        "pod_pending_days": 3,
        "contract_renewal_days": 30,
        "credit_limit_warn_pct": 90,
    },
    "payroll": {
        "pf_employee_pct": 12,
        "pf_employer_pct": 12,
        "pf_wage_ceiling": 15000,
        "esi_employee_pct": 0.75,
        "esi_employer_pct": 3.25,
        "esi_gross_ceiling": 21000,
        "pt_mode": "half_yearly_split",
        "pt_half_yearly_slabs": [
            {"upto": 21000, "tax": 0},
            {"upto": 30000, "tax": 135},
            {"upto": 45000, "tax": 315},
            {"upto": 60000, "tax": 690},
            {"upto": 75000, "tax": 1025},
            {"upto": None, "tax": 1250},
        ],
        "pt_note": "Tamil Nadu professional tax is levied half-yearly by the local body. Verify these slabs with your municipal corporation / panchayat before use.",
    },
    "backup": {"enabled": True, "hour": 23, "keep_last": 60, "include_files": True},
    "retention": {"audit_log_years": 8, "notification_log_days": 730, "login_history_days": 730},
    "language": {"default": "en", "available": ["en", "ta"]},
    "notifications": {"email": False, "whatsapp": False, "sms": False, "in_app": True, "staff_emails": []},
    "branding": {"primary_color": "#0f4c81", "tagline": "Goods Transport • Logistics • Warehousing"},
}


def get(db: Session, key: str) -> dict:
    row = db.get(AppSetting, key)
    value = copy.deepcopy(DEFAULTS.get(key, {}))
    if row and isinstance(row.value, dict):
        value.update(row.value)
    return value


def set_(db: Session, key: str, value: dict, user_id: int | None = None) -> dict:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value, updated_by=user_id)
        db.add(row)
    else:
        merged = dict(row.value or {})
        merged.update(value)
        row.value = merged
        row.updated_by = user_id
    db.flush()
    return get(db, key)


def all_settings(db: Session) -> dict:
    return {k: get(db, k) for k in DEFAULTS}


def company(db: Session) -> Company:
    c = db.query(Company).order_by(Company.id).first()
    if c is None:
        c = Company(legal_name="Sree Venkateswara Logistics", trade_name="Sree Venkateswara Logistics", city="Coimbatore", state="Tamil Nadu", state_code="33", fy_start_month=4)
        db.add(c)
        db.flush()
    return c
