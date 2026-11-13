"""Owned endpoint/assignment controls; no corpus inference or model selection."""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
import pytest

from scripts import note_boundary_diagnostics as diag


def note(start, end, pitch=69):
    return {"pitch": pitch, "onset": start, "offset": end, "is_drum": False}


def reference(intervals):
    return np.asarray(intervals, dtype=float).reshape(-1, 2), np.full(len(intervals), 440.)


def analyze(intervals, gaussian, runs=None, old=None, *, duration=4., hz=None, path=None, case="toy"):
    refs = {a: reference(intervals) for a in diag.ANNOTATORS}
    notes = {"pitch_runs": gaussian if runs is None else runs,
             "gaussian_exponent_1": gaussian, "note_state_hmm": gaussian if old is None else old}
    hz = np.full(int(duration / .01) + 1, 440.) if hz is None else hz
    path = np.full(len(hz), 325, dtype=np.int16) if path is None else path
    return diag.analyze_case(case, notes, refs, hz, path, duration)


def test_numeric_summaries_are_linear_and_empty_is_null():
    assert diag.numeric_summary([]) == {"count": 0, "min": None, "q25": None,
        "median": None, "q75": None, "max": None, "mean": None}
    assert diag.numeric_summary([0, 1, 2, 100]) == {"count": 4, "min": 0.,
        "q25": .75, "median": 1.5, "q75": 26.5, "max": 100., "mean": 25.75}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_summary_rejects_nonfinite(bad):
    with pytest.raises(ValueError, match="finite"):
        diag.numeric_summary([0, bad])


@pytest.mark.parametrize("delta,category", [(-.05004, "within"), (.05004, "within"),
                                           (-.05006, "early"), (.05006, "late")])
def test_fixed_pair_categories_apply_mir_eval_rounding_but_keep_raw_error(delta, category):
    pair = diag.endpoint_pair(2, 3, np.array([.1, .3]), np.array([.1, .3 + delta]))
    assert pair["category"] == category
    assert pair["signed_offset_seconds"] == pytest.approx(delta)
    assert pair["tolerance_seconds"] == .05
    assert pair["tolerance_excess_seconds"] == pytest.approx(abs(delta) - .05)
    summary = diag.fixed_pair_summary([pair])
    assert summary["within_with_raw_excess"] == (category == "within")


def test_long_reference_uses_reference_duration_tolerance():
    pair = diag.endpoint_pair(0, 0, np.array([0., 2.]), np.array([.01, 2.39]))
    assert pair["tolerance_seconds"] == .4
    assert pair["category"] == "within"
    assert pair["prediction_duration_seconds"] == pytest.approx(2.38)


def test_compatibility_uses_original_hz_and_unrounded_pitch_distance():
    ref = reference([[0., 1.]])
    pitches = np.array([440 * 2 ** (49.999 / 1200), 440 * 2 ** (50.001 / 1200)])
    pred = np.array([[.05004, 1.], [.05004, 1.]])
    onset, offset, overlap = diag.candidate_graphs(ref, (pred, pitches))
    assert onset.tolist() == [[True, False]]
    assert offset.tolist() == [[True, False]]
    assert overlap.tolist() == [[True, True]]
    pred[:, 0] = .05006
    assert not diag.candidate_graphs(ref, (pred, pitches))[0].any()


def test_offset_partition_preserves_the_complete_reference_population():
    intervals = [[.2, .4], [.5, .7], [.8, 1.], [1.1, 1.3]]
    public, private = analyze(intervals, [note(.2, .4), note(.8, 1.)],
                              runs=[note(.2, .4), note(.5, .7)], old=[])
    detail = private["annotators"]["A1"]
    assert detail["offset_partition_ids"] == {"retained": [0], "gained": [2], "lost": [1], "neither": [3]}
    groups = public["annotators"]["A1"]["offset_reference_partitions"]
    assert sum(g["references"] for g in groups.values()) == 4
    assert groups["lost"]["g_onset_unmatched"] == 1
    assert groups["gained"]["g_fixed_onset_pairs"]["within"] == 1
    empty = public["annotators"]["A1"]["arms"]["note_state_hmm"]
    assert empty["onset_matched"] == empty["offset_matched"] == empty["predicted_notes"] == 0
    assert empty["overlap"]["references_without_overlap"] == 4
    assert empty["fixed_onset_pairs"]["signed_offset_seconds"]["mean"] is None


