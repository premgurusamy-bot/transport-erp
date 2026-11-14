# Master architecture

## Shape: one modular monolith, one database
```
 Windows ERP PWA ─┐   Customer/Owner/Vendor portals ─┐   Website ─┐   Driver App (Flutter) ─┐   Management App (Flutter) ─┐
                  └──────────────── HTTPS + bearer session token (no client touches the database) ─────────────────────┘
                                                         │
                                      FastAPI application  (app/main.py)
   ┌───────────────┬──────────────┬───────────────┬──────────────┬────────────┬─────────────┬──────────────┬───────────────┐
   platform        masters        commercial      operations     fleet        finance       supply         risk / people
   (identity,      (customers,    (CRM, pricing,  (allocation,   (vehicles,   (double-entry, (procurement,  (complaints, claims,
   RBAC, audit,    owners,        quotations,     dispatch,      compliance,  invoices,     inventory,     legal, HR, payroll,
   config,         vendors,       bookings,       trips, GPS,    fuel, tyres, receipts,     godown)        SOP, checklists)
   approvals,      locations,     credit gate)    custody, POD,  maintenance, bank recon,
   documents,      goods, …)                      LR/e-way,      drivers,     settlements,  intelligence (control tower, BI,
   notifications,                                 consolidation) remuneration) payments,     AI gateway, marketing, sync)
   integrations)                                                              reports,     portals (tenant-scoped APIs)
                                                                              Tally)
                                                         │
                     PostgreSQL 16 (authoritative)   ·   encrypted object storage (documents/photos/POD)   ·   worker (jobs)
                                                         │
                     Provider adapters: bank · GST/IRN · e-way · SMS · WhatsApp · email · payment gateway · maps · GPS tracker
                                        · DVR/camera · OCR · AI (Anthropic/OpenAI) · Tally (file) — all MOCK until verified
```

## Module boundaries and rules
- Each module owns its tables (`app/modules/<module>/models.py`) and exposes APIs in `router.py`.
  Cross-module calls go through service functions (e.g. `operations.service.allocation_checks`, `finance.posting.post_voucher`),
  never through another module's HTTP API, and never by bypassing the owning module's rules.
- **Cross-cutting core** (`app/core`): configuration (`config.py`), DB session (`db.py`), authentication/permissions
  (`deps.py`, `rbac.py`), hash-chained audit (`audit.py`), versioned business configuration + numbering + maker-checker
  approvals + exception tasks (`services.py`), notifications hub (`notify.py`), encrypted storage (`storage.py`).
- **Maker-checker** is generic: a module calls `request_approval(...)`; a different authorised user decides via
  `/approvals/{id}/decide`; the module's registered `@on_approval(kind)` handler applies the result. Self-approval is refused.
- **Gates** return HTTP 422 with every failed check (`BlockedByRule`) so users see exactly why something is blocked.
  Legal and safety failures are never overridable; commercial ones only with `dispatch.override` + reason (audited);
  credit and owner acceptance only by their own approvals.
- **Money** is `NUMERIC(14,2)` in the database, `Decimal` in Python, and serialised as exact strings in JSON.
- **Time** is stored as UTC `timestamptz`; the UI shows Asia/Kolkata. Offline events keep the device's original time and source.
- **Tenancy**: customer/owner/vendor/driver users carry a scope id; every portal query filters by it
  (`modules/operations/access.py`, `modules/portals/router.py`). Unknown or foreign records return 404 (no existence leak).

## Why these choices
- Modular monolith (not microservices) for a small team: one deploy, one transaction boundary, simple backups (DECISION D-02).
- Opaque, revocable server-side sessions instead of JWT so role changes/exits revoke access immediately (D-05).
- Redis is provisioned in docker-compose but not yet used: the API rate limiter is in-process and the worker polls the DB.
  Introduce Redis when running more than one API instance (D-09).
- Integrations sit behind adapter classes with an explicit `mode` so the UI can never present MOCK as LIVE (D-07).

## Applications
| App | Tech | Notes |
|---|---|---|
| Windows ERP | React PWA (`web/`, `/erp`) | Installable from Edge/Chrome; responsive; printable invoice/LR |
| Management App | Flutter Android | Control tower, KPIs, approvals, alerts, AI (`mobile/management_app`) |
| Driver App | Flutter Android + web fallback (`/driver`) | OTP sign-in, trip-scoped access for attached drivers, offline queue |
| Customer portal / app | PWA (`/portal/customer`) | Mobile-first; same API contracts a future Flutter customer app would use |
| Owner portal, Vendor portal | PWA | Own records only |
| Website | PWA (`/`) | Tamil/English, verified coverage only, enquiry → CRM |
