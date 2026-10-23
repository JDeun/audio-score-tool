from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from music21 import converter, harmony, key, meter


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
            if at < last:
                raise SheetSageError(f"{name} events must be chronological")
            last = float(at)
            if name in ("chords", "keys") and not isinstance(event.get("label"), str):
                raise SheetSageError(f"{name} event requires label")
    return payload


def _quarter_offset(seconds: float, *, bpm: float) -> float:
    return seconds * bpm / 60.0


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
    if bpm <= 0:
        raise SheetSageError("bpm must be positive")
    events = load_sheetsage_events(sheetsage_json)
    score = converter.parse(str(amt_musicxml))
    parts = list(score.parts)
    if not parts:
        raise SheetSageError("AMT MusicXML has no parts")
    target = parts[0]
    added = {"chords": 0, "keys": 0, "meter": 0}
    for event in events.get("chords", []):
        label = event["label"].strip()
        if label in {"", "N", "N.C.", "no_chord"}:
            continue
        try:
            symbol = harmony.ChordSymbol(label)
        except Exception as exc:
            raise SheetSageError(f"unsupported chord label: {label}") from exc
        target.insert(_quarter_offset(event["time_seconds"], bpm=bpm), symbol)
        added["chords"] += 1
    for event in events.get("keys", []):
        try:
            signature = key.Key(event["label"])
        except Exception as exc:
            raise SheetSageError(f"unsupported key label: {event['label']}") from exc
        target.insert(_quarter_offset(event["time_seconds"], bpm=bpm), signature)
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
            "sheetsage": str(sheetsage_json), "tempo_assumption_bpm": bpm}
