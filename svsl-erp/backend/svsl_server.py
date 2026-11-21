"""Entry point for the bundled Windows server (PyInstaller) and for scripted use.

    svsl-server migrate        apply database migrations
    svsl-server seed           create reference data / admin user (INITIAL_ADMIN_PASSWORD)
    svsl-server serve          start the ERP on HOST:PORT (default 0.0.0.0:8000)
"""
import os
import sys
from pathlib import Path

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(BASE / "alembic"))
    command.upgrade(cfg, "head")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "migrate":
        migrate()
        print("Database is up to date.")
    elif cmd == "seed":
        from app.seed import main as seed_main

        seed_main()
    elif cmd == "serve":
        import uvicorn

        from app.main import app

        uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), log_level="info", proxy_headers=True)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
