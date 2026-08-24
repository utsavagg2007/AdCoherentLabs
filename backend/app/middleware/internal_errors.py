"""Middleware: turn an unhandled exception into the §11 error envelope from
*inside* the CORS layer.

FastAPI already registers `@app.exception_handler(Exception)` (errors.py), but
Starlette SPECIAL-CASES a handler for bare `Exception`: it is installed on
`ServerErrorMiddleware`, which wraps the entire user middleware stack. Its
response is therefore produced ABOVE CORSMiddleware and never receives
`Access-Control-Allow-Origin`.

The browser consequence is worse than the 500 itself. A CORS-less error
response is unreadable to JS, so `fetch` rejects with a TypeError and the
client cannot see the status at all — the frontend maps that to status 0 and
tells the user "the API is not responding" while the API is up and answering.
That sends people to restart Docker when the real problem is one broken query.

This middleware is added immediately BEFORE CORSMiddleware in main.py, which
(Starlette middleware being LIFO) places it INSIDE CORS. Exceptions from the
routes and from the inner rate-limit middleware are converted here, and the
resulting response travels back out through CORS and picks up the headers.

The errors.py handler stays as the last-resort net for anything raised outside
this middleware's reach.
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_log = structlog.get_logger("app.errors")


class InternalErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:                       # noqa: BLE001
            # Imported here: errors.py imports from .middleware.request_id, so
            # a module-level import of errors would be circular.
            from ..errors import error_response

            _log.exception("unhandled", error=str(exc), path=request.url.path)
            # Same envelope and the same disclosure rule as errors.py — the
            # request_id is the only thing that correlates to the server log.
            return error_response(500, "internal", "Internal error.")
