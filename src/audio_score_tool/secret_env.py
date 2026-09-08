from __future__ import annotations

import os
import re

_SECRET_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,99}$")
_SECRET_SUFFIXES = ("_API_KEY", "_TOKEN", "_ACCESS_TOKEN", "_SECRET", "_CLIENT_KEY")
_BLOCKED_NAMES = {
    "PATH",
    "HOME",
    "USER",
    "USERNAME",
    "SHELL",
    "PWD",
    "OLDPWD",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LOCALAPPDATA",
    "APPDATA",
    "USERPROFILE",
}


class SecretEnvError(ValueError):
    pass


def validate_secret_env_name(value: str | None) -> str | None:
    if value is None:
        return None
    name = str(value).strip()
    if not name:
        return None
    if name in _BLOCKED_NAMES or not _SECRET_ENV_RE.fullmatch(name):
        raise SecretEnvError("API credential environment variable name is not allowed")
    if not name.endswith(_SECRET_SUFFIXES):
        raise SecretEnvError(
            "API credential environment variable must end in _API_KEY, _TOKEN, _ACCESS_TOKEN, _SECRET, or _CLIENT_KEY"
        )
    return name


def secret_from_env(value: str | None) -> str | None:
    name = validate_secret_env_name(value)
    if not name:
        return None
    token = os.getenv(name, "").strip()
    return token or None
