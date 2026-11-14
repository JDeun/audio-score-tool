"""Independent event metrics for the bounded drum-lane study.

No waveform, predictor, MIDI renderer or dataset loader is imported. Roles are
fixed by the caller's declared source mapping. Unsupported roles remain in the
reference denominator. Event IDs retain simultaneous-event multiplicity.
Inclusive temporal endpoints allow 1e-12 seconds for floating-point subtraction
roundoff; event times and optimization costs are never rounded or shifted.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass

MAX_EVENTS = 2000
MAX_PAIR_CELLS = 2_000_000
TIME_EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    time: float
    role: str
    velocity: int | None = None


def _events(events):
    events = list(events)
    if len(events) > MAX_EVENTS:
        raise ValueError("event budget exceeded")
    ids = set()
    for event in events:
        if (not isinstance(event, Event) or not isinstance(event.event_id, str)
                or not event.event_id or event.event_id in ids
                or not isinstance(event.role, str) or not event.role.strip()
                or event.role != event.role.strip()
                or type(event.time) not in {int, float}
                or not math.isfinite(event.time) or event.time < 0
                or (event.velocity is not None and
                    (type(event.velocity) is not int or not 1 <= event.velocity <= 127))):
            raise ValueError("invalid or duplicate event")
        ids.add(event.event_id)
    return sorted(events, key=lambda event: (event.time, event.event_id))


def _tolerance(value):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("tolerance must be finite and nonnegative")


def _pair(reference, predicted):
    error = predicted.time - reference.time
    return {
        "reference_id": reference.event_id, "predicted_id": predicted.event_id,
        "reference_time": reference.time, "predicted_time": predicted.time,
        "reference_role": reference.role, "predicted_role": predicted.role,
        "error_seconds": error, "absolute_error_seconds": abs(error),
    }


def _ordered_pairs(reference, predicted, tolerance):
    """Maximum cardinality, then minimum absolute timing error, in time order.

    For one-dimensional interval eligibility and absolute distance an optimum
    has a noncrossing assignment. Exact ties use sorted IDs and a fixed DP
    transition order; labels never break a class-agnostic timing tie.
    """
    n, m = len(reference), len(predicted)
    if n * m > MAX_PAIR_CELLS:
        raise ValueError("matching cell budget exceeded")
    if not n or not m:
        return []
    directions = [bytearray([2] * (m + 1))]
    counts, costs = [0] * (m + 1), [0.0] * (m + 1)
    for i, ref in enumerate(reference, 1):
        next_counts, next_costs = [0] * (m + 1), [0.0] * (m + 1)
        route = bytearray(m + 1)
        route[0] = 1
        for j, pred in enumerate(predicted, 1):
            best_count, best_cost, choice = counts[j], costs[j], 1
            if (next_counts[j - 1] > best_count or
                    (next_counts[j - 1] == best_count and next_costs[j - 1] < best_cost)):
                best_count, best_cost, choice = next_counts[j - 1], next_costs[j - 1], 2
            delta = abs(pred.time - ref.time)
            if delta <= tolerance + TIME_EPSILON:
                candidate_count, candidate_cost = counts[j - 1] + 1, costs[j - 1] + delta
                if (candidate_count > best_count or
                        (candidate_count == best_count and candidate_cost <= best_cost)):
                    best_count, best_cost, choice = candidate_count, candidate_cost, 3
            next_counts[j], next_costs[j], route[j] = best_count, best_cost, choice
        directions.append(route)
        counts, costs = next_counts, next_costs
    pairs = []
    i, j = n, m
    while i and j:
        choice = directions[i][j]
        if choice == 3:
            pairs.append(_pair(reference[i - 1], predicted[j - 1]))
            i, j = i - 1, j - 1
        elif choice == 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def match_events(reference, predicted, tolerance=.05, *, require_role=True):
    _tolerance(tolerance)
    refs, preds = _events(reference), _events(predicted)
    if not require_role:
        return _ordered_pairs(refs, preds, tolerance)
    result = []
    for role in sorted({event.role for event in refs} | {event.role for event in preds}):
        result.extend(_ordered_pairs(
            [event for event in refs if event.role == role],
            [event for event in preds if event.role == role], tolerance,
        ))
    return sorted(result, key=lambda pair: (pair["reference_time"], pair["reference_id"]))


def _counts(reference, predicted, matched):
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    return {
        "reference": reference, "predicted": predicted, "matched": matched,
        "false_positives": predicted - matched, "false_negatives": reference - matched,
        "precision": precision, "recall": recall,
        "f1": 2 * matched / (reference + predicted) if reference + predicted else 0.0,
    }


def edit_cost_proxy(reference, predicted, association_tolerance=.05, move_tolerance=.005):
    """Minimize unit edit operations on a bounded, unrestricted bipartite graph.

    Insert/delete cost one each; a role change costs one; moving farther than
    move_tolerance costs one. Pairing is allowed only inside the association
    window. This is not measured human effort or an unrestricted edit distance.
    Velocity is not scored: the DSP arms do not estimate MIDI dynamics.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    _tolerance(association_tolerance)
    _tolerance(move_tolerance)
    refs, preds = _events(reference), _events(predicted)
    n, m = len(refs), len(preds)
    if (n + m) ** 2 > MAX_PAIR_CELLS:
        raise ValueError("edit assignment cell budget exceeded")
    pairs = []
    if n and m:
        # Integer scaling makes operation count strictly primary. A secondary
        # one-unit reward prefers associations over tied delete+insert plans.
        scale = min(n, m) + 1
        impossible = (2 * (n + m) + 1) * scale
        matrix = np.full((n + m, n + m), impossible, dtype=np.int64)
        for i, pred in enumerate(preds):
            matrix[i, n + i] = scale  # Delete this prediction.
            for j, ref in enumerate(refs):
                delta = abs(pred.time - ref.time)
                if delta <= association_tolerance + TIME_EPSILON:
                    cost = int(pred.role != ref.role) + int(delta > move_tolerance + TIME_EPSILON)
                    matrix[i, j] = cost * scale - 1
        for j in range(n):
            matrix[m + j, j] = scale  # Insert this reference.
        matrix[m:, n:] = 0  # Unused insertion/deletion placeholders.
        rows, columns = linear_sum_assignment(matrix)
        if any(matrix[row, column] == impossible for row, column in zip(rows, columns)):
            raise ValueError("edit assignment used an impossible edge")
        pairs = [_pair(refs[column], preds[row]) for row, column in zip(rows, columns)
                 if row < m and column < n]
        pairs.sort(key=lambda pair: (pair["reference_time"], pair["reference_id"]))
    ref_ids = {pair["reference_id"] for pair in pairs}
    pred_ids = {pair["predicted_id"] for pair in pairs}
    inserted = [event.event_id for event in refs if event.event_id not in ref_ids]
    deleted = [event.event_id for event in preds if event.event_id not in pred_ids]
    reclassified = sum(pair["reference_role"] != pair["predicted_role"] for pair in pairs)
    moved = sum(pair["absolute_error_seconds"] > move_tolerance + TIME_EPSILON for pair in pairs)
    cost = len(inserted) + len(deleted) + reclassified + moved
    return {
        "cost": cost, "normalized_cost": cost / max(1, n),
        "insertions": len(inserted), "deletions": len(deleted),
        "reclassifications": reclassified, "time_moves": moved,
        "association_tolerance_seconds": association_tolerance,
        "move_tolerance_seconds": move_tolerance, "matched_pairs": pairs,
        "temporal_endpoint_allowance_seconds": TIME_EPSILON,
        "inserted_reference_ids": inserted, "deleted_predicted_ids": deleted,
        "interpretation": "minimum unit operations within bounded association; not measured human time",
        "velocity_evaluated": False,
    }


