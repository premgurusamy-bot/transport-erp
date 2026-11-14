# Implementation plan (phases from the master prompt)

| Phase | Scope | Status |
|---|---|---|
| 0 Foundation | Workspace inspection (V1 Node ERP found and preserved), repository structure, registers, architecture | Done |
| 1 Core platform | Auth/RBAC/tenancy, audit chain, masters, documents, notifications, configuration, DB/migrations, backup | Done |
| 2 Commercial | CRM, locations/lanes, enquiry, pricing/quotation, FTL/PTL booking, credit gate | Done |
| 3 Transport operations | Vehicles/drivers/owners, compliance, allocation/dispatch, LR/e-way, trips, GPS abstraction, Driver App, POD/custody | Done (live GPS/e-way MOCK) |
| 4 Fleet & supply | Fuel, maintenance, tyres, owner portal, vendors/procurement/inventory, godown, PTL consolidation, goods safety | Done / Built |
| 5 Finance | Double entry, invoices, expenses, bank import & reconciliation, settlements, payments, credit/collections, Tally, GST/TDS registers | Done (bank/GST live MOCK) |
| 6 Customer & business development | Portal/PWA, website, communications hub, complaints/claims, insurance/legal, marketing | Done / Built |
| 7 Intelligence | HR/payroll, SOP/governance, control tower, BI/profitability, cash-flow, AI gateway + 7 assistants, 8 marketing agents | Done / Built |
| 8 Integrations & hardening | Adapters (MOCK), security tests, Tamil/English foundation, offline sync, backup/DR, Docker, CI | Partial – live integrations external; see backlog |
| 9 Real-world verification | Pilot with 3 own vehicles | Not started (by design – after development) |

## Remaining backlog (ordered)
1. ~~Docker images~~ – now built, booted, seeded and backed up in CI (`docker` job); still to be run on the target Windows PC.
2. ~~Camera QR scanning and POD photo capture in the Flutter Driver App~~ – done; debug APKs built in CI. Release signing key still needed (X-18).
3. ~~ERP screens for API-only items (attendance/leave, budget entry, driver advances, vendor scorecard, change-request queue)~~ – done.
4. ~~Numbered outage paper forms~~ – done (issue PDF, single-use numbers, supervisor review).
5. ~~Route-deviation and long-stoppage detection~~ – done (straight-line corridor until a maps provider is connected).
6. ~~Cross-dock / transshipment~~ – done (verified facilities only; PTL only).
7. ~~Fleet KPI dashboard~~ – done.
8. ~~Load test and accessibility audit~~ – done (scripts in `backend/scripts/load_test.py`, `web/e2e/a11y.cjs`); repeat on target hardware.
9. Live adapters as credentials arrive (X-01…X-13), each with a sandbox test before being marked LIVE.
10. ~~MFA~~ – TOTP two-step sign-in done (passkeys not implemented).
11. Remaining: live adapters (item 9), penetration test, native-speaker review of Tamil text, road-geometry corridors via maps provider, Redis-backed rate limiter for multi-worker deployments, bookings-list query optimisation (N+1) if volumes grow.
