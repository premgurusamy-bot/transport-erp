# Decision register

Categories: **Decided** (built this way) · **Configurable** (default chosen, changeable in Settings) · **Pending verification**
(needs a professional/real-world check) · **External action** (needs the business/user).

| ID | Decision | Category | Rationale / where |
|---|---|---|---|
| D-01 | Build platform v2 in `platform/` alongside the existing V1 Node ERP; do not modify or delete V1 | Decided | Preserve existing user work; migration path via Tally/Excel import |
| D-02 | Python FastAPI modular monolith + PostgreSQL + Alembic (as mandated) | Decided | §3; no microservices/Kubernetes |
| D-03 | UUID primary keys + human codes (BKG/2026-27/00001) with FY-bound numbering under row lock | Decided | Unguessable ids (IDOR), readable references |
| D-04 | Money NUMERIC(14,2); JSON money as strings | Decided | No binary floats anywhere |
| D-05 | Opaque server-side session tokens (hashed) rather than JWT | Decided | Immediate revocation on role change/exit/trip end |
| D-06 | scrypt password hashing (stdlib), AES-256-GCM for stored files and backups | Decided | No extra native deps; strong primitives |
| D-07 | Every integration behind an adapter with explicit MOCK/SANDBOX/LIVE mode; UI shows mode | Decided | Never claim live integrations |
| D-08 | One booking = one customer consignment = one LR; PTL trip carries several bookings | Decided | Natural per-customer LR/POD/rates/custody |
| D-09 | Redis provisioned but unused until multi-instance scale | Decided | Avoid unjustified components |
| D-10 | Generic maker-checker approvals with per-kind handlers | Decided | One consistent control for discounts, credit, payments, settlements, renewals, bank details, payroll, budgets, claims, content |
| D-11 | Legal/safety allocation failures non-overridable; credit & owner acceptance only via their own approvals; commercial checks overridable with reason | Decided | §10 |
| D-12 | GST on GTA freight defaults to RCM per customer; FCM rates configurable (12%/5%) | Configurable + Pending verification | Must be confirmed by CA |
| D-13 | TDS 194C rates configurable; deducted on owner settlements unless 194C(6) declaration recorded | Configurable + Pending verification | CA to confirm |
| D-14 | E-way applicability by configurable value threshold (₹50,000 default) | Configurable + Pending verification | State/goods exemptions vary |
| D-15 | Pricing cost model (fuel/km, maintenance/km, driver/day, fixed/day, deadhead %, toll/km) | Configurable | `pricing.cost_rates`; calibrate from real costs in pilot |
| D-16 | Minimum margin 8%, max discount 10% (PTL 15%), quote validity 7 days | Configurable | Owner-only settings |
| D-17 | PTL allocation formula hybrid weight 50% / volume 30% / floor 20%, capacity reserve 5% | Configurable | Versioned in settings |
| D-18 | Credit policy: warn 80%, block 100%, block when overdue > 60 days; no profile ⇒ full advance | Configurable | Owner-only |
| D-19 | GPS stale after 15 min; phone primary, tracker failover | Configurable | `gps.stale_minutes` |
| D-20 | Distances from lane master; otherwise straight-line × 1.25 labelled ESTIMATED | Decided (temporary) | Replace with maps provider when available |
| D-21 | AI default provider MOCK (deterministic summaries); Anthropic/OpenAI activate only with keys; tools read-only and scoped | Decided | §33 |
| D-22 | Customer app delivered as PWA; Flutter only for Driver and Management | Decided | §4 |
| D-23 | Driver web app (`/driver`) in addition to Flutter app | Decided | Temporary drivers without app install; same APIs |
| D-24 | Statutory payroll values are placeholders in settings | Configurable + Pending verification | CA/consultant |
| D-25 | Basement godown recorded as NOT verified; custody blocked there | Decided | §19 |
| D-26 | Backups: pg_dump custom format, AES-GCM with a key separate from DB credentials, manifest with row counts and audit-chain head | Decided | §35; RTO/RPO proposed (24h/8h) and NOT yet tested in production |
| D-27 | Audit is hash-chained (tamper-evident); not described as immutable | Decided | §5 |
| D-28 | Initial own vehicles seeded with placeholder registrations TN00GR0001-3 and status *unavailable* until real compliance documents are entered | Decided | Real registrations unknown; avoids dispatch on fake compliance |
