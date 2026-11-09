from __future__ import annotations

import bisect
import math
import unicodedata
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from music21 import converter, harmony, meter, note, stream

ANNOTATION_METRIC_PROTOCOL = "musicxml-absolute-seconds-chord-root-bass-pc-lyrics-text-50ms-v2"


def _first_measure(score) -> stream.Measure | None:
    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        if measures:
            return measures[0]
    return None


def _pickup_quarter_length(score) -> float | None:
    measure = _first_measure(score)
    if measure is None:
        return None

    signatures = list(measure.recurse().getElementsByClass(meter.TimeSignature))
    if not signatures:
        signatures = list(score.recurse().getElementsByClass(meter.TimeSignature))
    if not signatures:
        return None

    try:
        nominal_bar_length = float(signatures[0].barDuration.quarterLength)
    except (AttributeError, TypeError, ValueError):
        return None

    # music21 represents a true anacrusis with left padding when that metadata
    # survives the MusicXML round-trip. Prefer that explicit representation.
    try:
        padding_left = float(measure.paddingLeft)
    except (AttributeError, TypeError, ValueError):
        padding_left = 0.0
    if padding_left > 0.0:
        return min(padding_left, nominal_bar_length)

    # Some MusicXML producers preserve an incomplete first measure directly.
    # Use its actual duration when it remains shorter than the nominal bar.
    try:
        content_length = float(measure.duration.quarterLength)
    except (AttributeError, TypeError, ValueError):
        content_length = nominal_bar_length
    if content_length < nominal_bar_length:
        return max(0.0, nominal_bar_length - content_length)

    # Other producers/readers pad an incomplete first measure to the nominal
    # bar duration with implicit/hidden space. In that case, derive the occupied
    # musical span from notes/chords rather than the padded Measure.duration.
    # This keeps pickup measurement stable across MusicXML serialization.
    note_events = list(measure.recurse().notes)
    if not note_events:
        return 0.0

    try:
        occupied_start = min(float(event.getOffsetInHierarchy(measure)) for event in note_events)
        occupied_end = max(
            float(event.getOffsetInHierarchy(measure)) + float(event.duration.quarterLength)
            for event in note_events
        )
    except (AttributeError, TypeError, ValueError):
        return 0.0

    occupied_span = max(0.0, occupied_end - occupied_start)
    if occupied_span >= nominal_bar_length:
        return 0.0
    return max(0.0, nominal_bar_length - occupied_span)


def _first_meter(score) -> str | None:
    signatures = list(score.recurse().getElementsByClass(meter.TimeSignature))
    return signatures[0].ratioString if signatures else None


def _annotation_timeline(score):
    """Read annotation times on the score's own tempo map, without shifting to truth."""
    chords = {}
    lyrics = []
    end = 0.0
    for entry in score.flatten().secondsMap:
        item = entry["element"]
        start, finish = float(entry["offsetSeconds"]), float(entry["endTimeSeconds"])
        if not all(math.isfinite(value) and value >= 0 for value in (start, finish)):
            raise ValueError("Score annotation timeline must be finite and nonnegative")
        end = max(end, finish)
        if isinstance(item, harmony.ChordSymbol):
            label = None if isinstance(item, harmony.NoChord) else (
                item.root().pitchClass, item.bass().pitchClass,
                tuple(sorted({pitch.pitchClass for pitch in item.pitches})),
            )
            if start in chords and chords[start] != label:
                raise ValueError("Score has conflicting chord annotations at the same time")
            chords[start] = label
        elif isinstance(item, note.Note):
            for lyric in item.lyrics:
                text = unicodedata.normalize("NFC", (lyric.text or "").strip())
                if text:
                    lyrics.append((start, str(lyric.number), text))
    return sorted(chords.items()), sorted(lyrics), end


