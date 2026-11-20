# REST API

Interactive documentation: **`/docs`** (Swagger UI) and **`/redoc`** on the running server. The full
OpenAPI 3 specification is in [`openapi.json`](openapi.json) (152 paths / 173 operations).

## Authentication

```http
POST /api/auth/login        {"username": "...", "password": "...", "otp": "123456"?}
→ {"token": "<JWT>", "user": {...permissions...}}
```
Send `Authorization: Bearer <JWT>` on every request. Tokens are bound to a server-side session (revoked on
logout, password change or user deactivation). `401` → sign in again, `403` → missing permission, `409` →
conflict (duplicate, locked record), `400`/`422` → validation message in `detail`.

## Conventions

* Amounts are decimal strings/numbers in INR; dates `YYYY-MM-DD`; date-times ISO 8601 with time zone.
* List endpoints accept `limit`, `offset`, `q` (search) and field filters, and return `{items, total}`.
* Nothing financial is deleted: cancellations post reversals and are recorded in `/api/audit`.

## Main groups

| Group | Endpoints |
|---|---|
| Master data (generic) | `GET /api/r/{resource}/meta`, `GET/POST /api/r/{resource}`, `GET/PUT/DELETE /api/r/{resource}/{id}` – resources: branches, bank_accounts, customers, vehicles, vehicle_events, drivers, driver_incidents, duty_roster, driver_advances, vendors, routes, toll_plazas, route_tolls, fuel_stations, fuel_cards, fuel_entries, rate_contracts, bookings, maintenance_schedules, tyres, eway_bills, ledgers, gst_treatments, warehouses, items, warehouse_rate_cards, documents, departments, employees, leave_types, leave_requests, salary_advances, compliance_rules, statutory_registers, notification_templates, number_series |
| Freight | `POST /api/freight/calculate`, `GET /api/rates/{id}/history`, `POST /api/rates/{id}/revise` |
| LR | `GET/POST /api/lr`, `GET /api/lr/{id}`, `POST /api/lr/{id}/amend · cancel · deliver · pod · share · ewaybill`, `GET /api/lr/{id}/pdf?fmt=A4|thermal&copy=`, `GET /api/lr/{id}/ewaybill-json` |
| Trips | `GET/POST /api/trips`, `GET/PUT /api/trips/{id}`, `POST /api/trips/{id}/stage · cancel · expenses`, `DELETE /api/trips/{id}/expenses/{eid}`, `GET /api/fleet/availability`, `POST /api/bookings/{id}/convert` |
| Billing | `GET/POST /api/invoices`, `GET /api/invoices/{id}`, `/pdf`, `/cancel`, `/share`, `/einvoice-json`, `/einvoice`, `/einvoice/record`, `/einvoice/cancelled`, `POST /api/receipts` |
| Accounts | `GET/POST /api/vouchers`, `POST /api/vouchers/{id}/cancel`, `GET /api/ledgers/balances`, `POST /api/bank/{ledger}/statement`, `GET /api/bank/{ledger}/reconciliation`, `POST /api/bank/reconcile`, `GET /api/tally/vouchers · ledgers`, `POST /api/tally/import` |
| Fleet | `POST /api/fuel`, `GET /api/fuel/mileage/{vehicle}`, `GET/POST /api/maintenance/jobs`, `POST /api/maintenance/jobs/{id}/complete`, `GET /api/maintenance/due`, `POST /api/tyres/{id}/action`, `POST /api/vehicles/{id}/events`, `GET /api/vehicles/{id}/summary`, `POST /api/fastag/import`, `GET /api/fastag`, `POST /api/fastag/{id}/post-to-trip` |
| Drivers | `GET /api/drivers/{id}/settlement-preview`, `POST /api/drivers/{id}/settle`, `GET /api/driver-settlements` |
| Warehouse | `GET/POST /api/warehouse/docs`, `GET /api/warehouse/stock`, `GET /api/warehouse/scan/{code}`, `GET /api/warehouse/labels` |
| Purchase | `/api/purchase-orders`, `/api/purchase-orders/{id}/receive`, `/api/goods-receipts`, `/api/vendor-bills`, `/api/vendor-bills/{id}/cancel`, `/api/vendor-payments` |
| HR | `GET/POST /api/attendance`, `POST /api/payroll/{YYYY-MM}/compute · post`, `GET /api/payroll/{month}`, `GET /api/payslips/{id}/pdf` |
| Compliance & documents | `/api/compliance/tasks`, `/api/compliance/generate`, `/api/compliance/dashboard`, `/api/registers/{id}/entries`, `POST /api/documents/upload`, `/api/documents/{id}/download · versions · delete` |
| Reports | `GET /api/reports`, `GET /api/reports/{key}?start=&end=&format=xlsx|pdf|csv`, `GET /api/dashboard`, `GET /api/alerts`, `GET /api/export/all` |
| Customer portal | `/api/portal/summary · bookings · shipments · invoices · payments · statement · complaints`, `/api/portal/lr/{id}/pdf · pod`, `/api/portal/invoices/{id}/pdf` |
| Driver app | `/api/driver/me · consent · trips · location`, `/api/driver/trips/{id}/stage · pod · document · expense · incident` |
| Admin | `/api/company`, `/api/company/logo`, `/api/settings/{section}`, `/api/users`, `/api/roles`, `/api/audit`, `/api/login-history`, `/api/sessions`, `/api/backups`, `/api/backups/restore`, `/api/notifications`, `/api/integrations/status` |
| Public | `GET /api/public/verify/{lr|inv}/{number}?s=<signature>` – QR verification page; `GET /api/health` |
