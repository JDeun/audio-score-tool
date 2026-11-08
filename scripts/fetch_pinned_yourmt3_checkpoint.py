"""Fetch immutable YourMT3 YPTF.MoE+Multi (noPS) checkpoint for PRIVATE QA.

Upstream MT3-Infer 0.2.0 registry identifies a Hugging Face Space Git-LFS
checkpoint. Git LFS cloning is not sufficient proof of its bytes. Download
the exact Space revision and verify the recorded whole-file SHA-256 before
atomically staging it in the MT3_CHECKPOINT_DIR layout expected by mt3-infer.

No model deserialization, redistribution rights approval or public upload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from scripts.fetch_pinned_mrmt3_checkpoint import _private_directory

MODEL_REPO = "mimbres/YourMT3"
MODEL_REVISION = "5e66c1ea173a8186e0d20432b841d3180cc015b5"
MODEL_VARIANT = "mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops"
CHECKPOINT_FILENAME = f"amt/logs/2024/{MODEL_VARIANT}/checkpoints/last.ckpt"
CHECKPOINT_SHA256 = "ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25"
SOURCE_URL = (
    f"https://huggingface.co/spaces/{MODEL_REPO}/resolve/"
    f"{MODEL_REVISION}/{CHECKPOINT_FILENAME}"
)
_MIN_BYTES = 100 * 1024 * 1024
_MAX_BYTES = 1024 * 1024 * 1024


class YourMT3CheckpointError(ValueError):
    """A source revision, downloaded weight, or local destination is not trusted."""


def _sha256(path: Path) -> str:
    hash_value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(block)
    return hash_value.hexdigest()


def fetch_pinned_checkpoint(checkpoint_dir: Path, *, cache_dir: Path) -> dict:
    root = _private_directory(checkpoint_dir)
    cache = _private_directory(cache_dir)
    if root == cache or cache.is_relative_to(root) or root.is_relative_to(cache):
        raise YourMT3CheckpointError("Checkpoint and cache directories must be disjoint")
    model_dir = root / "yourmt3" / MODEL_VARIANT
    dest = model_dir / "last.ckpt"
    if model_dir.is_symlink() or dest.is_symlink():
        raise YourMT3CheckpointError("Model destination must not be a symlink")
    if dest.exists() and (not dest.is_file() or _sha256(dest) != CHECKPOINT_SHA256):
        raise YourMT3CheckpointError("Existing YourMT3 checkpoint is unverified")

    from huggingface_hub import hf_hub_download

    source = Path(hf_hub_download(
        repo_type="space",
        repo_id=MODEL_REPO,
        filename=CHECKPOINT_FILENAME,
        revision=MODEL_REVISION,
        cache_dir=str(cache),
    ))
    if not source.is_file() or not source.resolve().is_relative_to(cache):
        raise YourMT3CheckpointError("Source checkpoint is not inside the private HF cache")
    if not _MIN_BYTES <= source.stat().st_size <= _MAX_BYTES:
        raise YourMT3CheckpointError("Model checkpoint size is outside pinned download budget")

    sha = hashlib.sha256()
    total = 0
    model_dir.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".yourmt3-", suffix=".part", dir=model_dir, delete=False,
        ) as output:
            staged = Path(output.name)
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise YourMT3CheckpointError("Downloaded checkpoint exceeds size limit")
                    sha.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if sha.hexdigest() != CHECKPOINT_SHA256:
            raise YourMT3CheckpointError("Immutable YourMT3 checkpoint SHA-256 mismatch")
        if dest.exists():
            if not dest.is_file() or _sha256(dest) != CHECKPOINT_SHA256:
                raise YourMT3CheckpointError("Local checkpoint changed before staging")
        else:
            staged.replace(dest)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

    return {
        "schema_version": "1",
        "model": "yourmt3",
        "model_variant": "YPTF.MoE+Multi (noPS)",
        "upstream_repository": MODEL_REPO,
        "upstream_repository_type": "space",
        "upstream_revision": MODEL_REVISION,
        "upstream_source_url": SOURCE_URL,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_bytes": total,
        "immutable_revision_requested": True,
        "checkpoint_sha256_verified": True,
        "checkpoint_deserialized": False,
        "license_review": "source/checkpoint/runtime redistribution rights pending",
        "model_redistribution_approved": False,
        "release_catalog_modified": False,
        "redistribution_status": "pending",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Private pinned YourMT3 weight download")
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("A new metadata-only report output is required")
    try:
        proof = fetch_pinned_checkpoint(args.checkpoint_dir, cache_dir=args.cache_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(proof, file, ensure_ascii=False, sort_keys=True, indent=2)
            file.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"YourMT3 source verification failed: {exc}\n")
    print("Private immutable YourMT3 checkpoint SHA-256 verified; rights review pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
