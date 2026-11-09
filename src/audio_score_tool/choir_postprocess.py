from __future__ import annotations

import copy
import math
import statistics
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import mido
from music21 import chord, clef, converter, instrument, key, meter, note, stream, tempo

from .metrics import midi_notes
from .midi_ties import restore_instrument_bindings
from .notation_backend import musicxml_to_midi


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


def _rename_four_parts(
    score: stream.Score, source_path: Path, output_path: Path,
) -> ChoirResult:
    parts = _pitched_parts(score)
    medians = [(_part_median_pitch(part), part) for part in parts]
    if len(parts) != 4 or any(value is None for value, _ in medians):
        return ChoirResult(False, output_path, 0.0, "not-four-pitched-parts", len(parts))
    # Stable pitch order also handles unison parts without comparing Part objects.
    ordered = sorted(medians, key=lambda pair: float(pair[0] or 0), reverse=True)
    spread = [float(value or 0) for value, _ in medians]
    if min(spread) < 30 or max(spread) > 92:
        return ChoirResult(False, output_path, 0.0, "implausible-vocal-range", len(parts))

    # This operation only labels existing parts. Reserializing their notes via
    # music21 can quantize arbitrary AMT durations or replace GM instruments.
    tree = ET.parse(source_path)
    root = tree.getroot()
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    xml_parts = root.findall(f"{ns}part")
    definitions = {
        element.get("id"): element
        for element in root.findall(f"{ns}part-list/{ns}score-part")
    }
    indices = {id(part): index for index, part in enumerate(score.parts)}
    if len(xml_parts) != len(score.parts):
        raise ValueError("Cannot map existing score parts to their MusicXML definitions")
    for name, (_, part) in zip(_VOICE_NAMES, ordered, strict=True):
        definition = definitions[xml_parts[indices[id(part)]].get("id")]
        for tag, value in (("part-name", name), ("part-abbreviation", name[0])):
            element = definition.find(f"{ns}{tag}")
            if element is None:
                element = ET.Element(f"{ns}{tag}")
                preceding = {f"{ns}identification"}
                if tag == "part-abbreviation":
                    preceding.update({f"{ns}part-name", f"{ns}part-name-display"})
                index = next(
                    (index for index, child in enumerate(definition) if child.tag not in preceding),
                    len(definition),
                )
                definition.insert(index, element)
            element.text = value
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return ChoirResult(True, output_path, 0.86, "four-part-pitch-order", 4, len(xml_parts))


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
    candidates = sorted(pitches, reverse=True)
    if len(candidates) > 4 or len(set(candidates)) != len(candidates):
        raise ValueError("Four voice assignment cannot discard extra or unison chord pitches")
    if len(candidates) == 4:
        return candidates

    assignment: list[int | None] = [None, None, None, None]
    available = set(range(4))
    for midi in candidates:
        voice = min(available, key=lambda index: _assignment_cost(midi, index, previous[index]))
        assignment[voice] = midi
        available.remove(voice)
    return assignment


def _copy_measure_context(source_measure: stream.Measure, target: stream.Measure, voice_index: int) -> None:
    for element in source_measure:
        if isinstance(element, (meter.TimeSignature, key.KeySignature,
                                tempo.TempoIndication, instrument.Instrument)):
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
    if confidence < 0.45:
        return ChoirResult(False, output_path, confidence, "polyphony-confidence-too-low", 1)

    # Voice assignment for overlapping score voices or more than four pitches
    # needs a real arrangement decision. Do not drop notes to fit four staves.
    if list(part.recurse().getElementsByClass(stream.Voice)):
        return ChoirResult(False, output_path, confidence, "nested-voices-require-manual-arrangement", 1)
    for event in part.recurse().notes:
        if isinstance(event, chord.Chord):
            pitches = [pitch.midi for pitch in event.pitches]
            if len(pitches) > 4 or len(set(pitches)) != len(pitches):
                return ChoirResult(False, output_path, confidence, "chord-pitches-require-manual-arrangement", 1)

    result = stream.Score()
    if score.metadata is not None:
        result.metadata = copy.deepcopy(score.metadata)
    target_parts: list[stream.Part] = []
    for index, name in enumerate(_VOICE_NAMES):
        target = stream.Part(id=name.lower())
        target.partName = name
        target.partAbbreviation = name[0] if name != "Bass" else "B"
        # SATB is a notation assignment, not an instruction to relabel the AMT
        # instrument. Preserve explicit GM variants and later program changes.
        target.insert(0, copy.deepcopy(part.getInstrument()))
        for context in part.getElementsByClass(tempo.TempoIndication):
            target.insert(context.offset, copy.deepcopy(context))
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
                members = [item]
            elif isinstance(item, chord.Chord):
                members = list(item.notes)
            else:
                continue
            pitches = [member.pitch.midi for member in members]
            assigned = _assign_pitches(pitches, previous)
            for voice_index, midi in enumerate(assigned):
                if midi is None:
                    continue
                # Retain spelling, member-specific ties, articulations and
                # velocities instead of constructing a new default note.
                created = copy.deepcopy(next(member for member in members if member.pitch.midi == midi))
                created.duration = copy.deepcopy(item.duration)
                if created.volume.velocity is None:
                    created.volume = copy.deepcopy(item.volume)
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


