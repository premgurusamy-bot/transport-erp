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

Backlog tests (`test_backlog.py`): route deviation & long stoppage, transshipment, fleet KPIs, outage forms (issued/used/unissued numbers, independent review), TOTP two-step — **all PASS**.

Totals: backend **34 passed**; web typecheck + build **pass**; browser smoke **0 errors** over 49 ERP screens + all portals +
driver app; browser UI click-through workflow (`web/e2e/workflow.cjs`: enquiry → quote → send → acceptance → booking → credit gate) **PASS**; Flutter driver app **3 passed**, management app **2 passed**; `alembic check` **no drift**.

## CI (GitHub Actions)
Run 43607964611 on commit 6c8e865: **backend, web, mobile (debug APKs for both apps), docker (build → boot → seed → login → encrypted backup) all SUCCESS.** The two earlier failures (Android package name, restore across PostgreSQL versions) are DF-07/DF-08.

## Not yet done (honest)
- UI click-through tests beyond the commercial workflow (dispatch/POD/finance are covered at API level).
- Penetration test.

## Load test (sandbox, 4 vCPU, single API worker, PostgreSQL on same machine – indicative only)
`scripts/load_test.py --users 20 --requests 1000`: 76 req/s, **0 errors**; p95: approvals 221 ms, bookings 406 ms, control tower 473 ms, trips 267 ms, trial balance 244 ms, enquiry create 825 ms (serialised numbering and audit-chain lock). Docker image runs 2 API workers by default. Repeat on the real server before go-live.

## Accessibility
`web/e2e/a11y.cjs` (axe-core, WCAG 2 A/AA) on website, login, 9 ERP screens and the customer portal: **no serious or critical violations** after fixes (labels on all selects/inputs, sidebar contrast, underlined text links, visible focus).
- Docker image build/run and APK builds run in GitHub Actions (`.github/workflows/platform.yml`), not in the sandbox.
- Any real-world verification (see REAL_WORLD_PILOT.md). **No simulated test here is real-world verification.**

## How to run
```bash
cd platform/backend && .venv/bin/pytest -q                        # needs PostgreSQL; set GRL_DATABASE_URL to a TEST database
cd platform/web && npx tsc --noEmit && npx vite build
GRL_WEB=http://localhost:5173 node platform/web/e2e/smoke.cjs     # with API + web running and demo seed loaded
GRL_WEB=http://localhost:5173 node platform/web/e2e/workflow.cjs
GRL_WEB=http://localhost:5173 node platform/web/e2e/a11y.cjs
cd platform/backend && .venv/bin/python scripts/load_test.py --users 20 --requests 1000
cd platform/mobile/driver_app && flutter test
```
