from __future__ import annotations

import bisect
import json
import math
import os
import re
import shlex
import tempfile
import subprocess
from pathlib import Path
from typing import Any

from music21 import chord, converter, harmony, key, meter, note, stream, tempo

from .musicxml_metadata_projection import project_musicxml_annotations


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
    argv = shlex.split(executable)
    if not argv:
        raise SheetSageError("empty SheetSage2 adapter command")
    subprocess.run([*argv, str(audio), str(output)], check=True)
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
            if isinstance(at, bool) or not isinstance(at, (int, float)):
                raise SheetSageError(f"invalid {name} time_seconds")
            if not math.isfinite(at):
                raise SheetSageError(f"{name} time_seconds must be finite")
            if not 0 <= at < 1e8:
                raise SheetSageError(f"invalid {name} time_seconds")
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


# SheetSage2 emits Harte-style labels (e.g. C:aug); music21 expects C+.
# Only unambiguous, documented chord qualities are translated; unfamiliar
# alterations remain errors rather than silently changing harmonic content.
_HARTE_QUALITY_TO_MUSIC21 = {
    "maj": "",
    "min": "m",
    "aug": "+",
    "dim": "dim",
    "5": "power",
    "sus2": "sus2",
    "sus4": "sus4",
    "6": "6",
    "maj6": "6",
    "min6": "m6",
    "7": "7",
    "majmin7": "7",
    "min7": "m7",
    "minmin7": "m7",
    "maj7": "M7",
    "dim7": "dim7",
    "hdim7": "m7b5",
    "minmaj7": "mM7",
    "aug7": "7+",
    "9": "9",
    "maj9": "Maj9",
    "min9": "m9",
    "11": "11",
    "maj11": "Maj11",
    "min11": "m11",
    "13": "13",
    "maj13": "Maj13",
    "min13": "m13",
}


def _parse_chord_symbol(label: str) -> harmony.ChordSymbol:
    """Convert recognized Harte triad/seventh labels into music21 notation."""
    if ":" not in label:
        return harmony.ChordSymbol(label)
    root, quality = label.split(":", 1)
    if not re.fullmatch(r"[A-G](?:#|b)?", root) or quality not in _HARTE_QUALITY_TO_MUSIC21:
        raise SheetSageError(f"unsupported chord label: {label}")
    # music21 uses '-' rather than 'b' for a flat root (e.g. Bb -> B-).
    figure = root.replace("b", "-") + _HARTE_QUALITY_TO_MUSIC21[quality]
    return harmony.ChordSymbol(figure)


def _parse_key_label(label: str) -> key.Key:
    """Normalize the model's Harte `tonic:mode` notation without guessing."""
    normalized = label.strip()
    if ":" not in normalized:
        return key.Key(normalized)
    tonic, mode = normalized.split(":", 1)
    if not re.fullmatch(r"[A-G](?:#|b)?", tonic):
        raise SheetSageError(f"unsupported key label: {label}")
    if mode not in {"major", "minor", "maj", "min"}:
        raise SheetSageError(f"unsupported key label: {label}")
    music21_tonic = tonic.replace("b", "-")
    music21_mode = "major" if mode in {"major", "maj"} else "minor"
    return key.Key(music21_tonic, music21_mode)


def _insert_score_element(part: stream.Part, offset: float, element: Any) -> None:
    """Insert into the containing Measure so MusicXML exports the new metadata.

    MusicXML import creates measured parts. Inserting harmony directly into a
    Part instead of a Measure can leave the symbol out of the serialized XML,
    despite its presence in the in-memory stream.
    """
    measures = list(part.getElementsByClass(stream.Measure))
    if not measures:
        part.insert(offset, element)
        return
    starts = [float(measure.getOffsetBySite(part)) for measure in measures]
    index = max(0, bisect.bisect_right(starts, offset) - 1)
    measure = measures[index]
    measure.insert(max(0.0, offset - starts[index]), element)


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
    # ChordSymbol is exposed by music21's .notes iterator, but it is not
    # transcribed performance. A chord-only/rest-only source must not be
    # promoted into a successful hybrid transcription.
    if not any(
        isinstance(event, (note.Note, note.Unpitched))
        or (isinstance(event, chord.Chord) and not isinstance(event, harmony.ChordSymbol))
        for event in score.recurse().notes
    ):
        raise SheetSageError("AMT MusicXML has no performed note events")
    target = parts[0]
    added = {"chords": 0, "keys": 0, "meter": 0}
    beats = events.get("beats", [])
    for event in events.get("chords", []):
        label = event["label"].strip()
        if label in {"", "N", "N.C.", "no_chord"}:
            continue
        try:
            symbol = _parse_chord_symbol(label)
        except Exception as exc:
            raise SheetSageError(f"unsupported chord label: {label}") from exc
        _insert_score_element(
            target, _quarter_offset(event["time_seconds"], bpm=bpm, beats=beats), symbol
        )
        added["chords"] += 1
    for event in events.get("keys", []):
        try:
            signature = _parse_key_label(event["label"])
        except Exception as exc:
            raise SheetSageError(f"unsupported key label: {event['label']}") from exc
        _insert_score_element(
            target, _quarter_offset(event["time_seconds"], bpm=bpm, beats=beats), signature
        )
        added["keys"] += 1
    signature = events.get("meter")
    if signature is not None:
        if not isinstance(signature, str):
            raise SheetSageError("meter must be a string")
        _insert_score_element(target, 0, meter.TimeSignature(signature))
        added["meter"] += 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    # music21 renders chord/key/meter XML, but is not allowed to rewrite the
    # source AMT polyphonic performance. Project metadata onto original notes.
    with tempfile.TemporaryDirectory(prefix=".sheetsage-stage-", dir=destination.parent) as stage_dir:
        staged = Path(stage_dir) / "staged.musicxml"
        lossless = Path(stage_dir) / "lossless.musicxml"
        score.write("musicxml", fp=str(staged))
        project_musicxml_annotations(amt_musicxml, staged, lossless)
        lossless.replace(destination)
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
