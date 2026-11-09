"""Raw note-event scoring for mix-versus-estimated-stem AMT experiments.

Score the multiset union of independently decoded MIDI events directly. No
MIDI serialization, deduplication, timing correction, or instrument remapping
is performed here. Each metric finds its own maximum one-to-one matching.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from collections.abc import Sequence
from typing import Any

from .metrics import MidiNote

METHOD_ID = "maximum_bipartite_one_to_one_note_events_v1"
_ONSET_TOLERANCE = 0.05
_OFFSET_MINIMUM = 0.05
_OFFSET_RATIO = 0.2
_FLOAT_EPSILON = 1e-12


def _validate_notes(notes: Sequence[MidiNote], label: str) -> None:
    if not isinstance(notes, Sequence):
        raise ValueError(f"{label} must be a sequence of MidiNote events")
    for index, note in enumerate(notes):
        if not isinstance(note, MidiNote):
            raise ValueError(f"{label}[{index}] must be a MidiNote event")
        valid_times = False
        try:
            valid_times = (
                type(note.onset) in (int, float)
                and type(note.offset) in (int, float)
                and math.isfinite(note.onset)
                and math.isfinite(note.offset)
                and 0 <= note.onset < note.offset
            )
        except OverflowError:
            pass
        if not valid_times:
            raise ValueError(f"{label}[{index}] must have finite, nonnegative, positive-length times")
        if (
            type(note.pitch) is not int or not 0 <= note.pitch <= 127
            or type(note.program) is not int or not 0 <= note.program <= 127
            or type(note.channel) is not int or not 0 <= note.channel <= 15
            or type(note.is_drum) is not bool
        ):
            raise ValueError(f"{label}[{index}] has invalid MIDI pitch or instrument fields")


def _maximum_cardinality(adjacency: list[list[int]], prediction_count: int) -> int:
    """Find augmenting paths iteratively, retaining distinct duplicate events.

    Vertices are sequence indices, even when two entries are the same object.
    Breadth-first alternating paths avoid recursion limits on dense passages.
    """
    left_match = [-1] * len(adjacency)
    right_match = [-1] * prediction_count
    matched = 0
    for start in range(len(adjacency)):
        queue = deque([start])
        seen_left = {start}
        parent_right: dict[int, int] = {}
        free_right = -1
        while queue and free_right == -1:
            left = queue.popleft()
            for right in adjacency[left]:
                if right in parent_right:
                    continue
                parent_right[right] = left
                owner = right_match[right]
                if owner == -1:
                    free_right = right
                    break
                if owner not in seen_left:
                    seen_left.add(owner)
                    queue.append(owner)
        if free_right == -1:
            continue
        while free_right != -1:
            left = parent_right[free_right]
            previous = left_match[left]
            left_match[left] = free_right
            right_match[free_right] = left
            free_right = previous
        matched += 1
    return matched


def _statistics(matched: int, predicted: int, reference: int) -> dict[str, float | int]:
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * matched / (predicted + reference),
        "matched": matched,
    }


def score_note_events(
    predicted: Sequence[MidiNote], reference: Sequence[MidiNote],
) -> dict[str, Any]:
    """Score unmodified event multisets with maximum bipartite matching.

    All three metrics require equal pitch and onset within 50 ms. Full-note
    metrics also require offset within max(50 ms, 20% of reference duration).
    Instrument-aware full-note matching additionally uses MidiNote.instrument_key:
    pitched GM program plus drum identity; MIDI channel allocation is irrelevant.
    Drum program variants share the existing evaluator's percussion identity.

    Empty predictions are valid and score zero. An empty reference, malformed
    MIDI fields, nonfinite timing, or nonpositive note duration raises ValueError.
    The reported tiny epsilon only handles floating-point threshold boundaries.
    """
    _validate_notes(predicted, "predicted")
    _validate_notes(reference, "reference")
    if not reference:
        raise ValueError("reference must contain at least one performed note")

    by_pitch: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for index, note in enumerate(predicted):
        by_pitch[note.pitch].append((note.onset, index))
    for entries in by_pitch.values():
        entries.sort()
    onsets = {pitch: [entry[0] for entry in entries] for pitch, entries in by_pitch.items()}
    graphs: dict[str, list[list[int]]] = {
        name: [] for name in ("onset", "onset_offset", "instrument_onset_offset")
    }
    for ref in reference:
        for graph in graphs.values():
            graph.append([])
        entries = by_pitch.get(ref.pitch, [])
        times = onsets.get(ref.pitch, [])
        first = bisect_left(times, ref.onset - _ONSET_TOLERANCE - _FLOAT_EPSILON)
        last = bisect_right(times, ref.onset + _ONSET_TOLERANCE + _FLOAT_EPSILON)
        offset_tolerance = max(_OFFSET_MINIMUM, _OFFSET_RATIO * (ref.offset - ref.onset))
        for _onset, index in entries[first:last]:
            note = predicted[index]
            graphs["onset"][-1].append(index)
            if abs(note.offset - ref.offset) > offset_tolerance + _FLOAT_EPSILON:
                continue
            graphs["onset_offset"][-1].append(index)
            if note.instrument_key == ref.instrument_key:
                graphs["instrument_onset_offset"][-1].append(index)

    return {
        "method": METHOD_ID,
        "onset_tolerance_seconds": _ONSET_TOLERANCE,
        "offset_minimum_tolerance_seconds": _OFFSET_MINIMUM,
        "offset_reference_duration_ratio": _OFFSET_RATIO,
        "floating_point_epsilon_seconds": _FLOAT_EPSILON,
        "instrument_identity": "pitched_gm_program_or_percussion",
        "predicted_note_count": len(predicted),
        "reference_note_count": len(reference),
        **{
            name: _statistics(_maximum_cardinality(graph, len(predicted)),
                              len(predicted), len(reference))
            for name, graph in graphs.items()
        },
    }
