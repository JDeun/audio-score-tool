from __future__ import annotations

import os

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB; long lossless audio still fits.


def max_request_bytes() -> int:
    raw = os.getenv("AST_MAX_REQUEST_BYTES", "").strip()
    if not raw:
        return _DEFAULT_MAX_REQUEST_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_REQUEST_BYTES
    # Avoid accidental zero-byte configuration or absurdly high values.
    return max(16 * 1024 * 1024, min(value, 16 * 1024 * 1024 * 1024))


class RequestSizeLimitMiddleware:
    """Reject oversized HTTP request bodies before multipart parsing starts.

    Tauri/browser uploads include Content-Length, so this protects the normal desktop
    workflow before Starlette spools multipart data. The backend remains bound to
    loopback only; this is primarily a local stability/resource guard rather than an
    internet-facing quota system.
    """

    def __init__(self, app: ASGIApp, *, limit: int | None = None):
        self.app = app
        self.limit = limit or max_request_bytes()

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
            if content_length > self.limit:
                response = JSONResponse(
                    {
                        "detail": (
                            f"Upload is too large. Maximum request size is {self.limit} bytes. "
                            "Set AST_MAX_REQUEST_BYTES only if larger local projects are intentional."
                        )
                    },
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