def score_events(reference, predicted, tolerance=.05, move_tolerance=.005):
    refs, preds = _events(reference), _events(predicted)
    matched = match_events(refs, preds, tolerance)
    all_pairs = match_events(refs, preds, tolerance, require_role=False)
    ref_counts, pred_counts = Counter(event.role for event in refs), Counter(event.role for event in preds)
    role_matches = Counter(pair["reference_role"] for pair in matched)
    confusion = defaultdict(Counter)
    ambiguous = 0
    for pair in all_pairs:
        confusion[pair["reference_role"]][pair["predicted_role"]] += 1
        # Report timing ties rather than interpreting their arbitrary labels as
        # definitive class confusions in simultaneous-event groups.
        same_distance = sum(abs(event.time - pair["reference_time"]) ==
                            pair["absolute_error_seconds"] for event in preds)
        ambiguous += same_distance > 1
    result = _counts(len(refs), len(preds), len(matched))
    result.update({
        "tolerance_seconds": tolerance,
        "temporal_endpoint_allowance_seconds": TIME_EPSILON,
        "per_role": {role: _counts(ref_counts[role], pred_counts[role], role_matches[role])
                     for role in sorted(set(ref_counts) | set(pred_counts))},
        "matched_pairs": matched,
        "onset_mae_seconds": (sum(pair["absolute_error_seconds"] for pair in matched) /
                              len(matched)) if matched else None,
        "onset_signed_mean_seconds": (sum(pair["error_seconds"] for pair in matched) /
                                      len(matched)) if matched else None,
        "class_agnostic": {
            **_counts(len(refs), len(preds), len(all_pairs)), "matched_pairs": all_pairs,
            "confusion": {role: dict(sorted(counts.items())) for role, counts in sorted(confusion.items())},
            "timing_tied_pairs": ambiguous,
            "tie_policy": "time/ID order only; simultaneous confusion ties are not definitive",
        },
        # Keep one correction definition across both primary/strict F1 views.
        "edit_proxy": edit_cost_proxy(refs, preds, .05, move_tolerance),
    })
    return result


