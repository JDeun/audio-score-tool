"""Owned event examples verify scoring without audio/model execution."""
from __future__ import annotations

import itertools

import pytest

from scripts.drum_event_metrics import (
    Event,
    edit_cost_proxy,
    match_events,
    recovery_diagnostics,
    score_events,
)


def _events(times, prefix, role="kick"):
    return [Event(f"{prefix}{i}", time, role) for i, time in enumerate(times)]


def test_maximum_cardinality_precedes_nearest_match():
    # A nearest-first matcher takes .05 for the first reference, then misses
    # the second. The valid maximum-cardinality assignment retains both.
    result = score_events(_events([.04, .08], "r"), _events([0, .05], "p"))
    assert result["matched"] == 2
    assert [(pair["reference_id"], pair["predicted_id"]) for pair in result["matched_pairs"]] == [
        ("r0", "p0"), ("r1", "p1"),
    ]
    assert result["onset_mae_seconds"] == pytest.approx(.035)


@pytest.mark.parametrize("reference,predicted,tolerance", [
    ([.04, .08], [0, .05], .05),
    ([0, .10], [.02, .09, .12], .05),
    ([.1, .1, .18], [.11, .15, .20], .05),
    ([0, .09, .18], [.04, .05, .13, .23], .05),
])
def test_matching_objective_agrees_with_exhaustive_small_assignment(reference, predicted, tolerance):
    oracle = None
    for count in range(min(len(reference), len(predicted)) + 1):
        for selected in itertools.combinations(range(len(reference)), count):
            for assigned in itertools.permutations(range(len(predicted)), count):
                distances = [abs(reference[i] - predicted[j]) for i, j in zip(selected, assigned)]
                if all(distance <= tolerance + 1e-12 for distance in distances):
                    objective = (count, -sum(distances))
                    if oracle is None or objective > oracle:
                        oracle = objective
    pairs = match_events(_events(reference, "r"), _events(predicted, "p"), tolerance)
    assert len(pairs) == oracle[0]
    assert sum(pair["absolute_error_seconds"] for pair in pairs) == pytest.approx(-oracle[1])


def test_duplicate_predictions_and_simultaneous_references_are_never_collapsed():
    result = score_events(_events([0], "r"), _events([0, 0], "p"))
    assert (result["matched"], result["false_positives"], result["false_negatives"]) == (1, 1, 0)
    refs = [Event("kick", 1., "kick"), Event("snare", 1., "backbeat")]
    result = score_events(refs, [Event("p", 1., "kick")])
    assert (result["reference"], result["matched"], result["false_negatives"]) == (2, 1, 1)
    assert result["per_role"]["backbeat"]["false_negatives"] == 1
    assert result["class_agnostic"]["matched"] == 1


def test_class_errors_are_false_positive_and_false_negative_with_separate_confusion():
    result = score_events([Event("r", 1., "hat_closed")], [Event("p", 1., "backbeat")])
    assert result["matched"] == 0
    assert result["false_negatives"] == result["false_positives"] == 1
    assert result["class_agnostic"]["confusion"] == {"hat_closed": {"backbeat": 1}}
    assert result["edit_proxy"]["cost"] == 1
    assert result["edit_proxy"]["reclassifications"] == 1


def test_edit_proxy_can_reorder_cross_class_associations():
    refs = [Event("r0", 0., "kick"), Event("r1", .02, "backbeat")]
    preds = [Event("p0", .02, "backbeat"), Event("p1", .03, "kick")]
    result = edit_cost_proxy(refs, preds)
    assert result["cost"] == result["time_moves"] == 1
    assert result["insertions"] == result["deletions"] == result["reclassifications"] == 0
    assert {(pair["reference_id"], pair["predicted_id"]) for pair in result["matched_pairs"]} == {
        ("r0", "p1"), ("r1", "p0"),
    }


def test_edit_proxy_is_bounded_and_does_not_invent_velocity_accuracy():
    result = edit_cost_proxy([Event("r", 0., "kick", 1)], [Event("p", 1., "kick", 127)])
    assert result["cost"] == 2
    assert result["insertions"] == result["deletions"] == 1
    assert result["normalized_cost"] == 2
    assert result["velocity_evaluated"] is False
    result = edit_cost_proxy([Event("r", 0., "kick", 1)], [Event("p", 0., "kick", 127)])
    assert result["cost"] == 0


def test_empty_reference_and_predictions_have_explicit_counts():
    result = score_events([], [])
    assert result["reference"] == result["predicted"] == result["matched"] == 0
    assert result["f1"] == 0 and result["onset_mae_seconds"] is None
    assert result["edit_proxy"]["cost"] == 0
    assert score_events([], [Event("p", 0., "kick")])["edit_proxy"]["deletions"] == 1
    assert score_events([Event("r", 0., "kick")], [])["edit_proxy"]["insertions"] == 1


def test_tolerance_is_inclusive_and_never_reference_shifted():
    refs = [Event("r", 0., "kick")]
    assert len(match_events(refs, [Event("p", .05, "kick")], .05)) == 1
    assert len(match_events(refs, [Event("p", .050001, "kick")], .05)) == 0
    assert len(match_events(refs, [Event("p", .050001, "kick")], .01)) == 0


