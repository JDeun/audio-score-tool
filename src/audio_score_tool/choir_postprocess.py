from __future__ import annotations

import copy
import statistics
from dataclasses import dataclass
from pathlib import Path

from music21 import chord, clef, converter, instrument, key, meter, note, stream


@dataclass(slots=True)
class ChoirResult:
    applied: bool
    output_path: Path
    confidence: float
    reason: str
    source_parts: int
    target_parts: int = 4

    def as_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "output_path": str(self.output_path),
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "source_parts": self.source_parts,
            "target_parts": self.target_parts,
        }


_VOICE_NAMES = ("Soprano", "Alto", "Tenor", "Bass")
_TARGET_MIDI = (72, 64, 55, 45)
_RANGE = (
    (60, 84),
    (53, 77),
    (45, 69),
    (36, 60),
)


def _pitched_parts(score: stream.Score) -> list[stream.Part]:
    result: list[stream.Part] = []
    for part in score.parts:
        notes = list(part.recurse().notes)
        if not notes:
            continue
        pitched = [item for item in notes if isinstance(item, (note.Note, chord.Chord))]
        if pitched:
            result.append(part)
    return result


def _part_median_pitch(part: stream.Part) -> float | None:
    values: list[int] = []
    for item in part.recurse().notes:
        if isinstance(item, note.Note):
            values.append(item.pitch.midi)
        elif isinstance(item, chord.Chord):
            values.extend(p.midi for p in item.pitches)
    return statistics.median(values) if values else None


def _rename_four_parts(score: stream.Score, output_path: Path) -> ChoirResult:
    parts = _pitched_parts(score)
    medians = [(_part_median_pitch(part), part) for part in parts]
    if len(parts) != 4 or any(value is None for value, _ in medians):
        return ChoirResult(False, output_path, 0.0, "not-four-pitched-parts", len(parts))
    ordered = [part for _, part in sorted(medians, key=lambda pair: float(pair[0] or 0), reverse=True)]
    spread = [float(value or 0) for value, _ in sorted(medians, reverse=True)]
    if min(spread) < 30 or max(spread) > 92:
        return ChoirResult(False, output_path, 0.0, "implausible-vocal-range", len(parts))
    for name, part in zip(_VOICE_NAMES, ordered, strict=True):
        part.partName = name
        part.partAbbreviation = name[0] if name != "Bass" else "B"
        for existing in list(part.recurse().getElementsByClass(instrument.Instrument)):
            try:
                existing.instrumentName = name
            except Exception:
                pass
    score.write("musicxml", fp=str(output_path))
    return ChoirResult(True, output_path, 0.86, "four-part-pitch-order", 4)


def _event_pitch_sets(part: stream.Part) -> list[tuple[float, float, list[int]]]:
    events: list[tuple[float, float, list[int]]] = []
    for item in part.recurse().notes:
        if isinstance(item, note.Note):
            pitches = [item.pitch.midi]
        elif isinstance(item, chord.Chord):
            pitches = sorted({pitch.midi for pitch in item.pitches}, reverse=True)
        else:
            continue
        offset = float(item.getOffsetInHierarchy(part))
        duration = max(0.125, float(item.duration.quarterLength))
        events.append((offset, duration, pitches))
    return events


def _single_part_choir_confidence(part: stream.Part) -> float:
    events = _event_pitch_sets(part)
    if len(events) < 12:
        return 0.0
    cardinalities = [len(pitches) for _, _, pitches in events]
    poly = [value for value in cardinalities if value >= 2]
    triads = [value for value in cardinalities if value >= 3]
    if not poly:
        return 0.0
    poly_ratio = len(poly) / len(cardinalities)
    triad_ratio = len(triads) / len(cardinalities)
    max_cardinality = max(cardinalities)
    score = 0.42 * min(1.0, poly_ratio / 0.55) + 0.42 * min(1.0, triad_ratio / 0.35)
    if max_cardinality >= 4:
        score += 0.16
    return min(1.0, score)


