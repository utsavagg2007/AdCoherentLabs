"""Middleware #7a (§6.1/§9.2): ip:{addr} bucket for UNAUTHENTICATED traffic
(docs, 404s, auth callbacks). Authenticated requests carry credentials and are
limited by the user/org/key dependencies instead — this middleware skips them.
/webhooks/stripe is exempt (Stripe signs; Stripe retries hate 429s), and
/healthz//readyz are exempt (upstream probes).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..errors import ApiError
from ..services import ratelimit

_EXEMPT = ("/healthz", "/readyz", "/metrics", "/webhooks/stripe")
_IP_RPM = 30


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        authed = bool(request.headers.get("Authorization")
                      or request.headers.get("X-API-Key"))
        if authed or path.startswith(_EXEMPT):
            return await call_next(request)

        addr = request.client.host if request.client else "unknown"
        try:
            ban = await ratelimit.is_banned(f"ip:{addr}")
            if ban:
                return _reject(request, ban)
            decision = await ratelimit.check_bucket(
                f"ip:{addr}", _IP_RPM, audience="browser")
            if not decision.allowed:
                await ratelimit.record_429(f"ip:{addr}")
                return _reject(request, max(decision.retry_after, 1))
        except ApiError as exc:                       # degraded-closed path
            return _reject(request, 30, exc.message)
        return await call_next(request)


def _reject(request: Request, retry_after: int,
            message: str = "Rate limit exceeded.") -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": message,
                           "request_id": rid, "details": {}}},
        headers={"Retry-After": str(retry_after)},
    )
