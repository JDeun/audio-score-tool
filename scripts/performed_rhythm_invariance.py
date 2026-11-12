"""Declared onset-phase toy model; no score, groove label or audio is an input.

The four global phase maps act on every canonical subdivision, including thirds.
They are a bounded mathematical model, not a model of every human swing practice.
Nearest-position ties retain their alternatives. A representative fingerprint or
bar profile during ambiguity is a diagnostic, never an exhaustive candidate set.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Sequence

Q = 12
POSITION_TICKS = (0, 3, 4, 6, 8, 9)
KIT_PITCHES = (36, 38, 42, 43, 46, 47, 49, 50, 51)
PHASES = ((1, 2), (3, 5), (2, 3), (3, 4))
METHODS = ("straight_narrow", "straight_wide", "phase_aware")
NARROW_MAX_RESIDUAL_Q = 0.08
WIDE_MAX_RESIDUAL_Q = 0.18
PHASE_MARGIN_Q2 = 1e-4
NUMERIC_EPSILON = 1e-12
SETTINGS = {
    "ticks_per_quarter": Q,
    "position_ticks": list(POSITION_TICKS),
    "kit_pitches": list(KIT_PITCHES),
    "phases": [list(p) for p in PHASES],
    "narrow_max_residual_q": NARROW_MAX_RESIDUAL_Q,
    "wide_max_residual_q": WIDE_MAX_RESIDUAL_Q,
    "phase_margin_q2": PHASE_MARGIN_Q2,
    "numeric_epsilon": NUMERIC_EPSILON,
    "profile_bar_ticks": 48,
    "phase_scope": "one global phase per take",
    "warp_applies_to": "all canonical positions, including thirds",
    "collision_count_definition": "excess hits at identical instrument and tick",
    "tie_representative": "smallest canonical tick; alternatives retained",
    "candidate_fingerprints_exhaust_tie_alternatives": False,
    "margin_is_calibrated_confidence": False,
    "offsets_used": False,
    "velocity_used_for_selection": False,
}


@dataclass(frozen=True)
class Event:
    event_id: str
    instrument: int
    onset_q: float
    velocity: int


def fingerprint(data: object) -> str:
    """SHA256 of canonical JSON; callers provide JSON-compatible primitives."""
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_fingerprint(assignments: Iterable[tuple[int, int]]) -> str:
    """Hash an instrument/tick multiset, preserving multiplicity but not IDs."""
    pairs = []
    for instrument, tick in assignments:
        if (type(instrument) is not int or not 0 <= instrument < len(KIT_PITCHES)
                or type(tick) is not int or tick < 0):
            raise ValueError("invalid canonical instrument or tick")
        pairs.append([instrument, tick])
    return fingerprint(sorted(pairs))


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate(events: Sequence[Event], length_q: float) -> tuple[Event, ...]:
    if not _number(length_q) or length_q <= 0:
        raise ValueError("positive finite length_q required")
    values = tuple(events)
    if not values:
        raise ValueError("nonempty events required")
    ids = set()
    for event in values:
        if (not isinstance(event, Event) or not isinstance(event.event_id, str)
                or not event.event_id.strip() or event.event_id in ids
                or type(event.instrument) is not int
                or not 0 <= event.instrument < len(KIT_PITCHES)
                or not _number(event.onset_q) or type(event.velocity) is not int
                or not 1 <= event.velocity <= 127):
            raise ValueError("invalid event or duplicate event ID")
        ids.add(event.event_id)
    return values


def _positions(length_q: float) -> tuple[int, ...]:
    bound = Fraction(length_q)
    return tuple(beat * Q + tick for beat in range(math.ceil(bound))
                 for tick in POSITION_TICKS if Fraction(beat * Q + tick, Q) < bound)


def _warped_position(tick: int, phase: tuple[int, int]) -> float:
    beat, remainder = divmod(tick, Q)
    fraction, split = Fraction(remainder, Q), Fraction(*phase)
    within = (2 * fraction * split if remainder <= Q // 2
              else split + 2 * (fraction - Fraction(1, 2)) * (1 - split))
    return float(beat + within)


def _fit(events: tuple[Event, ...], positions: tuple[int, ...], phase: tuple[int, int]):
    warped = tuple(_warped_position(tick, phase) for tick in positions)
    assignments, residuals = [], []
    profile = [[0] * 48 for _ in KIT_PITCHES]
    for event in events:
        index = bisect_left(warped, event.onset_q)
        neighbours = range(max(0, index - 1), min(len(warped), index + 1))
        distances = [(abs(event.onset_q - warped[i]), i) for i in neighbours]
        nearest = min(distance for distance, _ in distances)
        alternatives = sorted(positions[i] for distance, i in distances
                              if distance <= nearest + NUMERIC_EPSILON)
        tick = alternatives[0]
        assignments.append({"event_id": event.event_id, "instrument": event.instrument,
                            "tick": tick, "alternatives": alternatives})
        residuals.append(nearest)
        profile[event.instrument][tick % 48] += 1
    counts = Counter((a["instrument"], a["tick"]) for a in assignments)
    try:
        mse = math.fsum(r * r for r in residuals) / len(events)
    except OverflowError as exc:
        raise ValueError("residual cost exceeds finite arithmetic") from exc
    if not math.isfinite(mse):
        raise ValueError("residual cost exceeds finite arithmetic")
    return {
        "phase": list(phase), "assignments": assignments, "profile": profile,
        "canonical_fingerprint": canonical_fingerprint(counts.elements()),
        "mse_q2": mse,
        "max_abs_residual_q": max(residuals),
        "tie_count": sum(len(a["alternatives"]) > 1 for a in assignments),
        "collision_count": sum(count - 1 for count in counts.values()),
    }


def _arm(fits: list[dict], diagnostic: list[int], max_residual: float) -> dict:
    retained = [i for i in diagnostic
                if fits[i]["max_abs_residual_q"] <= max_residual + NUMERIC_EPSILON]
    candidates = sorted({fits[i]["canonical_fingerprint"] for i in retained})
    tied = any(fits[i]["tie_count"] for i in retained)
    collided = any(fits[i]["collision_count"] for i in retained)
    if not retained:
        status = "residual_rejected"
    elif collided:
        status = "collision"
    elif tied:
        status = "nearest_tie"
    elif len(candidates) > 1:
        status = "ambiguous"
    else:
        status = "decided"
    return {
        "diagnostic_fit_indices": diagnostic,
        "retained_fit_indices": retained,
        "candidate_fingerprints": candidates,
        "selected_fingerprint": candidates[0] if status == "decided" else None,
        "status": status,
        "has_nearest_tie": tied,
        "has_collision": collided,
        "candidate_fingerprints_exhaustive": not tied,
    }


def infer_take(events: Sequence[Event], length_q: float) -> dict:
    """Interpret a take using only supplied event observations and score span.

    Small boundary microtiming is preserved even outside [0, length_q). Only
    canonical positions are restricted to that span. Nearest ties and collisions
    remain in retained fits and prohibit a decisive output; they are never erased
    to make another phase uniquely acceptable. Diagnostic profiles are kept even
    when the residual gate rejects the corresponding score interpretation.
    """
    values = _validate(events, length_q)
    positions = _positions(length_q)
    fits = [_fit(values, positions, phase) for phase in PHASES]
    best = min(fit["mse_q2"] for fit in fits)
    near = [i for i, fit in enumerate(fits)
            if fit["mse_q2"] <= best + PHASE_MARGIN_Q2 + NUMERIC_EPSILON]
    arms = {
        "straight_narrow": _arm(fits, [0], NARROW_MAX_RESIDUAL_Q),
        "straight_wide": _arm(fits, [0], WIDE_MAX_RESIDUAL_Q),
        "phase_aware": _arm(fits, near, NARROW_MAX_RESIDUAL_Q),
    }
    return {"fits": fits, "arms": arms}
