"""Event notifications through configurable templates (in-app, email, WhatsApp, SMS)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..integrations import channels
from ..models import InAppNotification, NotificationLog, NotificationTemplate
from . import settings as app_settings

EVENTS = {
    "lr_generated": "LR generated",
    "vehicle_dispatched": "Vehicle dispatched",
    "delivery_completed": "Delivery completed",
    "pod_pending": "POD pending",
    "invoice_generated": "Invoice generated",
    "payment_due": "Payment due",
    "payment_received": "Payment received",
    "permit_expiry": "Permit expiry",
    "insurance_expiry": "Insurance expiry",
    "fc_expiry": "Fitness / PUC / road tax expiry",
    "service_due": "Service due",
    "licence_expiry": "Driver licence expiry",
    "contract_expiry": "Contract expiry",
    "credit_limit": "Credit limit alert",
    "fuel_abnormal": "Abnormal fuel consumption",
    "delivery_delay": "Delivery delay",
    "eway_expiry": "E-way bill validity",
    "compliance_due": "Statutory due date",
}

DEFAULT_TEMPLATES = [
    ("lr_generated", "in_app", "LR {lr_no} generated", "LR {lr_no} for {customer}: {from} → {to}, vehicle {vehicle}, freight ₹{amount}", "staff"),
    ("lr_generated", "whatsapp", None, "Dear {customer}, LR {lr_no} has been booked from {from} to {to}. Vehicle: {vehicle}. – Sri Vengarai Suraj Logistics", "customer"),
    ("lr_generated", "email", "LR {lr_no} booked", "Dear {customer},\n\nLR {lr_no} has been booked from {from} to {to}. Vehicle: {vehicle}.\n\nRegards,\nSri Vengarai Suraj Logistics", "customer"),
    ("vehicle_dispatched", "in_app", "Trip {trip_no} dispatched", "Vehicle {vehicle} dispatched {from} → {to} (LR {lrs})", "staff"),
    ("vehicle_dispatched", "whatsapp", None, "Dear {customer}, your consignment (LR {lrs}) has been dispatched in vehicle {vehicle} from {from} to {to}.", "customer"),
    ("vehicle_dispatched", "sms", None, "LR {lrs} dispatched in {vehicle} {from}-{to}. SVSL", "customer"),
    ("delivery_completed", "in_app", "Delivered: trip {trip_no}", "LR {lrs} delivered at {to}", "staff"),
    ("delivery_completed", "whatsapp", None, "Dear {customer}, LR {lrs} has been delivered at {to}. Thank you.", "customer"),
    ("invoice_generated", "in_app", "Invoice {invoice_no} issued", "{customer}: ₹{amount}", "staff"),
    ("invoice_generated", "email", "Invoice {invoice_no}", "Dear {customer},\n\nPlease find invoice {invoice_no} dated {date} for ₹{amount}.\n\nRegards,\nSri Vengarai Suraj Logistics", "customer"),
    ("payment_received", "in_app", "Payment received ₹{amount}", "{customer} – receipt {voucher_no}", "staff"),
    ("payment_received", "whatsapp", None, "Dear {customer}, we have received ₹{amount} (receipt {voucher_no}). Thank you.", "customer"),
    ("payment_due", "in_app", "Payment overdue: {customer}", "{count} invoice(s) overdue, ₹{amount}", "staff"),
    ("pod_pending", "in_app", "POD pending: LR {lr_no}", "Delivered {days} day(s) ago, POD not received", "staff"),
    ("permit_expiry", "in_app", "{title}", "{body}", "staff"),
    ("insurance_expiry", "in_app", "{title}", "{body}", "staff"),
    ("fc_expiry", "in_app", "{title}", "{body}", "staff"),
    ("service_due", "in_app", "{title}", "{body}", "staff"),
    ("licence_expiry", "in_app", "{title}", "{body}", "staff"),
    ("contract_expiry", "in_app", "{title}", "{body}", "staff"),
    ("credit_limit", "in_app", "{title}", "{body}", "staff"),
    ("fuel_abnormal", "in_app", "{title}", "{body}", "staff"),
    ("delivery_delay", "in_app", "{title}", "{body}", "staff"),
    ("eway_expiry", "in_app", "{title}", "{body}", "staff"),
    ("compliance_due", "in_app", "{title}", "{body}", "staff"),
]


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(text: str | None, ctx: dict) -> str:
    return (text or "").format_map(_Safe({k: ("" if v is None else v) for k, v in ctx.items()}))


def in_app(db: Session, title: str, body: str, link: str | None = None, severity: str = "info", user_id: int | None = None, dedupe_key: str | None = None) -> bool:
    if dedupe_key and db.execute(select(InAppNotification.id).where(InAppNotification.dedupe_key == dedupe_key)).first():
        return False
    try:
        with db.begin_nested():
            db.add(InAppNotification(title=title[:200], body=body, link=link, severity=severity, user_id=user_id, dedupe_key=dedupe_key))
    except IntegrityError:
        return False
    return True


def event(db: Session, name: str, ctx: dict, customer=None, driver=None, entity: tuple[str, int] | None = None, severity: str = "info", dedupe_key: str | None = None, link: str | None = None) -> None:
    cfg = app_settings.get(db, "notifications")
    templates = db.execute(select(NotificationTemplate).where(NotificationTemplate.event == name, NotificationTemplate.is_active.is_(True))).scalars().all()
    for t in templates:
        subject, body = render(t.subject, ctx), render(t.body, ctx)
        if t.channel == "in_app":
            if cfg.get("in_app", True):
                in_app(db, subject or EVENTS.get(name, name), body, link, severity, dedupe_key=(f"{dedupe_key}" if dedupe_key else None))
            continue
        if not cfg.get(t.channel):
            continue  # channel switched off in settings – nothing to log
        targets: list[str] = []
        if t.recipients in ("customer", "all") and customer is not None:
            addr = customer.email if t.channel == "email" else (customer.whatsapp or customer.mobile)
            if addr:
                targets.append(addr)
        if t.recipients in ("driver", "all") and driver is not None and t.channel != "email" and driver.mobile:
            targets.append(driver.mobile)
        if t.recipients in ("staff", "all") and t.channel == "email":
            targets += cfg.get("staff_emails") or []
        for to in targets:
            if t.channel == "email":
                status, err = channels.send_email(to, subject or EVENTS.get(name, name), body)
            elif t.channel == "whatsapp":
                status, err = channels.send_whatsapp(to, body)
            else:
                status, err = channels.send_sms(to, body)
            db.add(NotificationLog(event=name, channel=t.channel, recipient=to, subject=subject, body=body, status=status, error=err, entity=entity[0] if entity else None, entity_id=str(entity[1]) if entity else None))
    db.flush()
