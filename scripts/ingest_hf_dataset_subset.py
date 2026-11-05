"""Pinned, fail-closed, small Hugging Face dataset subset ingestion.

The Hub is a distribution host, NOT a source of redistribution approval.
No download occurs without --fetch, operator-reviewed per-source rights, pinned
revision, exact per-file size/checksum and a small total byte/file budget.
This tool does not run inference and never uploads private source media.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FILE_COMPONENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+ -]{0,127}$")
RECORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PERMISSIVE = frozenset({"cc0-1.0", "cc-by-4.0", "apache-2.0", "mit"})
MAX_FILES = 8
MAX_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 32 * 1024 * 1024


def _required(record: dict, name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value.strip()


def _path(value: str) -> Path:
    if "\\" in value or value.startswith(("/", "~")) or "%" in value or ":" in value:
        raise ValueError("dataset file path must be a plain relative Hub filename")
    parts = value.split("/")
    if len(parts) > 8 or not all(
        part not in {".", ".."} and FILE_COMPONENT.fullmatch(part) for part in parts
    ):
        raise ValueError(f"unsafe Hub file path: {value!r}")
    return Path(*parts)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_subset_plan(
    payload: dict[str, Any], *, commercial: bool = False,
    max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES,
) -> dict:
    """Check operator attestations and cross-source recording/split integrity."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("subset schema_version must be 1")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise ValueError("subset datasets must be a nonempty array")
    if max_files < 1 or max_bytes < 1:
        raise ValueError("limits must be positive")
    ids: set[str] = set()
    file_keys: set[tuple[str, str]] = set()
    splits: dict[str, str] = {}
    audio_splits: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    total = 0
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise ValueError("dataset must be an object")
        dataset_id = _required(dataset, "id")
        if not RECORD.fullmatch(dataset_id) or dataset_id in ids:
            raise ValueError(f"duplicate or unsafe dataset id: {dataset_id}")
        ids.add(dataset_id)
        repo_id = _required(dataset, "repo_id")
        revision = _required(dataset, "revision")
        license_name = _required(dataset, "license").lower()
        if not REPO.fullmatch(repo_id) or not REVISION.fullmatch(revision):
            raise ValueError("Hub repo_id and exact 40-hex commit revision are required")
        if dataset.get("rights_reviewed") is not True:
            raise ValueError(f"dataset {dataset_id} requires an explicit operator rights review")
        if ("verify" in license_name or "other" in license_name or "unknown" in license_name
                or "per_source" in license_name):
            raise ValueError(f"dataset {dataset_id} source license is unresolved")
        if commercial and license_name not in PERMISSIVE:
            raise ValueError(f"dataset {dataset_id} is not approved for commercial ingestion")
        files = dataset.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("each source needs a minimal list of selected files")
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("file item must be an object")
            rel = _path(_required(item, "path"))
            size = item.get("size_bytes")
            if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_FILE_BYTES:
                raise ValueError("file size_bytes must be positive and <=32MiB")
            total += size
            digest = _required(item, "sha256")
            if not SHA.fullmatch(digest):
                raise ValueError("every selected file must have a pinned lowercase SHA-256")
            recording = _required(item, "recording_id")
            split = _required(item, "split")
            if not RECORD.fullmatch(recording) or split not in {"train", "validation", "test"}:
                raise ValueError("recording_id/split must use a safe ID and known split")
            key = (repo_id + "@" + revision, rel.as_posix())
            if key in file_keys:
                raise ValueError("duplicate selected Hub source file")
            file_keys.add(key)
            for bucket, label in ((splits, recording), (audio_splits, item.get("audio_sha256"))):
                if label is None:
                    continue
                if bucket is audio_splits and (not isinstance(label, str) or not SHA.fullmatch(label)):
                    raise ValueError("audio_sha256 must be lowercase SHA-256")
                if label in bucket and bucket[label] != split:
                    raise ValueError("cross-split recording overlap detected")
                bucket[label] = split
            items.append({
                "dataset_id": dataset_id,
                "repo_id": repo_id,
                "revision": revision,
                "license": license_name,
                "path": rel.as_posix(),
                "size_bytes": size,
                "sha256": digest,
                "recording_id": recording,
                "audio_sha256": item.get("audio_sha256"),
                "split": split,
            })
            if len(items) > max_files or total > max_bytes:
                raise ValueError("requested Hub subset exceeds the minimal download budget")
    return {
        "schema_version": 1,
        "mode": "reviewed_small_subset_only",
        "commercial": commercial,
        "file_count": len(items),
        "total_bytes": total,
        "items": items,
        "rights_reviewed_by_operator_only": True,
        "license_and_alignment_independently_verified": False,
    }


