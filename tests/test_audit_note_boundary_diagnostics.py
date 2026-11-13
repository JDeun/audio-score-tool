"""Owned examples and receipt mutations exercise the independent boundary audit."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from scripts import audit_note_boundary_diagnostics as audit


def prediction(intervals):
    values = np.asarray(intervals, dtype=float).reshape(-1, 2)
    return values, np.full(len(values), 440.)


def details_for(reference, pred):
    duration = max(1., float(reference[0][-1, 1]) + .1)
    hz = np.full(int(round(duration / .01)) + 1, 440.)
    path = np.full(len(hz), 325, dtype=np.int16)
    return audit.annotation_details(reference, {arm: pred for arm in audit.ARMS}, hz, path, duration)


def test_summary_uses_pooled_samples_and_linear_positions():
    result = audit.summary([-2, -1, 3, 8])
    assert result == {"count": 4, "min": -2., "q25": -1.25, "median": 1.,
                      "q75": 4.25, "max": 8., "mean": 2.}
    assert audit.summary([]) == {"count": 0, **dict.fromkeys(("min", "q25", "median", "q75", "max", "mean"))}
    with pytest.raises(ValueError, match="nonfinite"):
        audit.summary([float("inf")])


@pytest.mark.parametrize("bad", [
    {"matched": 1, "extra": 9}, {}, {"matched": True}, {"matched": -1}, {"matched": 1.0},
])
def test_strict_comparison_rejects_unknown_missing_or_wrong_count(bad):
    with pytest.raises(ValueError):
        audit.strict_equal(audit.Checks(), bad, {"matched": 1}, "fixture")


def test_strict_nested_inventory_and_nonfinite_are_rejected():
    with pytest.raises(ValueError, match="inventory"):
        audit.strict_equal(audit.Checks(), {"x": [{"n": 1, "unexpected": 0}]}, {"x": [{"n": 1}]}, "fixture")
    with pytest.raises(ValueError, match="invalid numeric"):
        audit.strict_equal(audit.Checks(), float("nan"), 0., "fixture")
    with pytest.raises(ValueError, match="mismatch"):
        audit.exact_equal(audit.Checks(), {"n": 1.0}, {"n": 1}, "historical")


def test_fixed_onset_residuals_follow_mir_eval_time_rounding():
    pytest.importorskip("mir_eval")
    reference = prediction([[0., 1.], [2., 3.], [4., 5.]])
    pred = prediction([[0., .75], [2., 3.20004], [4., 5.20006]])
    value = audit.arm_details(reference, pred)
    result = audit.fixed_pair_summary(value["onset_pairs"])
    assert (result["matched"], result["early"], result["within"], result["late"]) == (3, 1, 1, 1)
    assert result["within_with_raw_excess"] == 1
    assert value["onset_pairs"][1]["tolerance_excess_seconds"] == pytest.approx(.00004)
    assert len(value["offset_pairs"]) == 1


def test_assignment_switch_does_not_replace_fixed_onset_pair():
    pytest.importorskip("mir_eval")
    reference = prediction([[0., .4], [.04, .8]])
    pred = prediction([[.03, .8]])
    details = details_for(reference, pred)
    value = audit.summarize_annotations([details])["arms"][audit.GAUSSIAN]
    assert value["onset_matched"] == value["offset_matched"] == 1
    assert value["fixed_onset_pairs"]["late"] == 1
    assert value["fixed_onset_pairs"]["within"] == 0
    assert value["offset_assignment"]["offset_reference_without_fixed_onset_pair"] == 1
    assert value["candidate_graph"]["predictions_with_multiple_onset_candidates"] == 1
    assert value["candidate_graph"]["offset_edges"] == 1


def test_overlap_and_onset_coverage_have_distinct_half_open_rules():
    pytest.importorskip("mir_eval")
    reference = prediction([[0., .4], [.5, .9], [1., 1.3]])
    pred = prediction([[0., 1.]])
    details = audit.arm_details(reference, pred)
    assert details["overlap_ref_degrees"] == [1, 1, 0]
    assert details["prediction_covered_reference_onsets"] == [2]
    assert details["reference_onset_in_multi_onset_prediction"] == [True, True, False]


def test_empty_predictions_keep_all_references_without_overlap():
    pytest.importorskip("mir_eval")
    details = details_for(prediction([[0., .2], [.3, .8]]), prediction([]))
    result = audit.summarize_annotations([details])
    assert result["offset_reference_partitions"]["neither"]["references"] == 2
    assert result["offset_reference_partitions"]["neither"]["g_onset_unmatched"] == 2
    for arm in audit.ARMS:
        value = result["arms"][arm]
        assert value["onset_precision"] == value["onset_recall"] == 0
        assert value["fixed_onset_pairs"]["signed_offset_seconds"]["median"] is None
        assert value["overlap"]["references_without_overlap"] == 2


def test_reference_frame_windows_gaps_and_pruning_intersections():
    hz = np.array([440., 0., 0., 440., 0., 440., 440., 0., 440.])
    path = np.array([324, 325, 325, 325, 325, 326, 326, 326, 326], dtype=np.int16)
    intervals = np.array([[0., .08], [.01, .04], [.05, .09]])
    profiles = audit.reference_profiles(intervals, hz, path, .08)
    first = profiles[0]
    assert first["frames"] == 8  # Terminal observation at .08 is not audio support.
    assert first["raw_voiced_frames"] == 4
    assert first["internal_raw_unvoiced_runs"] == 2
    assert first["raw_voiced_g_silent_frames"] == 2
    assert first["raw_unvoiced_g_voiced_frames"] == 3
    assert first["short_segment_overlap_count"] == 1
    assert first["short_segment_overlap_seconds"] == pytest.approx(.05)
    assert profiles[1]["internal_raw_unvoiced_runs"] == 0  # Leading zero run is not bracketed.
    assert profiles[2]["frames"] == 3
    assert profiles[2]["short_segment_overlap_count"] == 0  # Touching does not overlap.


def test_sub_eighty_ms_rule_preserves_exact_eighty_ms_segment():
    hz = np.full(10, 440.)
    path = np.array([324, 325, 325, 325, 325, 325, 325, 325, 326, 326], dtype=np.int16)
    assert audit.short_intervals(path, hz, .09) == []
    path[7] = 326
    assert audit.short_intervals(path, hz, .09) == [(0., .07)]


def test_aggregate_pools_pair_residuals_instead_of_case_medians():
    pytest.importorskip("mir_eval")
    one = details_for(prediction([[0., 1.]]), prediction([[0., .8]]))
    three = details_for(prediction([[0., 1.], [2., 3.], [4., 5.]]), prediction([[0., 1.1], [2., 3.2], [4., 5.3]]))
    result = audit.summarize_annotations([one, three])["arms"][audit.GAUSSIAN]["fixed_onset_pairs"]
    assert result["signed_offset_seconds"]["count"] == 4
    assert result["signed_offset_seconds"]["median"] == pytest.approx(.15)


def authored_fixture():
    hz = np.full(21, 440.)
    path = np.array([324] * 9 + [325] * 2 + [326] * 10, dtype=np.int16)
    paths = {arm: path.copy() for arm in audit.SYNTHETIC_ARMS[1:]}
    note = {"pitch": 69, "onset": 0., "offset": .2, "is_drum": False}
    events = {arm: [note] for arm in audit.SYNTHETIC_ARMS}
    return hz, paths, events


def test_synthetic_nearest_transition_uses_earlier_tie_and_phase_not_label():
    hz, paths, events = authored_fixture()
    ref = [{"pitch": 69, "onset": 0., "offset": .1, "is_drum": False},
           {"pitch": 69, "onset": .1, "offset": .2, "is_drum": False}]
    result = audit.authored_boundaries(ref, events, hz, paths, .2)
    join = result[1]
    assert join["onset_reference_ids"] == [1] and join["offset_reference_ids"] == [0]
    value = join["arms"][audit.GAUSSIAN]
    assert value["nearest_phase_change_delta_frames"] == -1
    assert value["nearest_label_change_delta_frames"] == 1
    assert value["emitted_events_spanning_frame"] == 1
    assert not value["decoded_label_changed"]
    assert result[0]["raw_before_hz"] is None
    assert result[-1]["at_audio_end"] and result[-1]["arms"][audit.GAUSSIAN]["emitted_offsets_at_frame"] == 1


@pytest.mark.parametrize("bad", [-.1, .10001, float("nan"), True])
def test_authored_time_outside_fixed_clock_is_rejected(bad):
    with pytest.raises(ValueError):
        audit.frame_number(bad)


def test_missing_terminal_sample_is_rejected():
    hz, paths, events = authored_fixture()
    with pytest.raises(ValueError, match="terminal sample"):
        audit.authored_boundaries(events["pitch_runs"], events, hz[:-1], paths, .2)


@pytest.fixture(scope="module")
def historical():
    return audit.load_previous(audit.REPOSITORY / audit.PREVIOUS_RECEIPT, audit.Checks())


def test_complete_archived_replay_is_exact_and_non_scientific_times_can_change(historical):
    old_corpus, old_synthetic = historical
    corpus, synthetic = copy.deepcopy(old_corpus), copy.deepcopy(old_synthetic)
    corpus["elapsed_seconds"] += 1
    corpus["cases"][0]["inference_seconds"] += 1
    corpus["cases"][0]["observation_sha256"] = "0" * 64
    synthetic["elapsed_seconds"] += 1
    result = audit.verify_replay(corpus, synthetic, old_corpus, old_synthetic, audit.Checks())
    assert result["all_equal"]
    assert result["compared_corpus_prediction_files"] == 400
    assert result["compared_corpus_observation_arrays"] == 440
    assert result["compared_synthetic_state_paths"] == 1470


@pytest.mark.parametrize("target,path,value", [
    ("corpus", ("cases", 0, "arms", "gaussian_exponent_1", "event_sha256"), "0" * 64),
    ("corpus", ("cases", 0, "observations", "hz", "sha256"), "0" * 64),
    ("corpus", ("cases", 0, "arms", "pitch_runs", "count"), True),
    ("corpus", ("cases", 0, "arms", "pitch_runs", "annotators", "A1", "onset_f1"), -1.),
    ("corpus", ("cases", 0, "reference_sha256", "A2"), "0" * 64),
    ("corpus", ("source_sha256", "scripts/note_state_factors.py"), "0" * 64),
    ("synthetic", ("cases", 0, "accuracy_eligible"), False),
    ("synthetic", ("cases", 0, "observation", "sha256"), "0" * 64),
    ("synthetic", ("cases", 0, "arms", "gaussian_exponent_1", "state_path", "sha256"), "0" * 64),
    ("synthetic", ("cases", 0, "arms", "pitch_runs", "events", 0, "pitch"), 34),
    ("synthetic", ("extra_scientific_field",), 1),
])
def test_changed_evidence_cannot_pass_historical_gate(historical, target, path, value):
    old_corpus, old_synthetic = historical
    corpus, synthetic = copy.deepcopy(old_corpus), copy.deepcopy(old_synthetic)
    obj = corpus if target == "corpus" else synthetic
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(ValueError):
        audit.verify_replay(corpus, synthetic, old_corpus, old_synthetic, audit.Checks())


def test_missing_recording_rejects_complete_aggregate(historical, tmp_path):
    corpus, synthetic = copy.deepcopy(historical)
    corpus["cases"].pop()
    with pytest.raises(ValueError, match="population"):
        audit.verify_replay(corpus, synthetic, *historical, audit.Checks())
    with pytest.raises(ValueError, match="forty-case"):
        audit.corpus_from_private(tmp_path, corpus, audit.Checks())


def test_duplicate_json_and_unknown_published_nested_fields_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        audit._json(b'{"cases":[],"cases":[]}')
    with pytest.raises(ValueError, match="nonfinite"):
        audit._json(b'{"x":NaN}')
    expected = {"corpus": {"cases": [], "aggregate": None}}
    actual = json.loads(json.dumps(expected))
    actual["corpus"]["raw_event_times"] = []
    with pytest.raises(ValueError, match="inventory"):
        audit.strict_equal(audit.Checks(), actual, expected, "public_report")


def test_independent_auditor_does_not_import_new_reporters_or_models():
    tree = ast.parse(Path(audit.__file__).read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    assert not any(module.startswith(("scripts.note_boundary_", "scripts.run_note_", "scripts.note_state_",
                                      "scripts.dsp_note_probe", "scripts.vocadito_reference")) for module in modules)