def _assignment_cost(midi: int, voice_index: int, previous: int | None) -> float:
    low, high = _RANGE[voice_index]
    range_penalty = 0.0
    if midi < low:
        range_penalty += (low - midi) * 4.0
    elif midi > high:
        range_penalty += (midi - high) * 4.0
    center_penalty = abs(midi - _TARGET_MIDI[voice_index]) * 0.12
    continuity = abs(midi - previous) * 0.45 if previous is not None else 0.0
    return range_penalty + center_penalty + continuity


def _assign_pitches(pitches: list[int], previous: list[int | None]) -> list[int | None]:
    if not pitches:
        return [None, None, None, None]
    candidates = sorted(set(pitches), reverse=True)
    if len(candidates) >= 4:
        selected = [candidates[0], candidates[1], candidates[-2], candidates[-1]]
        if len(candidates) == 4:
            selected = candidates
        return selected

    assignment: list[int | None] = [None, None, None, None]
    available = set(range(4))
    for midi in candidates:
        voice = min(available, key=lambda index: _assignment_cost(midi, index, previous[index]))
        assignment[voice] = midi
        available.remove(voice)
    return assignment


def _copy_measure_context(source_measure: stream.Measure, target: stream.Measure, voice_index: int) -> None:
    for element in source_measure:
        if isinstance(element, (meter.TimeSignature, key.KeySignature)):
            target.insert(element.offset, copy.deepcopy(element))
    if voice_index == 0:
        target.insert(0, clef.TrebleClef())
    elif voice_index == 1:
        target.insert(0, clef.TrebleClef())
    elif voice_index == 2:
        target.insert(0, clef.Treble8vbClef())
    else:
        target.insert(0, clef.BassClef())


def _split_chordal_part(score: stream.Score, part: stream.Part, output_path: Path) -> ChoirResult:
    confidence = _single_part_choir_confidence(part)
    if confidence < 0.72:
        return ChoirResult(False, output_path, confidence, "polyphony-confidence-too-low", 1)

    result = stream.Score()
    if score.metadata is not None:
        result.metadata = copy.deepcopy(score.metadata)
    target_parts: list[stream.Part] = []
    for index, name in enumerate(_VOICE_NAMES):
        target = stream.Part(id=name.lower())
        target.partName = name
        target.partAbbreviation = name[0] if name != "Bass" else "B"
        target.insert(0, instrument.Vocalist())
        target_parts.append(target)
        result.append(target)

    previous: list[int | None] = [None, None, None, None]
    measures = list(part.getElementsByClass(stream.Measure))
    if not measures:
        measured = part.makeMeasures(inPlace=False)
        measures = list(measured.getElementsByClass(stream.Measure))

    for measure_number, source_measure in enumerate(measures, start=1):
        targets = [stream.Measure(number=source_measure.number or measure_number) for _ in range(4)]
        for voice_index, target_measure in enumerate(targets):
            _copy_measure_context(source_measure, target_measure, voice_index)

        for item in source_measure.notes:
            if isinstance(item, note.Note):
                pitches = [item.pitch.midi]
            elif isinstance(item, chord.Chord):
                pitches = [pitch.midi for pitch in item.pitches]
            else:
                continue
            assigned = _assign_pitches(pitches, previous)
            for voice_index, midi in enumerate(assigned):
                if midi is None:
                    continue
                created = note.Note(midi)
                created.duration = copy.deepcopy(item.duration)
                created.tie = copy.deepcopy(getattr(item, "tie", None))
                created.lyrics = copy.deepcopy(getattr(item, "lyrics", []))
                targets[voice_index].insert(item.offset, created)
                previous[voice_index] = midi

        for voice_index, target_measure in enumerate(targets):
            try:
                target_measure.makeRests(fillGaps=True, inPlace=True)
            except Exception:
                pass
            target_parts[voice_index].append(target_measure)

    result.write("musicxml", fp=str(output_path))
    return ChoirResult(True, output_path, confidence, "chordal-satb-assignment", 1)


