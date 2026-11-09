"""Resolve user-approved MuScriptor weights from AudioScoreTool's Hugging Face cache.

The model manager downloads explicitly with the in-memory HF session token.
Inference must load the exact local snapshot, not ask the child CLI to download
by model size (which loses the session token and may use a different HF_HOME).
This is cache readiness, NOT an independent SHA/redistribution attestation.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .config import component_dir, packaged_runtime

# Match the published MuScriptor config.json architecture for each variant.
_VARIANT_CONFIGS = {
    "small": (768, 12, 14, 1393),
    "medium": (1024, 16, 24, 1395),
    "large": (1536, 24, 48, 1395),
}
_REVISION = re.compile(r"[0-9a-f]{40}\\Z")
_MIN_CHECKPOINT_BYTES = 1024 * 1024


def hf_home() -> Path:
    if packaged_runtime():
        return component_dir() / "models" / "huggingface"
    raw = os.getenv("HF_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".cache" / "huggingface"


def hub_root() -> Path:
    return hf_home() / "hub"


def cached_muscriptor_checkpoint(
    variant: str, *, cache_root: Path | None = None,
) -> Path | None:
    """Return the exact locally cached checkpoint for a supported model variant.

    Require a complete same-revision config + weights pair. Hugging Face normally
    symlinks snapshot files to blobs within the same repo cache; allow those but
    reject external symlinks, ambiguous revisions, partial snapshots and mismatched
    model configs. Never invoke any network API or deserialize model weights here.
    """
    config = _VARIANT_CONFIGS.get(variant)
    if config is None:
        return None
    repo = (cache_root if cache_root is not None else hub_root()) / (
        f"models--MuScriptor--muscriptor-{variant}"
    )
    snapshots = repo / "snapshots"
    if repo.is_symlink() or snapshots.is_symlink() or not snapshots.is_dir():
        return None
    try:
        repo_resolved = repo.resolve(strict=True)
        main_ref = repo / "refs" / "main"
        if main_ref.is_symlink():
            return None
        if main_ref.is_file():
            revision = main_ref.read_text(encoding="ascii")[:80].strip()
            if not _REVISION.fullmatch(revision):
                return None
            candidates = [snapshots / revision]
        else:
            # A cache populated by an immutable revision can lack refs/main.
            # Never guess which revision is current when multiple exist.
            candidates = [
                path for path in snapshots.iterdir()
                if path.is_dir() and not path.is_symlink()
                and _REVISION.fullmatch(path.name)
            ]
            if len(candidates) != 1:
                return None
        snapshot = candidates[0]
        if snapshot.is_symlink() or not snapshot.is_dir() or not _REVISION.fullmatch(snapshot.name):
            return None
        weights = snapshot / "model.safetensors"
        settings = snapshot / "config.json"
        for path in (weights, settings):
            if not path.is_file() or not path.resolve(strict=True).is_relative_to(repo_resolved):
                return None
        if weights.stat().st_size < _MIN_CHECKPOINT_BYTES or not 0 < settings.stat().st_size < 65536:
            return None
        metadata = json.loads(settings.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict):
            return None
        if metadata.get("model_type", "muscriptor") != "muscriptor":
            return None
        if metadata.get("variant", variant) != variant:
            return None
        if tuple(metadata.get(field) for field in ("dim", "num_heads", "num_layers", "card")) != config:
            return None
        # Preserve the snapshot location: upstream loads adjacent config.json.
        # Returning weights.resolve() would relocate it into blobs/ and break that.
        return weights
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError):
        return None
