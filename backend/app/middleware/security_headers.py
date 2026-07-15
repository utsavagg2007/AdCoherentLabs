"""Middleware #2 (§6.1): security headers on every response.

API responses get a deny-all CSP; the OpenAPI docs pages get just enough to
render Swagger UI. HSTS is emitted always — it is inert over plain HTTP and
authoritative once the proxy terminates TLS.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_API_CSP = "default-src 'none'; frame-ancestors 'none'"
_DOCS_CSP = (
    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc", "/v1/docs")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Content-Security-Policy"] = (
            _DOCS_CSP if request.url.path.startswith(_DOCS_PATHS) else _API_CSP)
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        return response
