from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import mido


@dataclass(frozen=True, slots=True)
class MidiNote:
    pitch: int
    onset: float
    offset: float
    channel: int
    program: int
    is_drum: bool

    @property
    def instrument_key(self) -> tuple[bool, int]:
        # Channel numbers are allocator-dependent and are therefore not stable enough
        # for cross-render comparison. General-MIDI program plus the drum flag is a
        # better portable proxy for instrument assignment.
        return self.is_drum, self.program


@dataclass(frozen=True, slots=True)
class MidiMetrics:
    precision: float
    recall: float
    f1: float
    onset_mae_ms: float | None
    matched: int
    predicted: int
    reference: int
    offset_mae_ms: float | None = None
    instrument_precision: float | None = None
    instrument_recall: float | None = None
    instrument_f1: float | None = None
    instrument_matched: int = 0

    def as_dict(self) -> dict:
        return {
            "note_precision": self.precision,
            "note_recall": self.recall,
            "note_f1": self.f1,
            "onset_mae_ms": self.onset_mae_ms,
            "offset_mae_ms": self.offset_mae_ms,
            "matched_notes": self.matched,
            "predicted_notes": self.predicted,
            "reference_notes": self.reference,
            "instrument_precision": self.instrument_precision,
            "instrument_recall": self.instrument_recall,
            "instrument_f1": self.instrument_f1,
            "instrument_matched_notes": self.instrument_matched,
        }


def midi_notes(path: Path) -> list[MidiNote]:
    """Return note events with timing and portable instrument identity.

    mido's MidiFile iterator yields a merged, tempo-aware stream with message.time in
    seconds, which lets this parser work across multi-track files without reimplementing
    tempo-map conversion. Overlapping same-pitch notes on one channel are tracked FIFO.
    """
    elapsed = 0.0
    programs: dict[int, int] = defaultdict(int)
    active: dict[tuple[int, int], list[tuple[float, int]]] = defaultdict(list)
    notes: list[MidiNote] = []

    for message in mido.MidiFile(path):
        elapsed += float(message.time)
        if message.type == "program_change":
            programs[int(message.channel)] = int(message.program)
            continue
        if message.type == "note_on" and message.velocity > 0:
            channel = int(message.channel)
            active[(channel, int(message.note))].append((elapsed, programs[channel]))
            continue
        if message.type not in {"note_off", "note_on"}:
            continue
        if message.type == "note_on" and message.velocity > 0:
            continue
        channel = int(message.channel)
        pitch = int(message.note)
        key = (channel, pitch)
        if not active[key]:
            continue
        onset, program = active[key].pop(0)
        notes.append(
            MidiNote(
                pitch=pitch,
                onset=onset,
                offset=max(onset, elapsed),
                channel=channel,
                program=program,
                is_drum=channel == 9,
            )
        )

    # A malformed/truncated MIDI can leave notes open. Keep them measurable rather than
    # silently dropping their onsets; offset error is then naturally conservative.
    for (channel, pitch), pending in active.items():
        for onset, program in pending:
            notes.append(
                MidiNote(
                    pitch=pitch,
                    onset=onset,
                    offset=max(onset, elapsed),
                    channel=channel,
                    program=program,
                    is_drum=channel == 9,
                )
            )
    notes.sort(key=lambda note: (note.onset, note.pitch, note.channel))
    return notes


def note_onsets(path: Path) -> list[tuple[int, float]]:
    """Compatibility helper retained for callers that only need pitch/onset pairs."""
    return [(note.pitch, note.onset) for note in midi_notes(path)]


def _match_notes(
    predicted: list[MidiNote],
    reference: list[MidiNote],
    *,
    onset_tolerance_seconds: float,
    require_instrument: bool,
) -> tuple[list[tuple[MidiNote, MidiNote]], int]:
    candidates: dict[int, list[MidiNote]] = defaultdict(list)
    for note in predicted:
        candidates[note.pitch].append(note)

    used: set[int] = set()
    indexed = {id(note): index for index, note in enumerate(predicted)}
    matches: list[tuple[MidiNote, MidiNote]] = []
    for ref in reference:
        best: MidiNote | None = None
        best_error = onset_tolerance_seconds + 1.0
        for pred in candidates.get(ref.pitch, []):
            index = indexed[id(pred)]
            if index in used:
                continue
            if require_instrument and pred.instrument_key != ref.instrument_key:
                continue
            error = abs(pred.onset - ref.onset)
            if error <= onset_tolerance_seconds and error < best_error:
                best = pred
                best_error = error
        if best is not None:
            used.add(indexed[id(best)])
            matches.append((best, ref))
    return matches, len(used)


def _prf(matched: int, predicted: int, reference: int) -> tuple[float, float, float]:
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def evaluate_midi_files(
    predicted: Path,
    reference: Path,
    *,
    onset_tolerance_seconds: float = 0.05,
) -> MidiMetrics:
    pred = midi_notes(predicted)
    ref = midi_notes(reference)

    matches, matched = _match_notes(
        pred,
        ref,
        onset_tolerance_seconds=onset_tolerance_seconds,
        require_instrument=False,
    )
    precision, recall, f1 = _prf(matched, len(pred), len(ref))
    onset_errors = [abs(pred_note.onset - ref_note.onset) for pred_note, ref_note in matches]
    offset_errors = [abs(pred_note.offset - ref_note.offset) for pred_note, ref_note in matches]

    instrument_matches, instrument_matched = _match_notes(
        pred,
        ref,
        onset_tolerance_seconds=onset_tolerance_seconds,
        require_instrument=True,
    )
    del instrument_matches
    instrument_precision, instrument_recall, instrument_f1 = _prf(
        instrument_matched,
        len(pred),
        len(ref),
    )

    return MidiMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        onset_mae_ms=(sum(onset_errors) / len(onset_errors) * 1000.0) if onset_errors else None,
        offset_mae_ms=(sum(offset_errors) / len(offset_errors) * 1000.0) if offset_errors else None,
        matched=matched,
        predicted=len(pred),
        reference=len(ref),
        instrument_precision=instrument_precision,
        instrument_recall=instrument_recall,
        instrument_f1=instrument_f1,
        instrument_matched=instrument_matched,
    )
