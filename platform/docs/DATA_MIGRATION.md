# Data migration (Excel, Tally, V1 ERP)

Rules: never overwrite source Tally books or Excel files; keep read-only copies with file name, date and checksum; import masters and
opening balances first, then approved transaction batches; dry run → preview → approval by a different user → commit → reversal possible.

## Tally vouchers (implemented)
Accounts › Tally / migration › **Import from Tally**: upload a Tally XML export. The system parses each voucher, maps ledgers by name
to the chart of accounts and lists exceptions (unmapped ledger, unbalanced voucher, bad date, duplicate already imported). Valid vouchers
are held in an **import batch** (checksum stored). Another user with `accounts.approve` commits it; each voucher keeps its Tally reference
(`external_ref`) so it cannot be imported twice. A committed batch can be reversed with reversal vouchers.
Export back to Tally: **Download XML** for any period.

## Masters from Excel/CSV
Customers, owners, vendors, vehicles, drivers and locations can be loaded with the generic master APIs (`POST /api/v1/masters/...`,
`/vehicles`, `/drivers`) – customer de-duplication and GSTIN validation apply. A guided Excel importer UI is on the backlog.

## From the V1 Node ERP in this repository
V1 produces verified Excel backups (`GRL_ERP_BACKUP_*.xlsx`) and Tally-compatible data. Recommended path:
1. Take a V1 **EMERGENCY BACKUP** and keep it read-only.
2. Load customers/transporters/vehicles/drivers into v2 masters (transporters → vehicle owners).
3. Post opening balances per party as journals (or via Tally import) as at the cut-over date.
4. Run both systems in parallel for an agreed period; reconcile trial balance, receivables and payables.
5. Accountant/CA and Owner sign-off; then make v2 the authoritative system for each data domain.

## Reconciliation checklist
Opening balances · trial balance · cash/bank · receivables/payables by party · GST/TDS registers · fixed assets/loans · FY totals.
