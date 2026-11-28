"""Password hashing (bcrypt), JWT access tokens bound to server-side sessions, TOTP 2FA, field encryption."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pyotp
from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings

ALGO = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode())
    except ValueError:
        return False


def password_problem(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if password.isdigit() or password.isalpha():
        return "Password must contain both letters and numbers"
    return None


def create_token(user_id: int, session_id: str, minutes: int | None = None) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes or s.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, s.secret_key, algorithm=ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGO])


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return bool(secret) and pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1)


def totp_uri(secret: str, username: str, issuer: str = "A Prime Transport ERP") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def _fernet() -> Fernet:
    s = get_settings()
    key = s.data_encryption_key
    if not key:
        # Derive a stable key from SECRET_KEY when a dedicated key is not configured.
        key = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return _fernet().encrypt(str(value).encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def mask(value: str | None, show: int = 4) -> str | None:
    if not value:
        return None
    return "X" * max(0, len(value) - show) + value[-show:]


def sign(text: str) -> str:
    """Short HMAC used in QR verification links (cannot be forged without SECRET_KEY)."""
    return hmac.new(get_settings().secret_key.encode(), text.encode(), hashlib.sha256).hexdigest()[:20]
