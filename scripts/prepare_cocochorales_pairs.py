"""Prepare a tiny, local CocoChorales mix.wav + mix.mid Tier-2 pair manifest.

The official CocoChorales main_dataset keeps audio, aligned MIDI and metadata
under one <ensemble>_track###### directory. This tool never downloads bulk
data or assumes that a file's presence proves redistribution rights.

Only a user's explicitly selected, locally copied tracks are hashed/validated.
Actual audio and MIDI stay in the private corpus; outputs contain *only*
relative private:// locators, digests, note counts and bounded durations.
The existing validate_tier2_dataset_pairs CLI must still independently check
operator-reviewed per-source rights and exact evaluation status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import wave
from pathlib import Path
from typing import Any

import mido

_ROOT = Path(__file__).resolve().parents[1]
_TRACK = re.compile(r"^(string|brass|woodwind|random)_track[0-9]{6}$")
_SPLITS = frozenset({"train", "validation", "test"})
_SOURCE = "https://magenta.tensorflow.org/datasets/cocochorales"
_DATASET_ID = "cocochorales"
_LICENSE = "CC-BY-4.0"
_MAX_TRACKS = 16
_MAX_BYTES = 128 * 1024 * 1024


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def _regular(root: Path, relative: str) -> Path:
    if (
        not relative or "\\" in relative or relative.startswith("/")
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("Unsafe CocoChorales relative file path")
    path = root.joinpath(*relative.split("/"))
    if not path.is_file() or path.is_symlink():
        raise ValueError("CocoChorales track file is missing or linked")
    for parent in (path.parent, *path.parent.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("CocoChorales track directory is linked")
    if not path.resolve().is_relative_to(root):
        raise ValueError("CocoChorales asset escapes private corpus root")
    size = path.stat().st_size
    if not 0 < size <= _MAX_BYTES:
        raise ValueError("CocoChorales file exceeds local sample budget")
    return path


def _duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as reader:
            frame_rate = reader.getframerate()
            if (
                reader.getnchannels() not in {1, 2}
                or reader.getsampwidth() != 2
                or frame_rate != 16000
                or reader.getnframes() <= 0
            ):
                raise ValueError("CocoChorales WAV must be 16kHz 16-bit PCM")
            seconds = reader.getnframes() / frame_rate
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("CocoChorales WAV cannot be decoded") from exc
    if not 0 < seconds <= 600:
        raise ValueError("CocoChorales mix duration is unreasonable")
    return round(seconds, 6)


def _notes(path: Path) -> tuple[int, float]:
    try:
        midi = mido.MidiFile(path)
        count = sum(
            1 for track in midi.tracks for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        )
        seconds = float(midi.length)
    except (OSError, EOFError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("CocoChorales reference MIDI is invalid") from exc
    if count < 1 or not 0 <= seconds <= 600:
        raise ValueError("CocoChorales reference MIDI has no playable notes")
    return count, round(seconds, 6)


def prepare_pairs(
    selected: dict[str, Any], *, corpus_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return existing Tier-2 pair-validator input and metadata-only audit.

    The source is an operator-reviewed *local copy* of the official dataset;
    no approval is inferred from the included permissive dataset license.
    """
    root = corpus_root.expanduser().absolute()
    if not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise ValueError("CocoChorales corpus root must be an existing private directory")
    if root.is_relative_to(_ROOT) or root == _ROOT:
        raise ValueError("CocoChorales source audio must stay outside the repository")
    if (
        not isinstance(selected, dict) or selected.get("schema_version") != 1
        or selected.get("dataset_id") != _DATASET_ID
        or selected.get("official_source") != _SOURCE
        or selected.get("license") != _LICENSE
    ):
        raise ValueError("CocoChorales input must use exact official dataset identity")
    reviewed = selected.get("rights_reviewed") is True
    revision = selected.get("source_release_revision")
    if not isinstance(revision, str) or not 8 <= len(revision) <= 128:
        raise ValueError("CocoChorales exact source release/revision is required")
    # The operator must supply a non-placeholder, traceable source artifact
    # identity; this tool cannot independently audit external distribution rights.
    if revision.lower() in {"unknown", "unreviewed", "placeholder", "todo"}:
        raise ValueError("CocoChorales source release is a placeholder")
    tracks = selected.get("tracks")
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= _MAX_TRACKS:
        raise ValueError("Select 1 to 16 CocoChorales tiny tracks explicitly")
    used: set[str] = set()
    cases: list[dict[str, Any]] = []
    recorded: list[dict[str, Any]] = []
    for item in tracks:
        if not isinstance(item, dict):
            raise ValueError("CocoChorales track must be an object")
        track_id, split = item.get("track_id"), item.get("split")
        if (
            not isinstance(track_id, str) or not _TRACK.fullmatch(track_id)
            or track_id in used or split not in _SPLITS
        ):
            raise ValueError("Track IDs must be unique official CocoChorales names with explicit splits")
        used.add(track_id)
        audio_rel = f"{track_id}/mix.wav"
        midi_rel = f"{track_id}/mix.mid"
        metadata_rel = f"{track_id}/metadata.yaml"
        audio = _regular(root, audio_rel)
        reference = _regular(root, midi_rel)
        metadata = _regular(root, metadata_rel)
        duration = _duration(audio)
        count, midi_seconds = _notes(reference)
        # The dataset may add a small release/reverb tail; reject grossly
        # unaligned filenames, not legitimate trailing silence.
        if midi_seconds > duration + 3:
            raise ValueError("CocoChorales MIDI timing exceeds paired source audio")
        audio_sha, midi_sha = _digest(audio), _digest(reference)
        case_id = f"coco-{track_id}"
        cases.append({
            "id": case_id,
            "dataset_id": _DATASET_ID,
            "recording_id": track_id,
            "split": split,
            "rights_reviewed": reviewed,
            "license": _LICENSE,
            "audio": {"locator": f"private://{audio_rel}", "sha256": audio_sha},
            "reference_midi": {
                "locator": f"private://{midi_rel}", "sha256": midi_sha,
            },
        })
        recorded.append({
            "track_id": track_id, "split": split,
            "mix_wav_sha256": audio_sha, "mix_midi_sha256": midi_sha,
            "metadata_sha256": _digest(metadata),
            "duration_seconds": duration,
            "midi_duration_seconds": midi_seconds,
            "reference_note_on_count": count,
        })
    pairs = {"schema_version": 1, "cases": cases}
    audit = {
        "schema_version": 1,
        "dataset_id": _DATASET_ID,
        "official_source": _SOURCE,
        "source_release_revision": revision,
        "license": _LICENSE,
        "rights_reviewed_by_operator_only": reviewed,
        "case_count": len(cases),
        "tracks": recorded,
        "midi_audio_alignment_independently_measured": False,
        "model_inference_performed": False,
        "source_media_published": False,
        "commercial_model_redistribution_approved": False,
    }
    return pairs, audit


