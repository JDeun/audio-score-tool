"""Small independent contracts only; never execute a planned performance cohort."""

from __future__ import annotations

import inspect
import itertools
import json
import math
from collections import Counter
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from scripts.performed_rhythm_invariance import Event as LegacyEvent
from scripts.performed_rhythm_invariance import infer_take
from scripts.same_score_phase import (
    EPSILON,
    MARGIN_Q2,
    METHODS,
    PHASES,
    OnsetEvent,
    _graph,
    canonical_fingerprint,
    fingerprint,
    infer_performance,
)


def event(name="a", pitch=60, q=0.0, velocity=80):
    return OnsetEvent(name, pitch, q, velocity)


def test_api_has_no_target_voice_or_group_argument():
    assert tuple(inspect.signature(infer_performance).parameters) == ("events", "length_q")
    assert list(OnsetEvent.__dataclass_fields__) == ["event_id", "pitch", "onset_q", "velocity"]
    assert METHODS == ("straight_narrow", "straight_wide", "global_phase", "local_raw",
                       "local_switch005", "local_switch010")
    assert PHASES == ((1, 2), (3, 5), (2, 3), (3, 4))
    with pytest.raises(FrozenInstanceError):
        event().pitch = 61


@pytest.mark.parametrize("observations,length", [
    ((event("a", 0, 0), event("b", 2, .5), event("c", 1, 1.25)), 4),
    ((event("a", 0, -.01), event("b", 1, 3.99), event("c", 2, 4.01)), 8),
    ((event("a", 0, 0), event("b", 0, .01), event("c", 1, .01)), 4),
    ((event("a", 0, .125),), 4),
    ((event("a", 0, 0), event("b", 1, 2 / 3)), 8),
    ((event("a", 0, 0), event("b", 1, .6), event("c", 2, 4.6)), 8),
])
def test_unchanged_straight_and_global_math_matches_archived_small_inputs(observations, length):
    old = infer_take(tuple(LegacyEvent(e.event_id, e.pitch, e.onset_q, e.velocity)
                           for e in observations), length)
    new = infer_performance(observations, length)
    for previous, current in zip(old["fits"], new["fits"]):
        assert current["phase"] == previous["phase"]
        assert current["mse_q2"] == previous["mse_q2"]
        assert current["max_abs_residual_q"] == previous["max_abs_residual_q"]
        assert current["canonical_fingerprint"] == previous["canonical_fingerprint"]
        assert current["tie_count"] == previous["tie_count"]
        assert current["collision_count"] == previous["collision_count"]
        assert [(a["event_id"], a["pitch"], a["tick"], a["alternatives"])
                for a in current["assignments"]] == [
                    (a["event_id"], a["instrument"], a["tick"], a["alternatives"])
                    for a in previous["assignments"]]
    for before, after in (("straight_narrow", "straight_narrow"), ("straight_wide", "straight_wide"),
                          ("phase_aware", "global_phase")):
        assert new["arms"][after]["full_selected_fingerprint"] == old["arms"][before]["selected_fingerprint"]
    # New diagnostic event decisions are deliberately NOT the old whole-take gate.
    # Full abstention reason names combine nearest/path ambiguity rather than
    # preserving the old nearest_tie/collision precedence; decision parity holds.


def test_pitch_generalization_and_source_immutability():
    observations = (event("high", 127, .6), event("low", 0, 0), event("middle", 60, .6))
    before = fingerprint([asdict(e) for e in observations])
    result = infer_performance(observations, 8)
    assert set(result["arms"]) == set(METHODS)
    assert [a["event_id"] for a in result["fits"][0]["assignments"]] == ["high", "low", "middle"]
    assert all(len(f["assignments"]) == 3 for f in result["fits"])
    assert fingerprint([asdict(e) for e in observations]) == before
    json.dumps(result, allow_nan=False)


def test_ids_and_velocity_do_not_select_a_phase():
    observations = (event("one", 60, .6, 1), event("two", 72, 4.75, 127))
    altered = tuple(replace(e, event_id=f"opaque{i}", velocity=60) for i, e in enumerate(observations))
    original, changed = infer_performance(observations, 8), infer_performance(altered, 8)
    assert original["blocks"] == changed["blocks"]
    for method in METHODS:
        a, b = original["arms"][method], changed["arms"][method]
        assert a["diagnostic_graph"] == b["diagnostic_graph"]
        assert a["full_graph"] == b["full_graph"]
        assert a["full_selected_fingerprint"] == b["full_selected_fingerprint"]
        assert [x["candidate_ticks"] for x in a["diagnostic_assignments"]] == [
            x["candidate_ticks"] for x in b["diagnostic_assignments"]]