def test_lost_partition_separates_early_late_and_onset_unmatched():
    public, _ = analyze([[0., 1.], [1., 2.], [2., 3.]],
                        [note(0., .7), note(1., 2.3)],
                        runs=[note(0., 1.), note(1., 2.), note(2., 3.)])
    lost = public["annotators"]["A1"]["offset_reference_partitions"]["lost"]
    assert lost["references"] == 3
    assert lost["g_onset_unmatched"] == 1
    assert lost["g_fixed_onset_pairs"]["matched"] == 2
    assert lost["g_fixed_onset_pairs"]["early"] == 1
    assert lost["g_fixed_onset_pairs"]["late"] == 1
    assert lost["g_overlap"]["references_with_onset_in_multi_onset_prediction"] == 2


def test_fixed_onset_residuals_do_not_reassign_to_offset_matching():
    # One prediction and two onset-compatible references. The onset matcher picks
    # the first reference; the offset matcher can only pick the second reference.
    public, private = analyze([[0., .2], [0., .5]], [note(0., .5)])
    arm = private["annotators"]["A1"]["arms"]["gaussian_exponent_1"]
    assert [(p["reference_id"], p["prediction_id"]) for p in arm["onset_pairs"]] == [(0, 0)]
    assert arm["offset_pairs"] == [[1, 0]]
    summary = public["annotators"]["A1"]["arms"]["gaussian_exponent_1"]
    assert summary["fixed_onset_pairs"]["late"] == 1
    assert summary["fixed_onset_pairs"]["within"] == 0
    assert summary["offset_matched"] == 1
    assert summary["offset_assignment"]["offset_reference_without_fixed_onset_pair"] == 1
    assert summary["candidate_graph"]["predictions_with_multiple_onset_candidates"] == 1


def test_changed_prediction_assignment_is_counted_without_repairing_the_pair():
    public, private = analyze([[.05, .3]], [note(0., .08), note(.1, .3)])
    arm = private["annotators"]["A1"]["arms"]["gaussian_exponent_1"]
    assert arm["onset_pairs"][0]["prediction_id"] == 0
    assert arm["offset_pairs"] == [[0, 1]]
    summary = public["annotators"]["A1"]["arms"]["gaussian_exponent_1"]
    assert summary["offset_assignment"] == {
        "offset_reference_without_fixed_onset_pair": 0,
        "offset_reference_with_different_prediction": 1,
        "offset_reference_with_fixed_pair_failing_offset": 1}
    assert summary["fixed_onset_pairs"]["early"] == 1


def test_positive_overlap_and_half_open_onset_coverage_are_distinct():
    # A 10 ms crossing overlaps two intervals but contains only one onset.
    public, _ = analyze([[0., .5], [.5, 1.]], [note(.01, .51)])
    overlap = public["annotators"]["A1"]["arms"]["gaussian_exponent_1"]["overlap"]
    assert overlap["predictions_with_multiple_references"] == 1
    assert overlap["predictions_covering_multiple_reference_onsets"] == 0
    assert overlap["references_with_onset_in_multi_onset_prediction"] == 0
    public, _ = analyze([[0., .5], [.5, 1.], [1., 1.5]], [note(0., 1.)])
    overlap = public["annotators"]["A1"]["arms"]["gaussian_exponent_1"]["overlap"]
    assert overlap["edges"] == 2  # Touching the third reference is not overlap.
    assert overlap["predictions_covering_multiple_reference_onsets"] == 1
    assert overlap["references_with_onset_in_multi_onset_prediction"] == 2
    assert overlap["references_without_overlap"] == 1