def _write_new(path: Path, payload: dict) -> None:
    out = path.expanduser().absolute()
    if (
        out.is_relative_to(_ROOT) or out.is_symlink()
        or out.exists() or not out.parent.is_dir()
    ):
        raise ValueError("CocoChorales metadata output must be new and outside the repository")
    with out.open("x", encoding="utf-8") as target:
        json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
        target.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline CocoChorales tiny mix.wav+mix.mid pair manifest; no inference/download"
    )
    parser.add_argument("selection", type=Path)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    selected = json.loads(args.selection.read_text(encoding="utf-8"))
    pairs, report = prepare_pairs(selected, corpus_root=args.corpus_root)
    # Never produce a half-complete first output if the second would fail.
    for destination in (args.pairs, args.report):
        p = destination.expanduser().absolute()
        if p.is_relative_to(_ROOT) or p.is_symlink() or p.exists() or not p.parent.is_dir():
            raise ValueError("CocoChorales output paths must be new, outside git")
    if args.pairs.expanduser().absolute() == args.report.expanduser().absolute():
        raise ValueError("CocoChorales pairs and report outputs must differ")
    try:
        _write_new(args.pairs, pairs)
        _write_new(args.report, report)
    except BaseException:
        args.pairs.unlink(missing_ok=True)
        raise
    print(json.dumps({"cases": report["case_count"], "inference": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
