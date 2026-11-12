"""Invented contracts for repeat hypotheses, costs and joint-path preservation."""

from __future__ import annotations

import copy
import inspect
import json
import math
from dataclasses import asdict, replace
from itertools import product

import pytest

from scripts import repeat_context_phase as repeat
from scripts.same_score_phase import OnsetEvent, fingerprint, infer_performance


def block(index, offbeat=.61, *, pitch=60, prefix=None):
    prefix = str(index) if prefix is None else prefix
    return tuple(OnsetEvent(f"{prefix}-{i}", pitch + i % 2, index * 4. + q, 80)
                 for i, q in enumerate((.01, offbeat, 1.01, 1 + offbeat)))


def indices(encoded):
    mask = int(encoded, 16)
    result = []
    while mask:
        bit = mask & -mask
        result.append(bit.bit_length() - 1)
        mask ^= bit
    return result


def test_label_free_api_and_original_class():
    assert repeat.OnsetEvent is OnsetEvent
    assert list(inspect.signature(repeat.infer_repeated_performance).parameters) == ["events", "length_q"]
    assert repeat.METHODS == ("straight_narrow", "global_phase", "local_switch005",
                              "repeat_soft0025", "repeat_soft010", "repeat_hard")


def test_old_prediction_and_three_baselines_remain_exact():
    events = block(0) + block(1, .68)
    original = infer_performance(events, 8.)
    snapshot = copy.deepcopy(original)
    new = repeat.infer_repeated_performance(events, 8.)
    assert new["baseline_prediction_content_fingerprint"] == fingerprint(original)
    for field in ("fits", "blocks", "event_block_indices"):
        assert new[field] == original[field]
    for method in repeat.BASE_METHODS:
        assert new["arms"][method] == original["arms"][method]
        assert new["baseline_arm_content_fingerprints"][method] == fingerprint(original["arms"][method])
        summary = new["path_sets"][method]
        assert summary["diagnostic_retained_states"] == original["arms"][method]["diagnostic_graph"]["retained_states"]
        assert summary["full_retained_states"] == original["arms"][method]["full_graph"]["retained_states"]
    assert original == snapshot
    json.dumps(new, allow_nan=False)


def test_repeat_links_nearest_previous_nonadjacent_occurrence_only():
    events = block(0) + block(1, pitch=72) + block(2, .68) + block(3, .63)
    result = repeat.infer_repeated_performance(events, 16.)
    context = result["repeat_context"]
    assert context["eligible_block_count"] == 4
    assert [(e["left_block"], e["right_block"]) for e in context["links"]] == [(0, 2), (2, 3)]
    assert context["linked_event_pair_count"] == 8
    assert context["distinct_linked_event_count"] == 12
    assert context["unlinked_event_count"] == 4
    assert context["links"][0]["event_index_pairs"] == [[0, 8], [1, 9], [2, 10], [3, 11]]


def test_canonical_consistency_is_not_phase_equality():
    result = repeat.infer_repeated_performance(block(0) + block(1, .68), 8.)
    matrix = result["repeat_context"]["links"][0]["cost_matrix"]
    # Distinct phase hypotheses recover the same local tick sequence.
    assert matrix[1][2] == 0.
    # Four events are paired, and the two offbeats disagree under this pair.
    assert matrix[1][0] == .5
    assert all(0 <= value <= 1 for row in matrix for value in row)


@pytest.mark.parametrize("offbeat", [.5, 2 / 3])
def test_clean_observations_can_have_a_nearest_tie_in_another_phase(offbeat):
    result = repeat.infer_repeated_performance(block(0, offbeat) + block(1, offbeat), 8.)
    assert result["repeat_context"]["link_count"] == 0
    assert result["repeat_context"]["eligibility_reason_counts"] == {"nearest_tie": 2}


def test_repeat_admission_does_not_apply_the_whole_input_residual_gate_early():
    result = repeat.infer_repeated_performance(block(0, .2) + block(1, .2), 8.)
    assert result["repeat_context"]["link_count"] == 1
    assert any(f["max_abs_residual_q"] > .08 for f in result["fits"])
    assert result["repeat_context"]["eligible_block_count"] == 2


