# Security: threat model and controls

## Assets
Customer data and cargo details · money (payments, bank details, settlements) · financial records and tax data · driver/employee
personal and salary data · GPS/camera data · documents/evidence · credentials and API keys.

## Threats → controls (all enforced server-side)

| Threat | Control | Where | Tested |
|---|---|---|---|
| Account takeover / brute force | scrypt hashes; lockout after 5 failures/15 min; per-IP rate limit on auth/public endpoints; OTP hashed (HMAC), 5-min expiry, 5 attempts | `core/security.py`, `platform/router.py`, `main.py` | S: lockout |
| User enumeration | Same responses for unknown accounts (login, OTP request) | `platform/router.py` | S |
| Session theft / stale access | Opaque random tokens stored only as SHA-256; expiry; logout; revocation on role change, deactivation, password change, employee exit, trip end (temp drivers) | `deps.py`, `TempDriverAccess` | S: role change; N: wf7 temp driver |
| Broken access control / IDOR | Permission dependency on every route; tenant-scoped queries; foreign records return 404 | `deps.require`, `operations/access.py`, portals | S: tenant isolation; N: PTL; N: driver |
| Privilege misuse / fraud | Maker-checker with self-approval refusal; bank-account changes need approval; payments prepared → approved → executed by different users; idempotent execution | `core/services.py`, finance | C/N/S |
| Insider tampering with history | Hash-chained audit with verification endpoint; vouchers never edited (reversal only); versioned config, bookings, LR, SOP, remuneration rules | `core/audit.py`, posting | S: tamper detected |
| Data leakage between PTL customers | Customer views filter loads/milestones to own booking; raw trip API not available to customers; LR QR verification shows no customer details | portals, `trip_out(for_customer_id)` | N: wf4 |
| Exposure of internal costs | Customer-facing quote serializer whitelists fields; cost/margin only with `quote.view_cost`; owners see only their hire | `commercial/router.py`, owner portal | C: wf1; N: wf7 |
| Injection (SQL/XSS) | SQLAlchemy parameterised queries only; React escapes output; strict CSP via nginx; JSON APIs | everywhere | — |
| CSRF | Bearer tokens in headers (no cookies) – browser cannot auto-send credentials | `web/src/api.ts` | — |
| Malicious uploads | Type allow-list, magic-byte check, 15 MB limit, safe filenames, encrypted storage, short-lived HMAC-signed links, `nosniff`, malware-scan hook | `core/storage.py` | S: upload validation |
| Secrets in code/logs | Env-only config; `.env` git-ignored; startup refuses weak secret or dev-OTP exposure in staging/production; audit redacts password/otp/token/pin keys; OTP bodies hidden in message log | `config.py`, `audit.py` | S |
| AI overreach / data leaks | AI tools are read-only and scoped by the caller's principal; assistants restricted per app/role; no AI write path; budget caps; usage audit | `intelligence/ai.py` | S: AI guardrails |
| GPS/camera privacy | Phone GPS only during dispatched trip after recorded consent; no customer/driver camera access; attached camera only with owner permission; stream tokens short-lived; DVR credentials never sent to clients | operations router | C: wf3 |
| Replay / duplicate submissions | `client_event_id` for offline events/scans, payment idempotency keys, duplicate detection for receipts, expenses, bank rows, vendor invoices, statement files | sync, finance, bank | N: wf12 |
| Backup theft | Backups AES-256-GCM encrypted with a separate key; integrity manifest; restore refuses tampered files and refuses to overwrite live DB without explicit flag | `scripts/backup.py`, `restore.py` | B |

## Not yet implemented / to do before production
- MFA/passkeys for staff accounts (optional per brief, recommended for Owner/Accounts).
- Malware scanning engine (ClamAV or provider) behind the existing upload hook.
- Distributed rate limiting (Redis) if more than one API instance runs.
- Penetration test and dependency audit sign-off (CI runs `pip-audit`/`npm audit` informationally).
- TLS termination (reverse proxy / hosting provider) – the compose file serves HTTP on localhost only.

## Incident response (summary)
1. Isolate: disable affected users (`/users/{id}/deactivate`), revoke sessions, rotate `GRL_SECRET_KEY` (invalidates links) and provider keys.
2. Preserve: export audit (`/audit`), run `/audit/verify`, keep server logs; do not delete data.
3. Restore if needed from the last verified backup to a new database, verify (row counts, audit head, ledger balance), then switch.
4. Notify affected parties as legally required; record in Incidents (kind `cyber`).
