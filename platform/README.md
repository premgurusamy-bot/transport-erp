# G ROAD LINES – Transport Business Operating System (platform v2)

One integrated system for the whole business: enquiries → quotations → FTL/PTL bookings → credit check →
vehicle/driver allocation → dispatch → live trip → goods custody → POD → invoice → bank receipt →
settlements → profitability, plus fleet, drivers, owners, vendors, godown, accounts, HR, complaints/claims,
marketing, AI assistants and management dashboards.

> **Status (honest):** the application is built and passes its internal acceptance tests using **synthetic data
> and MOCK integrations**. Nothing has been verified with real vehicles, banks, GST portal, GPS trackers, cameras
> or customers yet — that is the **Real-World Pilot** stage (see `docs/REAL_WORLD_PILOT.md`). Every external
> connection is clearly labelled MOCK in the app until it is genuinely connected and tested.

The older V1 "Transport Agent ERP" (Node.js, in the repository root) is **untouched** and still works.
Its data can be moved into this platform using the migration tools (see `docs/DATA_MIGRATION.md`).

## What is in this folder

| Folder | What it is |
|---|---|
| `backend/` | Python **FastAPI** API (modular monolith), PostgreSQL schema + **Alembic** migrations, background worker, tests |
| `web/` | **React + TypeScript** installable PWA: Windows ERP, Control Tower, customer / vehicle-owner / vendor portals, driver web app, public website |
| `mobile/driver_app` | **Flutter** Android Driver App |
| `mobile/management_app` | **Flutter** Android Management App |
| `docs/` | Architecture, requirements traceability, decisions, security, guides, pilot checklist … |
| `scripts/` | Windows PowerShell scripts (setup, start, backup) |
| `docker-compose.yml` | Runs everything (database, API, worker, web) with one command |
| `PROJECT_STATE.json` | Machine-readable progress record used to resume work |

## Quick start on Windows (recommended: Docker Desktop)

1. Install **Docker Desktop** (free for small businesses) and start it.
2. Open **PowerShell** in this `platform` folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
   ```
   It creates `.env` with random secrets, builds and starts everything, and creates the Owner login
   (the password is printed **once** – write it down, then change it after signing in).
   Answer **y** to load clearly-labelled *SYNTHETIC* demo data for training.
3. Open **http://localhost:8080**. To install it as a Windows app: browser menu → *Install G ROAD LINES*.
4. Every day: `scripts\start-windows.ps1`. Backups: `scripts\backup-windows.ps1` (copy the `backups` folder off the PC).

**Keep `GRL_BACKUP_KEY` from `.env` somewhere safe and separate** – backups cannot be restored without it.

### Developer mode (no Docker)
Needs Python 3.12+, PostgreSQL 16, Node 22. Run `scripts\dev-native.ps1`, or manually:
```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export GRL_DATABASE_URL=postgresql+psycopg://postgres:PASSWORD@localhost:5432/groadlines
.venv/bin/alembic upgrade head && .venv/bin/python -m app.seed --demo
.venv/bin/uvicorn app.main:app --port 8000          # API + docs at http://localhost:8000/api/docs
cd ../web && npm install && npm run dev               # http://localhost:5173
```

### Tests
```bash
cd backend && .venv/bin/pytest -q          # 29 end-to-end/security/backup tests against a real PostgreSQL test DB
cd web && npx tsc --noEmit && npx vite build
cd mobile/driver_app && flutter test       # and mobile/management_app
node web/e2e/smoke.cjs                     # browser smoke test of every screen (needs API + web running)
```

## Who signs in where

| User | Where | How |
|---|---|---|
| Owner/Director, managers, dispatch, accounts, HR, support, sales, fleet, compliance, store, admin | `/erp` (Windows PWA) and the Management App | email/phone + password |
| Customers (admin/user) | `/portal/customer` | email + password (created by G ROAD LINES or the customer admin) |
| Attached vehicle owners | `/portal/owner` | email + password |
| Vendors | `/portal/vendor` | email + password |
| Company drivers | Driver App or `/driver` | phone + OTP |
| Attached/temporary drivers | Driver App or `/driver` | phone + OTP – **only while a trip is assigned**; access ends automatically when the trip closes |
| CA / auditor | `/erp` (read-only finance) | individually authorised, with purpose and end date |

Demo users (only with `--demo`): `operations.manager@demo.local`, `dispatcher@demo.local`, `accounts@demo.local`,
`customer1@demo.local`, `owner1@demo.local`, `vendor1@demo.local` … password `Demo@12345`; driver phones `9000000201`–`204`
(the MOCK OTP is shown on screen in development only).

## Documentation map
- `docs/USER_GUIDE.md` – daily use of the ERP · `docs/DRIVER_GUIDE.md` – driver app · `docs/ADMIN_GUIDE.md` – users, roles, approvals, settings
- `docs/MASTER_ARCHITECTURE.md` · `docs/DATABASE_SCHEMA.md` · `docs/API_DOCUMENTATION.md` · `docs/SECURITY.md`
- `docs/REQUIREMENTS_TRACEABILITY.md` · `docs/IMPLEMENTATION_PLAN.md` · `docs/PROGRESS.md` · `docs/TEST_PLAN.md` · `docs/DEFECTS.md`
- `docs/DECISION_REGISTER.md` · `docs/ASSUMPTIONS.md` · `docs/BLOCKERS.md` · `docs/INTEGRATIONS.md`
- `docs/DEPLOYMENT.md` · `docs/BACKUP_RECOVERY.md` · `docs/DATA_MIGRATION.md` · `docs/REAL_WORLD_PILOT.md`
