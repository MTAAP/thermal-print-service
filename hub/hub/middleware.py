from __future__ import annotations

from collections.abc import Awaitable, Callable

Scope = dict
Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before they reach a route handler.

    A pure-ASGI middleware (not BaseHTTPMiddleware) so it can refuse a request
    WITHOUT buffering the whole body into memory first -- the very thing the cap
    exists to prevent. Two checks:

    1. A declared Content-Length over the cap is refused immediately with 413.
    2. When Content-Length is absent (chunked / streamed), the wrapped receive
       counts bytes as they arrive and aborts the stream once the cap is passed,
       so a lying-or-missing length header cannot smuggle an unbounded body in.

    The cap is the SAME generous limit as the /send payload caps, so a legitimate
    max-size raw print still passes; only genuinely oversized bodies 413.
    """

    def __init__(self, app: Callable, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared > self.max_body_bytes:
                    await self._reject(send)
                    return
                break

        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    # Drop the rest of the stream; the app never sees the body.
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, counting_receive, send)
        except _BodyTooLarge:
            await self._reject(send)

    async def _reject(self, send: Send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"request body too large"}',
        })


class _BodyTooLarge(Exception):
    """Internal sentinel: a streamed body passed the cap mid-flight."""
