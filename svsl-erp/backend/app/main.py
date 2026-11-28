"""FastAPI application: routers, error handling, security headers, scheduler, SPA hosting."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import api  # noqa: F401
from .api import admin, auth, crud, finance, fleet, imports, operations, portal, resources  # noqa: F401
from .config import get_settings
from .db import SessionLocal

log = logging.getLogger("svsl")


async def _scheduler() -> None:
    """Hourly: alert scan; daily at the configured hour: automatic backup; housekeeping of logs."""
    from .models import BackupRecord, LoginHistory, NotificationLog
    from .services import files, people
    from .services import settings as app_settings

    while True:
        try:
            db = SessionLocal()
            try:
                people.run_alerts(db)
                cfg = app_settings.get(db, "backup")
                now = datetime.now()
                if cfg.get("enabled") and now.hour >= int(cfg.get("hour", 23)):
                    last = db.query(BackupRecord).filter(BackupRecord.kind == "scheduled").order_by(BackupRecord.at.desc()).first()
                    if not last or last.at.astimezone().date() < now.date():
                        files.create_backup(db, None, "scheduled", include_files=cfg.get("include_files", True))
                ret = app_settings.get(db, "retention")
                cut = datetime.now(timezone.utc) - timedelta(days=int(ret.get("notification_log_days") or 730))
                db.query(NotificationLog).filter(NotificationLog.at < cut).delete()
                cut = datetime.now(timezone.utc) - timedelta(days=int(ret.get("login_history_days") or 730))
                db.query(LoginHistory).filter(LoginHistory.at < cut).delete()
                db.commit()
            finally:
                db.close()
        except Exception:  # noqa: BLE001
            log.exception("scheduler run failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if get_settings().run_scheduler:
        task = asyncio.create_task(_scheduler())
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="A Prime Transport ERP", version="1.0.0", description="Transport & Logistics ERP – REST API. Authenticate with POST /api/auth/login and send `Authorization: Bearer <token>`.", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        return JSONResponse({"detail": f"Invalid input: {'.'.join(str(x) for x in first.get('loc', []))} {first.get('msg', '')}"}, status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    for r in (auth.router, admin.router, crud.router, operations.router, finance.router, fleet.router, portal.router, imports.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
        finally:
            db.close()

    dist = s.frontend_dist
    if dist.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not found"}, status_code=404)
            target = (dist / path).resolve()
            if path and target.is_file() and dist.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