def test_ids_velocity_and_input_order_do_not_choose_repeat_hypotheses():
    events = block(0) + block(1, .68)
    altered = tuple(replace(e, event_id=f"opaque{i}", velocity=1 if i % 2 else 127)
                    for i, e in enumerate(events))
    a = repeat.infer_repeated_performance(events, 8.)
    b = repeat.infer_repeated_performance(altered, 8.)
    assert a["repeat_context"] == b["repeat_context"]
    assert a["path_sets"] == b["path_sets"]
    reversed_result = repeat.infer_repeated_performance(tuple(reversed(events)), 8.)
    for method in repeat.METHODS:
        assert a["path_sets"][method] == reversed_result["path_sets"][method]
        assert {x["event_id"]: x["candidate_ticks"] for x in a["arms"][method]["diagnostic_assignments"]} == {
            x["event_id"]: x["candidate_ticks"] for x in reversed_result["arms"][method]["diagnostic_assignments"]}


@pytest.mark.parametrize("kind,reason", [
    ("partial", "partial_block"), ("few", "too_few_attacks"),
    ("tie", "nearest_tie"), ("simultaneous", "indistinct_same_pitch_onsets"),
    ("boundary", "coarse_quarter_disagreement"),
    ("onequarter", "too_few_populated_quarters"),
    ("outside", "canonical_outside_observed_block"),
])
def test_ambiguous_or_insufficient_structure_excludes_link_not_attacks(kind, reason):
    events, length = list(block(0)), 4.
    if kind == "partial":
        length = 3.9
    elif kind == "few":
        events.pop()
    elif kind == "tie":
        events[1] = replace(events[1], onset_q=.125)
    elif kind == "simultaneous":
        events[2] = replace(events[2], onset_q=events[0].onset_q)
    elif kind == "boundary":
        events[1] = replace(events[1], onset_q=.91)
    elif kind == "onequarter":
        events = [OnsetEvent(str(i), 60 + i, .01, 80) for i in range(4)]
    elif kind == "outside":
        events = [replace(e, onset_q=e.onset_q + 4) for e in events]
        events[-1] = replace(events[-1], onset_q=8.01)
        length = 12.
    observations = tuple(events)
    before = fingerprint([asdict(e) for e in observations])
    result = repeat.infer_repeated_performance(observations, length)
    if kind == "outside":
        # Test the exact source-grammar exclusion without relying on a particular
        # nearest grid location near the next block boundary.
        baseline = infer_performance(block(0), 8.)
        shifted = copy.deepcopy(baseline["fits"])
        for fit in shifted:
            for assignment in fit["assignments"]:
                assignment["alternatives"] = [48]
        assert repeat._block_skeleton(block(0), shifted, baseline["blocks"][0])[1] == reason
    else:
        assert result["repeat_context"]["eligibility"][0]["reason"] == reason
    assert result["repeat_context"]["link_count"] == 0
    for arm in result["arms"].values():
        assert [a["event_id"] for a in arm["diagnostic_assignments"]] == [e.event_id for e in observations]
    assert fingerprint([asdict(e) for e in observations]) == before


@pytest.mark.parametrize("events,length", [
    ((OnsetEvent("negative", 60, -.01, 80), OnsetEvent("late", 64, 8.01, 70)), 8.),
    (block(0) + block(1, pitch=72), 8.),
    (block(0), 3.9),
])
def test_no_link_all_new_decisions_exactly_equal_old_local(events, length):
    old = infer_performance(events, length)
    result = repeat.infer_repeated_performance(events, length)
    assert result["repeat_context"]["link_count"] == 0
    for method in repeat.REPEAT_METHODS:
        for key, value in result["arms"][method].items():
            assert value == old["arms"]["local_switch005"][key]
        assert result["path_sets"][method]["diagnostic_mask_hex"] == result["path_sets"]["local_switch005"]["diagnostic_mask_hex"]
        assert result["path_sets"][method]["full_mask_hex"] == result["path_sets"]["local_switch005"]["full_mask_hex"]


