from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

from .paths import app_data_dir


def managed_root() -> Path:
    configured = os.getenv("AST_COMPONENT_DIR")
    return (Path(configured).expanduser() if configured else app_data_dir() / "components").resolve()


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value.replace("\\", "/"))
    return bool(path.parts) and not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def registered_managed_tool(name: str) -> Path | None:
    root = managed_root()
    state_path = root / "state.json"
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return None
    components = payload.get("components")
    if not isinstance(components, dict):
        return None
    for entry in components.values():
        if not isinstance(entry, dict):
            continue
        relative_root = entry.get("root")
        tools = entry.get("tools")
        if not isinstance(relative_root, str) or not _safe_relative(relative_root) or not isinstance(tools, dict):
            continue
        relative_tool = tools.get(name)
        if not isinstance(relative_tool, str) or not _safe_relative(relative_tool):
            continue
        installed = root.joinpath(*PurePosixPath(relative_root).parts)
        tool = installed.joinpath(*PurePosixPath(relative_tool).parts)
        if tool.is_symlink() or not tool.is_file():
            continue
        try:
            installed_real = installed.resolve()
            installed_real.relative_to(root)
            tool.resolve().relative_to(installed_real)
        except (OSError, ValueError):
            continue
        return tool
    return None
