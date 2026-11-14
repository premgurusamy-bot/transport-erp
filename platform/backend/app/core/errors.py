"""Business errors returned to clients as {"error": {"code", "message", "details"}}."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status = 400

    def __init__(self, code: str, message: str, details: dict | list | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        if status:
            self.status = status


class NotFound(AppError):
    status = 404

    def __init__(self, what: str = "Record"):
        super().__init__("not_found", f"{what} not found")


class Forbidden(AppError):
    status = 403

    def __init__(self, message: str = "You do not have permission for this action", code: str = "forbidden"):
        super().__init__(code, message)


class Unauthorized(AppError):
    status = 401

    def __init__(self, message: str = "Sign in required"):
        super().__init__("unauthorized", message)


class Conflict(AppError):
    status = 409


class BlockedByRule(AppError):
    """A business/legal/safety gate refused the action. `details` lists every failed check."""

    status = 422


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [
            {"field": ".".join(str(p) for p in e.get("loc", [])[1:]), "message": e.get("msg")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Please correct the highlighted fields", "details": errs}},
        )
