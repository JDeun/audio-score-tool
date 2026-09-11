from __future__ import annotations

import asyncio
import weakref

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .benchmark_edit_telemetry import record_successful_song_mutation

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PREFIX = "/api/songs/"
_MAX_TELEMETRY_BODY_BYTES = 64 * 1024


class SongMutationSerializationMiddleware:
    """Serialize unsafe requests that target the same song.

    SQLite revision CAS protects the score document itself, but a mutation can also
    update publication settings, metadata, analyses or exports. Serializing per song
    gives the desktop workflow one transaction-like mutation lane across those stores
    while still allowing different songs to be edited independently.

    The lock pool uses weak references so songs that are no longer being mutated do not
    leave a permanent in-memory lock entry behind during long-running desktop sessions.

    When AST_TIER2_TELEMETRY_FILE points at an explicitly started benchmark session,
    successful song mutations are also reduced into human-correction product metrics.
    Normal product runs pay only the small no-op environment check.
    """

    def __init__(self, app: ASGIApp):
        self.app = app
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

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

        lock = self._locks.get(song_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[song_id] = lock

        captured_body = bytearray()
        status_code: int | None = None

        async def receive_with_capture() -> Message:
            message = await receive()
            if message.get("type") == "http.request" and len(captured_body) < _MAX_TELEMETRY_BODY_BYTES:
                chunk = message.get("body", b"")
                if isinstance(chunk, bytes):
                    remaining = _MAX_TELEMETRY_BODY_BYTES - len(captured_body)
                    captured_body.extend(chunk[:remaining])
            return message

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                raw_status = message.get("status")
                if isinstance(raw_status, int):
                    status_code = raw_status
            await send(message)

        async with lock:
            await self.app(scope, receive_with_capture, send_with_status)

        if status_code is not None:
            record_successful_song_mutation(
                song_id=song_id,
                method=str(scope.get("method") or ""),
                path=str(scope.get("path") or ""),
                status_code=status_code,
                request_body=bytes(captured_body),
            )
