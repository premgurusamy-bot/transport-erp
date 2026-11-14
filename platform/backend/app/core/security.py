"""Password hashing (scrypt), opaque session tokens, OTP hashing, signed links and at-rest encryption.

Nothing secret (passwords, OTPs, tokens) is ever stored or logged in plain text.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        # Constant-ish work to reduce user-enumeration timing differences
        hashlib.scrypt(b"x", salt=b"0" * 16, **_SCRYPT)
        return False
    _, salt_b64, dk_b64 = stored.split("$")
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")
    if not any(c.isalpha() for c in password):
        problems.append("at least one letter")
    return problems


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_otp(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))


def otp_hash(otp: str, purpose: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{purpose}:{otp}".encode(), hashlib.sha256).hexdigest()


def sign(value: str, expires_in: int = 300) -> str:
    exp = int(time.time()) + expires_in
    msg = f"{value}:{exp}"
    sig = hmac.new(get_settings().secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{exp}.{sig}"


def verify_signature(value: str, signature: str) -> bool:
    try:
        exp_s, sig = signature.split(".")
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    msg = f"{value}:{exp}"
    good = hmac.new(get_settings().secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig)


def _storage_key() -> bytes:
    return hashlib.sha256(("storage:" + get_settings().secret_key).encode()).digest()


def encrypt_bytes(data: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(_storage_key()).encrypt(nonce, data, None)


def decrypt_bytes(blob: bytes) -> bytes:
    return AESGCM(_storage_key()).decrypt(blob[:12], blob[12:], None)


def mask(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return value
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


# ---------------------------------------------------------------- TOTP (RFC 6238) for staff two-factor sign-in
import struct  # noqa: E402


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((at if at is not None else time.time()) // step)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    now = time.time()
    return any(hmac.compare_digest(totp(secret, now + i * 30), (code or "").strip()) for i in range(-window, window + 1))


def seal(text: str) -> str:
    return base64.b64encode(encrypt_bytes(text.encode())).decode()


def unseal(blob: str) -> str:
    return decrypt_bytes(base64.b64decode(blob)).decode()
