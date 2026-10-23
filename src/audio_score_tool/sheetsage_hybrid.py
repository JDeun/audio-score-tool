from __future__ import annotations

import bisect
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

from music21 import converter, harmony, key, meter, tempo


class SheetSageError(ValueError):
    """Invalid or unavailable SheetSage2 analysis."""


def run_sheetsage_adapter(audio: Path, output: Path, *, command: str | None = None) -> dict[str, Any]:
    """Execute a pinned, separately installed SheetSage2 CLI adapter.

    The command must accept: <audio> <output-json>. The adapter is responsible for
    producing schema_version=1, and for loading the licensed SheetSage2 checkpoint.
    No arbitrary Python model code is imported in the AudioScoreTool process.
    """
    executable = command or os.environ.get("AST_SHEETSAGE2_ADAPTER")
    if not executable:
        raise SheetSageError("Set AST_SHEETSAGE2_ADAPTER to a reviewed SheetSage2 executable")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([executable, str(audio), str(output)], check=True)
    return load_sheetsage_events(output)


def load_sheetsage_events(path: Path) -> dict[str, Any]:
    """Read normalized SheetSage2 output; never infer absent musical events."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SheetSageError("SheetSage2 adapter must produce schema_version=1 JSON")
    for name in ("chords", "beats", "downbeats", "keys"):
        events = payload.get(name, [])
        if not isinstance(events, list):
            raise SheetSageError(f"{name} must be an array")
        last = -1.0
        for event in events:
            if not isinstance(event, dict):
                raise SheetSageError(f"invalid {name} event")
            at = event.get("time_seconds")
            if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 <= at < 1e8:
                raise SheetSageError(f"invalid {name} time_seconds")
            if not math.isfinite(at):
                raise SheetSageError(f'{name} time_seconds must be finite')
            if at <= last:
                raise SheetSageError(f"{name} events must be chronological")
            last = float(at)
            if name in ("chords", "keys") and not isinstance(event.get("label"), str):
                raise SheetSageError(f"{name} event requires label")
    return payload


def _quarter_offset(seconds: float, *, bpm: float, beats: list[dict[str, Any]] | None = None) -> float:
    if not beats or len(beats) < 2:
        return seconds * bpm / 60.0
    anchors = [float(beat['time_seconds']) for beat in beats]
    index = min(max(bisect.bisect_right(anchors, seconds) - 1, 0), len(anchors) - 2)
    return index + (seconds - anchors[index]) / (anchors[index + 1] - anchors[index])


def merge_sheetsage_musicxml(
    amt_musicxml: Path,
    sheetsage_json: Path,
    destination: Path,
    *,
    bpm: float = 120.0,
) -> dict[str, Any]:
    """Preserve AMT note parts; add SheetSage2 harmony/key/meter metadata.

    Mapping from seconds to score position assumes constant tempo unless an
    explicit bpm is supplied. Do not claim this is beat-aligned on rubato audio.
    """
    if not math.isfinite(bpm) or bpm <= 0:
        raise SheetSageError("bpm must be positive")
    events = load_sheetsage_events(sheetsage_json)
    score = converter.parse(str(amt_musicxml))
    parts = list(score.parts)
    if not parts:
        raise SheetSageError("AMT MusicXML has no parts")
    target = parts[0]
    added = {"chords": 0, "keys": 0, "meter": 0}
    beats = events.get("beats", [])
    for event in events.get("chords", []):
        label = event["label"].strip()
        if label in {"", "N", "N.C.", "no_chord"}:
            continue
        try:
            symbol = harmony.ChordSymbol(label)
        except Exception as exc:
            raise SheetSageError(f"unsupported chord label: {label}") from exc
        target.insert(_quarter_offset(event["time_seconds"], bpm=bpm, beats=beats), symbol)
        added["chords"] += 1
    for event in events.get("keys", []):
        try:
            signature = key.Key(event["label"])
        except Exception as exc:
            raise SheetSageError(f"unsupported key label: {event['label']}") from exc
        target.insert(_quarter_offset(event["time_seconds"], bpm=bpm, beats=beats), signature)
        added["keys"] += 1
    signature = events.get("meter")
    if signature is not None:
        if not isinstance(signature, str):
            raise SheetSageError("meter must be a string")
        target.insert(0, meter.TimeSignature(signature))
        added["meter"] += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(destination))
    if not destination.is_file():
        raise SheetSageError("MusicXML merge did not produce an output")
    return {"schema_version": 1, "added": added, "source": str(amt_musicxml),
            "sheetsage": str(sheetsage_json), "tempo_assumption_bpm": bpm,
            "alignment": "beat_interpolated" if len(beats) >= 2 else "constant_bpm"
}


def normalize_lead_sheet_musicxml(
    lead_sheet: Path, destination: Path, *, fallback_bpm: float = 120.0,
) -> dict[str, Any]:
    """Convert a model-exported lead sheet to the normalized event protocol.

    This is an output adapter, not a model inference implementation. Offsets
    follow music21 quarter lengths, and tempo changes are integrated piecewise.
    """
    if not math.isfinite(fallback_bpm) or fallback_bpm <= 0:
        raise SheetSageError("fallback_bpm must be positive")
    score = converter.parse(str(lead_sheet))
    marks = [(0.0, fallback_bpm)]
    for mark in score.recurse().getElementsByClass(tempo.MetronomeMark):
        value = mark.getQuarterBPM()
        if value is not None and math.isfinite(value) and value > 0:
            marks.append((float(mark.getOffsetInHierarchy(score)), float(value)))
    marks.sort(key=lambda pair: pair[0])
    def to_seconds(offset: float) -> float:
        elapsed = 0.0
        for index, (start, rate) in enumerate(marks):
            if start >= offset:
                break
            end = min(offset, marks[index + 1][0] if index + 1 < len(marks) else offset)
            elapsed += max(0.0, end - start) * 60.0 / rate
        return elapsed
    chords = []
    keys = []
    for element in score.recurse():
        if isinstance(element, harmony.ChordSymbol):
            chords.append({
                "time_seconds": to_seconds(float(element.getOffsetInHierarchy(score))),
                "label": element.figure,
            })
        elif isinstance(element, key.Key):
            keys.append({
                "time_seconds": to_seconds(float(element.getOffsetInHierarchy(score))),
                "label": element.tonic.name,
            })
    chords.sort(key=lambda event: event["time_seconds"])
    keys.sort(key=lambda event: event["time_seconds"])
    time_signatures = list(score.recurse().getElementsByClass(meter.TimeSignature))
    result: dict[str, Any] = {"schema_version": 1, "chords": chords, "keys": keys}
    if time_signatures:
        result["meter"] = time_signatures[0].ratioString
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return load_sheetsage_events(destination)
