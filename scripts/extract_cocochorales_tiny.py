"""Safely extract only selected mix WAV/MIDI/metadata from an OFFLINE official shard.

Source: Magenta official CocoChorales tiny v1 downloader, main_dataset
{train,valid,test}/1.tar.bz2; archive MD5 checksums from the official
cocochorales_md5s.txt. This does not fetch or publish any original music.

An explicit operator rights review and a matching archive checksum are
prerequisites. Integrity and licensing review remain separate decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from scripts.prepare_cocochorales_pairs import (
    _MAX_BYTES,
    _ROOT,
    _SOURCE,
    official_split,
    prepare_pairs,
)

_OFFICIAL_MD5 = {
    "train": "999ba8284b0646a6c7f3ef357e15fd59",
    "validation": "697766f8e53ffc9f64708b8bf4acedb1",
    "test": "2c9e617b9f3ec622e0da35734036af49",
}
_SHARD_SPLIT = {"train": "train", "validation": "valid", "test": "test"}
_RELEASE = "cocochorales_full_v1_zipped"
_OFFICIAL_FORMAT_COMMIT = "4647edbce6719fe907e17fcc072651def168eaa5"
_ORIGIN = "https://storage.googleapis.com/magentadata/datasets/cocochorales/"
_MAX_ARCHIVE_BYTES = 8 * 1024**3
_MAX_ENTRIES = 100_000
_REQUIRED = ("mix.wav", "mix.mid", "metadata.yaml")


def _file_digests(path: Path) -> tuple[str, str, int]:
    sha, md5 = hashlib.sha256(), hashlib.md5()
    total = 0
    with path.open("rb") as source:
        for part in iter(lambda: source.read(1024 * 1024), b""):
            total += len(part)
            if total > _MAX_ARCHIVE_BYTES:
                raise ValueError("Official CocoChorales shard exceeds archive budget")
            sha.update(part)
            md5.update(part)
    return sha.hexdigest(), md5.hexdigest(), total


def _selection_details(selection: dict[str, Any]) -> tuple[str, set[str]]:
    if (
        not isinstance(selection, dict)
        or selection.get("schema_version") != 1
        or selection.get("dataset_id") != "cocochorales"
        or selection.get("official_source") != _SOURCE
        or selection.get("source_release_revision") != _RELEASE
        or selection.get("license") != "CC-BY-4.0"
        or selection.get("rights_reviewed") is not True
    ):
        raise ValueError("Official tiny selection needs exact v1 provenance and explicit rights review")
    tracks = selection.get("tracks")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 4:
        raise ValueError("Choose 1 to 4 official tracks, at most eight audio/MIDI files")
    splits, names = set(), set()
    for row in tracks:
        if not isinstance(row, dict):
            raise ValueError("CocoChorales track selection must be an object")
        name, split = row.get("track_id"), row.get("split")
        if not isinstance(name, str) or not isinstance(split, str):
            raise ValueError("CocoChorales track ID/split must be strings")
        if official_split(name) != split or name in names:
            raise ValueError("CocoChorales track split/duplicate contradicts official metadata")
        splits.add(split)
        names.add(name)
    if len(splits) != 1:
        raise ValueError("A single official shard cannot cover mixed dataset splits")
    return splits.pop(), names


def _private_destination(out: Path) -> Path:
    dest = out.expanduser().absolute()
    if dest.is_relative_to(_ROOT) or dest.is_symlink() or dest.exists():
        raise ValueError("CocoChorales extracted media must go to a new private directory outside git")
    if not dest.parent.is_dir() or dest.parent.is_symlink():
        raise ValueError("CocoChorales private destination parent must be a real directory")
    return dest


def extract_official_shard(
    archive: Path, selection: dict[str, Any], *,
    output_root: Path,
) -> dict[str, Any]:
    """Extract exact selected media only; leave no output on invalid pairs."""
    split, names = _selection_details(selection)
    dest = _private_destination(output_root)
    src = archive.expanduser().absolute()
    if (
        src.name != "1.tar.bz2" or src.is_symlink() or not src.is_file()
        or src.is_relative_to(_ROOT)
    ):
        raise ValueError("Use a regular, private official tiny main_dataset split/1.tar.bz2")
    sha, md5, bytes_count = _file_digests(src)
    if md5 != _OFFICIAL_MD5[split]:
        raise ValueError("Official CocoChorales shard MD5 differs from published source")
    target_files = {f"{name}/{item}" for name in names for item in _REQUIRED}
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix=".coco-tiny-", dir=dest.parent) as directory:
        staged = Path(directory) / "corpus"
        staged.mkdir()
        try:
            with tarfile.open(src, mode="r|bz2") as package:
                for count, member in enumerate(package, start=1):
                    if count > _MAX_ENTRIES:
                        raise ValueError("Official CocoChorales shard has too many members")
                    path = member.name.removeprefix("./")
                    if (
                        not path or path.startswith("/") or "\\" in path or ":" in path
                        or any(part in {"", ".", ".."} for part in path.split("/"))
                    ):
                        raise ValueError("Official shard contains unsafe member paths")
                    if path not in target_files:
                        continue
                    if path in seen or not member.isfile() or not 0 < member.size <= _MAX_BYTES:
                        raise ValueError("Selected CocoChorales asset is duplicate/unsafe/too large")
                    stream = package.extractfile(member)
                    if stream is None:
                        raise ValueError("Selected CocoChorales asset cannot be read")
                    output = staged / path
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with stream, output.open("xb") as target:
                        left = member.size
                        while left:
                            part = stream.read(min(1024 * 1024, left))
                            if not part:
                                raise ValueError("Official CocoChorales shard member was truncated")
                            target.write(part)
                            left -= len(part)
                    seen.add(path)
        except (tarfile.TarError, EOFError, OSError) as exc:
            raise ValueError("Official CocoChorales shard is malformed") from exc
        if seen != target_files:
            raise ValueError("Official shard lacks at least one selected audio/MIDI/metadata file")

        # Validate exact official WAV profile, split, MIDI notes and 4 SATB
        # instrument labels before making the final extraction visible.
        pairs, audit = prepare_pairs(selection, corpus_root=staged)
        if dest.exists() or dest.is_symlink():
            raise ValueError("CocoChorales destination was created concurrently")
        staged.replace(dest)

    return {
        "schema_version": 1,
        "dataset": "cocochorales",
        "official_source": _SOURCE,
        "official_release": _RELEASE,
        "official_format_source_commit": _OFFICIAL_FORMAT_COMMIT,
        "official_shard": f"main_dataset/{_SHARD_SPLIT[split]}/1.tar.bz2",
        "official_shard_url": (
            f"{_ORIGIN}{_RELEASE}/main_dataset/{_SHARD_SPLIT[split]}/1.tar.bz2"
        ),
        "official_published_md5_verified": True,
        "archive_md5": md5,
        "archive_sha256": sha,
        "archive_bytes": bytes_count,
        "track_count": len(names),
        "audio_midi_file_count": len(names) * 2,
        "tracks": audit["tracks"],
        "private_corpus_created": True,
        "operator_rights_reviewed": True,
        "upstream_rights_independently_verified": False,
        "model_inference_performed": False,
        "source_media_published": False,
        "commercial_model_redistribution_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract tiny official CocoChorales shard offline")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    out = args.report.expanduser().absolute()
    if (
        out.is_relative_to(_ROOT) or out.is_symlink() or out.exists()
        or not out.parent.is_dir()
    ):
        parser.error("Report must be a new private JSON outside git")
    try:
        plan = json.loads(args.selection.read_text(encoding="utf-8"))
        result = extract_official_shard(args.archive, plan, output_root=args.output_root)
        with out.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"Official CocoChorales shard rejected: {exc}\n")
    print(json.dumps({"track_count": result["track_count"], "source_sha256": result["archive_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
