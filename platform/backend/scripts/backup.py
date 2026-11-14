"""Encrypted PostgreSQL backup with manifest and integrity checksums.

    python scripts/backup.py [--out DIR]

Uses pg_dump (custom format), encrypts with AES-256-GCM using GRL_BACKUP_KEY (separate from the app secret),
and writes <name>.dump.enc + <name>.manifest.json (sha256, row counts, audit-chain head). Never overwrites files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _key() -> bytes:
    k = os.environ.get("GRL_BACKUP_KEY")
    if not k:
        raise SystemExit("Set GRL_BACKUP_KEY (store it separately from the database credentials and the app secret).")
    return hashlib.sha256(("backup:" + k).encode()).digest()


def pg_env(url: str) -> tuple[dict, list[str]]:
    u = make_url(url)
    env = {**os.environ, "PGPASSWORD": u.password or ""}
    return env, ["-h", u.host or "localhost", "-p", str(u.port or 5432), "-U", u.username or "postgres"]


def table_counts(url: str) -> dict:
    eng = create_engine(url)
    with eng.connect() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1"))]
        counts = {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in tables}
        head = c.execute(text("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1")).scalar() if "audit_log" in tables else None
    eng.dispose()
    return {"tables": counts, "audit_head": head}


def backup(url: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    name = "GRL_DB_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
    env, conn = pg_env(url)
    db = make_url(url).database
    raw = subprocess.run(["pg_dump", *conn, "-Fc", "-d", db], env=env, check=True, capture_output=True).stdout
    nonce = secrets.token_bytes(12)
    enc = nonce + AESGCM(_key()).encrypt(nonce, raw, None)
    f = out / f"{name}.dump.enc"
    f.write_bytes(enc)
    manifest = {"file": f.name, "created_at": datetime.now(timezone.utc).isoformat(), "sha256_encrypted": hashlib.sha256(enc).hexdigest(),
                "sha256_plain": hashlib.sha256(raw).hexdigest(), "size": len(enc), **table_counts(url), "format": "pg_dump custom + AES-256-GCM"}
    (out / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2))
    return f


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.environ.get("GRL_BACKUP_DIR", "./var/backups"))
    a = ap.parse_args()
    from app.core.config import get_settings
    p = backup(get_settings().database_url.replace("+psycopg", ""), Path(a.out))
    print(f"Backup written: {p}")
