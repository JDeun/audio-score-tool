"""Fixed repeat hypotheses inside the frozen local-phase candidate budget.

The imported estimator is unchanged. Repetition is a soft structural prior,
not an observed score label: matching coarse pitch inventories can describe
different written rhythms. Original attacks and baseline decisions are kept.
Complete paths are enumerated, including nonadjacent repeat links, for at most
eight four-quarter blocks. Candidate masks describe joint paths, not Cartesian
products of marginal event choices.
"""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from itertools import product
from typing import NamedTuple, Sequence

from scripts.same_score_phase import (
    EPSILON,
    MARGIN_Q2,
    OnsetEvent,
    canonical_fingerprint,
    fingerprint,
)
from scripts.same_score_phase import (
    infer_performance as _baseline_infer,
)

BASE_METHODS = ("straight_narrow", "global_phase", "local_switch005")
REPEAT_METHODS = ("repeat_soft0025", "repeat_soft010", "repeat_hard")
METHODS = BASE_METHODS + REPEAT_METHODS
ARMS = METHODS
SWITCH_COST_Q2 = .0025
RESIDUAL_GATE_Q = .08
MAX_BLOCKS = 8
SETTINGS = {
    "primary_method": "repeat_soft010", "maximum_four_quarter_blocks": MAX_BLOCKS,
    "switch_cost_q2": SWITCH_COST_Q2, "residual_gate_q": RESIDUAL_GATE_Q,
    "soft_repeat_costs_q2": [.0025, .01], "hard_repeat_epsilon": EPSILON,
    "phase_margin_q2_per_event": MARGIN_Q2, "numeric_epsilon": EPSILON,
    "minimum_block_attacks": 4, "minimum_populated_quarters": 2,
    "link_rule": "previous eligible occurrence of exact relative-quarter/pitch count skeleton",
    "coarse_quarter_rule": "all four phase nearest candidates agree, within original observed block",
    "nearest_tie_rule": "any nearest tie in any phase excludes the whole block from repeat links",
    "same_pitch_order_rule": "onsets within numeric epsilon exclude the whole block from repeat links",
    "repeat_cost": "mean relative canonical tick disagreement per linked block pair, summed over links",
    "original_local_candidate_budget_preserved": True,
    "full_gate_recenters_budget": False,
    "repeat_hypothesis_is_verified_written_repetition": False,
}


class _Path(NamedTuple):
    index: int
    phases: tuple[int, ...]
    base_cost_q2: float
    repeat_cost: float
    residual_ok: bool


def path_from_index(index: int, block_count: int) -> tuple[int, ...]:
    """Decode the base-four lexicographic index used by every private mask."""
    if (type(block_count) is not int or not 1 <= block_count <= MAX_BLOCKS
            or type(index) is not int or not 0 <= index < 4 ** block_count):
        raise ValueError("invalid path index or block count")
    phases = [0] * block_count
    for b in range(block_count - 1, -1, -1):
        index, phases[b] = divmod(index, 4)
    return tuple(phases)


