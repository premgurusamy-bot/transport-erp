"""Encrypted object storage. Development: AES-GCM encrypted files on local disk.
Production: an S3-compatible bucket (adapter to be configured - see INTEGRATIONS.md)."""
from __future__ import annotations

import hashlib
import os
import re
import uuid

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_bytes, encrypt_bytes

ALLOWED_TYPES = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG",
    "image/webp": b"RIFF",
    "application/pdf": b"%PDF",
    "text/csv": None,
    "text/plain": None,
    "application/xml": None,
    "text/xml": None,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": b"PK",
    "video/mp4": None,
}
MAX_BYTES = 15 * 1024 * 1024


def safe_filename(name: str) -> str:
    name = os.path.basename(name or "file")
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
    return name or "file"


def validate_upload(content_type: str, data: bytes) -> None:
    if content_type not in ALLOWED_TYPES:
        raise AppError("file_type", f"File type {content_type} is not allowed")
    if len(data) > MAX_BYTES:
        raise AppError("file_size", "File is larger than 15 MB")
    if not data:
        raise AppError("file_empty", "File is empty")
    magic = ALLOWED_TYPES[content_type]
    if magic and not data.startswith(magic):
        raise AppError("file_content", "File content does not match its type")
    # Malware scanning hook: integrate ClamAV/provider scanning here in production (see SECURITY.md).


def _path(key: str) -> str:
    base = get_settings().storage_dir
    return os.path.join(base, key[:2], key)


def put(data: bytes) -> tuple[str, str]:
    key = uuid.uuid4().hex
    sha = hashlib.sha256(data).hexdigest()
    p = _path(key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(encrypt_bytes(data))
    return key, sha


def get(key: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise AppError("bad_key", "Invalid storage key")
    with open(_path(key), "rb") as f:
        return decrypt_bytes(f.read())
