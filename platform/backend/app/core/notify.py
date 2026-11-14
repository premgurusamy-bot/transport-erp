"""Central communication hub: consent, opt-out, frequency caps, approval holds and delivery via adapters."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.services import get_config
from app.integrations.adapters import get_adapter
from app.modules.platform.models import CommConsent, IntegrationProvider, Notification

# Templates that must be approved by a human before sending (complaints, claims, pricing, liability, legal)
SENSITIVE_TEMPLATES = {"complaint_response", "claim_update", "price_change", "liability", "legal", "collection_final"}

TEMPLATES = {
    "booking_confirmed": "Booking {code} confirmed: {origin} to {destination}. {service}",
    "trip_dispatched": "Your consignment {code} has been dispatched. Vehicle {vehicle}. Track in the customer portal.",
    "delivered": "Consignment {code} delivered to {receiver} at {time}.",
    "pod_otp": "OTP for delivery of consignment {code}: {otp}. Share only with the driver at delivery.",
    "login_otp": "Your G ROAD LINES sign-in OTP is {otp}. Valid for 5 minutes. Do not share.",
    "invoice_issued": "Invoice {number} for Rs {total} is issued. Due {due}.",
    "payment_reminder": "Gentle reminder: invoice {number} of Rs {balance} is due on {due}. Please ignore if already paid.",
    "compliance_due": "{subject}: {kind} expires on {date}.",
    "duty_offer": "New trip {code} offered: {lane}. Open the driver app to accept.",
    "generic": "{text}",
}


def render(template: str, **kw) -> str:
    try:
        return TEMPLATES.get(template, "{text}").format(**kw)
    except KeyError:
        return TEMPLATES["generic"].format(text=kw.get("text", ""))


def queue(
    db: Session, *, channel: str, recipient: str, template: str, body: str | None = None, user_id=None,
    entity: str | None = None, entity_id=None, subject: str | None = None, deliver_now: bool = True, **kw,
) -> Notification:
    body = body or render(template, **kw)
    n = Notification(channel=channel, template=template, recipient=recipient, body=body, subject=subject,
                     user_id=user_id, entity=entity, entity_id=str(entity_id) if entity_id else None)
    if template in SENSITIVE_TEMPLATES:
        n.status, n.requires_approval = "held", True
    if channel != "in_app":
        consent = db.execute(
            select(CommConsent).where(CommConsent.recipient == recipient, CommConsent.channel == channel)
        ).scalar_one_or_none()
        if consent is not None and not consent.opted_in:
            n.status, n.error = "blocked", "Recipient opted out"
        cap = int(get_config(db, "notification.daily_cap_per_recipient") or 10)
        sent_today = db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.recipient == recipient, Notification.channel == channel,
                Notification.created_at >= utcnow() - timedelta(days=1), Notification.status == "sent",
            )
        ).scalar()
        # Transactional OTP messages are never capped
        if n.status == "queued" and sent_today >= cap and "otp" not in template:
            n.status, n.error = "blocked", f"Daily cap {cap} reached"
    db.add(n)
    db.flush()
    if deliver_now and n.status == "queued":
        deliver(db, n)
    return n


def deliver(db: Session, n: Notification) -> Notification:
    if n.channel == "in_app":
        n.status, n.sent_at, n.provider = "sent", utcnow(), "in_app"
        return n
    adapter = get_adapter(n.channel)
    res = adapter.send(n.recipient, n.body, n.subject)
    n.provider = f"{adapter.name} ({adapter.mode})"
    if res.ok:
        n.status, n.sent_at, n.provider_ref = "sent", utcnow(), res.data.get("provider_ref")
    else:
        n.status, n.error = "failed", res.error
    prov = db.execute(select(IntegrationProvider).where(IntegrationProvider.kind == n.channel)).scalar_one_or_none()
    if prov and res.ok:
        prov.last_success_at = utcnow()
    return n
