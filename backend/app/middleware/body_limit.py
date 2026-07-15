"""Middleware #3 (§6.1): body size cap — pre-read Content-Length plus a
streaming cap so a lying client cannot pump more than the limit through the
socket. Global 60 MB; the upload route tightens per tier before reading.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    return await self._reject(send)
            except ValueError:
                pass

        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _TooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(send)

    async def _reject(self, send: Send):
        body = (b'{"error":{"code":"payload_too_large",'
                b'"message":"Request body exceeds the global limit.",'
                b'"request_id":"","details":{}}}')
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass
