from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import mido


@dataclass(frozen=True, slots=True)
class MidiMetrics:
    precision: float
    recall: float
    f1: float
    onset_mae_ms: float | None
    matched: int
    predicted: int
    reference: int

    def as_dict(self) -> dict:
        return {
            "note_precision": self.precision,
            "note_recall": self.recall,
            "note_f1": self.f1,
            "onset_mae_ms": self.onset_mae_ms,
            "matched_notes": self.matched,
            "predicted_notes": self.predicted,
            "reference_notes": self.reference,
        }


def note_onsets(path: Path) -> list[tuple[int, float]]:
    elapsed = 0.0
    notes: list[tuple[int, float]] = []
    for message in mido.MidiFile(path):
        elapsed += float(message.time)
        if message.type == "note_on" and message.velocity > 0:
            notes.append((int(message.note), elapsed))
    return notes


def evaluate_midi_files(
    predicted: Path,
    reference: Path,
    *,
    onset_tolerance_seconds: float = 0.05,
) -> MidiMetrics:
    pred = note_onsets(predicted)
    ref = note_onsets(reference)

    pred_by_pitch: dict[int, list[float]] = defaultdict(list)
    ref_by_pitch: dict[int, list[float]] = defaultdict(list)
    for pitch, onset in pred:
        pred_by_pitch[pitch].append(onset)
    for pitch, onset in ref:
        ref_by_pitch[pitch].append(onset)

    matched = 0
    errors: list[float] = []
    for pitch, ref_onsets in ref_by_pitch.items():
        candidates = pred_by_pitch.get(pitch, [])
        used: set[int] = set()
        for ref_onset in ref_onsets:
            best_index: int | None = None
            best_error = onset_tolerance_seconds + 1.0
            for index, pred_onset in enumerate(candidates):
                if index in used:
                    continue
                error = abs(pred_onset - ref_onset)
                if error <= onset_tolerance_seconds and error < best_error:
                    best_index = index
                    best_error = error
            if best_index is not None:
                used.add(best_index)
                matched += 1
                errors.append(best_error)

    precision = matched / len(pred) if pred else 0.0
    recall = matched / len(ref) if ref else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    onset_mae_ms = (sum(errors) / len(errors) * 1000.0) if errors else None
    return MidiMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        onset_mae_ms=onset_mae_ms,
        matched=matched,
        predicted=len(pred),
        reference=len(ref),
    )
