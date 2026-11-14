"""Environment-based configuration. Secrets come from the environment only, never source code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("GRL_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: _env(
            "GRL_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/groadlines"
        )
    )
    # Used to sign download links and derive the storage encryption key. MUST be set in staging/production.
    secret_key: str = field(default_factory=lambda: _env("GRL_SECRET_KEY", "dev-only-insecure-secret-change-me"))
    storage_dir: str = field(default_factory=lambda: _env("GRL_STORAGE_DIR", "./var/storage"))
    session_hours: int = field(default_factory=lambda: int(_env("GRL_SESSION_HOURS", "12")))
    login_max_failures: int = field(default_factory=lambda: int(_env("GRL_LOGIN_MAX_FAILURES", "5")))
    login_lock_minutes: int = field(default_factory=lambda: int(_env("GRL_LOGIN_LOCK_MINUTES", "15")))
    cors_origins: str = field(default_factory=lambda: _env("GRL_CORS_ORIGINS", "http://localhost:5173"))
    # Expose OTPs in API responses ONLY in development/test so mock SMS can be exercised. Never in production.
    expose_dev_otp: bool = field(default_factory=lambda: _env("GRL_EXPOSE_DEV_OTP", "true") == "true")
    timezone: str = "Asia/Kolkata"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def validate(self) -> None:
        if self.env in ("staging", "production"):
            if self.secret_key.startswith("dev-only") or len(self.secret_key) < 32:
                raise RuntimeError("GRL_SECRET_KEY must be set to a strong value (32+ chars) outside development")
            if self.expose_dev_otp:
                raise RuntimeError("GRL_EXPOSE_DEV_OTP must be false outside development")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate()
    return s