def reconstruct_satb(
    musicxml_path: Path,
    output_path: Path,
    *,
    mode: str = "auto",
) -> ChoirResult:
    normalized = mode.strip().lower()
    if normalized not in {"auto", "choir", "off"}:
        raise ValueError("choir mode must be auto, choir, or off")
    if normalized == "off":
        return ChoirResult(False, output_path, 0.0, "disabled", 0)

    try:
        parsed = converter.parse(str(musicxml_path))
    except Exception as exc:
        return ChoirResult(False, output_path, 0.0, f"parse-failed:{exc}", 0)
    if not isinstance(parsed, stream.Score):
        return ChoirResult(False, output_path, 0.0, "not-a-score", 0)

    parts = _pitched_parts(parsed)
    if len(parts) == 4:
        result = _rename_four_parts(parsed, output_path)
        if result.applied:
            return result
    if len(parts) != 1:
        return ChoirResult(False, output_path, 0.0, "auto-requires-one-or-four-pitched-parts", len(parts))

    result = _split_chordal_part(parsed, parts[0], output_path)
    if normalized == "choir" and not result.applied and result.confidence >= 0.45:
        # Explicit choir mode lowers only the confidence gate; it never fabricates
        # voices from monophonic material.
        original = _single_part_choir_confidence(parts[0])
        if original >= 0.45:
            return _split_chordal_part_force(parsed, parts[0], output_path, original)
    return result


def _split_chordal_part_force(
    score: stream.Score,
    part: stream.Part,
    output_path: Path,
    confidence: float,
) -> ChoirResult:
    # Reuse the same safe transformation while temporarily meeting the threshold.
    # The implementation is intentionally explicit rather than mutating global policy.
    events = _event_pitch_sets(part)
    if len(events) < 8 or sum(1 for _, _, pitches in events if len(pitches) >= 2) < 4:
        return ChoirResult(False, output_path, confidence, "insufficient-polyphony", 1)

    result = stream.Score()
    if score.metadata is not None:
        result.metadata = copy.deepcopy(score.metadata)
    target_parts: list[stream.Part] = []
    for name in _VOICE_NAMES:
        target = stream.Part(id=name.lower())
        target.partName = name
        target.partAbbreviation = name[0] if name != "Bass" else "B"
        target.insert(0, instrument.Vocalist())
        target_parts.append(target)
        result.append(target)

    previous: list[int | None] = [None, None, None, None]
    measured = part if list(part.getElementsByClass(stream.Measure)) else part.makeMeasures(inPlace=False)
    for measure_number, source_measure in enumerate(measured.getElementsByClass(stream.Measure), start=1):
        targets = [stream.Measure(number=source_measure.number or measure_number) for _ in range(4)]
        for voice_index, target_measure in enumerate(targets):
            _copy_measure_context(source_measure, target_measure, voice_index)
        for item in source_measure.notes:
            pitches = [item.pitch.midi] if isinstance(item, note.Note) else [p.midi for p in item.pitches]
            assigned = _assign_pitches(pitches, previous)
            for voice_index, midi in enumerate(assigned):
                if midi is None:
                    continue
                created = note.Note(midi)
                created.duration = copy.deepcopy(item.duration)
                created.lyrics = copy.deepcopy(getattr(item, "lyrics", []))
                targets[voice_index].insert(item.offset, created)
                previous[voice_index] = midi
        for voice_index, target_measure in enumerate(targets):
            try:
                target_measure.makeRests(fillGaps=True, inPlace=True)
            except Exception:
                pass
            target_parts[voice_index].append(target_measure)
    result.write("musicxml", fp=str(output_path))
    return ChoirResult(True, output_path, confidence, "explicit-choir-satb-assignment", 1)
