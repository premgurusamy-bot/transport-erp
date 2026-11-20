# External integrations – status and what is required

Nothing in the ERP pretends an external action succeeded. Each integration below is either **working**,
**working once credentials are added** (code path exists, but has not been tested against the live service because
no credentials were available during development), or **manual workflow** (the ERP records what you do on the
official portal).

| Integration | Status | What you need | What works today without it |
|---|---|---|---|
| In-app notifications | **Working** | – | Bell icon, alert scan every hour, deduplicated |
| Email (SMTP) | Working once configured – *not tested against a live mailbox* | A mailbox / SMTP relay (Google Workspace, Zoho, Microsoft 365, or your hosting) → `SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM` | Messages are logged as `not_configured` |
| WhatsApp Business API | Code ready, **untested** – needs credentials | Meta Business account, verified WhatsApp Business number, Cloud API token → `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`. Business-initiated messages need **pre-approved templates** | **Click-to-chat links** (`wa.me`) with the LR/invoice text and verification link – the user taps Send |
| SMS gateway | Code ready (generic HTTP POST), **untested** – adapt to your provider | A DLT-registered entity, sender ID and templates (TRAI rules) with an SMS provider → `SMS_GATEWAY_URL, SMS_API_KEY, SMS_SENDER_ID` | – |
| E-invoice (IRP) | **Manual workflow working**; API client is a starting point only, **not certified** | Applicability (turnover above the notified threshold), API access from NIC/IRP or a GSP for your GSTIN → `IRP_*` settings; the client must be adapted to the GSP's exact API and tested on their sandbox | Download INV-01 JSON → upload on the IRP portal/offline tool → record IRN, Ack No, signed QR in the invoice. IRN cancellation (within 24 h) is recorded after doing it on the portal |
| E-way bill | **Manual workflow working**; API not implemented beyond a stub | E-way bill API credentials (NIC or GSP) → `EWB_*` | Download JSON for the bulk-upload tool, record the EWB number and validity, record Part-B vehicle changes, validity alerts, dispatch blocked without EWB above the configured value |
| FASTag | **Import working** | A corporate FASTag account; no direct API is connected | Upload the CSV/Excel statement from the issuer's portal; auto-match to trips; book to trip expenses; reconciliation report |
| GPS tracking | **Driver-app location working** (consent-based) | For vehicle GPS devices: vendor API documentation and key (not integrated) | Location pings from the driver's phone during active trips, only with recorded consent |
| Bank statements | **Import working** (CSV/Excel) | – | Auto-matching + manual reconciliation |
| Tally | **Excel/CSV export & journal import working** | A Tally Excel-import utility/TDL on the Tally side (not supplied) | Export vouchers/ledgers in a fixed column layout |
| GST returns (GSTR-1/3B) | **Not integrated** – no GSP filing | GSP filing access | Sales register and HSN/SAC summary reports for your practitioner; compliance tracker records ARN after filing |
| Payment gateway / UPI collections | Not included | – | Receipts are entered manually; UPI ID can be printed on invoices |

## Items that must be verified by a professional before go-live

* **GST treatments** (Settings → GST treatments) – GTA reverse/forward charge rates, ITC eligibility, exemptions,
  vehicle-hire treatment. Seeded values are marked *not verified*. The ERP applies whatever treatment you select per
  customer / contract / invoice; it does not decide legal eligibility.
* **Statutory due dates** (Compliance → Requirements) – defaults; government extensions are not fetched automatically.
* **Payroll statutory values** (Settings → Payroll) – EPF wage ceiling & rates, ESI rates & gross ceiling,
  Tamil Nadu professional tax half-yearly slabs (vary by local body).
* **LR declaration and terms** – have your legal adviser review the printed declaration.
