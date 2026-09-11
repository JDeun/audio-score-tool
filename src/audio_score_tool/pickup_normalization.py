from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from music21 import converter, meter, note, stream


@dataclass(slots=True)
class PickupNormalizationResult:
    applied: bool
    pickup_quarters: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "pickup_quarters": round(self.pickup_quarters, 3),
            "reason": self.reason,
        }


def _effective_bar_quarters(measure: stream.Measure, fallback_numerator: int, fallback_denominator: int) -> float:
    signature = measure.timeSignature
    if signature is None:
        signature = meter.TimeSignature(f"{fallback_numerator}/{fallback_denominator}")
    return float(signature.barDuration.quarterLength)


def _first_sounding_offset(measure: stream.Measure) -> float | None:
    offsets = [float(item.offset) for item in measure.notes if isinstance(item, (note.Note,)) or getattr(item, "pitches", None)]
    return min(offsets) if offsets else None


def _remove_leading_rests(measure: stream.Measure, boundary: float) -> None:
    for element in list(measure.notesAndRests):
        if not isinstance(element, note.Rest):
            continue
        end = float(element.offset + element.duration.quarterLength)
        if end <= boundary + 0.05:
            measure.remove(element)


def _shift_measure_content(measure: stream.Measure, amount: float) -> None:
    for element in list(measure):
        if isinstance(element, (meter.TimeSignature,)):
            continue
        if hasattr(element, "offset") and float(element.offset) >= amount - 0.05:
            element.offset = max(0.0, float(element.offset) - amount)


def normalize_pickup_measure(
    musicxml_path: Path,
    output_path: Path,
    *,
    pickup_quarters: float,
    numerator: int,
    denominator: int,
    confidence: float,
) -> PickupNormalizationResult:
    if pickup_quarters <= 0.0:
        return PickupNormalizationResult(False, 0.0, "no-pickup")
    if confidence < 0.45:
        return PickupNormalizationResult(False, pickup_quarters, "confidence-too-low")

    try:
        parsed = converter.parse(str(musicxml_path))
    except Exception as exc:
        return PickupNormalizationResult(False, pickup_quarters, f"parse-failed:{exc}")
    if not isinstance(parsed, stream.Score) or not parsed.parts:
        return PickupNormalizationResult(False, pickup_quarters, "not-a-score")

    plans: list[tuple[stream.Measure, float]] = []
    for part in parsed.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        if not measures:
            return PickupNormalizationResult(False, pickup_quarters, "part-has-no-measures")
        first = measures[0]
        bar_quarters = _effective_bar_quarters(first, numerator, denominator)
        if pickup_quarters >= bar_quarters - 0.05:
            return PickupNormalizationResult(False, pickup_quarters, "pickup-is-full-bar")
        expected_leading = bar_quarters - pickup_quarters
        sounding = _first_sounding_offset(first)
        if sounding is None:
            plans.append((first, expected_leading))
            continue
        if sounding + 0.15 < expected_leading:
            # The generated score does not contain the expected pre-pickup padding.
            # Do not rewrite its temporal content; keep only the analysis metadata.
            return PickupNormalizationResult(False, pickup_quarters, "score-timing-does-not-match-pickup")
        plans.append((first, expected_leading))

    transformed = copy.deepcopy(parsed)
    for part, (_, leading) in zip(transformed.parts, plans, strict=True):
        first = list(part.getElementsByClass(stream.Measure))[0]
        _remove_leading_rests(first, leading)
        _shift_measure_content(first, leading)
        try:
            first.paddingLeft = max(0.0, _effective_bar_quarters(first, numerator, denominator) - pickup_quarters)
        except Exception:
            pass

    try:
        transformed.write("musicxml", fp=str(output_path))
    except Exception as exc:
        return PickupNormalizationResult(False, pickup_quarters, f"write-failed:{exc}")
    return PickupNormalizationResult(True, pickup_quarters, "normalized-leading-padding")
