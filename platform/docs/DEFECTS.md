# Defect register

| ID | Found by | Severity | Description | Fix | Retest |
|---|---|---|---|---|---|
| DF-01 | `test_wf7` | High | Owner acceptance failure was classed "commercial" and could be overridden by dispatch override | Severity changed to non-overridable (`commercial_hard`) | PASS |
| DF-02 | `test_wf12` | Medium | Decimal amounts serialised as JSON floats (e.g. 350.0) – money precision risk in clients | Global encoder: Decimal → exact string | PASS (all suites) |
| DF-03 | `test_security::tenant_isolation` | High | Portal booking with another tenant's quotation id returned "already booked" (existence leak) | Quotation ownership checked first; returns 404 | PASS |
| DF-04 | OpenAPI generation | Medium | Generic CRUD schemas unresolved due to postponed annotations | Removed `from __future__ import annotations` in resource factory | PASS (342 operations at the time; 352 now) |
| DF-05 | Review | Low | Vendor document upload accepted any entity id for vendor/PO | Upload now requires the vendor's own id / own PO | Covered by code review; no dedicated test yet |
| DF-06 | Review | Low | Print stylesheet hid modal-based print documents | Visibility-based print CSS for `.print-doc` | Manual (browser print preview) |
| DF-07 | CI (mobile) | High | Android package `in.groadlines.*` invalid – `in` is a Java keyword; APK build failed | Renamed to `com.groadlines.grl_driver` / `grl_management` | CI PASS |
| DF-08 | CI (backend) | High | Restore failed when pg client (17) was newer than server (16): `SET transaction_timeout` rejected | Restore converts dump to SQL, strips unsupported settings, applies with `psql --single-transaction` | PASS locally and in CI |
| DF-09 | a11y audit | Medium | Unlabelled filter selects/file inputs; low-contrast sidebar text; colour-only links | aria-labels, contrast, underlines, focus outline | axe PASS |

Open defects: none known. Known gaps are tracked as backlog in `IMPLEMENTATION_PLAN.md` and `PROGRESS.md`, not as defects.
