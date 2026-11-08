"""Privately prepare a real, upstream-pinned CocoChorales official sample ZIP.

The project authors explicitly publish these example ZIPs on their GitHub
Pages site as the same track IDs/format as the full dataset. Unlike the large
tiny-v1 tar shards, a sample ZIP can provide a genuine audio+reference-MIDI
pair for a small, reproducible first model measurement.

Never uploads source media, model weights, or claims redistribution approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from scripts.prepare_cocochorales_pairs import _ROOT, _SOURCE, official_split, prepare_pairs
from scripts.validate_tier2_dataset_pairs import validate_pairs

SOURCE_REPO = "lukewys/lukewys.github.io"
SOURCE_COMMIT = "7a0b15e7be365a6b062027c38ce0f8d57ed1d98a"
SOURCE_PAGE = "https://lukewys.github.io/cocochorales/"
SOURCE_FORMAT_COMMIT = "4647edbce6719fe907e17fcc072651def168eaa5"
SOURCE_RELEASE = f"official-sample-site@{SOURCE_COMMIT}"
SAMPLE_ROOT = "cocochorales/assets/sample_examples/pieces"
# Immutable Git blob OIDs retrieved from the public, pinned upstream Git tree.
# These are content checks, not legal grants or modern signed attestations.
SAMPLE_BLOBS: dict[str, tuple[str, int]] = {
    "string_track001010": ("81fd702d468094a11b30cc2d41e87a85da4651b7", 18_345_823),
    "brass_track049013": ("edeac26f1f47825a3ce7f55ec2a9ffd62cdacf58", 14_796_241),
    "woodwind_track097010": ("f36e7059df65c8cfbbc854dcf714b97362e27083", 10_719_458),
    "random_track145011": ("6a249460961ba661056f7602001c6e2f55ffa449", 15_303_828),
}
MAX_ZIP_ENTRIES = 5000
MAX_TOTAL_EXTRACTED = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 128 * 1024 * 1024


def _private_new_dir(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    if (
        absolute.is_relative_to(_ROOT) or absolute.is_symlink() or absolute.exists()
        or not absolute.parent.is_dir() or absolute.parent.is_symlink()
    ):
        raise ValueError("Output must be a new private directory outside the repository")
    return absolute


def _digest_and_git_blob(path: Path, *, maximum: int) -> tuple[str, str, int]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("Official sample ZIP is missing, linked or exceeds resource budget")
    length = path.stat().st_size
    blob = hashlib.sha1(f"blob {length}\0".encode("ascii"))
    sha = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            blob.update(chunk)
            sha.update(chunk)
    return sha.hexdigest(), blob.hexdigest(), length


def _destination_member(name: str, track_id: str) -> str | None:
    if (
        not name or len(name) > 1024 or "\\" in name or name.startswith("/")
        or ":" in name or any(part in {"", ".", ".."} for part in name.split("/"))
        or PurePosixPath(name).is_absolute()
    ):
        raise ValueError("Official sample ZIP contains an unsafe member path")
    base = PurePosixPath(name).name
    if base in {"mix.wav", "mix.mid", "metadata.yaml"}:
        return base
    if base == f"{track_id}.yaml":
        return "metadata.yaml"
    return None


def prepare_official_sample(
    archive: Path, track_id: str, *, corpus_root: Path, metadata_root: Path,
) -> dict:
    if track_id not in SAMPLE_BLOBS:
        raise ValueError("Only commit-pinned, official example track IDs are supported")
    if official_split(track_id) != "train":
        raise ValueError("Official demonstration track has an unexpected dataset split")
    if archive.is_symlink() or archive.name != f"{track_id}.zip":
        raise ValueError("Official sample must retain its exact downloaded archive name")
    corpus = _private_new_dir(corpus_root)
    metadata = _private_new_dir(metadata_root)
    if (
        corpus == metadata or corpus.is_relative_to(metadata)
        or metadata.is_relative_to(corpus)
    ):
        raise ValueError("Private source and report destinations must be disjoint")
    archive_sha, git_blob, total_archive = _digest_and_git_blob(
        archive, maximum=64 * 1024 * 1024,
    )
    pinned_blob, pinned_length = SAMPLE_BLOBS[track_id]
    if (git_blob, total_archive) != (pinned_blob, pinned_length):
        raise ValueError("Official sample bytes differ from the pinned upstream Git blob")

    with tempfile.TemporaryDirectory(prefix=".coco-sample-", dir=corpus.parent) as tmp:
        stage = Path(tmp) / "corpus"
        stage.mkdir()
        directory = stage / track_id
        directory.mkdir()
        extracted: dict[str, str] = {}
        aggregate_size = 0
        try:
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                if not 0 < len(infos) <= MAX_ZIP_ENTRIES:
                    raise ValueError("Official sample ZIP member count is outside safe bounds")
                for info in infos:
                    name = info.filename.rstrip("/") if info.is_dir() else info.filename
                    if not name:
                        raise ValueError("Official sample ZIP contains an invalid member")
                    selected = _destination_member(name, track_id)
                    mode = info.external_attr >> 16
                    if stat.S_IFMT(mode) == stat.S_IFLNK:
                        raise ValueError("Official sample ZIP contains a symlink")
                    if selected is None or info.is_dir():
                        continue
                    if (
                        selected in extracted or not 0 < info.file_size <= MAX_MEMBER_BYTES
                        or not info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    ):
                        raise ValueError("Duplicate, unsupported or oversized sample member")
                    aggregate_size += info.file_size
                    if aggregate_size > MAX_TOTAL_EXTRACTED:
                        raise ValueError("Total selected sample media exceeds extraction budget")
                    output = directory / selected
                    with package.open(info) as incoming, output.open("xb") as out:
                        remaining = info.file_size
                        digest = hashlib.sha256()
                        while remaining:
                            chunk = incoming.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError("Official sample member ended prematurely")
                            remaining -= len(chunk)
                            digest.update(chunk)
                            out.write(chunk)
                    extracted[selected] = digest.hexdigest()
        except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
            raise ValueError("Official sample ZIP cannot be safely unpacked") from exc

        if set(extracted) != {"mix.wav", "mix.mid", "metadata.yaml"}:
            raise ValueError("Official sample must include original mix WAV, MIDI and metadata")

        selection = {
            "schema_version": 1, "dataset_id": "cocochorales",
            "official_source": _SOURCE,
            "source_release_revision": SOURCE_RELEASE,
            "license": "CC-BY-4.0", "rights_reviewed": True,
            "tracks": [{"track_id": track_id, "split": "train"}],
        }
        pairs, audit = prepare_pairs(selection, corpus_root=stage)
        # The committed production registry stays 'planned'. This *private*
        # evaluation copy is reviewed only for original CC-BY-4.0 sample use.
        registry = {
            "schema_version": 1,
            "datasets": [{
                "id": "cocochorales",
                "source": _SOURCE,
                "task": "ensemble_amt",
                "audio_included": True,
                "license": "CC-BY-4.0",
                "status": "verified_for_evaluation",
                "evaluation_scope": "official pinned author sample only",
            }],
        }
        pair_report, tier2 = validate_pairs(pairs, registry, corpus_root=stage)
        report = {
            "schema_version": 1,
            "dataset": "cocochorales",
            "source_kind": "official-sample-zip",
            "official_source": _SOURCE,
            "official_sample_page": SOURCE_PAGE,
            "source_repository": SOURCE_REPO,
            "source_revision": SOURCE_COMMIT,
            "official_format_source_commit": SOURCE_FORMAT_COMMIT,
            "official_release": SOURCE_RELEASE,
            "official_archive_path": f"{SAMPLE_ROOT}/{track_id}.zip",
            "archive_git_blob_sha1": git_blob,
            "archive_sha256": archive_sha,
            "archive_bytes": total_archive,
            "selected_uncompressed_bytes": aggregate_size,
            "track_count": 1,
            "case_count": pair_report["case_count"],
            "paired_fingerprint": pair_report["recording_pairs_fingerprint"],
            "tracks": audit["tracks"],
            "attribution": {
                "creator": "Yusong Wu and CocoChorales contributors",
                "license": "CC-BY-4.0",
                "license_page": _SOURCE,
                "changes": "Dataset media unchanged; model predictions and statistics separately generated",
            },
            "operator_rights_reviewed": True,
            "upstream_rights_independently_verified": False,
            "model_inference_performed": False,
            "source_media_published": False,
            "commercial_model_redistribution_approved": False,
        }
        metadata.mkdir()
        for name, value in [
            ("pairs.json", pairs),
            ("reviewed-registry.json", registry),
            ("tier2-manifest.json", tier2),
            ("source-proof.pending.json", report),
        ]:
            (metadata / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if corpus.exists():
            raise ValueError("Private corpus directory was created during extraction")
        stage.rename(corpus)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify original official CocoChorales sample")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--track-id", required=True)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--metadata-root", required=True, type=Path)
    args = parser.parse_args()
    report = prepare_official_sample(
        args.archive, args.track_id,
        corpus_root=args.corpus_root, metadata_root=args.metadata_root,
    )
    print(json.dumps({
        "source": report["source_repository"],
        "source_revision": report["source_revision"],
        "track_count": report["track_count"],
        "archive_sha256": report["archive_sha256"],
        "media_published": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
