"""The API error model (§11): every error is
{"error": {"code", "message", "request_id", "details"}} — no stack traces,
no secrets, cross-org ids answered with 404 so existence is never revealed.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .middleware.request_id import get_request_id


class ApiError(Exception):
    """Raise anywhere in a handler; rendered per the §11 error model."""

    def __init__(self, status: int, code: str, message: str,
                 details: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None):
        self.status, self.code, self.message = status, code, message
        self.details, self.headers = details or {}, headers or {}
        super().__init__(message)


def error_response(status: int, code: str, message: str,
                   details: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message,
                           "request_id": get_request_id(),
                           "details": details or {}}},
        headers=headers or {},
    )


def not_found() -> ApiError:
    """Uniform 404 — also returned for cross-org ids (never reveal existence)."""
    return ApiError(404, "not_found", "The requested resource does not exist.")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return error_response(400, "validation_error", "Request failed validation.",
                              {"errors": exc.errors()[:20]})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found",
                405: "method_not_allowed", 413: "payload_too_large",
                415: "unsupported_media_type", 429: "rate_limited"}.get(
                    exc.status_code, "error")
        return error_response(exc.status_code, code, str(exc.detail),
                              headers=dict(exc.headers or {}))

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception):
        # Never leak internals; the request_id correlates with server logs.
        import structlog
        structlog.get_logger("app.errors").exception("unhandled", error=str(exc))
        return error_response(500, "internal", "Internal error.")
