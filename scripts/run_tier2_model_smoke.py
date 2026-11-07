"""Run real MT3-Infer smoke; a parseable but empty score is a failed inference."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from music21 import chord, converter, harmony, note

from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import MT3InferEngine


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def verify_model_outputs(midi_path: Path, musicxml_path: Path) -> dict[str, int]:
    """Reject absent, corrupt, or musically empty outputs independently.

    A parseable MusicXML file can still contain only rests. A valid MIDI may
    similarly contain no note-on events. Neither is an inference smoke pass.
    The two note counts need not agree exactly because conversion can group
    simultaneous notes into chords or adjust instrument mapping.
    """
    summary: dict[str, int] = {}
    for label, path in (("MIDI", midi_path), ("MusicXML", musicxml_path)):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"{label} model output is missing or empty: {path}")
        # music21 leaves an open file handle on some malformed MIDI inputs.
        # Reject a missing Standard MIDI header before delegating to the parser.
        if label == "MIDI":
            with path.open("rb") as handle:
                if handle.read(4) != b"MThd":
                    raise RuntimeError(f"MIDI model output cannot be parsed: {path}")
        try:
            score = converter.parse(str(path))
            count = sum(
                1
                for event in score.recurse().notes
                if isinstance(event, (note.Note, note.Unpitched))
                or (isinstance(event, chord.Chord) and not isinstance(event, harmony.ChordSymbol))
            )
        except Exception as exc:
            raise RuntimeError(f"{label} model output cannot be parsed: {path}") from exc
        if count == 0:
            raise RuntimeError(f"{label} model output contains no notes: {path}")
        summary["midi_notes" if label == "MIDI" else "notes"] = count
        if label == "MusicXML":
            summary["parts"] = len(score.parts)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", choices=("yourmt3", "mr_mt3"), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = MT3InferEngine(Settings(mt3_model=args.model))
    if not engine.ready():
        raise RuntimeError(f"MT3-Infer engine unavailable: {engine.describe()}")
    artifacts = engine.transcribe(args.audio, args.output, device="cpu")
    summary = verify_model_outputs(artifacts.midi_path, artifacts.musicxml_path)
    result = {
        "model": args.model,
        "midi": str(artifacts.midi_path),
        "musicxml": str(artifacts.musicxml_path),
        "parts": summary["parts"],
        "notes": summary["notes"],
        "midi_notes": summary["midi_notes"],
        "note_events_detected": True,
        "audio_sha256": _sha256(args.audio),
        "midi_sha256": _sha256(artifacts.midi_path),
        "musicxml_sha256": _sha256(artifacts.musicxml_path),
        "source_commit": os.environ.get("GITHUB_SHA") or None,
        "runtime": {
            "device": "cpu",
            "python": platform.python_version(),
            "mt3_infer": _package_version("mt3-infer"),
            "transformers": _package_version("transformers"),
            "torch": _package_version("torch"),
        },
        # Package revision is not evidence of the downloaded model weights.
        # Never silently claim the remote checkpoint was SHA-256 verified.
        "checkpoint": {"revision": None, "sha256": None, "verified": False},
    }
    (args.output / "smoke-result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
