"""Restore an encrypted backup into a TARGET database and verify integrity.

    python scripts/restore.py BACKUP.dump.enc --target postgresql://user:pass@host:5432/restore_db

Refuses to restore into the live database unless --i-understand-this-replaces-data is given.
Verification: checksum, per-table row counts vs manifest, audit hash chain, balanced trial balance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup import _key, pg_env, table_counts  # noqa: E402


def restore(backup_file: Path, target_url: str) -> dict:
    manifest = json.loads(backup_file.with_name(backup_file.name.replace(".dump.enc", ".manifest.json")).read_text())
    enc = backup_file.read_bytes()
    if hashlib.sha256(enc).hexdigest() != manifest["sha256_encrypted"]:
        raise SystemExit("Checksum mismatch: backup file is damaged or modified. Nothing restored.")
    raw = AESGCM(_key()).decrypt(enc[:12], enc[12:], None)
    env, conn = pg_env(target_url)
    db = make_url(target_url).database
    subprocess.run(["pg_restore", *conn, "--clean", "--if-exists", "--no-owner", "-d", db], input=raw, env=env, check=True, capture_output=True)
    after = table_counts(target_url)
    mismatches = {t: (n, after["tables"].get(t)) for t, n in manifest["tables"].items() if after["tables"].get(t) != n}
    eng = create_engine(target_url)
    with eng.connect() as c:
        bal = c.execute(text("SELECT coalesce(sum(debit),0) - coalesce(sum(credit),0) FROM voucher_lines")).scalar()
    eng.dispose()
    return {"restored_tables": len(after["tables"]), "row_count_mismatches": mismatches, "audit_head_matches": after["audit_head"] == manifest["audit_head"],
            "ledger_balanced": bal == 0, "ok": not mismatches and after["audit_head"] == manifest["audit_head"] and bal == 0}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("backup")
    ap.add_argument("--target", required=True)
    ap.add_argument("--i-understand-this-replaces-data", action="store_true")
    a = ap.parse_args()
    from app.core.config import get_settings
    live = make_url(get_settings().database_url).database
    if make_url(a.target).database == live and not a.i_understand_this_replaces_data:
        raise SystemExit("Refusing to restore over the live database. Restore to a separate database first and verify.")
    print(json.dumps(restore(Path(a.backup), a.target), indent=2, default=str))