def test_complete_paths_masks_and_costs_match_independent_small_enumeration():
    result = repeat.infer_repeated_performance(block(0) + block(1, .68) + block(2, .63), 12.)
    blocks, links = result["blocks"], result["repeat_context"]["links"]
    costs = {}
    for index, phases in enumerate(product(range(4), repeat=3)):
        residual = math.fsum(b["sse_q2"][s] for b, s in zip(blocks, phases))
        switches = sum(a != b for a, b in zip(phases, phases[1:]))
        regularizer = sum(link["cost_matrix"][phases[link["left_block"]]][phases[link["right_block"]]] for link in links)
        costs[index] = (residual + .0025 * switches, regularizer)
        assert repeat.path_from_index(index, 3) == phases
    budget = result["path_sets"]["local_switch005"]["base_budget_q2"]
    pool = {i for i, (base, _) in costs.items() if base <= budget}
    assert set(indices(result["path_sets"]["local_switch005"]["diagnostic_mask_hex"])) == pool
    for method, weight in (("repeat_soft0025", .0025), ("repeat_soft010", .01)):
        augmented = {i: costs[i][0] + weight * costs[i][1] for i in pool}
        threshold = min(augmented.values()) + len(block(0) + block(1) + block(2)) * (1e-4 + 1e-12)
        expected = {i for i, cost in augmented.items() if cost <= threshold}
        observed = set(indices(result["path_sets"][method]["diagnostic_mask_hex"]))
        assert observed == expected
        assert observed <= pool
    minimum = min(costs[i][1] for i in pool)
    hard = {i for i in pool if costs[i][1] <= minimum + 1e-12}
    assert set(indices(result["path_sets"]["repeat_hard"]["diagnostic_mask_hex"])) == hard


def test_prior_ranks_original_pool_and_full_gate_never_recenters():
    # Stronger repeat agreement belongs to a path that fails a different event's
    # residual gate. Gating first would wrongly promote the surviving path.
    pool = [repeat._Path(0, (0,), 0., 0., False),
            repeat._Path(1, (1,), .00005, .2, True)]
    for mode, weight in (("soft", .0025), ("soft", .01), ("hard", None)):
        selected, selection = repeat._select_paths(pool, mode, weight, 2)
        assert [p.index for p in selected] == [0]
        assert not [p for p in selected if p.residual_ok]
        assert selection["selection_best_cost"] == 0.
    selected, _ = repeat._select_paths(pool, "soft", 0., 2)
    assert selected == pool


def test_noncartesian_masks_keep_joint_constraints():
    records = [repeat._Path(0, (0, 0), 0., 0., True), repeat._Path(5, (1, 1), 0., 0., True)]
    encoded = repeat._mask(records)
    assert repeat._states(records, 2) == [[0, 1], [0, 1]]
    assert indices(encoded) == [0, 5]
    assert 1 not in indices(encoded) and 4 not in indices(encoded)
    assert repeat._mask([]) == "0"
    largest = repeat._Path(4 ** 8 - 1, (3,) * 8, 0., 0., True)
    assert repeat.path_from_index(largest.index, 8) == largest.phases
    assert indices(repeat._mask([largest])) == [largest.index]


def test_hard_prior_is_a_strong_lexicographic_control_not_a_score_label():
    pool = [repeat._Path(0, (0,), 0., .25, True), repeat._Path(1, (1,), .00015, 0., True)]
    soft, _ = repeat._select_paths(pool, "soft", .00001, 2)
    hard, _ = repeat._select_paths(pool, "hard", None, 2)
    assert len(soft) == 2 and [p.index for p in hard] == [1]
    # Equal observations must get equal predictions whatever written truth an
    # evaluation-only counterfactual attaches to them.
    observed = block(0) + block(1)
    assert fingerprint(repeat.infer_repeated_performance(observed, 8.)) == fingerprint(
        repeat.infer_repeated_performance(copy.deepcopy(observed), 8.))


@pytest.mark.parametrize("length", [0, -1, float("nan"), float("inf"), 32.01, True, "8"])
def test_invalid_or_excessive_span_fails_before_enumeration(length):
    with pytest.raises(ValueError):
        repeat.infer_repeated_performance(block(0), length)


@pytest.mark.parametrize("index,size", [(-1, 2), (16, 2), (0, 0), (0, 9), (True, 1)])
def test_invalid_path_indices_fail(index, size):
    with pytest.raises(ValueError):
        repeat.path_from_index(index, size)
