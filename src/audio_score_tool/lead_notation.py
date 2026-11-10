"""Interpret a performed vocal melody on an observed audio beat grid.

This is separate from the lossless MIDI importer. Keep the raw performance:
an interpreted score can omit sub-grid events and needs its own quality review.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from .metrics import MidiNote, midi_notes


def vocal_grid(notes: Sequence[MidiNote], grid_seconds: Sequence[float]) -> tuple[np.ndarray, dict]:
    """Return native ABC pitch/attack cells and an auditable source-event map.

    shortcut: this fixed recipe uses the provider's sixteenth grid; triplets and
    sub-grid ornaments need musical-reference validation before release approval.
    """
    if any(isinstance(value, (bool, np.bool_)) for value in grid_seconds):
        raise ValueError("Audio grid cannot contain boolean times")
    times = np.asarray(grid_seconds, dtype=np.float64)
    if (times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times))
            or times[0] < 0 or not np.all(np.diff(times) > 0)):
        raise ValueError("Audio grid must contain increasing finite nonnegative times")
    if not notes:
        raise ValueError("Vocal interpretation requires performed notes")
    for event in notes:
        if (not isinstance(event, MidiNote) or type(event.pitch) is not int
                or not 0 <= event.pitch <= 127 or event.is_drum is not False
                or type(event.onset) not in (float, int) or type(event.offset) not in (float, int)
                or not math.isfinite(event.onset) or not math.isfinite(event.offset)
                or not 0 <= event.onset < event.offset):
            raise ValueError("Invalid performed vocal event")
    ordered = sorted(enumerate(notes), key=lambda item: (
        item[1].onset, item[1].offset, item[1].pitch, item[0],
    ))
    left, right = times[:-1], times[1:]
    best = np.zeros(len(left))
    winner = np.full(len(left), -1, dtype=np.int32)
    competing = np.zeros(len(left), dtype=np.int32)
    for index, event in ordered:
        first = max(0, int(np.searchsorted(times, event.onset, side="right")) - 1)
        last = min(len(left), int(np.searchsorted(times, event.offset, side="left")))
        if last <= first:
            continue
        overlap = np.maximum(0, np.minimum(event.offset, right[first:last])
                             - np.maximum(event.onset, left[first:last]))
        competing[first:last] += overlap >= 0.5 * (right[first:last] - left[first:last]) - 1e-12
        replace = overlap > best[first:last]
        winner[first:last][replace] = index
        best[first:last][replace] = overlap[replace]
    winner[best < 0.5 * (right - left) - 1e-12] = -1
    cells = np.zeros(len(times), dtype=np.int32)
    attacks = []
    previous = -1
    for position, index in enumerate(winner):
        if index < 0:
            previous = -1
            continue
        attack = index != previous
        cells[position] = notes[index].pitch * 2 + 2 + int(attack)
        if attack:
            attacks.append(int(index))
        previous = int(index)
    represented = set(attacks)
    if not represented or len(attacks) != len(represented):
        raise ValueError("Audio grid would erase the vocal or manufacture repeated attacks")
    return cells, {
        "algorithm": "dominant_overlap_on_audio_sixteenth_grid_v1",
        "raw_note_count": len(notes), "represented_note_count": len(represented),
        "notated_attacks": len(attacks),
        "unrepresented_note_indices": sorted(set(range(len(notes))) - represented),
        "source_note_indices": winner.tolist(),
        "overlap_review_cells": np.flatnonzero(competing > 1).tolist(),
        "pitch_adjustments": 0, "raw_events_mutated": False, "quality_approved": False,
    }


def verify_notated_midi(source, rendered, interpretation: dict) -> dict:
    """Refuse a completed draft when conversion changes its interpreted notes."""
    notes = midi_notes(source)
    times = np.asarray(interpretation["grid_audio_seconds"], dtype=np.float64)
    indices = interpretation["source_note_indices"]
    if (times.ndim != 1 or len(times) != len(indices) + 1 or not np.all(np.isfinite(times))
            or times[0] < 0 or not np.all(np.diff(times) > 0)
            or any(type(i) is not int or not -1 <= i < len(notes) for i in indices)):
        raise ValueError("Invalid vocal interpretation event map")
    expected = []
    previous = -1
    for position, index in enumerate(indices):
        if index < 0:
            previous = -1
            continue
        if index != previous:
            expected.append([notes[index].pitch, times[position], times[position + 1]])
        else:
            expected[-1][2] = times[position + 1]
        previous = index
    actual = midi_notes(rendered)
    if not expected or len(actual) != len(expected):
        raise ValueError("Notation conversion changed the interpreted vocal attack count")
    maximum = 0.0
    for wanted, played in zip(expected, actual, strict=True):
        difference = max(abs(wanted[1] - played.onset), abs(wanted[2] - played.offset))
        if wanted[0] != played.pitch or difference > .002:
            raise ValueError("Notation conversion changed an interpreted vocal pitch or audio time")
        maximum = max(maximum, float(difference))
    return {"performed_notes": len(actual), "max_time_difference_seconds": maximum,
            "tolerance_seconds": .002, "pitch_adjustments": 0,
            "matched_interpretation": True, "original_song_accuracy": None}
