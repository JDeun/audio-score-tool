"""Fetch the exact immutable upstream MR-MT3 checkpoint for PRIVATE QA.

The trusted source is a Hugging Face commit (never a mutable branch). The
download is independently SHA-256 verified before an atomic private staging
operation. No model deserialization, public artifact, license approval, or
modification to the production managed catalog occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

MODEL_REPO = "gudgud1014/MR-MT3"
MODEL_REVISION = "7bd24c3e1dc26468a6a9354c0a4f174405c9bad8"
CHECKPOINT_NAME = "mt3.pth"
CHECKPOINT_SHA256 = "b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f"
SOURCE_URL = (
    f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{CHECKPOINT_NAME}"
)
_ROOT = Path(__file__).resolve().parents[1]
_MIN_BYTES = 1024 * 1024
_MAX_BYTES = 1024**3


class PinnedCheckpointError(ValueError):
    """An upstream revision, cache entry, or staged checkpoint is not trusted."""


def _private_directory(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_relative_to(_ROOT):
        raise PinnedCheckpointError("Checkpoint/cache must remain outside the Git repository.")
    if path.is_symlink():
        raise PinnedCheckpointError("Checkpoint/cache directory cannot be linked.")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_pinned_checkpoint(checkpoint_dir: Path, *, cache_dir: Path) -> dict:
    """Request pinned Hugging Face snapshot bytes, then stage them if verified."""
    root = _private_directory(checkpoint_dir)
    cache = _private_directory(cache_dir)
    if root == cache or cache.is_relative_to(root) or root.is_relative_to(cache):
        raise PinnedCheckpointError("Checkpoint and HF cache locations must be separate.")
    model_dir = root / "mr_mt3"
    destination = model_dir / CHECKPOINT_NAME
    if model_dir.is_symlink() or destination.is_symlink():
        raise PinnedCheckpointError("Checkpoint destination cannot contain a symlink.")
    if destination.exists() and (
        not destination.is_file() or _sha256(destination) != CHECKPOINT_SHA256
    ):
        raise PinnedCheckpointError("Existing checkpoint is unverified; refusing replacement.")

    # Import only for actual fetching, so offline unit tests and release
    # contract inspections never initiate network activity.
    from huggingface_hub import hf_hub_download

    downloaded = Path(hf_hub_download(
        repo_id=MODEL_REPO,
        filename=CHECKPOINT_NAME,
        revision=MODEL_REVISION,
        cache_dir=str(cache),
    ))
    if not downloaded.is_file() or not downloaded.resolve().is_relative_to(cache):
        raise PinnedCheckpointError("HF cache did not return a regular private checkpoint.")
    if not _MIN_BYTES <= downloaded.stat().st_size <= _MAX_BYTES:
        raise PinnedCheckpointError("Pinned checkpoint file size is implausible.")

    model_dir.mkdir(parents=True, exist_ok=True)
    staged: Path | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".mt3-checkpoint-", suffix=".part",
            dir=model_dir, delete=False,
        ) as output:
            staged = Path(output.name)
            with downloaded.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    total += len(block)
                    if total > _MAX_BYTES:
                        raise PinnedCheckpointError("Checkpoint exceeded its safe size limit.")
                    digest.update(block)
                    output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if total < _MIN_BYTES or digest.hexdigest() != CHECKPOINT_SHA256:
            raise PinnedCheckpointError("Immutable upstream checkpoint SHA-256 mismatch.")
        if destination.exists():
            if not destination.is_file() or _sha256(destination) != CHECKPOINT_SHA256:
                raise PinnedCheckpointError("Existing checkpoint changed before installation.")
        else:
            staged.replace(destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

    return {
        "schema_version": "1",
        "model": "mr_mt3",
        "upstream_repository": MODEL_REPO,
        "upstream_revision": MODEL_REVISION,
        "upstream_source_url": SOURCE_URL,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_bytes": total,
        "immutable_revision_requested": True,
        "checkpoint_sha256_verified": True,
        "model_checkpoint_deserialized": False,
        "model_redistribution_approved": False,
        "release_catalog_modified": False,
        "redistribution_status": "pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Private, immutable MR-MT3 checkpoint fetch.")
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Evidence output must be a new regular file.")
    try:
        report = fetch_pinned_checkpoint(args.checkpoint_dir, cache_dir=args.cache_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(report, out, indent=2, sort_keys=True)
            out.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Private model fetch rejected: {exc}\n")
    print("Private immutable MR-MT3 checkpoint SHA-256 verified; redistribution pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