def test_raw_window_counts_only_bracketed_internal_gaps_and_excludes_terminal_frame():
    hz = np.full(11, 440.)
    hz[[4, 5, 7]] = 0
    path = np.full(11, 325, dtype=np.int16)
    path[6] = 326
    profiles = diag.raw_reference_profiles(np.array([[.03, .08], [.08, .2], [.031, .039]]), hz, path, .1)
    assert profiles[0]["frames"] == 5
    assert profiles[0]["raw_voiced_frames"] == 2
    assert profiles[0]["raw_unvoiced_frames"] == 3
    assert profiles[0]["internal_raw_unvoiced_runs"] == 1
    assert profiles[0]["raw_voiced_g_silent_frames"] == 1
    assert profiles[0]["raw_unvoiced_g_voiced_frames"] == 3
    assert profiles[1]["frames"] == 2  # i=10 at duration is not a duration-bearing frame.
    assert profiles[2]["frames"] == 0
    assert profiles[2]["internal_raw_unvoiced_runs"] == 0


def test_all_unvoiced_reference_has_no_internal_bracketed_gap():
    profiles = diag.raw_reference_profiles(np.array([[0., .1]]), np.zeros(11), np.full(11, 326), .1)
    assert profiles[0]["raw_unvoiced_frames"] == 10
    assert profiles[0]["internal_raw_unvoiced_runs"] == 0


def test_short_pruning_uses_frozen_80ms_threshold_and_requires_raw_support():
    hz = np.full(51, 440.)
    path = np.full(51, 326, dtype=np.int16)
    path[10:17] = 325  # 70 ms, discarded.
    path[30:38] = 325  # 80 ms, retained even with binary roundoff.
    assert diag.short_segment_intervals(hz, path, .5) == [(0.1, .17)]
    profiles = diag.raw_reference_profiles(np.array([[.05, .1], [.1, .2]]), hz, path, .5)
    assert profiles[0]["short_segment_overlap_count"] == 0
    assert profiles[1]["short_segment_overlap_count"] == 1
    assert profiles[1]["short_segment_overlap_seconds"] == pytest.approx(.07)
    hz[10:17] = 0
    assert diag.short_segment_intervals(hz, path, .5) == []


def test_clipped_terminal_segment_has_no_extra_frame_duration():
    hz = np.full(11, 440.)
    path = np.full(11, 326, dtype=np.int16)
    path[4:] = 325
    assert diag.short_segment_intervals(hz, path, .1) == [(.04, .1)]


def test_summary_pools_original_pair_samples_instead_of_case_medians():
    _, first = analyze([[0., .2]], [note(0., .1)])
    _, second = analyze([[0., .2], [1., 1.2], [2., 2.2]],
                        [note(0., .2), note(1., 1.2), note(2., 2.2)])
    summary = diag.summarize_annotations([first["annotators"]["A1"], second["annotators"]["A1"]])
    stats = summary["arms"]["gaussian_exponent_1"]["fixed_onset_pairs"]["signed_offset_seconds"]
    assert stats["count"] == 4
    assert stats["median"] == 0.
    assert stats["mean"] == pytest.approx(-.025)
    assert summary["recording_annotations"] == 2
    assert summary["reference_notes"] == 4


def cohort():
    row, detail = analyze([[0., .2]], [note(0., .2)])
    rows, details = [], []
    for case in diag.CASES:
        a, b = copy.deepcopy(row), copy.deepcopy(detail)
        a["id"] = b["id"] = case
        rows.append(a)
        details.append(b)
    return rows, details


def test_complete_aggregate_keeps_annotators_and_labels_pooled_judgments():
    rows, details = cohort()
    aggregate = diag.aggregate_cases(rows, details)
    assert aggregate["recordings"] == 40
    assert aggregate["recording_annotations"] == 80
    assert aggregate["by_annotator"]["A1"]["reference_notes"] == 40
    assert aggregate["pooled_annotation_judgments"]["reference_notes"] == 80
    assert aggregate["pooled_annotation_judgments"]["arms"]["gaussian_exponent_1"]["predicted_notes"] == 80
    json.dumps(aggregate, allow_nan=False)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failed", "annotator", "arm", "private_missing"])
