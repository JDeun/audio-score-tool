"""Independent small contract examples; no authored corpus or GMD study run."""

import inspect
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from scripts.performed_rhythm_invariance import (
    KIT_PITCHES,
    METHODS,
    PHASES,
    Event,
    canonical_fingerprint,
    fingerprint,
    infer_take,
)


def event(identity="a", instrument=0, onset=0.0, velocity=100):
    return Event(identity, instrument, onset, velocity)


def test_public_contract_is_label_and_reference_free():
    assert tuple(inspect.signature(infer_take).parameters) == ("events", "length_q")
    assert KIT_PITCHES == (36, 38, 42, 43, 46, 47, 49, 50, 51)
    assert PHASES == ((1, 2), (3, 5), (2, 3), (3, 4))
    with pytest.raises(FrozenInstanceError):
        event().velocity = 50


def test_straight_onset_inventory_and_concurrent_instruments():
    observations = (event("hat", 2, 0.5), event("kick", 0, 0), event("snare", 1, 0.5))
    before = fingerprint([asdict(x) for x in observations])
    result = infer_take(observations, 4)
    fit = result["fits"][0]
    assert fit["phase"] == [1, 2]
    assert [a["event_id"] for a in fit["assignments"]] == ["hat", "kick", "snare"]
    assert [a["tick"] for a in fit["assignments"]] == [6, 0, 6]
    assert fit["tie_count"] == fit["collision_count"] == 0
    assert fit["mse_q2"] == fit["max_abs_residual_q"] == 0
    assert result["arms"]["straight_narrow"]["status"] == "decided"
    assert fingerprint([asdict(x) for x in observations]) == before
    assert set(result["arms"]) == set(METHODS)
    json.dumps(result, allow_nan=False)


def test_profile_counts_all_hits_and_folds_only_the_profile_at_bar_edges():
    observations = (event("a", 2, 0), event("b", 2, 4), event("c", 0, 4.5))
    fit = infer_take(observations, 8)["fits"][0]
    assert len(fit["profile"]) == 9
    assert all(len(row) == 48 for row in fit["profile"])
    assert sum(map(sum, fit["profile"])) == 3
    assert fit["profile"][2][0] == 2
    assert fit["profile"][0][6] == 1
    assert [a["tick"] for a in fit["assignments"]] == [0, 48, 54]
    assert fit["collision_count"] == 0


def test_fingerprint_is_multiset_of_instrument_and_full_tick_only():
    assert canonical_fingerprint([(0, 6), (2, 0)]) == canonical_fingerprint([(2, 0), (0, 6)])
    assert canonical_fingerprint([(0, 6)]) != canonical_fingerprint([(0, 6), (0, 6)])
    assert canonical_fingerprint([(0, 0)]) != canonical_fingerprint([(0, 48)])
    assert canonical_fingerprint([(0, 6)]) != canonical_fingerprint([(1, 6)])
    assert canonical_fingerprint([(0, 6)]) == fingerprint([[0, 6]])


def test_velocity_and_source_ids_cannot_change_selection_or_cost():
    observations = (event("a", 0, 0.01), event("b", 2, 0.61))
    altered = tuple(replace(e, event_id=str(i), velocity=1 + i) for i, e in enumerate(observations))
    first, second = infer_take(observations, 4), infer_take(altered, 4)
    assert first["arms"] == second["arms"]
    for a, b in zip(first["fits"], second["fits"]):
        assert {k: v for k, v in a.items() if k != "assignments"} == {
            k: v for k, v in b.items() if k != "assignments"}
        assert [x["tick"] for x in a["assignments"]] == [x["tick"] for x in b["assignments"]]


def test_wide_tolerance_changes_acceptance_not_the_straight_mapping():
    result = infer_take((event(onset=0.11),), 4)
    narrow, wide = result["arms"]["straight_narrow"], result["arms"]["straight_wide"]
    assert narrow["status"] == "residual_rejected"
    assert narrow["retained_fit_indices"] == []
    assert narrow["diagnostic_fit_indices"] == wide["diagnostic_fit_indices"] == [0]
    assert wide["status"] == "decided"
    assert wide["selected_fingerprint"] == result["fits"][0]["canonical_fingerprint"]
    assert result["fits"][0]["assignments"][0]["tick"] == 0


def test_known_three_fifths_phase_is_recovered_without_a_phase_input():
    result = infer_take((event("a", 0, 0), event("b", 2, 0.6), event("c", 0, 1)), 4)
    fit = result["fits"][1]
    assert fit["phase"] == [3, 5]
    assert fit["mse_q2"] == fit["max_abs_residual_q"] == 0
    assert [a["tick"] for a in fit["assignments"]] == [0, 6, 12]
    arm = result["arms"]["phase_aware"]
    assert arm["retained_fit_indices"] == [1]
    assert arm["selected_fingerprint"] == canonical_fingerprint([(0, 0), (2, 6), (0, 12)])


def test_identical_swing_and_written_triplet_cannot_be_decided_by_timing():
    result = infer_take((event("a", 2, 0), event("b", 2, 2 / 3)), 4)
    arm = result["arms"]["phase_aware"]
    assert result["fits"][0]["assignments"][1]["tick"] == 8
    assert result["fits"][2]["assignments"][1]["tick"] == 6
    assert result["fits"][0]["mse_q2"] == result["fits"][2]["mse_q2"] == 0
    assert 0 in arm["retained_fit_indices"] and 2 in arm["retained_fit_indices"]
    assert len(arm["candidate_fingerprints"]) >= 2
    assert arm["status"] == "ambiguous" and arm["selected_fingerprint"] is None


