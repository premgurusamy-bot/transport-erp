"""Secure document storage (versioned) and database backup / restore."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Date, DateTime, Integer, Numeric, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.audit import jsonable, log
from ..core.deps import AppError
from ..models import Base, BackupRecord, Document, DocumentVersion

APP_VERSION = "1.0.0"
ALLOWED_MIME = {
    "application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "text/csv", "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword", "application/zip",
    "application/json",
}
MAGIC = {b"%PDF": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png", b"PK\x03\x04": "application/zip"}


def files_dir() -> Path:
    p = get_settings().storage_dir / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def store_upload(db: Session, user, document: Document, filename: str, content: bytes, mime: str | None, note: str | None = None) -> DocumentVersion:
    s = get_settings()
    if len(content) > s.max_upload_mb * 1024 * 1024:
        raise AppError(f"File is larger than {s.max_upload_mb} MB")
    if not content:
        raise AppError("Empty file")
    mime = (mime or mimetypes.guess_type(filename)[0] or "application/octet-stream").split(";")[0]
    if mime not in ALLOWED_MIME:
        raise AppError(f"File type {mime} is not allowed")
    for magic, kind in MAGIC.items():
        if content.startswith(magic):
            compatible = kind == mime or (kind == "application/zip" and "openxml" in mime)
            if not compatible:
                raise AppError("File content does not match its type")
    ext = Path(filename).suffix.lower()[:10]
    stored = secrets.token_hex(16) + ext
    (files_dir() / stored).write_bytes(content)
    document.current_version = (document.current_version or 0) + 1
    ver = DocumentVersion(document_id=document.id, version=document.current_version, file_name=Path(filename).name[:250], stored_name=stored, mime=mime,
                          size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), uploaded_by=getattr(user, "id", None),
                          uploaded_at=datetime.now(timezone.utc), note=note)
    db.add(ver)
    db.flush()
    log(db, user, "upload", "documents", document.id, None, {"version": ver.version, "file": ver.file_name, "sha256": ver.sha256})
    return ver


def read_version(ver: DocumentVersion) -> bytes:
    path = files_dir() / ver.stored_name
    if not path.exists():
        raise AppError("File is missing from storage – restore it from a backup", 404)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != ver.sha256:
        raise AppError("Stored file failed its integrity check", 500)
    return data


# ------------------------------------------------------------------ backup

SKIP_ON_RESTORE_KEEP_USERS = {"users", "roles", "user_sessions", "login_history"}


def backups_dir() -> Path:
    p = get_settings().backup_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def _alembic_revision(db: Session) -> str | None:
    try:
        return db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001
        db.rollback()
        return None


def create_backup(db: Session, user, kind: str = "manual", include_files: bool = True, note: str | None = None) -> BackupRecord:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"SVSL_ERP_BACKUP_{ts}_{kind}.zip"
    path = backups_dir() / name
    manifest = {"app": "SVSL ERP", "app_version": APP_VERSION, "created_at": datetime.now(timezone.utc).isoformat(), "kind": kind, "alembic_revision": _alembic_revision(db), "tables": {}}
    total_rows = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for table in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in db.execute(table.select())]
            payload = json.dumps(jsonable(rows), ensure_ascii=False).encode()
            z.writestr(f"data/{table.name}.json", payload)
            manifest["tables"][table.name] = {"rows": len(rows), "sha256": hashlib.sha256(payload).hexdigest()}
            total_rows += len(rows)
        if include_files:
            fdir = files_dir()
            listing = {}
            for f in sorted(fdir.iterdir()):
                if f.is_file():
                    data = f.read_bytes()
                    z.writestr(f"files/{f.name}", data)
                    listing[f.name] = hashlib.sha256(data).hexdigest()
            manifest["files"] = listing
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    pg_file = _pg_dump(ts, kind)
    ok, problems = verify_backup(path)
    rec = BackupRecord(kind=kind, file_name=name, size_bytes=path.stat().st_size, sha256=sha, status="Verified" if ok else "Failed", tables=len(manifest["tables"]), rows=total_rows,
                       pg_dump_file=pg_file, note=note if ok else f"{note or ''} {'; '.join(problems)}", created_by=getattr(user, "id", None))
    db.add(rec)
    db.flush()
    _prune(db)
    return rec


def _pg_dump(ts: str, kind: str) -> str | None:
    s = get_settings()
    if not shutil.which(s.pg_dump_path) and not Path(s.pg_dump_path).exists():
        return None
    url = s.database_url.replace("postgresql+psycopg://", "postgresql://")
    out = backups_dir() / f"SVSL_ERP_DB_{ts}_{kind}.dump"
    try:
        subprocess.run([s.pg_dump_path, "--format=custom", "--no-owner", f"--file={out}", url], check=True, capture_output=True, timeout=600)
        return out.name
    except (subprocess.SubprocessError, OSError):
        return None


def _prune(db: Session) -> None:
    from . import settings as app_settings

    keep = int(app_settings.get(db, "backup").get("keep_last") or 0)
    if keep <= 0:
        return
    recs = db.query(BackupRecord).filter(BackupRecord.kind == "scheduled").order_by(BackupRecord.at.desc()).all()
    for r in recs[keep:]:
        for fname in (r.file_name, r.pg_dump_file):
            if fname and (backups_dir() / fname).exists():
                (backups_dir() / fname).unlink()
        r.status = "Pruned"


def verify_backup(path: Path) -> tuple[bool, list[str]]:
    problems = []
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read("manifest.json"))
            for tname, meta in manifest["tables"].items():
                data = z.read(f"data/{tname}.json")
                if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                    problems.append(f"{tname}: checksum mismatch")
                elif len(json.loads(data)) != meta["rows"]:
                    problems.append(f"{tname}: row count mismatch")
            for fname, sha in (manifest.get("files") or {}).items():
                if hashlib.sha256(z.read(f"files/{fname}")).hexdigest() != sha:
                    problems.append(f"file {fname}: checksum mismatch")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        problems.append(f"Not a valid backup file: {exc}")
    return not problems, problems


def _convert(col, value):
    if value is None:
        return None
    t = col.type
    if isinstance(t, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(t, Date):
        return date.fromisoformat(value[:10])
    if isinstance(t, Numeric):
        return Decimal(str(value))
    return value


def restore_backup(db: Session, user, path: Path, keep_users: bool = True) -> dict:
    ok, problems = verify_backup(path)
    if not ok:
        raise AppError("Backup verification failed: " + "; ".join(problems[:5]))
    pre = create_backup(db, user, "pre_restore", include_files=True, note=f"Automatic backup before restoring {path.name}")
    db.commit()
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        all_tables = Base.metadata.sorted_tables
        # backup history and the audit trail are append-only: keep the current ones (unless empty, e.g. a new server)
        kept_names = (SKIP_ON_RESTORE_KEEP_USERS if keep_users else set()) | {"backup_records", "audit_logs"}
        kept: dict[str, list[dict]] = {}
        for t in all_tables:
            if t.name in kept_names:
                kept[t.name] = [dict(r._mapping) for r in db.execute(t.select())]
        kept_names = {n for n in kept_names if kept.get(n) or n in SKIP_ON_RESTORE_KEEP_USERS and keep_users}
        counts = {}
        try:
            names = ", ".join(f'"{t.name}"' for t in all_tables)
            db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            existing_ids: dict[str, set] = {}
            for t in all_tables:
                cols = {c.name: c for c in t.columns}
                if t.name in kept_names:
                    rows = kept.get(t.name, [])
                    if t.name == "users":
                        for r in rows:  # links to records that no longer exist after restore are cleared
                            for fk, ref in (("branch_id", "branches"), ("customer_id", "customers"), ("driver_id", "drivers")):
                                if r.get(fk) and r[fk] not in existing_ids.get(ref, set()):
                                    r[fk] = None
                    clean = rows
                else:
                    if t.name not in manifest["tables"]:
                        continue
                    data = json.loads(z.read(f"data/{t.name}.json"))
                    clean = [{k: _convert(cols[k], v) for k, v in r.items() if k in cols} for r in data]
                if clean:
                    db.execute(t.insert(), clean)
                if "id" in cols:
                    existing_ids[t.name] = {r.get("id") for r in clean}
                counts[t.name] = len(clean)
                if "id" in cols and cols["id"].primary_key and isinstance(cols["id"].type, Integer):
                    db.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"', 'id'), COALESCE((SELECT MAX(id) FROM \"{t.name}\"), 0) + 1, false)"))
            for t in all_tables:
                if t.name in manifest["tables"] and t.name not in kept_names:
                    actual = db.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar()
                    if actual != manifest["tables"][t.name]["rows"]:
                        raise AppError(f"Restore verification failed for {t.name}: {actual} rows vs {manifest['tables'][t.name]['rows']}")
            log(db, user, "restore", "backup", None, None, {"file": path.name, "tables": len(counts), "pre_restore": pre.file_name})
            db.commit()
        except Exception:
            db.rollback()
            raise
        fdir = files_dir()
        for fname in manifest.get("files") or {}:
            target = fdir / fname
            if not target.exists():
                target.write_bytes(z.read(f"files/{fname}"))
    return {"restored_tables": len(counts), "rows": sum(counts.values()), "pre_restore_backup": pre.file_name}