def test_incomplete_cohort_suppresses_aggregate(mutation):
    rows, details = cohort()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1]["id"] = rows[0]["id"]
    elif mutation == "failed":
        rows[-1]["status"] = "failed"
    elif mutation == "annotator":
        del rows[-1]["annotators"]["A2"]
    elif mutation == "arm":
        del details[-1]["annotators"]["A1"]["arms"]["note_state_hmm"]
    else:
        details.pop()
    assert diag.aggregate_cases(rows, details) is None


def test_aggregate_rejects_summary_mutation():
    rows, details = cohort()
    rows[0]["annotators"]["A1"]["reference_notes"] += 1
    with pytest.raises(ValueError, match="differs"):
        diag.aggregate_cases(rows, details)


def test_public_report_has_no_event_rows_or_absolute_endpoints():
    row, _ = analyze([[0., .2]], [note(0., .2)])
    forbidden = {"onset", "offset", "events", "onset_pairs", "offset_pairs", "reference_id",
                 "prediction_id", "raw_reference_profiles", "offset_partition_ids", "hz", "path"}
    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(row)
    json.dumps(row, allow_nan=False)


@pytest.mark.parametrize("mutation", ["missing_arm", "missing_annotator", "bad_path", "nan_hz", "negative_time"])
def test_invalid_analysis_inputs_are_rejected(mutation):
    notes = {arm: [note(0., .2)] for arm in diag.ARMS}
    refs = {ann: reference([[0., .2]]) for ann in diag.ANNOTATORS}
    hz, path = np.full(31, 440.), np.full(31, 325, dtype=np.int16)
    if mutation == "missing_arm":
        del notes["note_state_hmm"]
    elif mutation == "missing_annotator":
        del refs["A2"]
    elif mutation == "bad_path":
        path[0] = 435
    elif mutation == "nan_hz":
        hz[0] = np.nan
    else:
        notes["pitch_runs"][0]["onset"] = -.1
    with pytest.raises(ValueError):
        diag.analyze_case("toy", notes, refs, hz, path, .3)


def test_analyze_private_refuses_uncompleted_replay_before_accessing_files(tmp_path):
    with pytest.raises(ValueError, match="complete frozen"):
        diag.analyze_private(tmp_path, {"status": "failed", "cases": []})


def private_files(tmp_path):
    raw_notes = (json.dumps([note(0., .2)], indent=2) + "\n").encode()
    raw_reference = b"0,440,.2\n"
    rows = []
    for case in diag.CASES:
        directory = tmp_path / case
        directory.mkdir()
        for arm in diag.ARMS:
            (directory / (arm + ".json")).write_bytes(raw_notes)
        for ann in diag.ANNOTATORS:
            (directory / (ann + ".csv")).write_bytes(raw_reference)
        observation = directory / "observations.npz"
        np.savez_compressed(observation, hz=np.full(31, 440.),
                            gaussian_exponent_1_path=np.full(31, 325, dtype=np.int16))
        rows.append({"id": case, "status": "scored", "duration_seconds": .3,
                     "arms": {arm: {"event_sha256": hashlib.sha256(raw_notes).hexdigest()} for arm in diag.ARMS},
                     "reference_sha256": {ann: hashlib.sha256(raw_reference).hexdigest() for ann in diag.ANNOTATORS},
                     "observation_sha256": hashlib.sha256(observation.read_bytes()).hexdigest()})
    return {"status": "complete", "all_cases_complete": True, "cases": rows}


def test_analyze_private_parses_the_identity_checked_bytes(tmp_path):
    replay = private_files(tmp_path)
    public, private = diag.analyze_private(tmp_path, replay)
    assert len(public["cases"]) == len(private) == 40
    assert public["aggregate"]["by_annotator"]["A1"]["reference_notes"] == 40


@pytest.mark.parametrize("filename,label", [("pitch_runs.json", "prediction"),
                                          ("A1.csv", "reference"),
                                          ("observations.npz", "observation")])
def test_private_mutation_after_the_replay_audit_is_rejected(tmp_path, filename, label):
    replay = private_files(tmp_path)
    path = tmp_path / "vocadito_1" / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match=label + " identity changed"):
        diag.analyze_private(tmp_path, replay)
