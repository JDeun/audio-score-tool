"""Offline Demucs model binding for packaged selected-stem score modes.

A valid CLI alone is insufficient: both models used by the product must reside
in the same SHA-verified, app-owned immutable component payload. The --repo
argument stops normal Demucs from obtaining missing weights via network/cache.
This checks ownership/shape, not model quality or independent redistribution rights.
"""
from __future__ import annotations

from pathlib import Path

from .config import Settings, packaged_runtime
from .managed_tool_resolver import registered_managed_component_root, registered_managed_tool
from .runner import command_exists

# Official facebookresearch/demucs v4 model signatures and filenames. A future
# model update must explicitly revise this contract and the release acceptance.
_REQUIRED_MODELS = {
    "htdemucs": ("955717e8", "955717e8-8726e21a.th"),
    "htdemucs_6s": ("5c90dfd2", "5c90dfd2-34c22ccb.th"),
}


def managed_demucs_repository(settings: Settings) -> Path | None:
    """Return the verified local model directory, never a user-controlled cache."""
    if not packaged_runtime():
        return None
    owned = registered_managed_tool("demucs", component="demucs")
    if owned is None or Path(settings.demucs_cmd).expanduser() != owned:
        return None
    if not command_exists(settings.demucs_cmd):
        return None
    root = registered_managed_component_root("demucs", required_tool="demucs")
    if root is None:
        return None
    models = root / "models"
    if models.is_symlink() or not models.is_dir():
        return None
    try:
        for name, (signature, weight_name) in _REQUIRED_MODELS.items():
            config = models / f"{name}.yaml"
            weights = models / weight_name
            if (
                config.is_symlink() or not config.is_file()
                or config.read_text(encoding="utf-8").strip() != f"models: ['{signature}']"
                or weights.is_symlink() or not weights.is_file() or weights.stat().st_size < 1
            ):
                return None
    except (OSError, UnicodeError):
        return None
    return models


def demucs_ready(settings: Settings) -> bool:
    if packaged_runtime():
        return managed_demucs_repository(settings) is not None
    return command_exists(settings.demucs_cmd)


def demucs_repo_args(settings: Settings) -> list[str]:
    if not packaged_runtime():
        return []
    repository = managed_demucs_repository(settings)
    if repository is None:
        raise RuntimeError("Verified Demucs runtime or its offline models are unavailable.")
    return ["--repo", str(repository)]
