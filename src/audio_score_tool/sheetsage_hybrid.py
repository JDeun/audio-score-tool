from __future__ import annotations

import bisect
import copy
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from music21 import chord, converter, harmony, key, meter, note, pitch, stream

from .musicxml_metadata_projection import project_musicxml_annotations
from .runner import CommandError, run_command
from .runtime_settings import runtime_settings
from .score_timing import score_time_clocks


class SheetSageError(ValueError):
    """Invalid or unavailable SheetSage2 analysis."""


_MAX_EVENTS_JSON_BYTES = 16 * 1024 * 1024
_MAX_EVENTS_PER_TYPE = 100_000


def run_sheetsage_adapter(audio: Path, output: Path, *, command: str | None = None) -> dict[str, Any]:
    """Execute opt-in, noncommercial SheetSage2 inference with a verified runtime.

    The command accepts <audio> <output-json>. In packaged mode the shared
    runner requires a registered, checksum-validated managed executable. Never
    use arbitrary subprocess/PATH fallbacks, accept stale output as new evidence,
    or overwrite a previous valid analysis on an inference failure.
    """
    if runtime_settings().usage_mode == "commercial":
        raise SheetSageError(
            "SheetSage2 public checkpoints are CC BY-NC and unavailable in commercial mode."
        )
    executable = command or os.environ.get("AST_SHEETSAGE2_ADAPTER")
    if not executable or not executable.strip():
        raise SheetSageError("Set AST_SHEETSAGE2_ADAPTER to a reviewed SheetSage2 executable")
    if not audio.is_file():
        raise SheetSageError("SheetSage2 input audio is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Separate staging ensures the existing event JSON is not accidentally
    # accepted when the adapter exits 0 without writing any new output.
    with tempfile.TemporaryDirectory(prefix=".sheetsage2-events-", dir=output.parent) as folder:
        staged = Path(folder) / "events.json"
        try:
            run_command(executable, [audio, staged], timeout_seconds=1800)
        except CommandError as exc:
            # An external model's stderr may contain credentials or private
            # paths. Do not propagate it into API/user-facing errors.
            raise SheetSageError(
                "SheetSage2 execution failed; check the reviewed managed runtime."
            ) from exc
        if not staged.is_file() or staged.is_symlink():
            raise SheetSageError("SheetSage2 adapter did not produce fresh events JSON")
        events = load_sheetsage_events(staged)
        if events.get("model") != "sheetsage2":
            raise SheetSageError("SheetSage2 adapter output has no confirmed model identity")
        staged.replace(output)
    return events


def load_sheetsage_events(path: Path) -> dict[str, Any]:
    """Read bounded normalized events; never infer absent musical events."""
    try:
        if path.stat().st_size > _MAX_EVENTS_JSON_BYTES:
            raise SheetSageError("SheetSage2 events JSON exceeds the allowed size")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, SheetSageError):
            raise
        raise SheetSageError("SheetSage2 events JSON is missing or invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SheetSageError("SheetSage2 adapter must produce schema_version=1 JSON")
    for name in ("chords", "beats", "downbeats", "keys"):
        events = payload.get(name, [])
        if not isinstance(events, list):
            raise SheetSageError(f"{name} must be an array")
        if len(events) > _MAX_EVENTS_PER_TYPE:
            raise SheetSageError(f"{name} contains too many events")
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
    "sus4(b7)": "7sus4",
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

_HARTE_BASS_INTERVALS = {
    "2": "M2", "3": "M3", "b3": "m3", "5": "P5", "7": "M7", "b7": "m7",
}
_SHEETSAGE_INVERSIONS = {
    "maj": {"2", "3", "5"}, "min": {"2", "b3", "5"},
    "maj7": {"3", "5", "7"}, "min7": {"b3", "5", "b7"},
    "7": {"3", "5", "b7"},
}


def _normalize_native_chord_figure(label: str) -> str:
    match = re.fullmatch(r"([A-G](?:##|bb|#|b)?)([^/]*)(?:/([A-G](?:##|bb|#|b)?))?", label)
    if not match:
        return label
    root, quality, bass = match.groups()
    if quality == "m(maj7)":
        quality = "mM7"
    return root.replace("b", "-") + quality + ("/" + bass.replace("b", "-") if bass else "")


def _parse_chord_symbol(label: str) -> harmony.ChordSymbol:
    """Convert recognized Harte triad/seventh labels into music21 notation."""
    if ":" not in label:
        return harmony.ChordSymbol(_normalize_native_chord_figure(label))
    root, suffix = label.split(":", 1)
    quality, slash, bass = suffix.partition("/")
    if not re.fullmatch(r"[A-G](?:#|b)?", root) or quality not in _HARTE_QUALITY_TO_MUSIC21:
        raise SheetSageError(f"unsupported chord label: {label}")
    if slash and bass not in _SHEETSAGE_INVERSIONS.get(quality, set()):
        raise SheetSageError(f"unsupported chord label: {label}")
    # music21 uses '-' rather than 'b' for a flat root (e.g. Bb -> B-).
    figure = root.replace("b", "-") + _HARTE_QUALITY_TO_MUSIC21[quality]
    if slash:
        bass_pitch = pitch.Pitch(root.replace("b", "-")).transpose(_HARTE_BASS_INTERVALS[bass])
        figure += "/" + bass_pitch.name
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

    Annotations follow the unchanged AMT score's tempo map. A detected beat
    grid cannot replace that clock without also reconstructing the note grid.
    """
    if not math.isfinite(bpm) or bpm <= 0:
        raise SheetSageError("bpm must be positive")
    events = load_sheetsage_events(sheetsage_json)
    score = converter.parse(str(amt_musicxml))
    _, to_quarters = score_time_clocks(score, fallback_bpm=bpm)
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
    # Inference MusicXML may contain nonstandard multi-voice measures. Do not
    # re-export the performed score to generate annotation XML: music21 can
    # rebar its notes or create additional measures. Build an annotation-only
    # overlay using original measure numbering and absolute quarter offsets.
    source_part = parts[0]
    source_measures = list(source_part.getElementsByClass(stream.Measure))
    if not source_measures:
        raise SheetSageError("AMT MusicXML has no numbered measures")
    annotation_score = stream.Score()
    target = stream.Part()
    for original_measure in source_measures:
        measure = stream.Measure(number=original_measure.number)
        if original_measure.timeSignature is not None:
            measure.insert(0, copy.deepcopy(original_measure.timeSignature))
        # Use a short placeholder rest instead of the original performed
        # measure length: a sustained polyphonic note can extend beyond a
        # barline, which causes music21 to rebar an overlay into measure N+1.
        # Placeholder rests are never projected to the canonical MusicXML.
        length = float(original_measure.duration.quarterLength)
        if not math.isfinite(length) or length <= 0:
            raise SheetSageError("AMT MusicXML contains an invalid measure duration")
        measure.insert(0, note.Rest(quarterLength=min(1.0, length)))
        target.insert(float(original_measure.getOffsetBySite(source_part)), measure)
    annotation_score.append(target)
    added = {"chords": 0, "keys": 0, "meter": 0}
    for event in events.get("chords", []):
        label = event["label"].strip()
        if label in {"", "N", "N.C.", "no_chord"}:
            continue
        try:
            symbol = _parse_chord_symbol(label)
        except Exception as exc:
            raise SheetSageError(f"unsupported chord label: {label}") from exc
        _insert_score_element(
            target, to_quarters(event["time_seconds"]), symbol
        )
        added["chords"] += 1
    for event in events.get("keys", []):
        try:
            signature = _parse_key_label(event["label"])
        except Exception as exc:
            raise SheetSageError(f"unsupported key label: {event['label']}") from exc
        _insert_score_element(
            target, to_quarters(event["time_seconds"]), signature
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
        annotation_score.write("musicxml", fp=str(staged), makeNotation=False)
        project_musicxml_annotations(
            amt_musicxml, staged, lossless,
            include_key=bool(events.get("keys")),
            include_meter=events.get("meter") is not None,
        )
        lossless.replace(destination)
    if not destination.is_file():
        raise SheetSageError("MusicXML merge did not produce an output")
    return {"schema_version": 1, "added": added, "source": str(amt_musicxml),
            "sheetsage": str(sheetsage_json), "fallback_bpm": bpm,
            "alignment": "source_score_tempo_map", "beat_grid_applied": False,
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
    to_seconds, _ = score_time_clocks(score, fallback_bpm=fallback_bpm)
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
                "label": f"{element.tonic.name.replace('-', 'b')}:{element.mode}",
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