def _tempo_map(path: Path) -> list[tuple[Fraction, int]]:
    midi = mido.MidiFile(path)
    absolute = 0
    values = {Fraction(0): 500_000}
    for message in mido.merge_tracks(midi.tracks):
        absolute += message.time
        if message.type == "set_tempo":
            values[Fraction(absolute, midi.ticks_per_beat)] = message.tempo
    result: list[tuple[Fraction, int]] = []
    for offset, value in sorted(values.items()):
        if not result or result[-1][1] != value:
            result.append((offset, value))
    return result


def _preserves_performance(source: Path, candidate: Path, stage: Path) -> bool:
    """Check exact note multiplicity, instruments, tempo map and sounding times.

    Both XML documents use the same production playback converter. A one
    microsecond tolerance allows float accumulation, not musical quantization
    or the much looser benchmark onset/offset matching tolerances.
    """
    source_midi = musicxml_to_midi(source, stage / "source.mid")
    candidate_midi = musicxml_to_midi(candidate, stage / "candidate.mid")
    original = midi_notes(source_midi)
    transformed = midi_notes(candidate_midi)
    if not original or len(original) != len(transformed):
        return False
    if _tempo_map(source_midi) != _tempo_map(candidate_midi):
        return False

    def identity(event):
        return event.pitch, event.program, event.is_drum

    def order(event):
        return (*identity(event), event.onset, event.offset)

    for before, after in zip(sorted(original, key=order), sorted(transformed, key=order), strict=True):
        if identity(before) != identity(after) or not all(
            math.isclose(left, right, rel_tol=0, abs_tol=1e-6)
            for left, right in ((before.onset, after.onset), (before.offset, after.offset))
        ):
            return False
    return True


def reconstruct_satb(
    musicxml_path: Path,
    output_path: Path,
    *,
    mode: str = "auto",
) -> ChoirResult:
    """Apply an explicit SATB request only if the original performance survives.

    Instrumental polyphony and four pitched parts are not evidence of a choir.
    Auto mode only recognizes existing SATB labels and leaves the score intact.
    """
    normalized = mode.strip().lower()
    if normalized not in {"auto", "choir", "off"}:
        raise ValueError("choir mode must be auto, choir, or off")
    if normalized == "off":
        return ChoirResult(False, output_path, 0.0, "disabled", 0)

    source_parts = 0
    try:
        parsed = converter.parse(str(musicxml_path))
        if not isinstance(parsed, stream.Score):
            return ChoirResult(False, output_path, 0.0, "not-a-score", 0)
        parts = _pitched_parts(parsed)
        source_parts = len(parts)
        if normalized == "auto":
            labels = {(part.partName or "").strip().casefold() for part in parts}
            identified = source_parts == 4 and labels == {name.casefold() for name in _VOICE_NAMES}
            reason = "already-labelled-satb" if identified else "automatic-satb-not-established"
            return ChoirResult(False, output_path, 0.0, reason, source_parts)
        if source_parts not in {1, 4}:
            return ChoirResult(False, output_path, 0.0, "requires-one-or-four-pitched-parts", source_parts)
        if source_parts == 1 and len(parsed.parts) != 1:
            return ChoirResult(False, output_path, 0.0, "additional-parts-require-manual-arrangement", source_parts)

        restore_instrument_bindings(parsed, musicxml_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".choir-", dir=output_path.parent) as folder:
            stage = Path(folder)
            candidate = stage / "candidate.musicxml"
            result = (
                _rename_four_parts(parsed, musicxml_path, candidate)
                if source_parts == 4
                else _split_chordal_part(parsed, parts[0], candidate)
            )
            result.output_path = output_path
            if not result.applied:
                return result
            if not _preserves_performance(musicxml_path, candidate, stage):
                return ChoirResult(False, output_path, result.confidence, "performance-preservation-check-failed", source_parts)
            candidate.replace(output_path)
            return result
    except Exception as exc:
        # Choir reconstruction is optional. A valid canonical score must never
        # be lost because an arrangement or its verification cannot be written.
        return ChoirResult(False, output_path, 0.0, f"unsafe-transformation:{type(exc).__name__}:{exc}", source_parts)
