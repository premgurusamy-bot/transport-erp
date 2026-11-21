# Sree Venkateswara Logistics – Transport & Logistics ERP

A complete ERP for goods transportation, fleet operations, industrial logistics and godown management,
built for Sree Venkateswara Logistics, Coimbatore (Tamil Nadu). INR, Indian number/date formats,
GST, English + Tamil interface.

| Part | Technology |
|---|---|
| Backend / REST API | Python 3.12+ · FastAPI · SQLAlchemy 2 · Alembic |
| Database | PostgreSQL 16 |
| Web app (desktop + phone layout, installable PWA) | React 18 · TypeScript · Vite |
| Documents | ReportLab PDF (A4 + 80 mm thermal), openpyxl Excel, CSV |
| Security | bcrypt passwords, JWT bound to server-side sessions, optional TOTP 2FA, role-based permissions, Fernet field encryption, full audit trail |

```
svsl-erp/
  backend/            FastAPI app (app/), Alembic migrations, pytest suite (tests/)
  frontend/           React + TypeScript single-page app (customer portal and driver app included)
  desktop/            Windows app (Electron) bundling PostgreSQL + the server → installer .exe
  mobile/             Android app (Capacitor) → .apk
  docs/               INSTALL, DEPLOYMENT, ADMIN_MANUAL, USER_MANUAL, INTEGRATIONS, API, openapi.json
  deploy/             nginx (HTTPS) and systemd samples
  Dockerfile, docker-compose.yml, run-dev.sh, START-WINDOWS.bat
```

## Install as apps

* **Windows:** `SVL-ERP-Setup-1.0.0.exe` – one installer with the database and server included; the office PC becomes the ERP server.
* **Android:** `SVL-ERP.apk` – connects phones to that server (drivers, customers, staff).

Both are on the repository's **Releases** page, built by GitHub Actions. Step-by-step: [docs/INSTALL-APPS.md](docs/INSTALL-APPS.md).

## Quick start (development)

```bash
# PostgreSQL running locally, database created:  createdb svsl_erp
cd svsl-erp/backend
cp .env.example .env            # set DATABASE_URL, SECRET_KEY, DATA_ENCRYPTION_KEY
pip install -r requirements.txt
alembic upgrade head
python -m app.seed              # prints the one-time admin password
cd ../frontend && npm ci && npm run build
cd ../backend && uvicorn app.main:app --port 8000
# open http://localhost:8000  – sign in as "admin" and change the password
```

For a training database add demo data with `python -m app.seed --demo` (clearly marked *DEMO*; never on the
production database). Full instructions: [docs/INSTALL.md](docs/INSTALL.md). Production: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Modules (all connected to one database)

