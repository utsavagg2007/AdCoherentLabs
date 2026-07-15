"""Middleware #1 (§6.1): request id + structured access log.

The request_id is threaded into every log line (structlog contextvars),
every DB row the handlers write, and every error response.
"""

from __future__ import annotations

import secrets
import time
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_request_id: ContextVar[str] = ContextVar("request_id", default="")

logger = structlog.get_logger("app.access")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = "req_" + secrets.token_hex(8)
        _request_id.set(rid)
        structlog.contextvars.bind_contextvars(request_id=rid)
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request.crashed", method=request.method,
                             path=request.url.path)
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["X-Request-Id"] = rid
        logger.info("request", method=request.method, path=request.url.path,
                    status=response.status_code,
                    duration_ms=round((time.perf_counter() - start) * 1000, 1),
                    client=request.client.host if request.client else None,
                    request_id=rid)
        return response
