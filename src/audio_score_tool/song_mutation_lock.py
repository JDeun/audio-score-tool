from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PREFIX = "/api/songs/"


class SongMutationSerializationMiddleware:
    """Serialize unsafe requests that target the same song.

    SQLite revision CAS protects the score document itself, but a mutation can also
    update publication settings, metadata, analyses or exports. Serializing per song
    gives the desktop workflow one transaction-like mutation lane across those stores
    while still allowing different songs to be edited independently.
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _song_id(scope: Scope) -> str | None:
        if scope.get("type") != "http":
            return None
        method = str(scope.get("method") or "GET").upper()
        if method in _SAFE_METHODS:
            return None
        path = str(scope.get("path") or "")
        if not path.startswith(_PREFIX):
            return None
        remainder = path[len(_PREFIX) :]
        song_id = remainder.split("/", 1)[0].strip()
        return song_id or None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        song_id = self._song_id(scope)
        if song_id is None:
            await self.app(scope, receive, send)
            return
        lock = self._locks.setdefault(song_id, asyncio.Lock())
        async with lock:
            await self.app(scope, receive, send)
