"""Validate operator-licensed audio/reference-MIDI pairs from domain datasets.

No inference, downloading or remote license discovery is performed. A dataset
registry entry plus operator attestation is necessary but never constitutes
independent proof of copyright status or reference annotation accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import wave
from pathlib import Path

import mido
from mutagen import File as mutagen_file

if __package__:
    from scripts.validate_dataset_registry import KNOWN_TASKS
else:
    from validate_dataset_registry import KNOWN_TASKS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEX = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SPLITS = frozenset({"train", "validation", "test"})
AUDIO_TYPES = frozenset({".wav", ".flac", ".mp3", ".ogg", ".m4a"})
MIDI_TYPES = frozenset({".mid", ".midi"})
PERMISSIVE = frozenset({"cc-by-4.0", "cc0-1.0", "mit", "apache-2.0"})


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(obj: dict, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _asset(asset: dict, root: Path, extensions: frozenset[str]) -> tuple[Path, str]:
    if not isinstance(asset, dict):
        raise ValueError("audio/reference asset must be an object")
    locator = _text(asset, "locator")
    digest = _text(asset, "sha256")
    if not HEX.fullmatch(digest):
        raise ValueError("asset requires a lowercase SHA-256")
    if not locator.startswith("private://"):
        raise ValueError("only private:// locators are accepted for this audit")
    rel = locator.removeprefix("private://")
    if (not rel or "\\" in rel or rel.startswith("/")
            or any(x in {"", ".", ".."} for x in rel.split("/"))):
        raise ValueError("unsafe private asset locator")
    path = root / rel
    actual = path.resolve()
    if actual.suffix.lower() not in extensions:
        raise ValueError("asset type is not supported for its domain")
    if (path.is_symlink() or not actual.is_relative_to(root)
            or not actual.is_file()):
        raise ValueError("missing or unsafe private dataset asset")
    if _sha(actual) != digest:
        raise ValueError("private dataset asset SHA-256 mismatch")
    return actual, locator


def _audio_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as stream:
            if stream.getframerate() <= 0 or stream.getnchannels() <= 0:
                raise ValueError("invalid WAV timing metadata")
            duration = stream.getnframes() / stream.getframerate()
    else:
        parsed = mutagen_file(str(path))
        if parsed is None or parsed.info is None:
            raise ValueError("unreadable compressed audio metadata")
        duration = float(parsed.info.length)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("source audio duration must be positive")
    return round(duration, 6)


def _midi_note_count(path: Path) -> int:
    midi = mido.MidiFile(str(path))
    return sum(
        1 for track in midi.tracks for event in track
        if event.type == "note_on" and event.velocity > 0
    )


def validate_pairs(
    manifest: dict, registry: dict, *,
    corpus_root: Path, commercial: bool = False,
) -> tuple[dict, dict]:
    """Return privacy-safe verification report and a Tier 2 input manifest."""
    root = corpus_root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("corpus_root must be an accessible private directory")
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("cases"), list):
        raise ValueError("paired subset needs schema_version 1 with cases")
    if not manifest["cases"]:
        raise ValueError("paired subset must contain at least one case record")
    if registry.get("schema_version") != 1 or not isinstance(registry.get("datasets"), list):
        raise ValueError("source dataset registry is invalid")
    sources = {
        entry.get("id"): entry for entry in registry["datasets"]
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    if len(sources) != len(registry["datasets"]):
        raise ValueError("duplicate or malformed source dataset IDs")

    seen_cases: set[str] = set()
    recording_splits: dict[str, str] = {}
    hash_splits: dict[str, str] = {}
    verified: list[dict] = []
    tier2_cases: list[dict] = []
    for entry in manifest["cases"]:
        if not isinstance(entry, dict):
            raise ValueError("paired case must be an object")
        case_id, dataset = _text(entry, "id"), _text(entry, "dataset_id")
        if not ID.fullmatch(case_id) or case_id in seen_cases:
            raise ValueError("duplicate or invalid paired case ID")
        seen_cases.add(case_id)
        upstream = sources.get(dataset)
        if upstream is None:
            raise ValueError(f"dataset {dataset} has no upstream registry entry")
        task = _text(upstream, "task")
        if task not in KNOWN_TASKS or task not in {
            "multi_instrument_amt", "piano_amt", "guitar_amt", "ensemble_amt", "vocal_amt",
            "classical_amt", "drum_amt", "bass_amt", "pop_amt",
        }:
            raise ValueError("source dataset is not an audio/MIDI transcription task")
        if upstream.get("audio_included") is not True:
            raise ValueError("source dataset registry does not declare audio")
        if upstream.get("status") != "verified_for_evaluation":
            raise ValueError("source dataset must have reviewed evaluation status")
        license_value = _text(upstream, "license").lower()
        if any(term in license_value for term in ("verify", "other", "unknown", "per_source")):
            raise ValueError("source dataset license is unresolved")
        if commercial and license_value not in PERMISSIVE:
            raise ValueError("non-permissive source cannot enter a commercial evaluation")
        if entry.get("rights_reviewed") is not True:
            raise ValueError("paired case must have an explicit rights review")
        if _text(entry, "license").lower() != license_value:
            raise ValueError("case license does not match source registry")
        split = _text(entry, "split")
        recording = _text(entry, "recording_id")
        if split not in SPLITS or not ID.fullmatch(recording):
            raise ValueError("split/recording_id must be valid")
        audio, audio_locator = _asset(entry.get("audio"), root, AUDIO_TYPES)
        reference, midi_locator = _asset(entry.get("reference_midi"), root, MIDI_TYPES)
        duration = _audio_duration(audio)
        try:
            notes = _midi_note_count(reference)
        except (OSError, EOFError, ValueError) as exc:
            raise ValueError("reference MIDI is not parseable") from exc
        fingerprint = _sha(audio)
        for lookup, value in ((recording_splits, recording), (hash_splits, fingerprint)):
            if value in lookup and lookup[value] != split:
                raise ValueError("cross-split recording identity/audio SHA-256 overlap")
            lookup[value] = split

        verified.append({
            "case_id": case_id, "dataset_id": dataset, "task": task,
            "recording_id": recording, "split": split, "license": license_value,
            "audio_sha256": fingerprint, "reference_midi_sha256": _sha(reference),
            "audio_duration_seconds": duration, "reference_note_on_count": notes,
            "rights_independently_verified": False,
            "alignment_and_annotation_quality_verified": False,
        })
        tier2_cases.append({
            "id": case_id, "title": f"{dataset}/{case_id}",
            "category": "dataset_" + task,
            "genre": "unspecified", "tags": [task, split, dataset],
            "audio": {"locator": audio_locator,
                      "ownership": "operator_reviewed_license_not_independently_verified",
                      "redistributable": False},
            "reference": {"midi": midi_locator},
            "expected_structure": {},
        })
    fingerprint = hashlib.sha256(
        json.dumps([item["audio_sha256"] + ":" + item["reference_midi_sha256"]
                    for item in verified], separators=(",", ":")).encode()
    ).hexdigest()
    report = {
        "schema_version": 1,
        "case_count": len(verified),
        "recording_pairs_fingerprint": fingerprint,
        "by_dataset": {key: sum(item["dataset_id"] == key for item in verified)
                       for key in sorted({x["dataset_id"] for x in verified})},
        "cases": verified, "source_audio_published": False,
        "model_inference_performed": False, "commercial_model_approved": False,
        "upstream_rights_independently_verified": False,
        "paired_audio_alignment_measured": False,
    }
    return report, {"corpus_version": "paired-" + fingerprint[:16], "cases": tier2_cases}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit owned/authorized domain dataset pairs")
    parser.add_argument("pairs", type=Path, help="Private paired case manifest JSON")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--tier2-manifest", type=Path, required=True)
    parser.add_argument("--commercial", action="store_true")
    args = parser.parse_args()
    report, tier2 = validate_pairs(
        json.loads(args.pairs.read_text(encoding="utf-8")),
        json.loads(args.registry.read_text(encoding="utf-8")),
        corpus_root=args.corpus_root, commercial=args.commercial,
    )
    for path, data in ((args.report, report), (args.tier2_manifest, tier2)):
        destination = path.expanduser().resolve()
        if destination == PROJECT_ROOT or destination.is_relative_to(PROJECT_ROOT):
            raise ValueError("private dataset metadata outputs must be outside the repository")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    print(json.dumps({"case_count": report["case_count"],
                      "fingerprint": report["recording_pairs_fingerprint"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
