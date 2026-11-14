"""G ROAD LINES Transport Business Operating System - API application (modular monolith)."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import install_handlers

log = logging.getLogger("grl")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

VERSION = "2.0.0"

# Money is fixed-precision Decimal end to end: serialise as exact strings ("350.00"), never binary floats.
from decimal import Decimal  # noqa: E402

from fastapi.encoders import ENCODERS_BY_TYPE  # noqa: E402

ENCODERS_BY_TYPE[Decimal] = str


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="G ROAD LINES API", version=VERSION,
                  description="Transport Business Operating System. All clients use these secured APIs; none connect to the database.",
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    install_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    buckets: dict[str, deque] = defaultdict(deque)
    SENSITIVE = ("/api/v1/auth/", "/api/v1/public/", "/api/v1/pod/otp")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        path = request.url.path
        ip = request.client.host if request.client else "?"
        # Simple per-IP rate limit on authentication/public endpoints (Redis-backed limiter recommended for multi-instance)
        if path.startswith(SENSITIVE) and request.method == "POST" and not s.env == "test":
            q = buckets[ip + path]
            now = time.time()
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= 30:
                return JSONResponse(status_code=429, content={"error": {"code": "rate_limited", "message": "Too many requests"}})
            q.append(now)
        t0 = time.time()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("unhandled error rid=%s path=%s", rid, path)
            return JSONResponse(status_code=500, content={"error": {"code": "server_error", "message": "Unexpected error", "request_id": rid}})
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
        if path.startswith("/api/") and "cache-control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-store"
        log.info("%s %s %s %.0fms rid=%s", request.method, path, resp.status_code, (time.time() - t0) * 1000, rid)
        return resp

    from app.modules.commercial.router import router as commercial
    from app.modules.finance.router import router as finance
    from app.modules.fleet.router import router as fleet
    from app.modules.intelligence.router import router as intelligence
    from app.modules.masters.router import router as masters
    from app.modules.operations.router import router as operations
    from app.modules.people.router import router as people
    from app.modules.platform.router import router as platform
    from app.modules.portals.router import router as portals
    from app.modules.risk.router import router as risk
    from app.modules.supply.router import router as supply

    for r in (platform, masters, commercial, operations, fleet, finance, supply, risk, people, intelligence, portals):
        app.include_router(r)
    return app


app = create_app()
