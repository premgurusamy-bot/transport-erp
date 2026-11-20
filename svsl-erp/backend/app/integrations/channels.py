"""Outbound message channels. Each returns (status, error). Nothing is reported as sent unless the
provider accepted it. Unconfigured channels return 'not_configured'."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import httpx

from ..config import get_settings


def email_configured() -> bool:
    s = get_settings()
    return bool(s.smtp_host and s.smtp_from)


def send_email(to: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None) -> tuple[str, str | None]:
    s = get_settings()
    if not email_configured():
        return "not_configured", "SMTP is not configured (SMTP_HOST / SMTP_FROM)"
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_tls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return "sent", None
    except Exception as exc:  # noqa: BLE001
        return "failed", str(exc)[:500]


def whatsapp_configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_token and s.whatsapp_phone_id)


def send_whatsapp(to: str, body: str, template: str | None = None, lang: str = "en") -> tuple[str, str | None]:
    """WhatsApp Business Cloud API. Business-initiated messages outside a 24-hour customer window
    require a pre-approved template; pass its name in `template` (body is used as the first parameter)."""
    s = get_settings()
    if not whatsapp_configured():
        return "not_configured", "WhatsApp Business API is not configured (WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID)"
    number = "".join(ch for ch in to if ch.isdigit())
    if len(number) == 10:
        number = "91" + number
    payload: dict = {"messaging_product": "whatsapp", "to": number}
    if template:
        payload.update({"type": "template", "template": {"name": template, "language": {"code": lang}, "components": [{"type": "body", "parameters": [{"type": "text", "text": body[:1000]}]}]}})
    else:
        payload.update({"type": "text", "text": {"body": body[:4000]}})
    try:
        r = httpx.post(f"https://graph.facebook.com/v20.0/{s.whatsapp_phone_id}/messages", json=payload, headers={"Authorization": f"Bearer {s.whatsapp_token}"}, timeout=15)
        if r.status_code < 300:
            return "sent", None
        return "failed", r.text[:500]
    except httpx.HTTPError as exc:
        return "failed", str(exc)[:500]


def sms_configured() -> bool:
    s = get_settings()
    return bool(s.sms_url and s.sms_api_key)


def send_sms(to: str, body: str) -> tuple[str, str | None]:
    """Generic HTTP SMS gateway: POST {url} with api_key, sender, to, message.
    Indian SMS requires DLT-registered templates & sender ID – register with your provider first."""
    s = get_settings()
    if not sms_configured():
        return "not_configured", "SMS gateway is not configured (SMS_GATEWAY_URL / SMS_API_KEY)"
    try:
        r = httpx.post(s.sms_url, data={"api_key": s.sms_api_key, "sender": s.sms_sender, "to": to, "message": body}, timeout=15)
        return ("sent", None) if r.status_code < 300 else ("failed", r.text[:500])
    except httpx.HTTPError as exc:
        return "failed", str(exc)[:500]


def whatsapp_share_link(phone: str | None, text: str) -> str:
    """Click-to-chat link – works without any API: opens WhatsApp with the message pre-filled."""
    from urllib.parse import quote

    number = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(number) == 10:
        number = "91" + number
    return f"https://wa.me/{number}?text={quote(text)}" if number else f"https://wa.me/?text={quote(text)}"