def _paths(costs, allowed, switch_cost):
    paths = []
    for path in itertools.product(*allowed):
        if switch_cost is None and len(set(path)) != 1:
            continue
        total = costs[0][path[0]]
        for b in range(1, len(costs)):
            total = total + (0.0 if path[b] == path[b - 1] else switch_cost) + costs[b][path[b]]
        paths.append((total, path))
    return paths


@pytest.mark.parametrize("penalty", [None, 0.0, .0025, .01])
def test_dp_and_all_min_marginals_match_exhaustive_small_state_graph(penalty):
    costs = [[.03, .01, .04, .05], [.04, .03, .01, .02], [.01, .02, .03, .04]]
    allowed = [[0, 1, 2], [0, 1, 2, 3], [0, 1, 2]]
    result = _graph(costs, allowed, penalty, count=10, budget=.065)
    paths = _paths(costs, allowed, penalty)
    assert result["best_sse_q2"] == pytest.approx(min(v for v, _ in paths), abs=1e-15)
    assert tuple(result["best_path"]) in [p for v, p in paths if v == min(x for x, _ in paths)]
    for block in range(3):
        for state in range(4):
            candidates = [v for v, p in paths if p[block] == state]
            minimum = min(candidates) if candidates else None
            if minimum is None:
                assert result["min_marginals_sse_q2"][block][state] is None
            else:
                assert result["min_marginals_sse_q2"][block][state] == pytest.approx(minimum, abs=1e-15)
            assert (state in result["retained_states"][block]) == (minimum is not None and minimum <= .065)


def test_full_gate_retains_all_paths_under_original_budget_not_only_new_best():
    costs = [[0, .00005, .000075, 1.0], [0, .00005, .000075, 1.0]]
    diagnostic = _graph(costs, [[0, 1, 2, 3]] * 2, None, 2)
    full = _graph(costs, [[1, 2], [1, 2]], None, 2, diagnostic["budget_sse_q2"])
    assert full["best_path"] == [1, 1]
    assert full["retained_states"] == [[1, 2], [1, 2]]
    assert full["budget_sse_q2"] == diagnostic["budget_sse_q2"]


def test_full_gate_does_not_recenter_budget_after_eliminating_best_phase():
    costs = [[0, .01, .02, .03], [0, .01, .02, .03]]
    diagnostic = _graph(costs, [[0, 1, 2, 3]] * 2, None, 2)
    full = _graph(costs, [[1], [1]], None, 2, diagnostic["budget_sse_q2"])
    assert full["best_sse_q2"] == .02
    assert full["retained_states"] == [[], []]
    impossible = _graph(costs, [[0], []], .0025, 2, diagnostic["budget_sse_q2"])
    assert impossible["best_path"] is None and impossible["best_sse_q2"] is None
    assert impossible["retained_states"] == [[], []]
    json.dumps(impossible, allow_nan=False)


def test_per_block_state_unions_are_not_a_cartesian_joint_candidate_set():
    costs = [[0, 0, 1, 1], [0, 0, 1, 1]]
    graph = _graph(costs, [[0, 1], [0, 1]], .01, 2)
    assert graph["retained_states"] == [[0, 1], [0, 1]]
    assert all(v > graph["budget_sse_q2"] for v, p in _paths(costs, [[0], [1]], .01))
    assert {p for v, p in _paths(costs, [[0, 1], [0, 1]], .01)
            if v <= graph["budget_sse_q2"]} == {(0, 0), (1, 1)}


def test_local_phase_and_switch_complexity_have_separate_effects():
    result = infer_performance((event("a", 60, .6), event("b", 72, 4.75)), 8)
    raw = result["arms"]["local_raw"]["diagnostic_graph"]
    smooth = result["arms"]["local_switch005"]["diagnostic_graph"]
    global_fit = result["arms"]["global_phase"]["diagnostic_graph"]
    assert raw["best_sse_q2"] == 0
    assert raw["best_path"][0] != raw["best_path"][1]
    assert smooth["best_sse_q2"] == global_fit["best_sse_q2"] > 0
    assert len(set(smooth["best_path"])) == 1
    assert raw["budget_sse_q2"] == pytest.approx(2 * (MARGIN_Q2 + EPSILON))


def test_a_bad_event_does_not_erase_other_diagnostic_decisions():
    result = infer_performance((event("a", 60, .01), event("b", 72, 1.11)), 4)
    narrow, wide = (result["arms"][m] for m in ("straight_narrow", "straight_wide"))
    assert [a["selected_tick"] for a in narrow["diagnostic_assignments"]] == [0, None]
    assert narrow["full_status"] == "residual_rejected"
    assert narrow["full_selected_fingerprint"] is None
    assert [a["selected_tick"] for a in wide["diagnostic_assignments"]] == [0, 12]
    assert wide["full_status"] == "decided"
    assert wide["full_selected_fingerprint"] == canonical_fingerprint([(60, 0), (72, 12)])


