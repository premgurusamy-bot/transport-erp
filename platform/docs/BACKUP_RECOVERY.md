# Backup and recovery

## What is backed up
| Data | How | Frequency (recommended) |
|---|---|---|
| PostgreSQL database (all business data, audit, configuration) | `scripts/backup.py` → `pg_dump -Fc`, AES-256-GCM encrypted with `GRL_BACKUP_KEY`, plus manifest (SHA-256, per-table row counts, audit-chain head) | Daily (Windows Task Scheduler running `scripts\backup-windows.ps1`) and before every upgrade |
| Documents/photos/POD (`storage` volume) | Files are already encrypted at rest; copy the volume/folder | Daily |
| `.env` secrets | Store separately (password manager / sealed copy) – **never** in the same place as the backups | On change |

Keep at least one copy **off the PC** (external drive kept elsewhere or cloud storage with separate credentials), and one
copy that cannot be overwritten (e.g. versioned/immutable bucket or rotated offline drive).

## Restore (always to a NEW database first)
```bash
createdb groadlines_restore
GRL_BACKUP_KEY=... python scripts/restore.py backups/GRL_DB_2026....dump.enc --target postgresql://user:pass@host:5432/groadlines_restore
```
The restore refuses a backup whose checksum does not match, then verifies: every table's row count equals the manifest,
the audit-chain head matches, and the ledger is balanced. It refuses to overwrite the live database unless
`--i-understand-this-replaces-data` is given. After verification, point `GRL_DATABASE_URL` at the restored database.

Tested: `backend/tests/test_backup_restore.py` (backup → restore into scratch DB → verification → tampered file refused) – PASS in sandbox.

## RTO / RPO
Proposed: **RPO 24 h** (daily backup; PITR/WAL archiving can reduce this when hosted on a managed database) and **RTO 8 h**.
These are configuration values (`backup.targets`) and are **not claimed** until a restore drill on the real environment is timed and recorded.

## Restore drill (monthly checklist item "Backup restore drill evidence checked")
1. Restore the latest backup into a scratch database with `restore.py`. 2. Record time taken and the verification output.
3. Sign in to a test API instance pointed at it and open a few records. 4. File the evidence.

## Outage procedure
- Use numbered paper forms for enquiry, booking, dispatch, trip, POD, fuel, expense and incident. **No offline payments, statutory filings or credit approvals.**
- On recovery, enter forms via the sync API with `source=paper_form` and original event time; they land as *needs_review* for supervisor reconciliation.
- Driver apps keep events on the phone and replay them idempotently when back online.

## Cyber incident
Isolate (disable users, revoke sessions), preserve logs and audit, rotate secrets, restore a clean verified backup into a new
database, validate integrity (audit chain, trial balance), then resume. Record as an incident of kind `cyber`.