| # | Module | Highlights |
|---|---|---|
| 1 | Company master | Legal/trade name, GSTIN (checksum-validated), PAN, CIN, addresses, logo, bank accounts, signatory, terms, FY; multiple branches / warehouses / operational locations |
| 2 | Customers | Credit limit & period, category, contracts, billing rules, auto ledger, outstanding, credit alerts, profitability, trip history, statement (PDF/Excel), documents, portal logins |
| 3 | Vehicles | Unlimited fleet (24 initially), full master incl. loan/EMI, insurance, FC, permits, PUC, road tax, GPS/FASTag; purchase / sale / transfer / deactivation with accounting; availability board; income, expenditure, profitability, utilisation, downtime; expiry alerts |
| 4 | Drivers | Licence & expiry, Aadhaar & bank no. encrypted (restricted), salary/bata/food/trip/km allowances, attendance, duty roster, advances, settlements, accidents & fines, performance, GPS consent |
| 5 | LR / consignments | Unique per-FY numbering, FTL/PTL, multiple consignments & delivery points, return LR, HSN, e-way bill & e-invoice refs, freight from contract or manual, advance/balance, amendment with authorisation and before/after history, cancellation with audit, A4 & thermal PDF, QR verification, WhatsApp / email sharing |
| 6 | Trips | 12-stage lifecycle with validations (vehicle/driver availability, document expiry, e-way bill before dispatch, km readings), expenses posted to accounts, daily trip sheet, delays, POD, return trips, trip P&L |
| 7 | Freight rate engine | 12 pricing bases (trip, turn, vehicle, km, tonne, kg, piece, load, monthly fixed, route, distance slab, weight slab) + minimum guarantee, waiting, detention, loading/unloading, extra stops, return-load; customer/route/vehicle-type/goods-specific; versioned revisions with effective dates – history never overwritten |
| 8 | Invoice & GST | Tax invoice, bill of supply, proforma, debit/credit notes, advance receipt; LR-wise, trip-wise, consolidated, monthly-contract, warehouse and manual billing; configurable GST treatments (GTA RCM/FCM, exempt, vehicle hire, warehousing…), CGST/SGST/IGST by place of supply, RCM shown not charged; cancellation by reversal; e-invoice JSON + IRN recording; amount in words |
| 9 | Accounts | Double-entry (balanced vouchers enforced by code and DB constraints), journal/payment/receipt/contra/sales/purchase/notes, reversal instead of deletion, period lock, bill-wise allocation, TDS, bank reconciliation with statement import, cash/bank/day book, ledgers, trial balance, P&L, balance sheet, cash flow, ageing, Tally Excel/CSV export & journal import |
| 10 | Diesel & fuel | Stations, cards, entries (office & driver app), full-tank-to-full-tank km/L, vehicle- & driver-wise reports, abnormal consumption alerts |
| 11 | Maintenance | Job cards with parts/labour/GST, vendor bills, downtime, preventive schedules by km & date, reminders, tyre & battery life history with cost per km |
| 12 | Tolls & routes | Routes, toll plazas, FASTag statement import (CSV/Excel), auto-matching to trips, booking to trip expense, vehicle-wise toll statement, reconciliation, route profitability |
| 13 | Godown / warehouse | Multiple godowns, item/SKU/HSN, batches, customer-owned stock, inward/outward/transfer/damage/shortage/stock count, stock register, loading/unloading registers, QR labels & camera/USB scanning, storage & handling rental billing |
| 14 | Purchase & vendors | Vendor master with ledger, purchase orders, goods receipts, vendor bills (GST input, RCM, TDS), payments with allocation, outstanding |
| 15 | Documents | Versioned upload with SHA-256 integrity, type/expiry/links, search, role restriction, download, included in backups |
| 16 | Customer portal | Own data only: book vehicles, track shipments, download LR / invoices / POD, outstanding, payments, statement, complaints |
| 17 | Driver app (PWA) | Assigned trips, route, loading/departure/delivery confirmation, POD & receipt photos, expenses, diesel, odometer, incidents, consented location sharing only during active trips |
| 18 | HR | Employees, departments, attendance (staff & drivers), leave, advances, payroll with EPF/ESI/PT/TDS (configurable), payslips, exit records |
| 19 | Compliance | Configurable statutory calendar (GST, TDS, IT, EPF, ESI, PT, labour), statutory registers, document expiry dashboard – never marked filed without ARN + uploaded acknowledgement |
| 20 | Reports | 40 reports (operations, profitability, fleet, finance, GST, accounts, management, warehouse, HR) – every one exports to Excel, PDF and CSV |
| 21 | Notifications | Templates per event & channel; in-app (working), email via SMTP, WhatsApp Business API, SMS gateway (need credentials); delivery log |
| 22 | Users & security | 11 default roles + custom roles with a permission matrix, lockout, 2FA, sessions, login history, audit trail, encrypted fields, backups & verified restore |
| 23 | Dashboard | Fleet, today's trips/LR/billing, revenue, receivables, fuel & maintenance cost, profit, pending deliveries/POD, expiring documents, alerts, trends; date & customer filters |
| 24 | Settings | Company, GST, numbering, FY lock, alerts, payroll statutory values, notification templates, backup schedule, retention, language |

## Tests

```bash
cd backend && python -m pytest -q        # 55 tests: core, freight engine, end-to-end workflows, security, modules, backup/restore
```

## What needs external subscriptions or approvals

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md). In short: e-invoice IRP/GSP and e-way bill API credentials,
SMTP mailbox, WhatsApp Business (Meta) account with approved templates, a DLT-registered SMS gateway, and
FASTag/GPS data providers. Until they are configured the ERP works through manual portal workflows and **never
reports an IRN, e-way bill or message as generated/sent unless the external service confirms it.**

GST treatments, statutory due dates, PT slabs and payroll rates are seeded as *defaults marked "not verified"* –
confirm them with your GST practitioner / auditor before go-live.
