from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from .paths import app_data_dir

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def managed_root() -> Path:
    configured = os.getenv("AST_COMPONENT_DIR")
    return (Path(configured).expanduser() if configured else app_data_dir() / "components").resolve()


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(path.parts) and not path.is_absolute() and all(
        part not in {"", ".", ".."} for part in path.parts
    )


def _safe_identifier(value: str) -> bool:
    return bool(_SAFE_IDENTIFIER.fullmatch(value)) and value not in {".", ".."}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def registered_managed_tool(name: str) -> Path | None:
    if not _safe_identifier(name):
        return None
    root = managed_root()
    state_path = root / "state.json"
    if state_path.is_symlink():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return None
    components = payload.get("components")
    if not isinstance(components, dict):
        return None
    for component_name, entry in components.items():
        if not _safe_identifier(str(component_name)) or not isinstance(entry, dict):
            continue
        relative_root = entry.get("root")
        tools = entry.get("tools")
        digests = entry.get("tool_sha256")
        if (
            not isinstance(relative_root, str)
            or not _safe_relative(relative_root)
            or not isinstance(tools, dict)
            or not isinstance(digests, dict)
        ):
            continue
        relative_tool = tools.get(name)
        expected_digest = digests.get(name)
        if (
            not isinstance(relative_tool, str)
            or not _safe_relative(relative_tool)
            or not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_digest)
        ):
            continue
        installed = root.joinpath(*PurePosixPath(relative_root).parts)
        tool = installed.joinpath(*PurePosixPath(relative_tool).parts)
        if installed.is_symlink() or tool.is_symlink() or not installed.is_dir() or not tool.is_file():
            continue
        try:
            installed_real = installed.resolve()
            installed_real.relative_to(root)
            tool.resolve().relative_to(installed_real)
            if _sha256(tool) != expected_digest:
                continue
        except (OSError, ValueError):
            continue
        return tool
    return None