def test_same_pitch_collisions_are_reported_without_deleting_diagnostic_hits():
    observations = (event("a", 60, 0), event("b", 60, .01), event("c", 61, 0))
    arm = infer_performance(observations, 4)["arms"]["straight_narrow"]
    assert [a["selected_tick"] for a in arm["diagnostic_assignments"]] == [0, 0, 0]
    assert [a["collision"] for a in arm["diagnostic_assignments"]] == [True, True, False]
    assert arm["diagnostic_collision_count"] == 1
    assert arm["full_status"] == "collision" and arm["full_selected_assignments"] is None


def test_nearest_tie_and_observationally_identical_rhythms_stay_ambiguous():
    tied = infer_performance((event(q=.125),), 4)["arms"]["straight_wide"]
    assert tied["diagnostic_assignments"][0]["candidate_ticks"] == [0, 3]
    assert tied["diagnostic_assignments"][0]["selected_tick"] is None
    assert tied["full_selected_fingerprint"] is None
    observations = (event("a", 60, 0), event("b", 60, 2 / 3))
    result = infer_performance(observations, 4)
    for method in ("global_phase", "local_raw", "local_switch005", "local_switch010"):
        arm = result["arms"][method]
        assert arm["diagnostic_assignments"][1]["candidate_ticks"] == [6, 8]
        assert arm["full_status"] == "ambiguous"
        assert arm["full_selected_fingerprint"] is None


def test_empty_windows_add_no_false_score_ambiguity():
    result = infer_performance((event("a", 60, 0), event("b", 72, 8)), 12)
    assert result["blocks"][1]["event_indices"] == []
    assert result["blocks"][1]["sse_q2"] == [0, 0, 0, 0]
    for arm in result["arms"].values():
        assert arm["full_status"] == "decided"
        assert arm["full_selected_fingerprint"] == canonical_fingerprint([(60, 0), (72, 96)])


def test_observed_partition_preserves_early_late_and_boundary_events():
    observations = (event("a", 60, -.01), event("b", 61, 3.99),
                    event("c", 62, 4.01), event("d", 63, 8.01))
    result = infer_performance(observations, 8)
    assert result["event_block_indices"] == [0, 0, 1, 1]
    assert [a["tick"] for a in result["fits"][0]["assignments"]] == [0, 48, 48, 93]
    assert observations[0].onset_q == -.01 and observations[-1].onset_q == 8.01
    assert sorted(i for b in result["blocks"] for i in b["event_indices"]) == [0, 1, 2, 3]
    assert all(0 <= a["tick"] < 96 for f in result["fits"] for a in f["assignments"])


def test_no_grid_extension_or_hidden_score_padding():
    result = infer_performance((event(q=.125),), .5)
    assert all(t in (0, 3, 4) for f in result["fits"] for a in f["assignments"] for t in a["alternatives"])
    assert result["blocks"][0]["end_q"] == .5
    assert all(a["tick"] / 12 != .125 for f in result["fits"] for a in f["assignments"])


def test_hash_preserves_pitch_and_multiplicity_but_not_source_identity():
    assert canonical_fingerprint([(60, 6), (72, 0)]) == canonical_fingerprint([(72, 0), (60, 6)])
    assert canonical_fingerprint([(60, 6)]) != canonical_fingerprint([(60, 6), (60, 6)])
    assert canonical_fingerprint([(60, 6)]) != canonical_fingerprint([(61, 6)])
    result = infer_performance((event("a", 60, 0), event("b", 60, .01)), 4)
    assert all(sum(Counter((a["pitch"], a["tick"]) for a in f["assignments"]).values()) == 2
               for f in result["fits"])


@pytest.mark.parametrize("length", [0, -1, math.inf, math.nan, True, "8"])
def test_invalid_length_fails(length):
    with pytest.raises(ValueError):
        infer_performance((event(),), length)


@pytest.mark.parametrize("change", [
    {"event_id": ""}, {"event_id": 5}, {"pitch": -1}, {"pitch": 128}, {"pitch": True},
    {"onset_q": math.nan}, {"onset_q": math.inf}, {"onset_q": True},
    {"velocity": 0}, {"velocity": 128}, {"velocity": 1.5},
])
def test_invalid_observation_fails(change):
    with pytest.raises(ValueError):
        infer_performance((replace(event(), **change),), 8)


def test_empty_duplicate_and_nonrepresentable_cost_fail():
    for observations in ((), (event(), event()), (object(),), (event(q=1e200),)):
        with pytest.raises(ValueError):
            infer_performance(observations, 8)
