from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_TRUSTED_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


def _trusted_origin(value: str) -> bool:
    origin = value.strip().rstrip("/")
    if origin in _TRUSTED_ORIGINS:
        return True
    parsed = urlparse(origin)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port == 5173


class LocalMutationOriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject browser-originated unsafe requests from unrelated web pages.

    The backend is loopback-only, but browsers can still reach loopback services from
    arbitrary websites. Tauri production origins and the local Vite dev origin are
    accepted. Non-browser clients without an Origin header remain supported.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _SAFE_METHODS:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin and not _trusted_origin(origin):
            return JSONResponse(
                {"detail": "Untrusted browser origin for local mutation API."},
                status_code=403,
            )
        return await call_next(request)