@pytest.mark.parametrize("start,tolerance", [(.25, .01), (.5, .05)])
def test_onset_endpoints_have_only_declared_one_picosecond_allowance(start, tolerance):
    refs = [Event("r", start, "kick")]
    endpoint = start + tolerance
    assert len(match_events(refs, [Event("p", endpoint, "kick")], tolerance)) == 1
    assert len(match_events(refs, [Event("p", endpoint + .5e-12, "kick")], tolerance)) == 1
    assert match_events(refs, [Event("p", endpoint + 2e-12, "kick")], tolerance) == []


def test_edit_association_and_no_move_endpoints_share_allowance():
    refs = [Event("r", .25, "kick")]
    assert edit_cost_proxy(refs, [Event("p", .255, "kick")])["cost"] == 0
    assert edit_cost_proxy(refs, [Event("p", .255 + 2e-12, "kick")])["time_moves"] == 1
    refs = [Event("r", .5, "kick")]
    associated = edit_cost_proxy(refs, [Event("p", .55, "kick")])
    assert associated["cost"] == associated["time_moves"] == 1
    assert len(associated["matched_pairs"]) == 1
    outside = edit_cost_proxy(refs, [Event("p", .55 + 2e-12, "kick")])
    assert outside["cost"] == 2 and not outside["matched_pairs"]


def test_ninety_millisecond_flams_survive_subtraction_roundoff():
    refs = _events([.25, .34], "r", "backbeat")
    assert refs[1].time - refs[0].time > .09  # The motivating binary-float endpoint.
    exact = recovery_diagnostics(refs, _events([.25, .34], "p", "backbeat"))
    assert exact["flam"]["pairs"] == exact["flam"]["recovered_pairs"] == 1
    assert exact["temporal_endpoint_allowance_seconds"] == 1e-12
    outside = recovery_diagnostics(_events([.25, .34 + 2e-12], "r", "backbeat"), [])
    assert outside["flam"]["pairs"] == 0


def test_simultaneous_and_gap_endpoints_use_same_small_allowance():
    refs = [Event("r0", .25, "kick"), Event("r1", .255, "backbeat")]
    # Both onsets are strict matches; the inter-event gap expands by exactly 10 ms.
    preds = [Event("p0", .245, "kick"), Event("p1", .26, "backbeat")]
    result = recovery_diagnostics(refs, preds)
    assert result["simultaneous"]["groups"] == result["simultaneous"]["timing_preserved_groups"] == 1
    late = [preds[0], Event("p1", .26 + 2e-12, "backbeat")]
    result = recovery_diagnostics(refs, late)
    assert result["simultaneous"]["matched_groups"] == 1
    assert result["simultaneous"]["timing_preserved_groups"] == 0
    outside = [refs[0], Event("r1", .255 + 2e-12, "backbeat")]
    assert recovery_diagnostics(outside, [])["simultaneous"]["groups"] == 0


def test_flam_gap_error_endpoint_does_not_allow_coincident_events():
    refs = _events([.25, .28], "r", "backbeat")
    endpoint = recovery_diagnostics(refs, _events([.245, .285], "p", "backbeat"))
    assert endpoint["flam"]["recovered_pairs"] == 1
    outside = recovery_diagnostics(refs, _events([.245, .285 + 2e-12], "p", "backbeat"))
    assert outside["flam"]["details"][0]["both_matched"] is True
    assert outside["flam"]["recovered_pairs"] == 0


def test_flams_need_two_strict_matches_and_a_positive_preserved_gap():
    refs = _events([0, .015], "r", "backbeat")
    coincident = _events([.0075, .0075], "p", "backbeat")
    assert score_events(refs, coincident)["matched"] == 2
    diagnostic = recovery_diagnostics(refs, coincident)
    assert diagnostic["flam"]["details"][0]["both_matched"] is True
    assert diagnostic["flam"]["recovered_pairs"] == 0
    recovered = recovery_diagnostics(refs, _events([0, .02], "p", "backbeat"))
    assert recovered["flam"]["recovered_pairs"] == 1
    assert recovery_diagnostics(refs, _events([0], "p", "backbeat"))["flam"]["recovered_pairs"] == 0


def test_simultaneous_groups_need_each_role_and_relative_timing():
    refs = [Event("r0", .1, "kick"), Event("r1", .1, "backbeat")]
    preds = [Event("p0", .1, "kick"), Event("p1", .1, "backbeat")]
    result = recovery_diagnostics(refs, preds)
    assert result["simultaneous"]["groups"] == result["simultaneous"]["timing_preserved_groups"] == 1
    assert recovery_diagnostics(refs, preds[:1])["simultaneous"]["matched_groups"] == 0


@pytest.mark.parametrize("event", [
    Event("", 0., "kick"), Event("r", float("nan"), "kick"),
    Event("r", -1., "kick"), Event("r", True, "kick"),
    Event("r", 0., ""), Event("r", 0., "kick", 0),
])
def test_invalid_events_fail_closed(event):
    with pytest.raises(ValueError, match="event"):
        score_events([event], [])


def test_duplicate_ids_and_invalid_tolerances_fail_closed():
    with pytest.raises(ValueError, match="duplicate"):
        score_events([Event("r", 0., "kick"), Event("r", .1, "kick")], [])
    with pytest.raises(ValueError, match="tolerance"):
        score_events([], [], float("nan"))
