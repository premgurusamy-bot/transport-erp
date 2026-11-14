# Test plan and results

## Strategy
- **API end-to-end tests** (pytest + FastAPI TestClient) against a real PostgreSQL test database rebuilt from the models and seeded with
  SYNTHETIC users. Tests use only public APIs, exactly as the apps do. `backend/tests/`.
- **Security/tenant/AI tests** in the same suite. **Backup/restore** uses real `pg_dump`/`pg_restore` into a scratch database.
- **Web**: TypeScript strict typecheck + production build; Playwright smoke test opening every ERP screen and every portal,
  failing on console errors or API errors (`web/e2e/smoke.cjs`).
- **Mobile**: `flutter analyze` + unit/widget tests for both apps.
- **Migrations**: `alembic upgrade head` on an empty DB and `alembic check` (no drift between models and migrations).

## Critical workflow coverage (master prompt §38)

| # | Workflow | Test | Result (2026-11-14, sandbox, synthetic data, MOCK integrations) |
|---|---|---|---|
| 1 | Enquiry → quotation → accepted booking (+ cost protection, below-floor approval, discount cap) | `test_wf1_*`, `test_wf1b_*` | PASS |
| 2 | Booking → credit validation → allocation → dispatch | `test_wf2_wf3_*`, `test_capacity_and_compliance_gates` | PASS |
| 3 | Dispatch → tracking → delay → delivery → POD → close | `test_wf2_wf3_*` | PASS |
| 4 | PTL multi-customer → consolidation → scans → separate POD; confidentiality | `test_wf4_*`, `test_ptl_incompatible_goods_rejected` | PASS |
| 5 | FTL exclusivity (no override) | `test_wf5_ftl_exclusivity` | PASS |
| 6 | Expenses → voucher → invoice → bank receipt → reconciliation → profitability; TB & BS balanced | `test_wf6_*` | PASS |
| 7 | Attached owner quote → acceptance → docs → trip → temp driver access revoked → settlement → maker-checker bank account → payment | `test_wf7_*` | PASS |
| 8 | Driver duty → inspection → trip → expenses → POD → remuneration → approval → settlement; grievance | `test_wf8_*` | PASS |
| 9 | Renewal → quote → Owner approval → payment evidence → updated compliance | `test_wf9_*` | PASS |
| 10 | Incident → claim → approved financial treatment → cash received | `test_wf10_*` | PASS |
| 11 | Credit limit → exposure → block → authorised exception; no-profile advance rule | `test_wf11_*` | PASS |
| 12 | Offline events → reconnect → idempotent sync (replay, partial reject, original time) | `test_wf12_*` | PASS |
| 13 | Backup → restore → integrity verification; tampered backup refused | `test_wf13_*` | PASS |

Security tests: unauthenticated access, lockout & no enumeration, server-side permissions, tenant isolation & IDOR,
self-approval, audit tamper detection, no secrets in audit/logs, role change revokes sessions, owner-only policy settings,
upload validation & signed links, AI guardrails & budget cap, integrations reported as MOCK, public endpoints & honeypot,
unverified godown blocks custody — **all PASS**.

Totals: backend **29 passed**; web typecheck + build **pass**; browser smoke **0 errors** over 48 ERP screens + all portals +
driver app; Flutter driver app **3 passed**, management app **2 passed**; `alembic check` **no drift**.

## Not yet done (honest)
- UI end-to-end tests that click through full workflows (only API-level E2E + screen smoke today).
- Load/performance tests; accessibility audit; penetration test.
- Docker image build/run (sandbox has no container network – X-19); Android APK build (needs Android SDK – CI job prepared).
- Any real-world verification (see REAL_WORLD_PILOT.md). **No simulated test here is real-world verification.**

## How to run
```bash
cd platform/backend && .venv/bin/pytest -q                        # needs PostgreSQL; set GRL_DATABASE_URL to a TEST database
cd platform/web && npx tsc --noEmit && npx vite build
GRL_WEB=http://localhost:5173 node platform/web/e2e/smoke.cjs     # with API + web running and demo seed loaded
cd platform/mobile/driver_app && flutter test
```
