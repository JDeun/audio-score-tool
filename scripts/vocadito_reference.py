"""Shared exact reference parsing/scoring for isolated vocal model runtimes."""
from __future__ import annotations

import csv
import io
import math

import numpy as np


def read_notes(raw: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Retain original annotation Hz; note columns are start, Hz, duration."""
    intervals, pitches = [], []
    for row in csv.reader(io.StringIO(raw.decode("utf-8"))):
        if len(row) != 3:
            raise ValueError("Vocadito note row must contain start, Hz, duration")
        start, pitch, duration = map(float, row)
        if (not all(math.isfinite(x) for x in (start, pitch, duration))
                or start < 0 or pitch <= 0 or duration <= 0):
            raise ValueError("Vocadito note row contains an invalid time or pitch")
        intervals.append((start, start + duration))
        pitches.append(pitch)
    if not intervals:
        raise ValueError("Vocadito human annotation is empty")
    order = np.argsort(np.asarray(intervals)[:, 0], kind="stable")
    return np.asarray(intervals)[order], np.asarray(pitches)[order]


def score_annotations(notes, raw: bytes) -> dict:
    import mir_eval

    reference_intervals, reference_pitches = read_notes(raw)
    pitched = [n for n in notes if not n.is_drum and n.offset > n.onset]
    intervals = np.asarray([(n.onset, n.offset) for n in pitched], dtype=float).reshape(-1, 2)
    pitches = np.asarray([440.0 * 2 ** ((n.pitch - 69) / 12) for n in pitched])
    result = {"reference_note_count": len(reference_pitches)}
    for name, ratio in (("onset", None), ("onset_offset", 0.2)):
        # Empty output remains a scored zero, without mir_eval's empty-input warning.
        if not pitched:
            result[name + "_f1"] = 0.0
            continue
        _, _, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
            reference_intervals, reference_pitches, intervals, pitches,
            onset_tolerance=0.05, pitch_tolerance=50.0,
            offset_ratio=ratio, offset_min_tolerance=0.05,
        )
        result[name + "_f1"] = round(float(f1), 8)
    return result