def test_equal_phases_with_the_same_canonical_score_are_deduplicated():
    result = infer_take((event("a", 0, 0), event("b", 1, 1)), 4)
    arm = result["arms"]["phase_aware"]
    assert arm["retained_fit_indices"] == [0, 1, 2, 3]
    assert len(arm["candidate_fingerprints"]) == 1
    assert arm["status"] == "decided"


def test_exact_nearest_tie_keeps_per_hit_alternatives_and_abstains():
    result = infer_take((event(onset=0.125),), 4)
    fit = result["fits"][0]
    assert fit["assignments"] == [{"event_id": "a", "instrument": 0,
                                   "tick": 0, "alternatives": [0, 3]}]
    assert fit["tie_count"] == 1
    arm = result["arms"]["straight_wide"]
    assert len(arm["candidate_fingerprints"]) == 1
    assert arm["status"] == "nearest_tie"
    assert arm["selected_fingerprint"] is None
    assert not arm["candidate_fingerprints_exhaustive"]


def test_numerical_tie_guard_cannot_force_a_near_midpoint_decision():
    fit = infer_take((event(onset=0.125 + 1e-14),), 4)["fits"][0]
    assert fit["assignments"][0]["alternatives"] == [0, 3]
    distinct = infer_take((event(onset=0.125 + 1e-6),), 4)["fits"][0]
    assert distinct["assignments"][0]["alternatives"] == [3]


def test_same_instrument_collision_preserves_hits_and_blocks_decision():
    observations = (event("a", 0, 0), event("b", 0, 0.01), event("c", 0, 0.01))
    result = infer_take(observations, 4)
    for fit in result["fits"]:
        assert fit["collision_count"] == 2
        assert len(fit["assignments"]) == sum(map(sum, fit["profile"])) == 3
    for arm in result["arms"].values():
        assert arm["status"] == "collision"
        assert arm["selected_fingerprint"] is None
        assert arm["retained_fit_indices"]


def test_boundary_microtiming_is_kept_while_score_positions_stay_in_span():
    observations = (event("a", 0, -0.01), event("b", 1, 1.01))
    result = infer_take(observations, 1)
    assert observations[0].onset_q == -0.01 and observations[1].onset_q == 1.01
    for fit in result["fits"]:
        assert all(0 <= a["tick"] < 12 for a in fit["assignments"])
    assert [a["tick"] for a in result["fits"][0]["assignments"]] == [0, 9]


def test_partial_length_excludes_endpoint_without_inventing_padding():
    fit = infer_take((event(onset=0.5),), 0.5)["fits"][0]
    assert fit["assignments"][0]["tick"] == 4
    assert all(t < 6 for a in fit["assignments"] for t in a["alternatives"])


def test_reported_residual_cost_uses_all_hits_in_quarter_units():
    fit = infer_take((event("a", 0, 0.01), event("b", 1, 0.48)), 4)["fits"][0]
    assert fit["mse_q2"] == pytest.approx((0.01**2 + 0.02**2) / 2)
    assert fit["max_abs_residual_q"] == pytest.approx(0.02)


@pytest.mark.parametrize("phase_index,warped", [
    (0, (0, 1 / 4, 1 / 3, 1 / 2, 2 / 3, 3 / 4)),
    (1, (0, 3 / 10, 2 / 5, 3 / 5, 11 / 15, 4 / 5)),
    (2, (0, 1 / 3, 4 / 9, 2 / 3, 7 / 9, 5 / 6)),
    (3, (0, 3 / 8, 1 / 2, 3 / 4, 5 / 6, 7 / 8)),
])
def test_declared_phase_map_transforms_thirds_as_well_as_binary_positions(phase_index, warped):
    observations = tuple(event(str(i), i % 3, value) for i, value in enumerate(warped))
    fit = infer_take(observations, 1)["fits"][phase_index]
    assert [a["tick"] for a in fit["assignments"]] == [0, 3, 4, 6, 8, 9]
    assert fit["mse_q2"] == 0


def test_phase_diagnostics_survive_residual_rejection():
    result = infer_take((event(onset=-0.15),), 4)
    arm = result["arms"]["phase_aware"]
    assert arm["status"] == "residual_rejected"
    assert arm["diagnostic_fit_indices"] == [0, 1, 2, 3]
    assert arm["retained_fit_indices"] == []
    assert arm["selected_fingerprint"] is None
    assert all(sum(map(sum, f["profile"])) == 1 for f in result["fits"])


def test_nonrepresentable_loss_fails_instead_of_returning_nonfinite_json():
    with pytest.raises(ValueError, match="finite arithmetic"):
        infer_take((event(onset=1e200),), 4)


@pytest.mark.parametrize("length", [0, -1, math.inf, math.nan, True, "4"])
def test_bad_length_rejected(length):
    with pytest.raises(ValueError):
        infer_take((event(),), length)


@pytest.mark.parametrize("change", [
    {"event_id": ""}, {"event_id": " "}, {"event_id": 2},
    {"instrument": -1}, {"instrument": 9}, {"instrument": True},
    {"onset_q": math.nan}, {"onset_q": math.inf}, {"onset_q": True},
    {"velocity": 0}, {"velocity": 128}, {"velocity": 1.5}, {"velocity": True},
])
def test_bad_event_rejected(change):
    with pytest.raises(ValueError):
        infer_take((replace(event(), **change),), 4)


def test_empty_duplicate_and_non_event_inputs_rejected():
    for observations in ((), (event(), event()), (object(),)):
        with pytest.raises(ValueError):
            infer_take(observations, 4)


@pytest.mark.parametrize("pair", [(-1, 0), (9, 0), (0, -1), (True, 0), (0, 1.5)])
def test_invalid_canonical_pair_rejected(pair):
    with pytest.raises(ValueError):
        canonical_fingerprint([pair])