def recovery_diagnostics(reference, predicted, tolerance=.01, *, simultaneous_tolerance=.005,
                         gap_tolerance=.01, flam_max_gap=.09):
    """Require distinct, strictly matched events for pair recovery diagnostics."""
    for value in (tolerance, simultaneous_tolerance, gap_tolerance, flam_max_gap):
        _tolerance(value)
    refs, preds = _events(reference), _events(predicted)
    matched = {pair["reference_id"]: pair for pair in match_events(refs, preds, tolerance)}
    groups = []
    for event in refs:
        if not groups or event.time - groups[-1][0].time > simultaneous_tolerance + TIME_EPSILON:
            groups.append([event])
        else:
            groups[-1].append(event)
    simultaneous = []
    for group in groups:
        if len({event.role for event in group}) < 2:
            continue
        pairs = [matched.get(event.event_id) for event in group]
        complete = all(pair is not None for pair in pairs)
        gaps_preserved = complete and all(
            abs((pairs[j]["predicted_time"] - pairs[i]["predicted_time"]) -
                (group[j].time - group[i].time)) <= gap_tolerance + TIME_EPSILON
            for i in range(len(group)) for j in range(i + 1, len(group))
        )
        simultaneous.append({
            "reference_ids": [event.event_id for event in group],
            "predicted_ids": [pair["predicted_id"] if pair is not None else None for pair in pairs],
            "all_matched": complete, "gaps_preserved": gaps_preserved,
        })
    flams = []
    for role in sorted({event.role for event in refs}):
        lane = [event for event in refs if event.role == role]
        for left, right in zip(lane, lane[1:]):
            gap = right.time - left.time
            if not 0 < gap <= flam_max_gap + TIME_EPSILON:
                continue
            a, b = matched.get(left.event_id), matched.get(right.event_id)
            complete = a is not None and b is not None
            predicted_gap = b["predicted_time"] - a["predicted_time"] if complete else None
            recovered = (complete and predicted_gap > 0
                         and abs(predicted_gap - gap) <= gap_tolerance + TIME_EPSILON)
            flams.append({
                "reference_ids": [left.event_id, right.event_id],
                "predicted_ids": [a["predicted_id"] if a else None, b["predicted_id"] if b else None],
                "role": role, "reference_gap_seconds": gap, "predicted_gap_seconds": predicted_gap,
                "both_matched": complete, "recovered": recovered,
            })
    return {
        "onset_tolerance_seconds": tolerance,
        "temporal_endpoint_allowance_seconds": TIME_EPSILON,
        "simultaneous_tolerance_seconds": simultaneous_tolerance,
        "gap_tolerance_seconds": gap_tolerance, "flam_max_gap_seconds": flam_max_gap,
        "simultaneous": {
            "groups": len(simultaneous),
            "matched_groups": sum(row["all_matched"] for row in simultaneous),
            "timing_preserved_groups": sum(row["gaps_preserved"] for row in simultaneous),
            "details": simultaneous,
        },
        "flam": {"pairs": len(flams), "recovered_pairs": sum(row["recovered"] for row in flams),
                 "details": flams},
    }
