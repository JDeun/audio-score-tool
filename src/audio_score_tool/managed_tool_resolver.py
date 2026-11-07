"""Resolve only app-owned, pinned executables.

Some managed bundles contain tools with identical names. The YouTube toolchain
must use its own yt-dlp, Deno, FFmpeg and ffprobe as one verified provider,
rather than silently selecting FFmpeg from an unrelated validation package.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from .paths import app_data_dir

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Defaults prioritize the corresponding provider, but other verified owners
# can still serve unrelated callers when that provider is not installed.
_PREFERRED_OWNERS = {
    "yt-dlp": "youtube_runtime",
    "deno": "youtube_runtime",
    "ffmpeg": "youtube_runtime",
    "ffprobe": "youtube_runtime",
    "mt3-infer": "transcription_engine",
    "audiveris": "audiveris",
    "whisperx": "whisperx",
}


def managed_root() -> Path:
    configured = os.getenv("AST_COMPONENT_DIR")
    return (Path(configured).expanduser() if configured else app_data_dir() / "components").resolve()


def _safe_relative(value: str) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts) and not value.startswith("/")


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


def _component_order(components: dict, name: str, *, owner: str | None) -> list[str]:
    """Order explicitly pinned owners before any generic fallback."""
    if owner is not None:
        return [owner] if _safe_identifier(owner) and owner in components else []
    preferred = _PREFERRED_OWNERS.get(name)
    if preferred in components:
        return [preferred, *(component for component in components if component != preferred)]
    return list(components)


def _validated_tool(
    root: Path, component: str, entry: object, name: str,
) -> Path | None:
    if not _safe_identifier(component) or not isinstance(entry, dict):
        return None
    version = entry.get("version")
    relative_root = entry.get("root")
    tools = entry.get("tools")
    digests = entry.get("tool_sha256")
    if (
        not isinstance(version, str)
        or not _safe_identifier(version)
        or not isinstance(relative_root, str)
        or not isinstance(tools, dict)
        or not isinstance(digests, dict)
    ):
        return None
    expected_root = (PurePosixPath("installed") / component / version).as_posix()
    if relative_root != expected_root:
        return None
    relative_tool = tools.get(name)
    digest = digests.get(name)
    if (
        not isinstance(relative_tool, str)
        or not _safe_relative(relative_tool)
        or not isinstance(digest, str)
        or re.fullmatch(r"[a-f0-9]{64}", digest) is None
    ):
        return None
    installed = root.joinpath(*PurePosixPath(relative_root).parts)
    tool = installed.joinpath(*PurePosixPath(relative_tool).parts)
    if installed.is_symlink() or tool.is_symlink() or not installed.is_dir() or not tool.is_file():
        return None
    # Even an in-root symlinked ancestor must not masquerade as the owner of
    # another bundle's binary; bind every path component to physical storage.
    current = tool.parent
    while current != root and current.is_relative_to(root):
        if current.is_symlink():
            return None
        current = current.parent
    try:
        installed_real = installed.resolve()
        installed_real.relative_to(root)
        tool.resolve().relative_to(installed_real)
        if _sha256(tool) != digest:
            return None
    except (OSError, ValueError):
        return None
    return tool


def _registered_state(root: Path) -> dict | None:
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
    return components if isinstance(components, dict) else None


def registered_managed_tool(name: str, *, component: str | None = None) -> Path | None:
    """Get a verified executable, optionally confined to a specific owner."""
    if not _safe_identifier(name):
        return None
    root = managed_root()
    components = _registered_state(root)
    if components is None:
        return None
    for owner in _component_order(components, name, owner=component):
        resolved = _validated_tool(root, owner, components[owner], name)
        if resolved is not None:
            return resolved
    return None


def is_registered_managed_executable(command: str | Path) -> bool:
    """Accept any genuine SHA-256-verified owner, never generic PATH entries.

    An explicit absolute tool path from audio_validation remains executable
    even when the default FFmpeg provider is youtube_runtime.
    """
    candidate = Path(command).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        return False
    root = managed_root()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    components = _registered_state(root)
    if components is None:
        return False
    for component, entry in components.items():
        if not _safe_identifier(str(component)) or not isinstance(entry, dict):
            continue
        tools = entry.get("tools")
        if not isinstance(tools, dict):
            continue
        for name in tools:
            if not _safe_identifier(str(name)):
                continue
            if _validated_tool(root, str(component), entry, str(name)) == candidate:
                return True
    return False
