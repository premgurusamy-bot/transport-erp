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
1. Build and run the Docker images on the target Windows PC / CI; run `alembic upgrade head` + seed there (X-19).
2. Build signed release APKs (X-18); add camera-based QR scanning and photo capture to the Flutter Driver App (currently label entry + web upload).
3. ERP screens for items that are API-only today: attendance/leave entry, budget entry, driver advances, vendor scorecard entry, customer modification-request queue.
4. Printable numbered paper outage forms (enquiry, booking, dispatch, trip, POD, fuel, expense, incident).
5. Route-deviation geofencing and long-stoppage detection from GPS tracks.
6. Cross-dock / transshipment workflow between verified facilities.
7. Fleet KPI dashboard (cost/km, mileage trend, downtime) as a dedicated screen (data available via reports).
8. Load/performance tests and an accessibility audit.
9. Live adapters as credentials arrive (X-01…X-13), each with a sandbox test before being marked LIVE.
10. MFA/passkeys for staff (optional per brief).
