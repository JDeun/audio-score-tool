"""Score-free onset phase interpretation with bounded local expression paths.

Integer beat anchors are fixed. Local states occupy four-quarter windows, not
inferred bars or voices. Diagnostic event decisions apply only that event's
residual gate; they need not coexist in one admitted full-performance path.
The saved layered graph supports evaluation-only joint-path membership checks.
No duration, score label, grouping, voice or grace marker enters this module.
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
PHASES = ((1, 2), (3, 5), (2, 3), (3, 4))
BLOCK_QUARTERS = 4
MARGIN_Q2 = 1e-4
EPSILON = 1e-12
METHODS = (
    "straight_narrow", "straight_wide", "global_phase",
    "local_raw", "local_switch005", "local_switch010",
)
ARMS = METHODS
SETTINGS = {
    "ticks_per_quarter": Q, "position_ticks": list(POSITION_TICKS),
    "phases": [list(p) for p in PHASES], "block_quarters": BLOCK_QUARTERS,
    "phase_margin_q2_per_event": MARGIN_Q2, "numeric_epsilon": EPSILON,
    "narrow_residual_gate_q": 0.08, "wide_residual_gate_q": 0.18,
    "local_switch_costs_q2": [0.0, 0.0025, 0.01],
    "primary_method": "local_switch005",
    "objective": "(sum squared onset residuals + switch cost times phase changes) / events",
    "partition": "observed onset divided by four quarters; index clamped, onset unchanged",
    "unsupported_score_values_change_lattice": False,
    "offsets_or_velocity_used_for_fit": False,
    "candidate_tick_unions_are_joint_cartesian_candidates": False,
    "margin_is_calibrated_confidence": False,
}


@dataclass(frozen=True)
class OnsetEvent:
    event_id: str
    pitch: int
    onset_q: float
    velocity: int


def fingerprint(data: object) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def canonical_fingerprint(pairs: Iterable[tuple[int, int]]) -> str:
    values = []
    for pitch, tick in pairs:
        if type(pitch) is not int or not 0 <= pitch <= 127 or type(tick) is not int or tick < 0:
            raise ValueError("invalid canonical pitch or tick")
        values.append([pitch, tick])
    return fingerprint(sorted(values))


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate(events: Sequence[OnsetEvent], length_q: float) -> tuple[OnsetEvent, ...]:
    if not _number(length_q) or length_q <= 0:
        raise ValueError("positive finite length required")
    values = tuple(events)
    if not values:
        raise ValueError("nonempty observed inventory required")
    ids = set()
    for event in values:
        if (not isinstance(event, OnsetEvent) or not isinstance(event.event_id, str)
                or not event.event_id.strip() or event.event_id in ids
                or type(event.pitch) is not int or not 0 <= event.pitch <= 127
                or not _number(event.onset_q) or type(event.velocity) is not int
                or not 1 <= event.velocity <= 127):
            raise ValueError("invalid observation or duplicate event identity")
        ids.add(event.event_id)
    return values


def _render(tick: int, phase: tuple[int, int]) -> float:
    beat, remainder = divmod(tick, Q)
    fraction, split = Fraction(remainder, Q), Fraction(*phase)
    within = (2 * fraction * split if remainder <= Q // 2
              else split + 2 * (fraction - Fraction(1, 2)) * (1 - split))
    return float(beat + within)


def _fit(events: tuple[OnsetEvent, ...], ticks: tuple[int, ...], phase: tuple[int, int]) -> dict:
    rendered = tuple(_render(tick, phase) for tick in ticks)
    assignments, residuals = [], []
    for event in events:
        index = bisect_left(rendered, event.onset_q)
        neighbours = range(max(0, index - 1), min(len(ticks), index + 1))
        distances = [(abs(event.onset_q - rendered[i]), i) for i in neighbours]
        residual = min(value for value, _ in distances)
        alternatives = sorted(ticks[i] for value, i in distances if value <= residual + EPSILON)
        assignments.append({"event_id": event.event_id, "pitch": event.pitch,
                            "tick": alternatives[0], "alternatives": alternatives,
                            "abs_residual_q": residual})
        residuals.append(residual)
    try:
        sse = math.fsum(r * r for r in residuals)
    except OverflowError as exc:
        raise ValueError("nonfinite residual cost") from exc
    if not math.isfinite(sse):
        raise ValueError("nonfinite residual cost")
    counts = Counter((a["pitch"], a["tick"]) for a in assignments)
    return {"phase": list(phase), "assignments": assignments,
            "canonical_fingerprint": canonical_fingerprint(counts.elements()),
            "sse_q2": sse, "mse_q2": sse / len(events),
            "max_abs_residual_q": max(residuals),
            "tie_count": sum(len(a["alternatives"]) > 1 for a in assignments),
            "collision_count": sum(n - 1 for n in counts.values())}


def _graph(costs: list[list[float]], allowed: list[list[int]], switch_cost: float | None,
           count: int, budget: float | None = None) -> dict:
    """Exact layered-state shortest paths and min-marginals, without path pruning.

    A None switch cost forbids phase changes (straight/global controls). Empty
    allowed rows make all complete paths unavailable. Costs remain JSON-finite.
    """
    size = len(costs)
    forward = [[None] * 4 for _ in costs]
    paths = [[None] * 4 for _ in costs]
    for state in allowed[0]:
        forward[0][state], paths[0][state] = costs[0][state], (state,)
    for block in range(1, size):
        for state in allowed[block]:
            choices = [(forward[block - 1][previous]
                        + (0.0 if previous == state else switch_cost) + costs[block][state],
                        paths[block - 1][previous] + (state,))
                       for previous in allowed[block - 1]
                       if forward[block - 1][previous] is not None
                       and (switch_cost is not None or previous == state)]
            if choices:
                forward[block][state], paths[block][state] = min(choices)
    finals = [(forward[-1][s], paths[-1][s]) for s in allowed[-1]
              if forward[-1][s] is not None]
    best, path = min(finals) if finals else (None, None)
    if budget is None:
        if best is None:
            raise ValueError("unconstrained graph has no path")
        budget = best + count * (MARGIN_Q2 + EPSILON)
    backward = [[None] * 4 for _ in costs]
    for state in allowed[-1]:
        backward[-1][state] = 0.0
    for block in range(size - 2, -1, -1):
        for state in allowed[block]:
            choices = [(0.0 if state == following else switch_cost)
                       + costs[block + 1][following] + backward[block + 1][following]
                       for following in allowed[block + 1]
                       if backward[block + 1][following] is not None
                       and (switch_cost is not None or state == following)]
            if choices:
                backward[block][state] = min(choices)
    marginals = [[forward[b][s] + backward[b][s]
                  if forward[b][s] is not None and backward[b][s] is not None else None
                  for s in range(4)] for b in range(size)]
    return {"allowed_states": [list(row) for row in allowed], "best_sse_q2": best,
            "best_objective_q2": best / count if best is not None else None,
            "budget_sse_q2": budget, "best_path": list(path) if path is not None else None,
            "min_marginals_sse_q2": marginals,
            "retained_states": [[s for s in range(4) if row[s] is not None and row[s] <= budget]
                                for row in marginals]}


def _tick_union(fits: list[dict], index: int, states: list[int], gate: float | None) -> list[int]:
    return sorted({tick for state in states
                   if gate is None or fits[state]["assignments"][index]["abs_residual_q"] <= gate + EPSILON
                   for tick in fits[state]["assignments"][index]["alternatives"]})


def _arm(events: tuple[OnsetEvent, ...], fits: list[dict], blocks: list[dict],
         event_blocks: list[int], mode: str, switch_cost: float | None, gate: float) -> dict:
    costs = [b["sse_q2"] for b in blocks]
    allowed = [[0] if mode == "straight" else list(range(4)) for _ in blocks]
    diagnostic = _graph(costs, allowed, switch_cost, len(events))
    gated = [[s for s in row if blocks[b]["max_abs_residual_q"][s] <= gate + EPSILON]
             for b, row in enumerate(allowed)]
    full = _graph(costs, gated, switch_cost, len(events), diagnostic["budget_sse_q2"])
    decisions, full_candidates = [], []
    for i, event in enumerate(events):
        block = event_blocks[i]
        ticks = _tick_union(fits, i, diagnostic["retained_states"][block], gate)
        decisions.append({"event_id": event.event_id, "pitch": event.pitch,
                          "candidate_ticks": ticks, "selected_tick": ticks[0] if len(ticks) == 1 else None,
                          "status": "decided" if len(ticks) == 1 else "ambiguous" if ticks else "residual_rejected",
                          "collision": False})
        full_candidates.append({"event_id": event.event_id, "pitch": event.pitch,
                                "candidate_ticks": _tick_union(fits, i, full["retained_states"][block], None)})
    counts = Counter((a["pitch"], a["selected_tick"]) for a in decisions if a["selected_tick"] is not None)
    for item in decisions:
        item["collision"] = item["selected_tick"] is not None and counts[item["pitch"], item["selected_tick"]] > 1
    selected = None
    if not all(full["retained_states"]):
        status = "residual_rejected"
    elif any(len(a["candidate_ticks"]) != 1 for a in full_candidates):
        status = "ambiguous"
    else:
        candidate = [{"event_id": a["event_id"], "pitch": a["pitch"], "tick": a["candidate_ticks"][0]}
                     for a in full_candidates]
        unique = {(a["pitch"], a["tick"]) for a in candidate}
        status = "decided" if len(unique) == len(candidate) else "collision"
        if status == "decided":
            selected = candidate
    return {"mode": mode, "switch_cost_q2": switch_cost, "residual_gate_q": gate,
            "diagnostic_graph": diagnostic, "diagnostic_assignments": decisions,
            "diagnostic_collision_count": sum(n - 1 for n in counts.values()),
            "full_graph": full, "full_candidate_assignments": full_candidates,
            "full_selected_assignments": selected,
            "full_selected_fingerprint": canonical_fingerprint((a["pitch"], a["tick"]) for a in selected)
            if selected is not None else None, "full_status": status}


def infer_performance(events: Sequence[OnsetEvent], length_q: float) -> dict:
    values = _validate(events, length_q)
    bound = Fraction(length_q)
    ticks = tuple(beat * Q + tick for beat in range(math.ceil(bound)) for tick in POSITION_TICKS
                  if Fraction(beat * Q + tick, Q) < bound)
    fits = [_fit(values, ticks, phase) for phase in PHASES]
    block_count = math.ceil(bound / BLOCK_QUARTERS)
    event_blocks = [min(block_count - 1, max(0, math.floor(e.onset_q / BLOCK_QUARTERS))) for e in values]
    blocks = []
    for b in range(block_count):
        indices = [i for i, block in enumerate(event_blocks) if block == b]
        residuals = [[fit["assignments"][i]["abs_residual_q"] for i in indices] for fit in fits]
        blocks.append({"index": b, "start_q": float(b * BLOCK_QUARTERS),
                       "end_q": float(min(bound, (b + 1) * BLOCK_QUARTERS)), "event_indices": indices,
                       "sse_q2": [math.fsum(r * r for r in row) for row in residuals],
                       "max_abs_residual_q": [max(row, default=0.0) for row in residuals]})
    settings = (("straight", None, .08), ("straight", None, .18), ("global", None, .08),
                ("local", 0.0, .08), ("local", .0025, .08), ("local", .01, .08))
    arms = {name: _arm(values, fits, blocks, event_blocks, *setting)
            for name, setting in zip(METHODS, settings)}
    return {"fits": fits, "blocks": blocks, "event_block_indices": event_blocks, "arms": arms}
