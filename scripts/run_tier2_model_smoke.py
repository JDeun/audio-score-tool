"""Run an actual MT3-Infer model and verify generated MIDI/MusicXML artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from music21 import converter

from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import MT3InferEngine


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
    if not artifacts.midi_path.is_file() or not artifacts.musicxml_path.is_file():
        raise RuntimeError("Missing model outputs")
    score = converter.parse(str(artifacts.musicxml_path))
    result = {
        "model": args.model,
        "midi": str(artifacts.midi_path),
        "musicxml": str(artifacts.musicxml_path),
        "parts": len(score.parts),
        "notes": len(list(score.recurse().notes)),
    }
    (args.output / "smoke-result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