def _timed_chord_accuracy(predicted, reference, predicted_end, reference_end) -> float | None:
    """Exact root/bass/pitch-class duration recall over the annotated reference span."""
    if not reference or reference_end <= reference[0][0]:
        return None
    starts = [event[0] for event in predicted]
    boundaries = sorted({
        reference[0][0], reference_end,
        *(at for at, _ in reference if reference[0][0] < at < reference_end),
        *(at for at, _ in predicted if reference[0][0] < at < reference_end),
        *(at for at in (predicted_end,) if reference[0][0] < at < reference_end),
    })
    reference_starts = [event[0] for event in reference]
    matched = 0.0
    for start, finish in zip(boundaries, boundaries[1:]):
        expected = reference[bisect.bisect_right(reference_starts, start) - 1][1]
        index = bisect.bisect_right(starts, start) - 1
        if index >= 0 and start < predicted_end and predicted[index][1] == expected:
            matched += finish - start
    return round(matched / (reference_end - reference[0][0]), 6)


def _timed_lyric_coverage(predicted, reference) -> float | None:
    """Match text/verse and onset within 50 ms, consuming each prediction once."""
    if not reference:
        return None
    candidates = defaultdict(deque)
    for at, verse, text in sorted(predicted):
        candidates[(verse, text)].append(at)
    matched = 0
    for onset, verse, text in sorted(reference):
        times = candidates[(verse, text)]
        while times and times[0] < onset - 0.05 - 1e-9:
            times.popleft()
        if times and times[0] <= onset + 0.05 + 1e-9:
            times.popleft()
            matched += 1
    return round(matched / len(reference), 6)


def _satb_order_correct(score) -> bool:
    expected = ("soprano", "alto", "tenor", "bass")
    parts = list(score.parts)
    if len(parts) != 4:
        return False
    names = [str(part.partName or part.partAbbreviation or "").strip().lower() for part in parts]
    return all(name.startswith(prefix) for name, prefix in zip(names, expected, strict=True))


def evaluate_musicxml_structure(
    prediction_path: Path,
    *,
    reference_path: Path | None,
    expected_structure: dict[str, Any],
    tags: tuple[str, ...],
    category: str,
) -> dict[str, Any]:
    if not prediction_path.is_file():
        return {}
    predicted = converter.parse(str(prediction_path))
    reference = converter.parse(str(reference_path)) if reference_path and reference_path.is_file() else None
    metrics: dict[str, Any] = {}

    expected_meter = expected_structure.get("meter")
    if isinstance(expected_meter, str) and expected_meter.strip():
        metrics["meter_correct"] = _first_meter(predicted) == expected_meter.strip()

    expected_pickup = expected_structure.get("pickup_quarter_length")
    pickup = _pickup_quarter_length(predicted)
    if isinstance(expected_pickup, (int, float)) and not isinstance(expected_pickup, bool) and pickup is not None:
        metrics["pickup_mae_quarter_length"] = round(abs(pickup - float(expected_pickup)), 6)

    expected_parts = expected_structure.get("part_count")
    if isinstance(expected_parts, int) and not isinstance(expected_parts, bool) and expected_parts >= 0:
        metrics["part_count_correct"] = len(predicted.parts) == expected_parts

    if expected_structure.get("has_lyrics") is True or expected_structure.get("has_chords") is True:
        predicted_chords, predicted_lyrics, predicted_end = _annotation_timeline(predicted)
        if reference is not None:
            reference_chords, reference_lyrics, reference_end = _annotation_timeline(reference)

    if expected_structure.get("has_lyrics") is True:
        if reference is not None:
            coverage = _timed_lyric_coverage(predicted_lyrics, reference_lyrics)
            if coverage is not None:
                metrics["lyrics_alignment_coverage"] = coverage
        else:
            metrics["has_lyrics"] = bool(predicted_lyrics)

    if expected_structure.get("has_chords") is True:
        if reference is not None:
            accuracy = _timed_chord_accuracy(
                predicted_chords, reference_chords, predicted_end, reference_end,
            )
            if accuracy is not None:
                metrics["chord_accuracy"] = accuracy
        else:
            metrics["has_chord_symbols"] = bool(predicted_chords)

    is_satb = "satb" in {tag.lower() for tag in tags} or category.strip().lower() in {"choir", "satb"}
    if is_satb:
        metrics["satb_part_count_correct"] = len(predicted.parts) == 4
        metrics["satb_voice_order_correct"] = _satb_order_correct(predicted)

    return metrics
