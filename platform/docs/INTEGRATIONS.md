# Integrations

All integrations are adapters in `backend/app/integrations/adapters.py`. **Current mode of every adapter: MOCK.**
The ERP shows the mode in Admin › Integrations and labels mock outputs on screen (e.g. "MOCK e-way bill – not filed",
"SIMULATED bank execution – no money moved", "SIMULATED STREAM – no DVR hardware connected").
Core ERP operations never depend on an integration being available.

| Kind | Adapter now | What works today | To go LIVE |
|---|---|---|---|
| Bank (statements, payments, account check) | `mock_bank` | CSV statement import (real), matching, reconciliation; payment execution simulated or recorded manually with UTR from bank portal | Bank corporate API/H2H or authorised aggregator; sandbox test; never store net-banking passwords/OTPs (X-01) |
| GST / GSTIN / IRN | `mock_gsp` | Offline GSTIN format + check-digit validation; IRN mock | GSP/ASP credentials, sandbox, CA sign-off (X-02) |
| E-way bill | `mock_eway` | Applicability rule (configurable threshold), validity gate at dispatch, manual entry of real e-way numbers | GSP/NIC e-way API credentials (X-02) |
| SMS / WhatsApp / Email | `mock_sms` / `mock_whatsapp` / `mock_email` | Outbox, consent/opt-out, caps, held sensitive messages; delivery simulated | DLT-registered SMS provider, WhatsApp BSP + templates, SMTP/API (X-05, X-06) |
| Payment gateway | `mock_gateway` | Order creation simulated; confirmation must be server-side + bank reconciliation | Merchant account + webhook signature verification (X-07) |
| Maps | `haversine_estimate` | Lane master distances; otherwise straight-line × 1.25 labelled ESTIMATED | Maps/routing provider key (X-08) |
| GPS tracker | webhook `/api/v1/gps/tracker-webhook` (shared key) | Accepts tracker pings; phone→tracker failover logic | Vendor API/SDK + devices (X-09) |
| Camera / DVR | `mock_dvr_gateway` | Permission-checked, audited, short-lived stream tokens (simulated) | DVR SDK + streaming gateway; verify compatibility before purchase (X-10) |
| OCR | `mock_ocr_regex` | Pattern extraction from text receipts, labelled "EXTRACTED – NOT VERIFIED" | OCR provider |
| AI | `mock` + Anthropic/OpenAI HTTP adapters | Deterministic summaries over scoped data; usage/budget tracking | Set `GRL_ANTHROPIC_API_KEY` or `GRL_OPENAI_API_KEY` and `ai.routing.default` (X-12) |
| Tally | file-based XML | Export vouchers to Tally XML; import Tally XML with dry-run/approval/reversal | Confirm Tally edition; optional ODBC/HTTP integration (X-04) |
| Social / GBP | MOCK publish | Content queue, approvals, caps, consent | Platform API access (X-13) |
| Object storage | encrypted local disk | AES-GCM encrypted files + metadata in DB + signed links | S3-compatible bucket (X-11) |

## Rule for going live
1. Read the provider's current official documentation; never assume capabilities.
2. Implement the LIVE adapter class next to the MOCK one; keep the same interface.
3. Test in the provider sandbox; record evidence in `TEST_PLAN.md`.
4. Set `verified_live_at` only after an authenticated live call succeeded; the UI then shows LIVE.
