from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HEADER = b"x-audioscore-token"


class ApiTokenMiddleware:
    """Require the Tauri sidecar's per-launch token for unsafe API methods.

    Development remains frictionless when ``AST_API_TOKEN`` is unset. Packaged Tauri
    launches set a random token in the sidecar environment and retrieve the same value
    through a Rust IPC command, so another local process cannot mutate the API merely by
    knowing that it listens on loopback.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _provided(scope: Scope) -> str:
        for key, value in scope.get("headers") or []:
            if key.lower() == _HEADER:
                return value.decode("utf-8", errors="ignore")
        return ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        expected = os.getenv("AST_API_TOKEN", "")
        if (
            expected
            and scope.get("type") == "http"
            and str(scope.get("path") or "").startswith("/api/")
            and str(scope.get("method") or "GET").upper() not in _SAFE_METHODS
        ):
            provided = self._provided(scope)
            if not provided or not hmac.compare_digest(provided, expected):
                response = JSONResponse({"detail": "Invalid local API token"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
