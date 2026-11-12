"""Reference-free, bounded research edits; NOT a production correction policy."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Event:
    pitch: int
    onset: float
    offset: float
    channel: int = 0
    program: int = 0
    is_drum: bool = False


def events_from(notes) -> list[Event]:
    result = [Event(**{key: getattr(n, key) for key in Event.__dataclass_fields__}) for n in notes]
    for n in result:
        if (not all(math.isfinite(v) for v in (n.pitch, n.onset, n.offset))
                or int(n.pitch) != n.pitch or not 0 <= n.pitch <= 127
                or n.onset < 0 or n.offset <= n.onset):
            raise ValueError("Invalid predicted event")
    return result


def event_digest(notes: list[Event]) -> str:
    raw = json.dumps([asdict(n) for n in notes], sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def isolated(notes: list[Event], index: int) -> bool:
    note = notes[index]
    return not note.is_drum and not any(
        j != index and not other.is_drum
        and min(note.offset, other.offset) - max(note.onset, other.onset) > 1e-6
        for j, other in enumerate(notes)
    )


def octave_proposals(notes: list[Event], times: np.ndarray, hz: np.ndarray) -> list[Event]:
    """Only isolated notes and stable voiced interiors can propose exactly +/-12.

    All timings, note count and instrument identities are invariant. Reference
    notes, keys, song names and annotation boundaries are not accepted as inputs.
    Voicing is supplied by the fixed Tiny predictor, not treated as truth.
    """
    times, hz = np.asarray(times), np.asarray(hz)
    if (times.ndim != 1 or times.shape != hz.shape or len(times) < 2
            or not np.isfinite(times).all() or not np.isfinite(hz).all()
            or np.any(np.diff(times) <= 0) or np.any(times < 0) or np.any(hz < 0)):
        raise ValueError("Invalid acoustic observations")
    proposed = list(notes)
    for i, n in enumerate(notes):
        if not isolated(notes, i):
            continue
        margin = max(0.03, min(0.10, (n.offset - n.onset) * 0.15))
        window = hz[(times >= n.onset + margin) & (times < n.offset - margin)]
        voiced = window[window > 0]
        if len(window) < 6 or len(voiced) < 6 or len(voiced) / len(window) < 0.85:
            continue
        pitches = 69 + 12 * np.log2(voiced / 440)
        median = float(np.median(pitches))
        target = int(round(median))
        if (float(np.quantile(pitches, 0.9) - np.quantile(pitches, 0.1)) <= 0.4
                and abs(median - target) <= 0.2 and abs(target - n.pitch) == 12
                and 0 <= target <= 127):
            proposed[i] = replace(n, pitch=target)
    return proposed


def onset_proposals(notes: list[Event], peaks: np.ndarray) -> list[Event]:
    """Use a unique audio attack within 60 ms; never cross/reorder/delete notes.

    Simultaneous/polyphonic notes and peaks claimed by multiple notes abstain.
    Offset is unchanged. This is a hypothesis, not a guaranteed improvement.
    """
    peaks = np.asarray(peaks, dtype=float)
    if (peaks.ndim != 1 or not np.isfinite(peaks).all() or np.any(peaks < 0)
            or np.any(np.diff(peaks) <= 0)):
        raise ValueError("Invalid attack observations")
    candidates: dict[int, int] = {}
    for i, note in enumerate(notes):
        if not isolated(notes, i):
            continue
        nearby = np.flatnonzero(np.abs(peaks - note.onset) <= 0.060)
        if len(nearby) == 1:
            candidates[i] = int(nearby[0])
    result = list(notes)
    for i, k in candidates.items():
        if list(candidates.values()).count(k) != 1:
            continue
        n, value = notes[i], float(peaks[k])
        others = [x.onset for j, x in enumerate(notes) if j != i]
        lower = max((x for x in others if x < n.onset), default=-1.0)
        upper = min((x for x in others if x > n.onset), default=float("inf"))
        if not lower < value < upper or n.offset - value < 0.040:
            continue
        candidate = replace(n, onset=value)
        # Moving an onset earlier must not create a new overlap with another note.
        if any(j != i and not x.is_drum
               and min(candidate.offset, x.offset) - max(candidate.onset, x.onset) > 1e-6
               for j, x in enumerate(notes)):
            continue
        result[i] = candidate
    return result


def matched_transition(before: set[int], after: set[int]) -> dict:
    """Matching-ID changes, not a claim of confirmed musical correction/harm."""
    return {"matched_prediction_ids_gained": len(after - before),
            "matched_prediction_ids_lost": len(before - after)}


def aggregate(cases: list[dict], planned: tuple[str, ...], arms: tuple[str, ...]) -> dict | None:
    """Missing, duplicated or failed recordings/arms prohibit an overall score."""
    if (len(cases) != len(planned) or {c['id'] for c in cases} != set(planned)
            or any(c.get('status') != 'scored' or set(c.get('arms', {})) != set(arms) for c in cases)):
        return None
    output = {}
    metrics = ('onset_f1', 'onset_offset_f1')
    for arm in arms:
        output[arm] = {}
        for metric in metrics:
            scores = np.asarray([np.mean([c['arms'][arm]['annotators'][a][metric]
                                         for a in ('A1', 'A2')]) for c in cases])
            baseline = np.asarray([np.mean([c['arms']['raw']['annotators'][a][metric]
                                           for a in ('A1', 'A2')]) for c in cases])
            if not np.isfinite(scores).all() or not np.isfinite(baseline).all():
                raise ValueError('Nonfinite scored metric')
            delta = scores - baseline
            rng = np.random.default_rng(0)
            boot = rng.choice(delta, size=(2000, len(delta)), replace=True).mean(axis=1)
            output[arm][metric] = {
                'macro': float(scores.mean()), 'delta_vs_raw': float(delta.mean()),
                'paired_recording_bootstrap_95': np.quantile(boot, [0.025, 0.975]).tolist(),
                'recordings_improved': int((delta > 1e-8).sum()),
                'recordings_worse': int((delta < -1e-8).sum()),
            }
    return output
