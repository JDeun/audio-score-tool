"""Invented evaluator contracts and generator admission; no cohort inference."""
from __future__ import annotations

import copy
from collections import Counter, defaultdict
from dataclasses import asdict
from fractions import Fraction

import pytest

from scripts import repeat_context_study as study
from scripts.repeat_context_phase import OnsetEvent, infer_repeated_performance


def test_factorial_generation_is_complete_balanced_and_label_free():
    cases = study.prepare_factorial_inputs()
    evaluation = study.load_factorial_evaluation()
    assert [c["id"] for c in cases] == study.factorial_plan()
    assert len(cases) == 1028
    assert set(evaluation) == set(study.factorial_plan())
    main = cases[:1024]
    families = defaultdict(set)
    seeds = defaultdict(set)
    conditions = Counter()
    for case in main:
        assert set(case) == {"id", "scope", "events", "length_q", "receipt"}
        assert case["scope"] == "factorial_authored" and case["length_q"] == 16
        assert len(case["events"]) == 56
        assert Counter(e.pitch for e in case["events"]) == {36: 16, 38: 8, 42: 32}
        assert all(set(asdict(e)) == {"event_id", "pitch", "onset_q", "velocity"} for e in case["events"])
        row = evaluation[case["id"]]
        families[row["family"]].add(row["truth_fingerprint"])
        condition = (row["stationarity"], row["vocabulary_support"], row["trajectory_variant"], row["take"])
        seeds[condition].add(case["receipt"]["seed"])
        conditions[condition] += 1
        assert study.signature((t["pitch"], t["tick"]) for t in row["truth"]) == row["truth_fingerprint"]
        assert all(study.target_tick(t["tick"] / 12, 16) == t["tick"] for t in row["truth"])
    assert len(families) == 32 and all(len(values) == 1 for values in families.values())
    assert len({next(iter(values)) for values in families.values()}) == 32
    assert set(conditions.values()) == {32}
    assert len(seeds) == 32 and all(len(values) == 1 for values in seeds.values())
    assert len({next(iter(values)) for values in seeds.values()}) == 8
    for variant in (0, 1):
        for take in range(4):
            assert len({next(iter(values)) for key, values in seeds.items() if key[2:] == (variant, take)}) == 1


def test_factorial_phase_separation_and_marginal_exposure_match():
    assert all(b - a == Fraction(1, 6) for a, b in study.PHASE_PAIRS.values())
    for support, pair in study.PHASE_PAIRS.items():
        stationary = [p for v in (0, 1) for p in study._trajectory("stationary", support, v)]
        changing = [p for v in (0, 1) for p in study._trajectory("changing", support, v)]
        assert Counter(stationary) == Counter(changing) == {pair[0]: 4, pair[1]: 4}
        assert all(len(set(study._trajectory("stationary", support, v))) == 1 for v in (0, 1))
        assert all(len(set(study._trajectory("changing", support, v))) == 2 for v in (0, 1))


