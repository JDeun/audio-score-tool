"""Small invented contracts; never execute the 488-case research cohort here."""
from __future__ import annotations

import copy
import math
from dataclasses import asdict

import pytest

from scripts import same_score_expression_study as study
from scripts.run_same_score_expression import MAX_EVALUATION_BYTES, _public_component
from scripts.same_score_phase import OnsetEvent, infer_performance


def real_fixture():
    cases, predictions, evaluations = [], {}, {}
    for index in range(4):
        cid, family = f"nasap{index + 1:03d}", index // 2
        pitch, onset = (60, 0.) if family == 0 else (62, 1.)
        eid = f"attack-{index}"
        events = (OnsetEvent(eid, pitch, onset, 80 + index),)
        case = {"id": cid, "scope": "real_same_score", "length_q": 32.,
                "events": events, "receipt": {"status": "complete"}}
        cases.append(case)
        predictions[cid] = infer_performance(events, 32.)
        evaluations[cid] = {
            "status": "complete", "id": cid, "score_id": f"score{family + 1:03d}",
            "performance_id": cid, "score_sha256": str(family + 1) * 64,
            "score_window_start_q": 4., "length_q": 32., "receipt": {},
            "target_notes": [{"score_id": f"ref-{family}", "pitch": pitch,
                              "onset_q": onset, "duration_q": 1., "grace": False,
                              "event_id": eid, "coverage": "observed"}],
            "input_links": [{"event_id": eid, "classification": "ordinary_target", "score_id": f"ref-{family}"}],
        }
    return cases, predictions, evaluations


def add_reference(evaluation, *, ref, pitch=60, onset=2., coverage="deletion", grace=False):
    evaluation["target_notes"].append({"score_id": ref, "pitch": pitch, "onset_q": onset,
                                       "duration_q": .25, "grace": grace,
                                       "event_id": None, "coverage": coverage})


def test_reused_generator_has_opaque_ids_and_preserves_observations():
    cases = study.prepare_synthetic_inputs()
    previous = study.legacy.prepare_synthetic()
    assert [c["id"] for c in cases] == study.synthetic_plan()
    assert len(cases) == 484
    assert any(e.onset_q < 0 for c in cases for e in c["events"])
    for case, old in zip(cases, previous, strict=True):
        assert set(case) == {"id", "scope", "events", "length_q", "receipt"}
        assert case["receipt"]["reused_development_control"] is True
        for event, source in zip(case["events"], old["events"], strict=True):
            assert set(asdict(event)) == {"event_id", "pitch", "onset_q", "velocity"}
            assert (event.event_id, event.onset_q, event.velocity) == (source.event_id, source.onset_q, source.velocity)
            assert event.pitch == study.PITCHES[source.instrument]
    truth = study.load_synthetic_evaluation()
    assert set(truth) == set(study.synthetic_plan())
    assert all(e["status"] == "complete" for e in truth.values())
    assert all(e["truth_fingerprint"] == study.signature((t["pitch"], t["tick"]) for t in e["truth"]) for e in truth.values())


@pytest.mark.parametrize("onset,tick", [(0., 0), (.25, 3), (1 / 3, 4), (.5, 6), (2 / 3, 8), (.75, 9), (1., 12), (.125, None), (-.25, None), (32., None)])
def test_canonical_target_is_exact_lattice_not_tolerance(onset, tick):
    assert study.target_tick(onset, 32.) == tick


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "0"])
def test_nonfinite_or_untyped_target_is_rejected(bad):
    with pytest.raises(ValueError, match="finite target"):
        study.target_tick(bad, 32.)


def test_all_real_targets_pairs_and_constant_collapse():
    cases, predictions, evaluations = real_fixture()
    for case in cases:
        study.validate_prediction(case, predictions[case["id"]])
    result = study.evaluate_real(cases, predictions, evaluations)
    _public_component(result, (), MAX_EVALUATION_BYTES)
    assert {k: result["summary"][k] for k in ("cases", "score_families", "same_score_pairs", "different_score_pairs", "input_attacks", "ordinary_targets")} == {
        "cases": 4, "score_families": 2, "same_score_pairs": 2, "different_score_pairs": 4, "input_attacks": 4, "ordinary_targets": 4}
    for method in study.METHODS:
        summary = result["summary"]["methods"][method]
        assert (summary["correct"], summary["wrong"], summary["abstained"], summary["unobserved"]) == (4, 0, 0, 0)
        assert summary["equal_score_correct_rate"] == 1
        assert summary["same_score_strict_equal_pairs"] == 2
        assert summary["different_score_strict_equal_pairs"] == 0
        assert summary["paired_references"] == {"same_correct": 2, "same_wrong": 0, "disagreement": 0, "abstention": 0, "unobserved": 0}
    assert result["constant_score_control"]["same_score_equal_pairs"] == 2
    assert result["constant_score_control"]["different_score_equal_pairs"] == 4
    assert result["constant_score_control"]["per_hit_alignment_not_defined"] is True


