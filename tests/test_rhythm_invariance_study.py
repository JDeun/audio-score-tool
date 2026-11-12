"""Independent small contracts; never execute the planned inference cohort here."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import asdict, fields

import pytest

from scripts.performed_rhythm_invariance import METHODS, PHASES, Event, canonical_fingerprint
from scripts.rhythm_invariance_study import (
    FAMILIES,
    REAL_METHODS,
    _contains_truth,
    _distance_summary,
    _make_case,
    _normalize,
    _written,
    evaluate_real,
    evaluate_study,
    evaluate_synthetic,
    prepare_synthetic,
    profile_distance,
    synthetic_plan,
    validate_prediction,
)


def _manual_prediction(events, ticks, selected=True):
    """Hand-built perfect observations, independent of the phase estimator."""
    assignments = [{"event_id": e.event_id, "instrument": e.instrument,
                    "tick": tick, "alternatives": [tick]} for e, tick in zip(events, ticks)]
    profile = [[0] * 48 for _ in range(9)]
    for e, tick in zip(events, ticks):
        profile[e.instrument][tick % 48] += 1
    digest = canonical_fingerprint([(e.instrument, t) for e, t in zip(events, ticks)])
    fit = {"assignments": assignments, "profile": profile, "canonical_fingerprint": digest,
           "mse_q2": 0.0, "max_abs_residual_q": 0.0, "tie_count": 0, "collision_count": 0}
    return {"fits": [dict(copy.deepcopy(fit), phase=list(p)) for p in PHASES],
            "arms": {m: {"diagnostic_fit_indices": [0], "retained_fit_indices": [0],
                         "candidate_fingerprints": [digest], "candidate_fingerprints_exhaustive": True,
                         "selected_fingerprint": digest if selected else None,
                         "status": "decided" if selected else "ambiguous"} for m in METHODS}}


def test_families_have_identical_inventory_but_distinct_written_positions():
    scores = [_written(family) for family in FAMILIES]
    assert len({canonical_fingerprint(score) for score in scores}) == 8
    for score in scores:
        assert Counter(i for i, _ in score) == {0: 8, 1: 4, 2: 16}
        assert len(score) == len(set(score)) == 28
        assert all(0 <= tick < 96 and tick % 12 in (0, 3, 4, 6, 8, 9) for _, tick in score)


def test_generator_plan_and_input_schema_have_no_inference_labels():
    cases = prepare_synthetic()  # generate inputs only, not a single inference
    assert [c["id"] for c in cases] == synthetic_plan()
    assert len(cases) == len({c["id"] for c in cases}) == 484
    assert [f.name for f in fields(Event)] == ["event_id", "instrument", "onset_q", "velocity"]
    assert all(len(c["events"]) == 28 for c in cases)
    assert all(e.event_id.startswith("e") and e.event_id[1:].isdigit() for c in cases for e in c["events"])


@pytest.mark.parametrize("pair", ["two_to_one", "three_to_one"])
def test_identical_observations_really_have_different_written_targets(pair):
    cases = [c for c in prepare_synthetic() if c["evaluation"]["counterfactual_pair"] == pair]
    assert len(cases) == 2
    assert cases[0]["events"] == cases[1]["events"]
    assert cases[0]["receipt"]["input_events_sha256"] == cases[1]["receipt"]["input_events_sha256"]
    assert cases[0]["evaluation"]["truth_fingerprint"] != cases[1]["evaluation"]["truth_fingerprint"]


def test_supplied_clock_removes_tempo_units_not_expression_or_velocity():
    slow = _make_case("sixteenth_hats", "changing_swing", 3, 80)
    fast = _make_case("sixteenth_hats", "changing_swing", 3, 160)
    assert slow["evaluation"]["truth"] == fast["evaluation"]["truth"]
    assert [e.onset_q for e in slow["events"]] == pytest.approx([e.onset_q for e in fast["events"]], abs=2e-14)
    assert [e.velocity for e in slow["events"]] == [e.velocity for e in fast["events"]]
    assert slow["receipt"]["performed_seconds_sha256"] != fast["receipt"]["performed_seconds_sha256"]
    assert len({e.velocity for e in slow["events"]}) > 1


def test_ground_truth_membership_requires_all_distinct_event_identities():
    truth = [{"event_id": "a", "instrument": 0, "tick": 0},
             {"event_id": "b", "instrument": 0, "tick": 6}]
    fit = {"assignments": [{"event_id": "a", "instrument": 0, "alternatives": [0, 3]},
                            {"event_id": "b", "instrument": 0, "alternatives": [4, 6]}]}
    assert _contains_truth(fit, truth)
    fit["assignments"][1] = fit["assignments"][0]
    assert not _contains_truth(fit, truth)


def test_normalized_distance_and_correlated_pair_auc_arithmetic():
    assert _normalize([2, 0, 2]) == [0.5, 0.0, 0.5]
    assert profile_distance([[1, 0]], [[0, 1]]) == 1.0
    assert profile_distance([[1, 0], [0, 1]], [[0, 1]]) == 0.0
    summary = _distance_summary([0, 0.5], [0.5, 1])
    assert summary["pair_separation_auc"] == 0.875
    assert summary["same_groove_pairs"] == summary["different_groove_pairs"] == 2


@pytest.mark.parametrize("values", [[0, 0], [-1, 2], [float("nan"), 1], [float("inf"), 1]])
def test_invalid_profiles_fail_closed(values):
    with pytest.raises(ValueError):
        _normalize(values)


def _small_real_population(selected=True):
    cases, predictions = [], {}
    for drummer in ("a", "b"):
        for groove, tick in (("groove1", 0), ("groove7", 6)):
            case_id = f"{drummer}/{groove}"
            events = (Event("e000000", 2, tick / 12, 80),)
            cases.append({"id": case_id, "events": events, "length_q": 4,
                          "evaluation": {"drummer": drummer, "groove": groove}})
            predictions[case_id] = _manual_prediction(events, [tick], selected=selected)
    return cases, predictions


def test_real_retrieval_holds_out_drummer_and_constant_profile_cannot_win_ties():
    cases, predictions = _small_real_population()
    result = evaluate_real(cases, predictions)
    assert len(result["pair_rows"]) == 4
    summary = result["summary"]["methods"]
    for method in METHODS:
        assert summary[method]["correct"] == 4
        assert summary[method]["pair_separation_auc"] == 1.0
        assert summary[method]["same_groove_pairs"] == 2
        assert summary[method]["different_groove_pairs"] == 2
    for method in ("constant_profile", "instrument_inventory"):
        assert summary[method]["ambiguous"] == 4
        assert summary[method]["correct"] == 0
        assert summary[method]["different_zero_distance_pairs"] == 2
    assert len(result["retrieval_rows"]) == 4 * len(REAL_METHODS)
    assert all(r["gallery_size"] == 2 for r in result["retrieval_rows"])


def test_abstention_is_not_same_canonical_score_even_when_profiles_match():
    cases, predictions = _small_real_population(selected=False)
    result = evaluate_real(cases, predictions)
    for method in METHODS:
        assert result["summary"]["methods"][method]["correct"] == 4
        assert result["summary"]["methods"][method]["strict_canonical"]["decided_takes"] == 0
        assert not any(p["strict_canonical"][method]["same_decided_score"] for p in result["pair_rows"])


def test_stable_wrong_synthetic_control_is_not_counted_as_correct_invariance():
    # No estimator is executed: explicitly force the constant score as a corruption control.
    case = _make_case("offbeat_kick", "straight", 0, 120)
    ticks_by_instrument = {i: [tick for inst, tick in _written("four_on_floor_eighth") if inst == i]
                           for i in range(3)}
    rank = Counter()
    ticks = []
    for event in case["events"]:
        ticks.append(ticks_by_instrument[event.instrument][rank[event.instrument]])
        rank[event.instrument] += 1
    predictions = {case["id"]: _manual_prediction(case["events"], ticks)}
    result = evaluate_synthetic([case], predictions)
    for method in (*METHODS, "always_four_on_floor"):
        summary = result["summary"]["methods"][method]
        assert summary["correct"] == 0 and summary["wrong"] == 1
        assert summary["stable_wrong_families"] == 1
        assert summary["all_takes_correct_families"] == 0


@pytest.mark.parametrize("corruption", ["identity", "mass", "hash", "tie", "decision", "phase", "nonfinite"])
def test_prediction_contract_rejects_lost_attacks_bad_mass_and_false_certainty(corruption):
    case = {"events": (Event("a", 0, 0.0, 100), Event("b", 2, 0.5, 60)), "length_q": 1}
    prediction = _manual_prediction(case["events"], [0, 6])
    validate_prediction(case, prediction)
    if corruption == "identity":
        prediction["fits"][0]["assignments"][1]["event_id"] = "a"
    elif corruption == "mass":
        prediction["fits"][0]["profile"][0][0] += 1
    elif corruption == "hash":
        prediction["fits"][0]["canonical_fingerprint"] = "f" * 64
    elif corruption == "tie":
        prediction["fits"][0]["tie_count"] = 1
    elif corruption == "decision":
        prediction["arms"]["phase_aware"]["selected_fingerprint"] = "a" * 64
    elif corruption == "phase":
        prediction["fits"].pop()
    else:
        prediction["fits"][0]["mse_q2"] = float("nan")
    with pytest.raises(ValueError):
        validate_prediction(case, prediction)


def test_incomplete_population_cannot_produce_an_overall_result():
    case = {"id": "incomplete", "events": (), "receipt": {"status": "failed"}}
    with pytest.raises(ValueError, match="source failure"):
        evaluate_study([case], {"incomplete": {}})
    with pytest.raises(ValueError, match="one-to-one"):
        evaluate_study([case], {})


def test_generated_observations_are_not_changed_by_evaluation_helpers():
    case = _make_case("mixed_thirds_sparse", "light_swing", 2, 120)
    before = [asdict(e) for e in case["events"]]
    expected = [{"event_id": e.event_id, "instrument": e.instrument, "tick": t["tick"],
                 "alternatives": [t["tick"]]} for e, t in zip(case["events"], case["evaluation"]["truth"])]
    assert _contains_truth({"assignments": expected}, case["evaluation"]["truth"])
    assert before == [asdict(e) for e in case["events"]]
