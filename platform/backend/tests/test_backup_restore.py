"""Workflow 13: backup → restore → integrity verification (real pg_dump/pg_restore against a scratch database)."""
import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_settings


@pytest.mark.skipif(not shutil.which("pg_dump"), reason="PostgreSQL client tools not installed")
def test_wf13_backup_restore_verify(client, owner, tmp_path):
    os.environ["GRL_BACKUP_KEY"] = "test-backup-key-kept-separately"
    from scripts.backup import backup
    from scripts.restore import restore
    src = get_settings().database_url.replace("+psycopg", "")
    f = backup(src, tmp_path)
    assert f.exists() and f.with_name(f.name.replace(".dump.enc", ".manifest.json")).exists()
    admin = create_engine(src.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS groadlines_restore_test"))
        c.execute(text("CREATE DATABASE groadlines_restore_test"))
    target = src.rsplit("/", 1)[0] + "/groadlines_restore_test"
    res = restore(f, target)
    assert res["ok"], res
    # Tampered backup is refused
    data = bytearray(f.read_bytes())
    data[100] ^= 0xFF
    bad = tmp_path / ("BAD_" + f.name)
    bad.write_bytes(bytes(data))
    Path(str(bad).replace(".dump.enc", ".manifest.json")).write_text(f.with_name(f.name.replace(".dump.enc", ".manifest.json")).read_text())
    with pytest.raises(SystemExit):
        restore(bad, target)
    with admin.connect() as c:
        c.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='groadlines_restore_test'"))
        c.execute(text("DROP DATABASE groadlines_restore_test"))
