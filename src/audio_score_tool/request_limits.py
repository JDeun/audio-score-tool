from __future__ import annotations

import os

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB; long lossless audio still fits.


class RequestTooLarge(RuntimeError):
    pass


def max_request_bytes() -> int:
    raw = os.getenv("AST_MAX_REQUEST_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_REQUEST_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_REQUEST_BYTES
    return max(16 * 1024 * 1024, min(value, 16 * 1024 * 1024 * 1024))


class RequestSizeLimitMiddleware:
    """Bound request bodies with and without Content-Length.

    Normal Tauri/browser uploads are rejected from the declared Content-Length before
    multipart parsing. A wrapped ASGI receive path also counts streamed/chunked bodies so
    malformed or non-browser clients cannot bypass the local resource guard.
    """

    def __init__(self, app: ASGIApp, *, limit: int | None = None):
        self.app = app
        self.limit = limit or max_request_bytes()

    def _too_large_response(self) -> JSONResponse:
        return JSONResponse(
            {
                "detail": (
                    f"Upload is too large. Maximum request size is {self.limit} bytes. "
                    "Set AST_MAX_REQUEST_BYTES only if larger local projects are intentional."
                )
            },
            status_code=413,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        raw_length = headers.get("content-length")
        if raw_length:
            try:
                content_length = int(raw_length)
            except ValueError:
                response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                await response(scope, receive, send)
                return
            if content_length < 0:
                response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                await response(scope, receive, send)
                return
            if content_length > self.limit:
                await self._too_large_response()(scope, receive, send)
                return

        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.limit:
                    raise RequestTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestTooLarge:
            if not response_started:
                await self._too_large_response()(scope, receive, send)
            else:
                # A handler should not normally start a response before consuming its
                # upload body. If it does, abort rather than send a second response.
                raise
