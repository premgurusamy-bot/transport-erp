"""Runtime configuration, read from environment variables (see .env.example).

Nothing business-specific (GSTIN, bank, addresses) lives here: those are edited in
Settings → Company inside the application and stored in the database.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(os.environ.get("SVSL_ENV_FILE", Path(__file__).resolve().parents[1] / ".env"))
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/svsl_erp"
        )
        self.secret_key: str = os.environ.get("SECRET_KEY", "")
        if not self.secret_key:
            # Development fallback only. Production installs MUST set SECRET_KEY.
            self.secret_key = "dev-only-insecure-secret-change-me-" + "x" * 32
        self.data_encryption_key: str = os.environ.get("DATA_ENCRYPTION_KEY", "")
        self.access_token_minutes: int = int(os.environ.get("ACCESS_TOKEN_MINUTES", "720"))
        self.storage_dir: Path = Path(
            os.environ.get("STORAGE_DIR", Path(__file__).resolve().parents[2] / "storage")
        )
        self.backup_dir: Path = Path(os.environ.get("BACKUP_DIR", self.storage_dir / "backups"))
        self.max_upload_mb: int = int(os.environ.get("MAX_UPLOAD_MB", "15"))
        self.public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
        self.cors_origins: list[str] = [
            o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]
        self.run_scheduler: bool = os.environ.get("RUN_SCHEDULER", "true").lower() == "true"
        self.pg_dump_path: str = os.environ.get("PG_DUMP_PATH", "pg_dump")
        self.frontend_dist: Path = Path(
            os.environ.get("FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")
        )
        self.env: str = os.environ.get("APP_ENV", "development")
        # Integrations (all optional; features report "not configured" until set)
        self.smtp_host = os.environ.get("SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.smtp_from = os.environ.get("SMTP_FROM", "")
        self.smtp_tls = os.environ.get("SMTP_TLS", "true").lower() == "true"
        self.whatsapp_token = os.environ.get("WHATSAPP_TOKEN", "")
        self.whatsapp_phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.sms_url = os.environ.get("SMS_GATEWAY_URL", "")
        self.sms_api_key = os.environ.get("SMS_API_KEY", "")
        self.sms_sender = os.environ.get("SMS_SENDER_ID", "")
        self.irp_base_url = os.environ.get("IRP_BASE_URL", "")
        self.irp_client_id = os.environ.get("IRP_CLIENT_ID", "")
        self.irp_client_secret = os.environ.get("IRP_CLIENT_SECRET", "")
        self.irp_username = os.environ.get("IRP_USERNAME", "")
        self.irp_password = os.environ.get("IRP_PASSWORD", "")
        self.ewb_base_url = os.environ.get("EWB_BASE_URL", "")
        self.ewb_client_id = os.environ.get("EWB_CLIENT_ID", "")
        self.ewb_client_secret = os.environ.get("EWB_CLIENT_SECRET", "")
        self.ewb_username = os.environ.get("EWB_USERNAME", "")
        self.ewb_password = os.environ.get("EWB_PASSWORD", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