def _remote_size(item: dict) -> int:
    """Server size preflight: refuse a large shard before any download."""
    from huggingface_hub import get_hf_file_metadata, hf_hub_url

    url = hf_hub_url(
        repo_id=item["repo_id"], repo_type="dataset",
        filename=item["path"], revision=item["revision"],
    )
    metadata = get_hf_file_metadata(url)
    if metadata.size is None:
        raise ValueError("Hub server did not return file size")
    return int(metadata.size)


def _download(item: dict, cache: Path) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(
        repo_id=item["repo_id"],
        repo_type="dataset",
        revision=item["revision"],
        filename=item["path"],
        cache_dir=str(cache),
    ))


def ingest(
    plan: dict,
    private_root: Path,
    *,
    fetch: bool = False,
    commercial: bool = False,
) -> dict:
    """Produce metadata only; when fetch=True verify every selected local byte."""
    prepared = validate_subset_plan(plan, commercial=commercial)
    result = {**prepared, "executed": fetch, "verified_files": 0}
    if not fetch:
        return result
    destination = private_root.expanduser().resolve()
    if destination == ROOT or destination.is_relative_to(ROOT):
        raise ValueError("private_root must be outside the tracked repository")
    if destination.exists() and not destination.is_dir():
        raise ValueError("private_root must be a directory")
    destination.mkdir(parents=True, exist_ok=True)
    cache = destination / ".hf-cache"
    for item in result["items"]:
        size = _remote_size(item)
        if size != item["size_bytes"] or size > MAX_FILE_BYTES:
            raise ValueError(f"remote size mismatch or oversize: {item['path']}")
        source = _download(item, cache)
        if not source.is_file() or source.stat().st_size != size or _sha(source) != item["sha256"]:
            raise ValueError(f"download checksum or length mismatch: {item['path']}")
        target = destination / item["dataset_id"] / item["revision"] / item["path"]
        if not target.resolve().is_relative_to(destination):
            raise ValueError("unsafe dataset destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file() or _sha(target) != item["sha256"]:
                raise ValueError("existing private dataset artifact differs; refusing overwrite")
        else:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".subset-", delete=False) as temporary:
                temporary_path = Path(temporary.name)
                try:
                    with source.open("rb") as handle:
                        shutil.copyfileobj(handle, temporary, length=1024 * 1024)
                finally:
                    temporary.flush()
                    os.fsync(temporary.fileno())
            try:
                if _sha(temporary_path) != item["sha256"]:
                    raise ValueError("copied private dataset checksum mismatch")
                temporary_path.replace(target)
            finally:
                temporary_path.unlink(missing_ok=True)
        result["verified_files"] += 1
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Pinned small Hub dataset subset; default dry-run")
    parser.add_argument("manifest", type=Path, help="Operator-reviewed local subset JSON")
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="Explicitly download selected files")
    parser.add_argument("--commercial", action="store_true", help="Reject noncommercial licenses")
    parser.add_argument("--report", type=Path, help="Optional metadata-only result file")
    args = parser.parse_args()
    input_data = json.loads(args.manifest.read_text(encoding="utf-8"))
    output = ingest(input_data, args.private_root, fetch=args.fetch, commercial=args.commercial)
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
