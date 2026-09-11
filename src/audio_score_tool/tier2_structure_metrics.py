from __future__ import annotations

from pathlib import Path
from typing import Any

from music21 import converter, harmony, meter, note, stream


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


def _lyric_count(score) -> int:
    count = 0
    for item in score.recurse().notes:
        if isinstance(item, note.Note):
            count += sum(1 for lyric in item.lyrics if (lyric.text or "").strip())
    return count


def _chord_symbols(score) -> list[str]:
    return [str(item.figure) for item in score.recurse().getElementsByClass(harmony.ChordSymbol)]


def _sequence_accuracy(predicted: list[str], reference: list[str]) -> float | None:
    if not reference:
        return None
    matches = sum(1 for left, right in zip(predicted, reference) if left == right)
    return round(matches / len(reference), 6)


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

    if expected_structure.get("has_lyrics") is True:
        predicted_lyrics = _lyric_count(predicted)
        if reference is not None:
            reference_lyrics = _lyric_count(reference)
            metrics["lyrics_alignment_coverage"] = (
                round(min(predicted_lyrics / reference_lyrics, 1.0), 6) if reference_lyrics else 1.0
            )
        else:
            metrics["lyrics_alignment_coverage"] = 1.0 if predicted_lyrics else 0.0

    if expected_structure.get("has_chords") is True:
        predicted_chords = _chord_symbols(predicted)
        if reference is not None:
            accuracy = _sequence_accuracy(predicted_chords, _chord_symbols(reference))
            metrics["chord_accuracy"] = accuracy if accuracy is not None else 1.0
        else:
            metrics["chord_accuracy"] = 1.0 if predicted_chords else 0.0

    is_satb = "satb" in {tag.lower() for tag in tags} or category.strip().lower() in {"choir", "satb"}
    if is_satb:
        metrics["satb_part_count_correct"] = len(predicted.parts) == 4
        metrics["satb_voice_order_correct"] = _satb_order_correct(predicted)

    return metrics