def test_written_contexts_change_rhythm_preserving_coarse_inventory():
    for base in study.legacy.FAMILIES:
        contexts = [study._written_context(base, style) for style in study.STYLES]
        assert len(set(contexts)) == 4
        assert len({study.fingerprint(sorted(Counter((i, t // 12) for i, t in written).items())) for written in contexts}) == 1
        assert all(len(written) == len(set(written)) == 56 for written in contexts)


def test_new_counterfactual_pairs_have_identical_observations_distinct_truth():
    cases = study._factorial_cases()[-4:]
    for left, right in ((cases[0], cases[1]), (cases[2], cases[3])):
        assert left["events"] == right["events"]
        assert left["receipt"]["input_events_sha256"] == right["receipt"]["input_events_sha256"]
        assert left["evaluation"]["truth_fingerprint"] != right["evaluation"]["truth_fingerprint"]
        assert left["evaluation"]["counterfactual_pair"] == right["evaluation"]["counterfactual_pair"]


def test_reused_inputs_and_truth_are_unmodified():
    old = study.previous.prepare_synthetic_inputs()
    current = study.prepare_reused_inputs()
    assert study.reused_plan() == study.previous.synthetic_plan()
    assert len(current) == 484
    for case, baseline in zip(current, old, strict=True):
        assert case == {**baseline, "scope": "reused_authored"}
    assert study.load_reused_evaluation() == study.previous.load_synthetic_evaluation()


def test_joint_truth_uses_complete_mask_not_marginal_cross_product():
    events = (OnsetEvent("a", 60, .52, 70), OnsetEvent("b", 60, 4.52, 80))
    case = {"events": events}
    fits = [{"assignments": [{"alternatives": [0 if s == 0 else 3], "abs_residual_q": 0.},
                              {"alternatives": [48 if s == 0 else 51], "abs_residual_q": 0.}]} for s in range(4)]
    prediction = {"fits": fits, "blocks": [{}, {}], "event_block_indices": [0, 1],
                  "path_sets": {"x": {"diagnostic_mask_hex": "12", "full_mask_hex": "0"}}}
    # 0x12 holds only (0,1) and (1,0), even though both block marginals include 0.
    assert study.joint_truth_available(case, prediction, "x", {"a": (60, 0), "b": (60, 48)}, full=False) is False
    assert study.joint_truth_available(case, prediction, "x", {"a": (60, 0), "b": (60, 51)}, full=False) is True
    assert study.joint_truth_available(case, prediction, "x", {"a": (60, 0)}, full=True) is False
    assert study.joint_truth_available(case, prediction, "x", {}, full=False) is None


@pytest.mark.parametrize("truth", [{"missing": (60, 0)}, {"a": (61, 0)}, {"a": (60, None)}])
def test_joint_truth_rejects_missing_pitch_and_unsupported(truth):
    case = {"events": (OnsetEvent("a", 60, 0., 90),)}
    prediction = infer_repeated_performance(case["events"], 4.)
    assert study.joint_truth_available(case, prediction, "repeat_soft010", truth, full=False) is False


@pytest.mark.parametrize("encoded", ["", "00", "0x1", "G", "-1", "10000000000000000"])
def test_invalid_joint_masks_fail_closed(encoded):
    with pytest.raises(ValueError, match="mask"):
        list(study._mask_indices(encoded, 1))


def test_prediction_validation_detects_changed_mask_and_identity():
    case = {"events": (OnsetEvent("a", 60, .1, 90), OnsetEvent("b", 62, 1.1, 80)), "length_q": 4.}
    prediction = infer_repeated_performance(case["events"], 4.)
    study.validate_prediction(case, prediction)
    changed = copy.deepcopy(prediction)
    changed["path_sets"]["repeat_soft010"]["diagnostic_mask_hex"] = "0"
    with pytest.raises(ValueError, match="count"):
        study.validate_prediction(case, changed)
    changed = copy.deepcopy(prediction)
    changed["arms"]["repeat_soft010"]["diagnostic_assignments"][0]["event_id"] = "new"
    with pytest.raises(ValueError, match="identity"):
        study.validate_prediction(case, changed)


def real_fixture():
    cases, predictions, evaluations = [], {}, {}
    for index in range(4):
        cid, family = f"made-up-{index}", index // 2
        pitch, onset = (60, 0.) if family == 0 else (62, 1.)
        eid = f"attack-{index}"
        events = (OnsetEvent(eid, pitch, onset, 80 + index),)
        case = {"id": cid, "scope": "additional_real", "length_q": 8., "events": events, "receipt": {"status": "complete"}}
        cases.append(case)
        predictions[cid] = infer_repeated_performance(events, 8.)
        evaluations[cid] = {"status": "complete", "id": cid, "score_id": f"score{family}",
                            "score_sha256": str(family + 1) * 64, "receipt": {},
                            "target_notes": [{"score_id": f"ref-{family}", "pitch": pitch, "onset_q": onset,
                                              "duration_q": 1., "grace": False, "event_id": eid, "coverage": "observed"}],
                            "input_links": [{"event_id": eid, "classification": "ordinary_target", "score_id": f"ref-{family}"}]}
    return cases, predictions, evaluations


def test_real_evaluation_keeps_correct_pairs_missing_targets_and_no_links():
    cases, predictions, evaluations = real_fixture()
    for cid in ("made-up-0", "made-up-1"):
        evaluations[cid]["target_notes"].append({"score_id": "missing", "pitch": 64, "onset_q": .125,
                                                 "duration_q": .25, "grace": False, "event_id": None, "coverage": "deletion"})
    result = study.evaluate_real(cases, predictions, evaluations)
    assert result["summary"]["ordinary_targets"] == 6
    assert result["summary"]["context"]["cases_with_links"] == 0
    for method in study.METHODS:
        row = result["summary"]["methods"][method]
        assert (row["correct"], row["wrong"], row["abstained"], row["unobserved"]) == (4, 0, 0, 2)
        assert row["lattice_supported_targets"] == 4
        assert row["paired_references"] == {"same_correct": 2, "same_wrong": 0, "disagreement": 0, "abstention": 0, "unobserved": 1}
        assert row["correct_gained_vs_local_switch005"] == row["correct_lost_vs_local_switch005"] == 0
    assert result["constant_score_control"]["different_score_equal_pairs"] == 4


def test_context_truth_audit_does_not_certify_partial_or_different_repetition():
    case = {"events": tuple(OnsetEvent(str(i), 60, float(i), 90) for i in range(4))}
    context = {"links": [{"left_block": 0, "right_block": 1, "event_index_pairs": [[0, 2], [1, 3]]}], "eligibility": []}
    same = {"0": (60, 0), "1": (60, 6), "2": (60, 48), "3": (60, 54)}
    result = study._context_summary(case, {"repeat_context": context}, same)["evaluation_only_link_truth"]
    assert result["links_same_canonical"] == 1 and result["event_pairs_same_canonical"] == 2
    partial = dict(same)
    del partial["3"]
    result = study._context_summary(case, {"repeat_context": context}, partial)["evaluation_only_link_truth"]
    assert result["links_unscorable"] == 1 and result["links_same_canonical"] == 0
    different = {**same, "3": (60, 57)}
    result = study._context_summary(case, {"repeat_context": context}, different)["evaluation_only_link_truth"]
    assert result["links_different_canonical"] == 1


def test_baseline_parity_rejects_changed_inputs_or_full_old_prediction():
    case = {"id": "invented", "events": (OnsetEvent("x", 60, 0., 90),)}
    row = {"id": "invented", "input_content_fingerprint": study.fingerprint([asdict(e) for e in case["events"]]),
           "prediction_content_fingerprint": "a" * 64}
    predictions = {"invented": {"baseline_prediction_content_fingerprint": "a" * 64}}
    result = study._check_baseline_rows([case], predictions, [row])
    assert result["full_original_prediction_fingerprints_equal"] == 1
    with pytest.raises(ValueError, match="input"):
        study._check_baseline_rows([case], predictions, [{**row, "input_content_fingerprint": "b" * 64}])
    with pytest.raises(ValueError, match="baseline"):
        study._check_baseline_rows([case], predictions, [{**row, "prediction_content_fingerprint": "b" * 64}])


def test_study_requires_complete_population():
    with pytest.raises(ValueError, match="1520-case"):
        study.evaluate_study([], {}, {})
