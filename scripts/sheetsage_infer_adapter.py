"""Standalone SheetSage inference executable for AST_SHEETSAGE2_ADAPTER.

Install sheetsage-infer in an isolated research environment. Checkpoint weights
are noncommercial; this program refuses commercial usage.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from music21 import chord as m21chord
from music21 import harmony


def transcribe(audio: Path, *, use_jukebox: bool = False) -> dict:
    if os.environ.get("AST_USAGE_MODE", "research").lower() == "commercial":
        raise RuntimeError("SheetSage weights are CC BY-NC-SA; commercial use is prohibited")
    try:
        from sheetsage.infer import sheetsage
    except ImportError as exc:
        raise RuntimeError("Install sheetsage-infer in the isolated adapter environment") from exc
    lead, segment_beats, beat_times = sheetsage(
        audio, use_jukebox=use_jukebox, device="auto",
    )
    if len(segment_beats) != len(beat_times) or len(beat_times) < 2:
        raise RuntimeError("SheetSage returned insufficient beat anchors")
    anchors = [(float(beat), float(time)) for beat, time in zip(segment_beats, beat_times)]
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in anchors):
        raise RuntimeError("SheetSage returned nonfinite beat anchors")
    anchors.sort()
    if any(b[0] <= a[0] or b[1] <= a[1] for a, b in zip(anchors, anchors[1:])):
        raise RuntimeError("SheetSage returned nonmonotonic beat anchors")
    meter_changes, _, _, chords, _, _ = lead
    meter_value = meter_changes[0][1]
    tertiary_per_beat = math.prod(meter_value[1:])

    def seconds(tertiary: float) -> float:
        beat = tertiary / tertiary_per_beat
        for i in range(len(anchors) - 1):
            if beat <= anchors[i + 1][0]:
                break
        else:
            i = len(anchors) - 2
        (b0, t0), (b1, t1) = anchors[i], anchors[i + 1]
        return t0 + (beat - b0) * (t1 - t0) / (b1 - b0)

    events = []
    for position, symbol in chords:
        if symbol[0] is None:
            continue
        pitches = symbol.as_midi_pitches()
        if not pitches:
            continue
        try:
            figure = harmony.chordSymbolFigureFromChord(m21chord.Chord(pitches))
        except Exception:
            continue
        events.append({"time_seconds": max(0.0, seconds(position)), "label": figure})
    events.sort(key=lambda event: event["time_seconds"])
    dedup = []
    for event in events:
        if dedup and event["time_seconds"] <= dedup[-1]["time_seconds"]:
            continue
        dedup.append(event)
    beats = [{"time_seconds": t} for _, t in anchors if t >= 0]
    meter = f"{meter_value[0]}/{tertiary_per_beat}"
    return {"schema_version": 1, "chords": dedup, "beats": beats, "meter": meter,
            "provider": "sheetsage-infer", "use_jukebox": use_jukebox}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--jukebox", action="store_true")
    args = parser.parse_args()
    result = transcribe(args.audio, use_jukebox=args.jukebox)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
