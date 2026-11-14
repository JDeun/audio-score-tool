"""Independent corruption and assignment checks for drum-lane receipts."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json

import pytest

from scripts.audit_drum_event_lanes import (
    ARMS,
    COHORT_COUNTS,
    AuditError,
    audit_case_metrics,
    audit_counts,
    audit_directory,
    audit_edit_proxy,
    audit_metric,
    audit_pairs,
    audit_recovery,
    count_metrics,
    maximum_weight_assignment,
    onset_assignment,
    reconstructed_aggregates,
    reconstructed_decision,
    validate_events,
)


def event(identity, time, role="kick", *, prediction=False):
    row = {"event_id": identity, "time": time, "role": role, "velocity": None}
    if prediction:
        row["strength"] = .7
    return row


def test_assignment_reassigns_nearest_hit_to_preserve_cardinality():
    reference = [event("r0", 1.0), event("r1", 1.03)]
    predicted = [event("p0", .98), event("p1", 1.01)]
    matches = onset_assignment(reference, predicted, .025)
    assert sorted(matches) == [(0, 0), (1, 1)]


def test_assignment_minimizes_timing_error_after_match_count():
    reference = [event("r0", .1), event("r1", .14)]
    predicted = [event("p0", .11), event("p1", .13)]
    matches = onset_assignment(reference, predicted, .05)
    assert sorted(matches) == [(0, 0), (1, 1)]


def test_optional_weighted_assignment_does_not_force_bad_cardinality():
    # The sole high-reward edge must beat two low-reward associations.
    assert maximum_weight_assignment(2, 2, [(0, 0, 10), (0, 1, 1), (1, 0, 1)]) == [(0, 0)]


def test_matching_counts_simultaneous_roles_separately_and_rejects_duplicates():
    reference = [event("r0", .2), event("r1", .2, "backbeat")]
    predicted = [event("p0", .2), event("p1", .2)]
    assert len(onset_assignment(reference, predicted, .05)) == 1
    assert len(onset_assignment(reference, predicted, .05, class_aware=False)) == 2
    with pytest.raises(AuditError, match="duplicate assignment edge"):
        maximum_weight_assignment(1, 1, [(0, 0, 1), (0, 0, 2)])


def test_non_target_reference_events_remain_false_negatives():
    reference = [event("r0", .2, "hat"), event("r1", .4, "tom")]
    predicted = [event("p0", .2), event("p1", .4, "backbeat")]
    result = count_metrics(2, 2, len(onset_assignment(reference, predicted, .05)))
    assert result["matched"] == 0
    assert result["false_positives"] == result["false_negatives"] == 2
    assert result["f1"] == 0


@pytest.mark.parametrize("key,value", [("matched", True), ("reference", 3),
                                     ("false_positives", 0), ("precision", .9),
                                     ("f1", float("nan"))])
def test_metric_corruption_is_detected(key, value):
    expected = count_metrics(2, 3, 2)
    actual = dict(expected, **{key: value})
    with pytest.raises(AuditError, match=key):
        audit_counts(actual, expected, "mutated")


def test_empty_truth_predictions_still_penalize_false_positives():
    result = count_metrics(0, 3, 0)
    assert result["false_positives"] == 3
    assert result["precision"] == result["recall"] == result["f1"] == 0
    assert count_metrics(0, 0, 0)["f1"] == 0


@pytest.mark.parametrize("change,label", [
    ({"time": float("nan")}, "event time"),
    ({"time": 2.0}, "event time"),
    ({"role": "hat"}, "unsupported prediction role"),
    ({"velocity": 99}, "invented predicted velocity"),
    ({"strength": float("inf")}, "prediction strength"),
])
def test_prediction_receipts_reject_unavailable_or_invalid_semantics(change, label):
    row = dict(event("p0", .5, prediction=True), **change)
    with pytest.raises(AuditError, match=label):
        validate_events([row], duration=2, prediction=True, label="receipt")


def test_event_identity_and_temporal_order_are_preserved():
    with pytest.raises(AuditError, match="unique event id"):
        validate_events([event("r0", .1), event("r0", .2)],
                        duration=2, prediction=False, label="receipt")
    with pytest.raises(AuditError, match="event ordering"):
        validate_events([event("r0", .2), event("r1", .1)],
                        duration=2, prediction=False, label="receipt")


def pair(reference, prediction):
    error = prediction["time"] - reference["time"]
    return {"reference_id": reference["event_id"], "predicted_id": prediction["event_id"],
            "reference_time": reference["time"], "predicted_time": prediction["time"],
            "reference_role": reference["role"], "predicted_role": prediction["role"],
            "error_seconds": error, "absolute_error_seconds": abs(error)}


def test_residual_assignment_agrees_with_exhaustive_small_graphs():
    # A separate finite enumeration oracle includes sparse, tied and negative
    # rewards. It checks optional cardinality and alternating-path reassignment.
    for size in (1, 2, 3):
        for salt in range(7):
            weights = {(ri, pi): ((ri + 2) * (pi + 3) + salt) % 7 - 2
                       for ri in range(size) for pi in range(size)
                       if (ri * 3 + pi + salt) % 4 != 0}
            optimum = 0
            for choices in itertools.product(range(-1, size), repeat=size):
                selected = [(ri, pi) for ri, pi in enumerate(choices) if pi != -1]
                if len({pi for _, pi in selected}) != len(selected) or any(edge not in weights for edge in selected):
                    continue
                optimum = max(optimum, sum(weights[edge] for edge in selected))
            assigned = maximum_weight_assignment(size, size, [(ri, pi, value) for (ri, pi), value in weights.items()])
            assert sum(weights[edge] for edge in assigned) == optimum


def test_pair_receipt_rejects_suboptimal_timing_and_duplicate_use():
    refs = [event("r0", .1), event("r1", .14)]
    preds = [event("p0", .11), event("p1", .13)]
    with pytest.raises(AuditError, match="minimum total onset error"):
        audit_pairs([pair(refs[0], preds[1]), pair(refs[1], preds[0])], refs, preds, .05,
                    class_aware=True, label="receipt")
    with pytest.raises(AuditError, match="one-to-one pairs"):
        audit_pairs([pair(refs[0], preds[0]), pair(refs[1], preds[0])], refs, preds, .05,
                    class_aware=True, label="receipt")


def measured(reference, predicted, tolerance=.05):
    # Only these hand-authored event fixtures call the experiment scorer. No
    # waveform, source MIDI or planned study/control input is evaluated here.
    from scripts.drum_event_metrics import Event, score_events

    def convert(rows):
        return [Event(row["event_id"], row["time"], row["role"], row["velocity"]) for row in rows]

    return score_events(convert(reference), convert(predicted), tolerance=tolerance)


def test_metric_schema_preserves_unsupported_truth_and_catches_corruption():
    refs = [event("r0", .1), event("r1", .1, "hat"), event("r2", .3, "backbeat")]
    preds = [event("p0", .1), event("p1", .3, "backbeat"), event("p2", .5)]
    actual = measured(refs, preds)
    derived = audit_metric(actual, refs, preds, .05, "fixture")
    assert derived["reference"] == 3
    assert derived["matched"] == 2
    assert derived["edit_cost"] == 2
    assert derived["per_role"]["hat"]["false_negatives"] == 1
    broken = copy.deepcopy(actual)
    del broken["per_role"]["hat"]
    with pytest.raises(AuditError, match="complete per-role inventory"):
        audit_metric(broken, refs, preds, .05, "fixture")
    broken = copy.deepcopy(actual)
    broken["class_agnostic"]["confusion"]["backbeat"]["backbeat"] += 1
    with pytest.raises(AuditError, match="class confusion counts"):
        audit_metric(broken, refs, preds, .05, "fixture")


def test_edit_audit_rejects_internally_consistent_but_nonminimal_plan():
    refs = [event("r0", .1), event("r1", .1, "backbeat")]
    preds = [event("p0", .1), event("p1", .1, "backbeat")]
    actual = measured(refs, preds)["edit_proxy"]
    actual.update(matched_pairs=[pair(refs[0], preds[1]), pair(refs[1], preds[0])],
                  reclassifications=2, cost=2, normalized_cost=1.0)
    with pytest.raises(AuditError, match="optimal edit objective"):
        audit_edit_proxy(actual, refs, preds, "fixture")


def test_fixed_endpoint_allowance_keeps_ninety_millisecond_pair():
    from scripts.drum_event_metrics import Event, recovery_diagnostics

    refs = [event("r0", .25), event("r1", .34)]
    preds = [event("p0", .25), event("p1", .34)]
    actual = recovery_diagnostics([Event(x["event_id"], x["time"], x["role"]) for x in refs],
                                  [Event(x["event_id"], x["time"], x["role"]) for x in preds])
    checked = audit_recovery(actual, refs, measured(refs, preds, .01)["matched_pairs"], "fixture")
    assert checked["flam"]["pairs"] == checked["flam"]["recovered_pairs"] == 1
    assert len(onset_assignment([event("r", .25)], [event("p", .26 + 5e-13)], .01)) == 1
    assert not onset_assignment([event("r", .25)], [event("p", .26 + 2e-12)], .01)


def test_failed_cases_cannot_be_silently_removed_from_conditional_denominators():
    cases = [{"id": f"{cohort}/{index}", "cohort": cohort, "category": None, "status": "not_scored"}
             for cohort, count in COHORT_COUNTS.items() for index in range(count)]
    aggregates = reconstructed_aggregates(cases)
    assert all(row["conditional_on_admitted_cases"] for row in aggregates.values())
    assert sum(row["planned"] for row in aggregates.values()) == 110
    assert sum(row["scored"] for row in aggregates.values()) == 0
    decision = reconstructed_decision(cases, aggregates)
    assert decision["outcome"] == "inconclusive_incomplete"
    assert decision["candidate"] == "independent10"
    with pytest.raises(AuditError, match="aggregate planned population"):
        reconstructed_aggregates(cases[:-1])


def test_case_adapter_checks_four_arms_and_preserves_failed_reference_status():
    planned = [{"id": "fixture", "cohort": "new_waveform", "status": "ready",
                "input_sha256": "a" * 64, "duration_seconds": 1.0}]
    predictions = {"cases": [{"id": "fixture", "cohort": "new_waveform", "status": "predicted",
                               "input_sha256": "a" * 64, "arms": {arm: [] for arm in ARMS}}]}
    references = {"cases": [{"id": "fixture", "cohort": "new_waveform", "status": "reference_failed",
                              "reason": "fixture reference unavailable"}]}
    report = [{"id": "fixture", "cohort": "new_waveform", "category": None, "status": "not_scored",
               "prediction_status": "predicted", "reference_status": "reference_failed"}]
    assert audit_case_metrics(planned, predictions, references, report)[0]["status"] == "not_scored"
    del predictions["cases"][0]["arms"]["global10"]
    with pytest.raises(AuditError, match="four prediction arms"):
        audit_case_metrics(planned, predictions, references, report)


def receipt_files(directory, *, broken_chain=False):
    def save(name, content):
        raw = json.dumps(content).encode()
        (directory / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    schema = "drum-event-lanes-v1"
    qualification = save("qualification.json", {"status": "compatible"})
    preflight = save("preflight.json", {"schema": schema, "qualification_sha256": qualification})
    prediction = save("predictions.json", {"schema": schema, "arms": list(ARMS),
                                           "preflight_sha256": "f" * 64 if broken_chain else preflight,
                                           "reference_calls_before_freeze": 0})
    reference = save("references.json", {"schema": schema, "predictions_sha256": prediction,
                                         "all_predictions_frozen_before_reference_access": True})
    save("report.json", {"schema": schema, "arms": list(ARMS), "candidate": "independent10",
                          "hashes": {"preflight.json": preflight, "predictions.json": prediction,
                                     "references.json": reference, "qualification.json": qualification}})


@pytest.mark.parametrize("name", ["preflight.json", "predictions.json", "references.json", "qualification.json"])
def test_artifact_byte_mutations_are_rejected_before_source_or_metric_access(tmp_path, name):
    receipt_files(tmp_path)
    path = tmp_path / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(AuditError, match="report evidence byte bindings"):
        audit_directory(tmp_path, root=tmp_path)


def test_outer_file_hashes_cannot_hide_wrong_prediction_preflight_binding(tmp_path):
    receipt_files(tmp_path, broken_chain=True)
    with pytest.raises(AuditError, match="preflight/prediction/reference hash chain"):
        audit_directory(tmp_path, root=tmp_path)