def _block_skeleton(events, fits, block):
    indices, b = block["event_indices"], block["index"]
    if block["end_q"] - block["start_q"] != 4.:
        return None, "partial_block"
    if len(indices) < 4:
        return None, "too_few_attacks"
    if any(len(fit["assignments"][i]["alternatives"]) != 1 for fit in fits for i in indices):
        return None, "nearest_tie"
    by_pitch = defaultdict(list)
    for i in indices:
        by_pitch[events[i].pitch].append(events[i].onset_q)
    for values in by_pitch.values():
        values.sort()
        if any(right - left <= EPSILON for left, right in zip(values, values[1:])):
            return None, "indistinct_same_pitch_onsets"
    groups = defaultdict(list)
    for i in indices:
        quarters = {fit["assignments"][i]["alternatives"][0] // 12 - 4 * b for fit in fits}
        if len(quarters) != 1:
            return None, "coarse_quarter_disagreement"
        quarter = quarters.pop()
        if not 0 <= quarter < 4:
            return None, "canonical_outside_observed_block"
        groups[quarter, events[i].pitch].append(i)
    if len({q for q, _ in groups}) < 2:
        return None, "too_few_populated_quarters"
    return {key: sorted(values, key=lambda i: events[i].onset_q)
            for key, values in sorted(groups.items())}, "eligible"


def _repeat_context(events, baseline):
    fits, blocks = baseline["fits"], baseline["blocks"]
    previous, groups_by_block, eligibility, links = {}, {}, [], []
    for block in blocks:
        b = block["index"]
        groups, reason = _block_skeleton(events, fits, block)
        row = {"block_index": b, "eligible": groups is not None, "reason": reason,
               "event_count": len(block["event_indices"]), "skeleton_fingerprint": None}
        if groups is not None:
            skeleton = tuple((quarter, pitch, len(values)) for (quarter, pitch), values in groups.items())
            row["skeleton_fingerprint"] = fingerprint(skeleton)
            groups_by_block[b] = groups
            if skeleton in previous:
                left = previous[skeleton]
                pairs = [[i, j] for key in groups
                         for i, j in zip(groups_by_block[left][key], groups[key], strict=True)]
                matrix = []
                for s in range(4):
                    values = []
                    for t in range(4):
                        mismatches = sum(fits[s]["assignments"][i]["tick"] - 48 * left
                                         != fits[t]["assignments"][j]["tick"] - 48 * b for i, j in pairs)
                        values.append(mismatches / len(pairs))
                    matrix.append(values)
                links.append({"left_block": left, "right_block": b,
                              "event_index_pairs": pairs, "cost_matrix": matrix})
            previous[skeleton] = b
        eligibility.append(row)
    linked_events = {i for link in links for pair in link["event_index_pairs"] for i in pair}
    return {"block_count": len(blocks), "eligible_block_count": sum(r["eligible"] for r in eligibility),
            "eligibility_reason_counts": dict(Counter(r["reason"] for r in eligibility)),
            "link_count": len(links), "linked_event_pair_count": sum(len(x["event_index_pairs"]) for x in links),
            "distinct_linked_event_count": len(linked_events),
            "unlinked_event_count": len(events) - len(linked_events),
            "eligibility": eligibility, "links": links,
            "graph_fingerprint": fingerprint({"eligibility": eligibility, "links": links})}


def _enumerate_paths(blocks, links):
    records = []
    for index, phases in enumerate(product(range(4), repeat=len(blocks))):
        cost = blocks[0]["sse_q2"][phases[0]]
        for b in range(1, len(blocks)):
            cost = cost + (SWITCH_COST_Q2 if phases[b] != phases[b - 1] else 0.) + blocks[b]["sse_q2"][phases[b]]
        repeat = math.fsum(link["cost_matrix"][phases[link["left_block"]]][phases[link["right_block"]]]
                           for link in links)
        valid = all(blocks[b]["max_abs_residual_q"][s] <= RESIDUAL_GATE_Q + EPSILON
                    for b, s in enumerate(phases))
        records.append(_Path(index, phases, cost, repeat, valid))
    return records


def _select_paths(pool, mode, weight, count):
    if not pool:
        raise ValueError("original local budget has no enumerated path")
    if mode == "hard":
        minimum = min(p.repeat_cost for p in pool)
        selected = [p for p in pool if p.repeat_cost <= minimum + EPSILON]
        return selected, {"selection_cost_unit": "mean canonical disagreement summed over links",
                          "selection_best_cost": minimum, "selection_budget": minimum + EPSILON,
                          "repeat_weight_q2": None}
    values = [(p.base_cost_q2 + weight * p.repeat_cost, p.index) for p in pool]
    best = min(value for value, _ in values)
    budget = best + count * (MARGIN_Q2 + EPSILON)
    selected = [p for p, (value, _) in zip(pool, values, strict=True) if value <= budget]
    return selected, {"selection_cost_unit": "quarter_squared",
                      "selection_best_cost": best, "selection_budget": budget,
                      "repeat_weight_q2": weight}


def _mask(records):
    result = 0
    for record in records:
        result |= 1 << record.index
    return format(result, "x")


def _states(records, size):
    return [sorted({p.phases[b] for p in records}) for b in range(size)]


def _path_summary(diagnostic, full, size, *, base_best, base_budget, selection):
    weight = selection["repeat_weight_q2"]

    def ordered(p):
        if selection["selection_cost_unit"] == "mean canonical disagreement summed over links":
            return p.repeat_cost, p.base_cost_q2, p.index
        return p.base_cost_q2 + (weight or 0.) * p.repeat_cost, p.index

    best = min(diagnostic, key=ordered)
    full_best = min(full, key=ordered) if full else None
    return {"diagnostic_mask_hex": _mask(diagnostic), "full_mask_hex": _mask(full),
            "diagnostic_path_count": len(diagnostic), "full_path_count": len(full),
            "diagnostic_retained_states": _states(diagnostic, size), "full_retained_states": _states(full, size),
            "base_best_cost_q2": base_best, "base_budget_q2": base_budget,
            "minimum_repeat_cost": min(p.repeat_cost for p in diagnostic),
            "best_phase_indices": list(best.phases),
            "full_best_phase_indices": list(full_best.phases) if full_best is not None else None,
            **selection}


def _repeat_decisions(events, baseline, diagnostic, full):
    fits, membership = baseline["fits"], baseline["event_block_indices"]
    size = len(baseline["blocks"])
    diagnostic_states, full_states = _states(diagnostic, size), _states(full, size)
    decisions, candidates = [], []
    for i, event in enumerate(events):
        b = membership[i]
        ticks = sorted({tick for s in diagnostic_states[b]
                        if fits[s]["assignments"][i]["abs_residual_q"] <= RESIDUAL_GATE_Q + EPSILON
                        for tick in fits[s]["assignments"][i]["alternatives"]})
        decisions.append({"event_id": event.event_id, "pitch": event.pitch, "candidate_ticks": ticks,
                          "selected_tick": ticks[0] if len(ticks) == 1 else None,
                          "status": "decided" if len(ticks) == 1 else "ambiguous" if ticks else "residual_rejected",
                          "collision": False})
        candidates.append({"event_id": event.event_id, "pitch": event.pitch,
                           "candidate_ticks": sorted({tick for s in full_states[b]
                                                       for tick in fits[s]["assignments"][i]["alternatives"]})})
    counts = Counter((a["pitch"], a["selected_tick"]) for a in decisions if a["selected_tick"] is not None)
    for a in decisions:
        a["collision"] = a["selected_tick"] is not None and counts[a["pitch"], a["selected_tick"]] > 1
    chosen = None
    if not full:
        status = "residual_rejected"
    elif any(len(a["candidate_ticks"]) != 1 for a in candidates):
        status = "ambiguous"
    else:
        proposed = [{"event_id": a["event_id"], "pitch": a["pitch"], "tick": a["candidate_ticks"][0]} for a in candidates]
        status = "decided" if len({(a["pitch"], a["tick"]) for a in proposed}) == len(proposed) else "collision"
        if status == "decided":
            chosen = proposed
    return {"diagnostic_assignments": decisions, "diagnostic_collision_count": sum(v - 1 for v in counts.values()),
            "full_candidate_assignments": candidates, "full_selected_assignments": chosen,
            "full_selected_fingerprint": canonical_fingerprint((a["pitch"], a["tick"]) for a in chosen)
            if chosen is not None else None, "full_status": status}


def infer_repeated_performance(events: Sequence[OnsetEvent], length_q: float) -> dict:
    if (type(length_q) not in (int, float) or not math.isfinite(length_q)
            or not 0 < length_q <= 4 * MAX_BLOCKS):
        raise ValueError("the exact repeat model requires a positive finite span of at most 32 quarters")
    values = tuple(events)
    baseline = _baseline_infer(values, length_q)
    original_fingerprint = fingerprint(baseline)
    context = _repeat_context(values, baseline)
    records = _enumerate_paths(baseline["blocks"], context["links"])
    arms = {method: copy.deepcopy(baseline["arms"][method]) for method in BASE_METHODS}
    path_sets = {}
    for method in BASE_METHODS:
        graph = baseline["arms"][method]["diagnostic_graph"]
        diagnostic = [p for p in records if p.base_cost_q2 <= graph["budget_sse_q2"]
                      and (method == "local_switch005" or len(set(p.phases)) == 1)
                      and (method != "straight_narrow" or p.phases[0] == 0)]
        full = [p for p in diagnostic if p.residual_ok]
        selection = {"selection_cost_unit": "quarter_squared", "repeat_weight_q2": 0.,
                     "selection_best_cost": graph["best_sse_q2"], "selection_budget": graph["budget_sse_q2"]}
        path_sets[method] = _path_summary(diagnostic, full, len(baseline["blocks"]),
                                        base_best=graph["best_sse_q2"], base_budget=graph["budget_sse_q2"], selection=selection)
    local = baseline["arms"]["local_switch005"]["diagnostic_graph"]
    pool = [p for p in records if p.base_cost_q2 <= local["budget_sse_q2"]]
    for method, mode, weight in (("repeat_soft0025", "soft", .0025), ("repeat_soft010", "soft", .01),
                                 ("repeat_hard", "hard", None)):
        diagnostic, selection = _select_paths(pool, mode, weight, len(values))
        full = [p for p in diagnostic if p.residual_ok]
        chosen = _repeat_decisions(values, baseline, diagnostic, full)
        if not context["links"]:
            # Preserve exact old decisions even at numerical membership boundaries.
            chosen = {key: copy.deepcopy(baseline["arms"]["local_switch005"][key]) for key in chosen}
        arms[method] = chosen
        path_sets[method] = _path_summary(diagnostic, full, len(baseline["blocks"]),
                                        base_best=local["best_sse_q2"], base_budget=local["budget_sse_q2"], selection=selection)
    return {"baseline_prediction_content_fingerprint": original_fingerprint,
            "baseline_arm_content_fingerprints": {m: fingerprint(baseline["arms"][m]) for m in BASE_METHODS},
            "fits": baseline["fits"], "blocks": baseline["blocks"], "event_block_indices": baseline["event_block_indices"],
            "repeat_context": context, "arms": arms, "path_sets": path_sets,
            "path_mask_encoding": {"radix": 4, "block_count": len(baseline["blocks"]),
                                   "total_indices": len(records), "bit_zero": "all phases zero",
                                   "hex_format": "no prefix or padding; bit i denotes base-four lexicographic path i"}}
