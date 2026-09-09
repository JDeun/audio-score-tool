from __future__ import annotations

import os
from threading import Lock

_lock = Lock()
_token: str | None = None
_identity: str | None = None


def environment_token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")


def active_token() -> str | None:
    with _lock:
        return _token or environment_token()


def authenticated() -> bool:
    return bool(active_token())


def identity() -> str | None:
    with _lock:
        return _identity


def set_session(token: str, identity_name: str) -> None:
    global _identity, _token
    with _lock:
        _token = token
        _identity = identity_name


def clear_session() -> None:
    global _identity, _token
    with _lock:
        _token = None
        _identity = None
