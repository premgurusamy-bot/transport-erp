# Requirements traceability

Status key: **Done** = implemented end-to-end and covered by an automated test · **Built** = implemented and exercised
(smoke/UI) but no dedicated automated test yet · **Partial** = core implemented, listed gaps remain · **Mock** = works
against a labelled MOCK adapter; live provider pending · **Pending** = not yet built.
Tests: `backend/tests/test_e2e_core.py` (C), `test_e2e_network.py` (N), `test_security.py` (S), `test_backup_restore.py` (B),
web smoke `web/e2e/smoke.cjs` (W), Flutter tests (F).

| § | Requirement | Module / API | UI | Key permission(s) | Test | Status |
|---|---|---|---|---|---|---|
| 5 | Central identity, RBAC, multi-role users | platform `/auth/*`, `/users`, `/roles` | Admin › Users | users.manage | S: permissions, role change revokes | Done |
| 5 | Tenant isolation customers/owners/vendors/drivers | `operations/access.py`, `/portal/*` | portals | portal.* | S: tenant isolation, N: PTL confidentiality, N: driver sees own trips | Done |
| 5 | Temp attached-driver OTP, trip-scoped, auto-revoke | `/auth/otp/*`, TempDriverAccess | Driver app | driver.app | N: wf7 (revoked after close) | Done |
| 5 | CA/auditor limited by purpose & period | User.access_valid_* , `ca.read` | Admin › Users | ca.read | — | Built |
| 5 | Password hashing, lockout, rate limit, no secret logging | security.py, login attempts, middleware | Login | — | S: lockout, no secrets | Done |
| 5 | MFA / passkeys | `/auth/mfa/*`, TOTP | My security, Admin › Reset 2-step | users.manage (reset) | backlog: TOTP | Done (TOTP; passkeys pending) |
| 5,34 | Tamper-evident audit | `core/audit.py`, `/audit/verify` | Admin › Audit | audit.read | S: tamper detected | Done |
| 5,34 | Maker-checker, no self-approval | `core/services.py` approvals | Approvals | per kind | C/N/S: multiple | Done |
| 5 | Masking of bank/salary/identity | bank_out, emp_out, driver id masked | — | driver.view_sensitive, hr.view_salary | N: wf7 masked account | Done |
| 5 | Secure uploads (type/size/magic, safe names, signed links) | `core/storage.py`, `/documents` | Booking docs, driver expense | documents.* | S: upload validation | Done (malware scan hook only) |
| 6 | Master data with dedup, validation, history | `/masters/*` generic CRUD + audit | Admin › Customers/Masters | masters.* | C: wf1 (customer create) | Done |
| 6 | Sensitive master changes approved (bank details) | `/masters/bank-accounts` | — | masters.approve | N: wf7 | Done |
| 7 | Enquiry capture all channels, dup detection, missing fields | `/enquiries`, `/public/enquiries`, `/portal/customer/enquiries` | Enquiries, Website, Portal | crm.* | C: wf1, S: public | Done |
| 7 | Quotation engine: cost/owner quote/market/selling/margin, protected | `commercial/pricing.py`, `/quotations` | Enquiries › Quote, Quotations | quote.view_cost | C: wf1 cost hidden | Done |
| 7 | Versioned quotes, validity, terms, PTL disclosure | `/quotations/{id}/revise` | Quotations | quote.write | C: wf1 | Done |
| 7 | Below-floor approval, discount cap, AI cannot approve | `_route_approval`, discount cap | Approvals | quote.approve_discount | C: wf1b | Done |
| 8 | Bookings from quotes/manual, validation, feasibility | `/bookings`, `/bookings/{id}/confirm` | Bookings | booking.write | C/N: all flows | Done |
| 8 | Modifications versioned; customer changes are requests; cancellation | PATCH, `/cancel`, modification requests | Booking detail, Portal | booking.write/cancel | — | Built |
| 9 | FTL exclusivity; FTL→PTL only with consent + revised quote | allocation check `ftl_exclusive`, `/convert-to-ptl` | Dispatch | — | C: wf5 | Done |
| 9 | PTL consent, confidentiality, per-consignment LR/labels/POD | Booking.ptl_consent, Package labels, portal filters | Portal, Dispatch | — | N: wf4 | Done |
| 9 | Consolidation engine (corridor, detour, windows, compatibility, capacity, reserve) | `operations/service.consolidation_proposals` | Dispatch › PTL proposals | consolidation.plan | N: wf4, incompatible goods | Done (straight-line distances, provisional) |
| 9 | Configurable, versioned PTL cost allocation; estimated vs actual | `ptl.allocation_formula`, TripLoad est/actual | Trip profitability | settings.write | C: wf6 | Done |
| 9 | Multi-stop, manifests, loading map, failed/partial delivery | trip loads seq, load_plan, POD partial | Trip detail | — | N: wf4 partial | Done (transshipment via verified facilities) |
| 10 | Vehicle states; allocation checks (legal/safety/commercial) | `allocation_checks` | Dispatch › Allocate | dispatch.plan | C: capacity/compliance/defect gates | Done |
| 10 | Double-booking prevention; override with reason only for commercial | `blocking_failures` | Allocate modal | dispatch.override | C: wf5 | Done |
| 10 | Dispatch plan: inspection, scans, LR/e-way, driver ack, authorisation | `dispatch_readiness`, `/dispatch` | Trip detail | dispatch.authorize | C: wf2 blocked until ready | Done |
| 11 | Trip events, delay, ETA source, deviation/long stoppage | `/trips/{id}/events`, worker GPS staleness | Trip detail, Control tower | trip.update | C: wf3 delay | Done (straight-line corridor until maps provider) |
| 11,15 | GPS phone primary, tracker failover, stale/last-known, never fabricated | `record_ping`, `position()`, tracker webhook | Trip, Control tower | gps.view | C: wf3 live | Done (tracker MOCK) |
| 12 | Chain of custody, count/condition/seal exceptions block | `record_custody`, `scan_package` | Trip, Driver app | custody.write | N: wf4 wrong-trip scan | Done |
| 12 | POD with OTP/signature/photo, partial, verification | `/pod/otp`, `/pod`, `/pod/{id}/verify` | Driver app, Trip | — | C: wf3, N: wf4 | Done (photos from Flutter camera + web upload) |
| 13 | LR auto-numbered by FY, QR verify, amendments, cancellation | `operations/lr.py`, `/lr/*` | Booking › LR print | lr.write | C: wf1 LR number | Done |
| 13 | E-way applicability/validity | `ensure_eway`, `eway_ok_for_dispatch` | Trip › E-way | lr.write | C: dispatch flow | Mock |
| 13 | OCR labelled "extracted, not verified" | MockOcr, Document.extracted | Expenses | — | — | Mock |
| 14 | Driver profiles, permanent vs attached | `/drivers` | Fleet › Drivers | driver.* | N: wf7/wf8 | Done |
| 14 | Configurable, versioned, approved remuneration; transparent calc | `fleet/drivers.py`, `/remuneration-rules` | Drivers › Pay & rules, Driver app | remuneration.* | N: wf8 | Done |
| 14 | Settlement readiness (closed trip, POD, expenses reviewed) | `close_trip`, `/driver-earnings/{id}/submit` | Settlements | settlement.* | N: wf8 | Done |
| 14 | Disputes/grievances human review | `/grievances` | Driver app | hr.write | N: wf8 | Done |
| 14 | Safety: parked/one-tap UI, rest reminders | Driver apps | Driver app | — | F | Partial (rest events recorded; no automatic fatigue reminder push) |
| 15 | Camera: on-demand stream via gateway, short-lived token, no DVR secrets | `/vehicles/{id}/camera/{ch}/live` | Trip › Cargo camera | camera.view | — | Mock |
| 16 | Vehicle master, cost centres | `/vehicles`, VoucherLine.cost_centre | Fleet | fleet.* | — | Done |
| 16 | Fuel with tank/odometer/duplicate/mileage anomaly → review only | `fuel_anomalies` | Fleet › Fuel | fleet.write | C: wf6 | Done |
| 16 | Maintenance: preventive schedule, job cards, approvals, defects block | `/job-cards`, `/maintenance/due`, defects | Fleet › Maintenance/Defects | fleet.* | C: defect gate | Done |
| 16 | Tyres/battery lifecycle, cost/km | `/tyres`, `/tyres/{id}/events` | Fleet › Tyres | fleet.write | — | Built |
| 16,31 | KPIs cost/km, revenue/km, utilisation, loaded/empty km | trip profitability, close_trip km | Reports | reports.read | C: wf6 | Done (Fleet › Fleet KPIs) |
| 17 | Owner KYC, acceptance with vehicle/driver identity, own-records portal | `/owner-offers`, `/portal/owner/*` | Fleet › Owners, Owner portal | owner.*, portal.owner | N: wf7 | Done |
| 18 | Vendor master, scorecard, approval | `/masters/vendors`, `/vendors/{id}/score|approval` | Supply › Vendors | vendor.* | — | Built |
| 18 | Procurement → RFQ → approval → PO → receipt → 3-way match | `supply/router.py` | Supply › Procurement, Vendor portal | procurement.* | — | Built |
| 18 | Inventory: min/max, issue to vehicle/job, stocktake, valuation | `/inventory/*` | Supply › Inventory | inventory.* | — | Built |
| 19 | Godown only at verified facilities; basement unverified | `/godown/*`, Facility.verified | Supply › Godown | godown.* | S: unverified blocks | Done |
| 20 | Double-entry, CoA, vouchers, reversal not deletion | `finance/posting.py` | Accounts › Reports | accounts.* | C/N: trial balance balanced | Done |
| 20 | Billing from verified milestones, no duplicate invoices, GST configurable | `billing.generate_invoice` | Accounts › Invoices (print) | invoice.write | C: wf6 | Done |
| 20 | Expenses with evidence, duplicates, approval thresholds | `/finance/expenses` | Accounts › Expenses | accounts.* | C: wf6, S: self-approval | Done |
| 20 | Owner/driver/vendor settlements, maker-checker, no unapproved deductions | `owner_settlement`, `driver_settlement`, vendor invoices | Settlements | settlement.* | N: wf7, wf8 | Done |
| 20 | Payments prepared/approved/executed, idempotent, never autonomous | `/finance/payments` | Settlements & payments | payment.* | N: wf7 | Done (bank API MOCK) |
| 20,31 | Reports: day book, GL, TB, P&L, BS, ageing, GST, TDS, exports PDF/Excel/CSV | `finance/reports.py`, `/reports/export` | Accounts › Reports | reports.* | C: TB/BS balanced | Done |
| 20,31 | Profitability: own/attached/FTL/PTL, contribution vs fully allocated | `trip_profitability`, `profitability_summary` | Reports | reports.read | C: wf6 | Done |
| 21 | Statement import, normalise, dedupe, exact/partial/multiple matching, exception queue | `finance/bank.py` | Accounts › Bank | bank.* | C: wf6 | Done (API connection MOCK; CSV import real) |
| 21 | Unmatched credit never treated as payment | match_one / confirm | Bank | — | C: wf6 | Done |
| 22 | Credit profile, exposure without double counting, warn/block/exception | `commercial/credit.py` | Booking, Customers › Credit | credit.* | C: wf11 | Done |
| 22 | Collections: ageing, priority, promises, disputes, polite reminders, statements | `/finance/collections*`, statement | Accounts › Collections, Portal | collections.write | — | Built |
| 23 | Cash-flow forecast labelled, budget vs actual | `cashflow_forecast`, budgets | Accounts › Cash flow | cashflow.read | — | Built |
| 24 | GST/IRN/e-way/IT via authorised providers | adapters | — | — | — | Mock / Pending external |
| 24,36 | Tally XML export; import with dry-run, exceptions, approval, reversal | `/finance/tally/*`, import batches | Accounts › Tally | accounts.* | — | Built |
| 25 | Employees, attendance, leave, payroll (configurable statutory), exit revokes access | `people/router.py` | HR & SOP | hr.*, payroll.* | — | Built |
| 26 | Customer portal: enquiry/quote/booking/tracking/POD/invoices/statement/pay/complaints | `/portal/customer/*` | Customer portal | portal.customer | S/N | Done (payment gateway MOCK) |
| 26 | Communication hub: consent, opt-out, caps, held sensitive messages | `core/notify.py` | Admin › Messages | — | S: OTP hidden | Done (delivery MOCK) |
| 27 | Website Tamil/English, verified coverage only, enquiries → CRM | `/public/*` | Website | — | S: public | Done |
| 27 | 8 marketing agents, controlled publishing, caps, consent, opportunity DB/map | `/marketing/*`, `/opportunities` | Marketing | marketing.* | — | Built (template drafts; platform APIs MOCK) |
| 28 | Complaints with SLA, escalation, root cause | `/complaints` | Complaints | complaint.* | — | Built |
| 29 | Insurance register, incident register, claims with separated finance, legal (privileged) | `risk/router.py` | Complaints & Claims | incident.*, legal.* | N: wf10 | Done |
| 30 | Control tower, role views, daily cycle, exceptions with owner/due/closure | `/control-tower`, `/daily-plan`, tasks | Control Tower, Management App | controltower.read | W | Built |
| 31 | Owner dashboard KPIs with source/freshness/basis | `/dashboard/owner` | Control Tower | reports.read | W | Built |
| 32 | SOP library, versioning, acknowledgement; checklists with owner/backup | `/sops`, `/checklists` | HR & SOP | sop.* | — | Built |
| 32 | Configurable approval matrix; Owner approval for compliance renewals | `approval.thresholds`, renewal flow | Settings | — | N: wf9 | Done |
| 33 | AI gateway: providers, routing, fallback, budget/alerts, audit, scoped read-only tools | `intelligence/ai.py` | AI Assistants, portals, apps | ai.use, ai.admin | S: AI guardrails | Done (MOCK model; live adapters need keys) |
| 35 | Backups encrypted, integrity checked, restore verified | `scripts/backup.py`, `restore.py` | — | — | B: wf13 | Done |
| 35 | Paper/offline forms recorded with original time, supervisor review | `/sync/events` paper_form | — | sync.write | N: wf12 | Done (numbered forms, single use, supervisor review) |
| 12/38 | Offline sync idempotent | `/sync/events` | Driver apps | sync.write | N: wf12, F | Done |
| 41 | Settings with RBAC, effective dates, versions, audit | `/settings` | Admin › Settings | settings.* | S: settings versioned | Done |
| 3 | Docker, environments, CI | Dockerfiles, compose, `.github/workflows/platform.yml` | — | — | — | Built (images built and booted in CI) |
| 4 | Flutter Driver & Management apps | `mobile/*` | — | — | F | Built (debug APKs built in CI) |
