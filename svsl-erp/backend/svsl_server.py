"""Entry point for the bundled Windows server (PyInstaller) and for scripted use.

    svsl-server migrate        apply database migrations
    svsl-server seed           create reference data / admin user (INITIAL_ADMIN_PASSWORD)
    svsl-server serve          start the ERP on HOST:PORT (default 0.0.0.0:8000)
    svsl-server sample-backup [file.zip]
                               build DEMO sample data in an EMPTY database (DATABASE_URL) and save it as a backup
                               file that can be loaded with Admin → Backup → Restore from file
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
    elif cmd == "sample-backup":
        import shutil

        out = Path(sys.argv[2] if len(sys.argv) > 2 else "A_PRIME_ERP_SAMPLE_DATA.zip").resolve()
        migrate()
        from app.core.deps import CurrentUser
        from app.db import SessionLocal
        from app.services import files, sample_data

        db = SessionLocal()
        try:
            info = sample_data.build(db)
            db.commit()
            rec = files.create_backup(db, CurrentUser(id=1, username="admin", full_name="Admin", role="Super Admin", permissions=["*"]), "sample", include_files=False, note="DEMO sample data", sample=True)
            db.commit()
            if rec.status != "Verified":
                raise SystemExit(f"Sample backup failed verification: {rec.note}")
            shutil.copyfile(files.backups_dir() / rec.file_name, out)
            print(f"Sample backup written to {out} ({rec.rows} rows; {info['trips']} trips, {info['invoices']} invoices, {info['from']} to {info['to']}; books balanced: {info['ledger_check']})")
        finally:
            db.close()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