def test_missing_boundary_and_unsupported_targets_are_never_dropped():
    cases, predictions, evaluations = real_fixture()
    for cid in ("nasap001", "nasap002"):
        add_reference(evaluations[cid], ref="deleted", onset=2.)
        add_reference(evaluations[cid], ref="outside", onset=.125, coverage="outside_input_window")
        add_reference(evaluations[cid], ref="grace", onset=1., grace=True)
    result = study.evaluate_real(cases, predictions, evaluations)
    assert (result["summary"]["ordinary_targets"], result["summary"]["grace_targets"]) == (8, 2)
    for method in study.METHODS:
        summary = result["summary"]["methods"][method]
        assert (summary["targets"], summary["correct"], summary["unobserved"], summary["lattice_supported_targets"]) == (8, 4, 4, 6)
        assert summary["paired_references"]["unobserved"] == 2
        assert summary["equal_score_correct_rate"] == pytest.approx((1 / 3 + 1) / 2)
        assert result["case_rows"][0]["arms"][method]["conditional_observed_diagnostic_truth_available"] is True


def test_stable_wrong_is_distinct_from_correct_and_abstention():
    cases, predictions, evaluations = real_fixture()
    for cid in ("nasap001", "nasap002"):
        evaluations[cid]["target_notes"][0]["onset_q"] = 1.
    result = study.evaluate_real(cases, predictions, evaluations)
    for method in study.METHODS:
        summary = result["summary"]["methods"][method]
        assert (summary["correct"], summary["wrong"]) == (2, 2)
        assert summary["paired_references"]["same_wrong"] == 1
        assert summary["same_score_strict_equal_pairs"] == 2


def test_pitch_error_keeps_onset_only_evidence_and_target_denominator():
    cases, predictions, evaluations = real_fixture()
    first = cases[0]
    first["events"] = (OnsetEvent("attack-0", 61, 0., 90),)
    predictions[first["id"]] = infer_performance(first["events"], 32.)
    result = study.evaluate_real(cases, predictions, evaluations)
    for method in study.METHODS:
        summary = result["summary"]["methods"][method]
        assert (summary["targets"], summary["correct"], summary["onset_correct"], summary["pitch_mismatched_observations"]) == (4, 3, 4, 1)
        assert summary["paired_references"]["disagreement"] == 1
        assert result["case_rows"][0]["arms"][method]["conditional_observed_diagnostic_truth_available"] is False


def test_compact_reference_masks_are_ordered_and_reconstruct_counts():
    cases, predictions, evaluations = real_fixture()
    for cid in ("nasap001", "nasap002"):
        add_reference(evaluations[cid], ref="unobserved", onset=.125)
        evaluations[cid]["target_notes"].reverse()
    result = study.evaluate_real(cases, predictions, evaluations)
    for row in result["case_rows"]:
        n = row["ordinary_targets"]
        assert len(row["reference_keys"]) == len(set(row["reference_keys"])) == n
        assert len(row["reference_coverage"]) == len(row["lattice_support_mask"]) == n
        for method in study.METHODS:
            arm = row["arms"][method]
            assert "reference_outcomes" not in arm
            assert all(len(mask) == n for mask in arm["reference_masks"].values())
            for code, key in (("C", "correct"), ("W", "wrong"), ("A", "abstained"), ("U", "unobserved")):
                assert arm["reference_masks"]["status"].count(code) == arm[key]
    first_pair = next(p for p in result["pair_rows"] if p["left"] == "nasap001" and p["right"] == "nasap002")
    assert first_pair["methods"]["global_phase"]["reference_status_mask"] == "CU"
    assert "paired_reference_rows" not in result


def test_observed_target_must_have_input_and_unobserved_must_not():
    cases, predictions, evaluations = real_fixture()
    target = evaluations["nasap001"]["target_notes"][0]
    target["event_id"] = None
    with pytest.raises(ValueError, match="observed target"):
        study.evaluate_real(cases, predictions, evaluations)
    target.update(event_id="attack-0", coverage="deletion")
    with pytest.raises(ValueError, match="unobserved target"):
        study.evaluate_real(cases, predictions, evaluations)


@pytest.mark.parametrize("field,value", [("onset_q", .25), ("pitch", 61), ("duration_q", .5)])
def test_same_xml_pair_requires_identical_canonical_occurrences(field, value):
    cases, predictions, evaluations = real_fixture()
    evaluations["nasap002"]["target_notes"][0][field] = value
    with pytest.raises(ValueError, match="canonical"):
        study.evaluate_real(cases, predictions, evaluations)


def test_input_classification_and_score_occurrence_inventory_are_complete():
    cases, predictions, evaluations = real_fixture()
    evaluations["nasap001"]["input_links"] = []
    with pytest.raises(ValueError, match="every original"):
        study.evaluate_real(cases, predictions, evaluations)
    cases, predictions, evaluations = real_fixture()
    evaluations["nasap001"]["target_notes"] *= 2
    with pytest.raises(ValueError, match="unique score"):
        study.evaluate_real(cases, predictions, evaluations)


def test_diagnostic_gate_is_per_event_and_not_a_full_sequence_claim():
    case = {"events": (OnsetEvent("bad", 60, .9, 80),), "length_q": 1.}
    prediction = infer_performance(case["events"], 1.)
    study.validate_prediction(case, prediction)
    assert prediction["arms"]["straight_narrow"]["diagnostic_assignments"][0]["candidate_ticks"] == []
    assert not study.joint_truth_available(case, prediction, "straight_narrow", {"bad": (60, 9)}, full=False)
    assert study.joint_truth_available(case, prediction, "straight_wide", {"bad": (60, 9)}, full=False)
    assert study.joint_truth_available(case, prediction, "straight_narrow", {}, full=False) is None


def test_marginal_truth_candidates_do_not_imply_joint_global_path():
    case = {"events": (OnsetEvent("a", 60, 0., 90), OnsetEvent("b", 62, 4., 90))}
    fits = []
    for state in range(4):
        fits.append({"assignments": [
            {"alternatives": [0 if state == 0 else 3], "abs_residual_q": 0.},
            {"alternatives": [48 if state == 1 else 51], "abs_residual_q": 0.}]})
    graph = {"allowed_states": [[0, 1], [0, 1]], "retained_states": [[0, 1], [0, 1]], "budget_sse_q2": .001}
    arm = {"mode": "global", "switch_cost_q2": None, "residual_gate_q": .08,
           "diagnostic_graph": graph, "full_graph": graph}
    prediction = {"fits": fits, "blocks": [{"sse_q2": [0.] * 4}] * 2,
                  "event_block_indices": [0, 1], "arms": {"test": arm}}
    truth = {"a": (60, 0), "b": (62, 48)}
    assert not study.joint_truth_available(case, prediction, "test", truth, full=False)
    arm.update(mode="local", switch_cost_q2=0.)
    assert study.joint_truth_available(case, prediction, "test", truth, full=False)
    arm["switch_cost_q2"] = .0025
    assert not study.joint_truth_available(case, prediction, "test", truth, full=False)
    graph["budget_sse_q2"] = .0025
    assert study.joint_truth_available(case, prediction, "test", truth, full=False)
    graph["allowed_states"] = [[0], []]
    assert not study.joint_truth_available(case, prediction, "test", truth, full=True)


@pytest.mark.parametrize("mutation", ["identity", "pitch", "lattice", "fingerprint", "residual", "block", "candidate", "full_hash"])
def test_invalid_saved_prediction_cannot_be_evaluated(mutation):
    cases, predictions, _ = real_fixture()
    case, prediction = cases[0], predictions["nasap001"]
    if mutation == "identity":
        prediction["fits"][0]["assignments"][0]["event_id"] = "other"
    elif mutation == "pitch":
        prediction["fits"][0]["assignments"][0]["pitch"] = 61
    elif mutation == "lattice":
        prediction["fits"][0]["assignments"][0].update(tick=1, alternatives=[1])
    elif mutation == "fingerprint":
        prediction["fits"][0]["canonical_fingerprint"] = "bad"
    elif mutation == "residual":
        prediction["fits"][0]["sse_q2"] += 1
    elif mutation == "block":
        prediction["blocks"][0]["event_indices"] = []
    elif mutation == "candidate":
        prediction["arms"]["straight_narrow"]["diagnostic_assignments"][0]["candidate_ticks"] = [3]
    else:
        prediction["arms"]["straight_narrow"]["full_selected_fingerprint"] = "bad"
    with pytest.raises(ValueError):
        study.validate_prediction(case, prediction)


def test_identical_observation_controls_reject_changed_predictions(monkeypatch):
    cases, predictions, real_evaluations = real_fixture()
    cases = cases[:2]
    cases[1]["events"] = cases[0]["events"]
    predictions["nasap002"] = copy.deepcopy(predictions["nasap001"])
    evaluations = {}
    for i, case in enumerate(cases):
        truth = [{"event_id": "attack-0", "pitch": 60, "tick": i * 12}]
        evaluations[case["id"]] = {"truth": truth, "truth_fingerprint": study.signature([(60, i * 12)]),
                                   "family": f"family-{i}", "profile": "toy", "take": 0,
                                   "nominal_bpm": 120, "counterfactual_pair": "toy-pair"}
    monkeypatch.setattr(study, "_constant_synthetic", lambda events: {e.event_id: 0 for e in events})
    result = study.evaluate_synthetic(cases, predictions, evaluations)
    _public_component(result, (), MAX_EVALUATION_BYTES)
    assert result["counterfactuals"][0]["inputs_and_predictions_identical"] is True
    assert result["counterfactuals"][0]["targets_differ"] is True
    assert result["counterfactuals"][0]["methods"]["global_phase"]["full_correct"] == 1
    predictions["nasap002"]["extra"] = "changed"
    with pytest.raises(ValueError, match="identical-observation"):
        study.evaluate_synthetic(cases, predictions, evaluations)


def test_full_study_rejects_missing_and_reordered_population_without_inference():
    with pytest.raises(ValueError, match="488-case"):
        study.evaluate_study([], {}, {})
    ids = list(reversed(study.synthetic_plan() + list(study.REAL_IDS)))
    with pytest.raises(ValueError, match="488-case"):
        study.evaluate_study([{"id": cid} for cid in ids], dict.fromkeys(ids), dict.fromkeys(ids))
