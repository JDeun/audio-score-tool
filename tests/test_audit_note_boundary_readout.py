"""Owned counterexamples and evidence mutations for the independent #296 audit."""
from __future__ import annotations

import ast
import copy
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from scripts import audit_note_boundary_readout as audit


def frequencies(pitches):
    pitches = np.asarray(pitches, dtype=float)
    return np.where(pitches >= 0, 440 * 2 ** ((pitches - 69) / 12), 0.)


def fixed_path(count):
    path = np.full(count, 325, dtype=np.int16)
    if count:
        path[0] = 324
    return path


@pytest.mark.parametrize("raw,expected", [
    ([69] * 4 + [70] * 4, [69] * 8),
    ([69] * 4 + [70] * 5, [69] * 4 + [70] * 5),
    ([69] + [70] * 3 + [71] * 2 + [70] * 3, [69] * 9),
    ([69] + [70] * 5 + [69] * 4, [69] + [70] * 9),
    ([69] * 2 + [-1] + [70] * 2, [69] * 2 + [-1] + [70] * 2),
    ([-1] * 3, [-1] * 3),
    ([], []),
])
def test_independent_hysteresis_uses_runs_backdates_and_resets(raw, expected):
    assert audit.independent_labels(frequencies(raw)).tolist() == expected


@pytest.mark.parametrize("raw,path,duration", [
    ([69] * 20 + [70] * 21, fixed_path(41), .4),
    ([69] * 5 + [70] * 6, fixed_path(11), .1),
    ([69] * 9 + [-1] * 2 + [70] * 10, fixed_path(21), .2),
    ([69] * 9 + [70] * 12, np.array([324] + [325] * 9 + [326] + [333] + [334] * 9, dtype=np.int16), .2),
    ([69.49] * 10 + [69.51] * 11, fixed_path(21), .205),
    ([-1] * 9, fixed_path(9), .08),
    ([], np.empty(0, dtype=np.int16), 0.),
])
def test_independent_reconstruction_agrees_on_small_owned_controls(raw, path, duration):
    from scripts import note_boundary_readout as implementation

    hz = frequencies(raw)
    expected_notes, expected_diagnostics, expected_trace = audit.reconstruct_split(path, hz, duration)
    notes, diagnostics, trace = implementation.notes_from_state_path(path, hz, duration)
    audit.exact_equal(audit.Checks(), [asdict(note) for note in notes], expected_notes, "owned_events")
    audit.strict_equal(audit.Checks(), diagnostics, expected_diagnostics, "owned_diagnostics")
    audit.exact_equal(audit.Checks(), trace, expected_trace, "owned_trace")


def test_added_cuts_can_prune_every_child_of_a_formerly_emitted_parent():
    notes, diagnostics, trace = audit.reconstruct_split(fixed_path(11), frequencies([69] * 5 + [70] * 6), .1)
    assert not notes
    assert diagnostics["originally_emitted_parents_all_children_pruned"] == 1
    assert diagnostics["readout"]["short_segments_discarded"] == 2
    assert diagnostics["emitted_seconds_change"] == pytest.approx(-.1)
    assert trace["parents"][0]["original"]["prediction_index"] == 0
    assert all(child["prediction_index"] is None for child in trace["parents"][0]["children"])


def test_no_raw_zero_gate_and_no_cut_byte_identity():
    hz = frequencies([69] * 10 + [-1] * 2 + [70] * 9)
    notes, diagnostics, trace = audit.reconstruct_split(fixed_path(21), hz, .2)
    old, _ = audit.reconstruct_readout(fixed_path(21), hz, .2)
    assert notes == old
    assert diagnostics["candidate_cut_count"] == diagnostics["applied_cut_count"] == 0
    assert diagnostics["readout"]["emitted_raw_unvoiced_frames"] == 2
    assert trace["parents"][0]["original"]["raw_positive_midi_median"] == 69


def test_global_raw_support_is_not_restarted_at_a_parent_boundary():
    hz = frequencies([69] * 8 + [70] * 8)
    path = np.array([324] + [325] * 9 + [326] + [333] + [334] * 4, dtype=np.int16)
    _, diagnostics, trace = audit.reconstruct_split(path, hz, .15)
    assert trace["candidate_cut_frames"] == [8]
    assert trace["parents"][0]["applied_cut_frames"] == [8]
    assert trace["parents"][1]["applied_cut_frames"] == []
    assert diagnostics["affected_parent_count"] == 1


@pytest.mark.parametrize("path,hz,duration", [
    (np.array([325.]), [440.], 0.),
    (np.array([-1]), [440.], 0.),
    (np.array([435]), [440.], 0.),
    (np.array([325]), [float("nan")], 0.),
    (np.array([325]), [-1.], 0.),
    (np.array([325]), [440.], .1),
    (np.array([325]), [440.], True),
    (np.array([], dtype=np.int16), [], .1),
    (np.array([325]), frequencies([82]), 0.),
])
def test_independent_reconstruction_rejects_invalid_saved_input(path, hz, duration):
    with pytest.raises(ValueError):
        audit.reconstruct_split(path, hz, duration)


def prediction(intervals, pitch=69):
    return np.asarray(intervals, dtype=float).reshape(-1, 2), np.full(len(intervals), 440 * 2 ** ((pitch - 69) / 12))


def test_pruning_harm_links_lost_matching_to_original_parent_and_pools_judgments():
    pytest.importorskip("mir_eval")
    _, _, trace = audit.reconstruct_split(fixed_path(11), frequencies([69] * 5 + [70] * 6), .1)
    parent_pitch = trace["parents"][0]["original"]["pitch"]
    reference = prediction([[0., .1]], parent_pitch)
    base = prediction([[0., .1]], parent_pitch)
    predictions = {name: base for name in audit.DIAGNOSTIC_ARMS}
    predictions[audit.ARM] = prediction([])
    detail = audit.annotation_details(reference, predictions, trace)
    assert detail["comparisons"][audit.BASE_ARM]["onset_offset"] == {
        "retained": [], "gained": [], "lost": [0], "neither": []}
    assert detail["pruning_harm"]["onset_offset"] == dict.fromkeys(audit.HARM_KEYS, 1)
    pooled = audit.summarize_annotations([detail, detail])
    assert pooled["recording_annotations"] == pooled["reference_notes"] == 2
    assert pooled["pruning_harm"]["onset_offset"] == dict.fromkeys(audit.HARM_KEYS, 2)
    assert pooled["arms"][audit.ARM]["fixed_onset_pairs"]["matched"] == 0


def test_reassignment_does_not_replace_fixed_onset_pairs():
    pytest.importorskip("mir_eval")
    reference = prediction([[0., .4], [.04, .8]])
    pred = prediction([[.03, .8]])
    arms = {name: pred for name in audit.DIAGNOSTIC_ARMS}
    trace = {"parents": [{"original": {"emitted": True, "prediction_index": 0},
                          "applied_cut_frames": [], "children": [{"emitted": True, "discard_reason": None}]}]}
    detail = audit.annotation_details(reference, arms, trace)
    value = audit.summarize_annotations([detail])["arms"][audit.ARM]
    assert value["onset_matched"] == value["offset_matched"] == 1
    assert value["fixed_onset_pairs"]["late"] == 1
    assert value["fixed_onset_pairs"]["within"] == 0


def score_rows():
    rows = []
    for number, case in enumerate(audit.CASES):
        arms = {}
        for arm in audit.ARMS:
            annotations = {}
            for ann, offset in (("A1", .02), ("A2", -.02)):
                value = .25 + (number / 100 if arm == audit.ARM else 0.) + offset
                annotations[ann] = {"onset_f1": value, "onset_offset_f1": value,
                    **dict.fromkeys(("onset_precision", "onset_recall", "offset_precision", "offset_recall"), value),
                    **{criterion + "_" + kind + "_reference_ids": [] for criterion in audit.CRITERIA for kind in ("gained", "lost")}}
            arms[arm] = {"count": 2, "annotators": annotations}
        rows.append({"id": case, "status": "scored", "arms": arms})
    return rows


def test_bootstrap_pairs_annotators_within_recordings_and_fixed_seed():
    rows = score_rows()
    actual = audit.primary_summary(rows)
    deltas = np.array([i / 100 for i in range(40)])
    draws = np.random.default_rng(296).integers(0, 40, size=(10000, 40))
    low, high = np.quantile(deltas[draws].mean(axis=1), [.025, .975], method="linear")
    assert actual["mean_delta"] == pytest.approx(.195)
    assert actual["bootstrap"]["low"] == pytest.approx(low)
    assert actual["bootstrap"]["high"] == pytest.approx(high)
    assert actual["recordings_improved"] == 39
    assert actual["recordings_tied"] == 1


def test_full_aggregate_retains_empty_zero_score_recordings():
    rows = score_rows()
    rows[0]["arms"][audit.ARM]["count"] = 0
    for ann in audit.ANNOTATORS:
        for key in ("onset_f1", "onset_offset_f1", "onset_precision", "onset_recall", "offset_precision", "offset_recall"):
            rows[0]["arms"][audit.ARM]["annotators"][ann][key] = 0.
    actual = audit.aggregate_rows(rows)[audit.ARM]
    assert actual["predicted_notes"] == 78
    assert actual["onset_f1"]["macro"] == pytest.approx((sum(.25 + i / 100 for i in range(40)) - .25) / 40)
    assert actual["onset_f1"]["recordings_worse"] == 1


@pytest.mark.parametrize("mutation", ["missing", "reordered", "missing_arm", "missing_annotator", "failed"])
def test_partial_or_reordered_corpus_cannot_gain_aggregate(mutation):
    rows = score_rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "reordered":
        rows.reverse()
    elif mutation == "missing_arm":
        rows[0]["arms"].pop(audit.ARM)
    elif mutation == "missing_annotator":
        rows[0]["arms"][audit.ARM]["annotators"].pop("A2")
    else:
        rows[0]["status"] = "failed"
    with pytest.raises(ValueError):
        audit.aggregate_rows(rows)


@pytest.mark.parametrize("actual,expected", [
    ({"count": 1, "unknown": 2}, {"count": 1}),
    ({"count": True}, {"count": 1}),
    ({"count": 1.}, {"count": 1}),
    ({"list": [1]}, {"list": [1, 2]}),
])
def test_strict_inventory_and_count_types_are_not_subset_checks(actual, expected):
    with pytest.raises(ValueError):
        audit.strict_equal(audit.Checks(), actual, expected, "owned_mutation")


def test_original_receipt_and_source_inventory_are_fixed():
    corpus, synthetic, diagnostics = audit.load_previous(audit.Checks())
    assert len(corpus["cases"]) == 40 and len(synthetic["cases"]) == 245
    assert len(diagnostics["source_sha256"]) == len(audit.FROZEN_SOURCE_PATHS) == 35
    assert len(audit.SOURCE_PATHS) == len(set(audit.SOURCE_PATHS)) == 51


def test_legacy_audit_is_bound_to_exact_report_bytes_and_script():
    raw = b'{"status":"complete"}'
    legacy = json.loads(raw)
    metadata = {"schema": "note-state-factors-audit-v1", "status": "pass", "audit_completed": True,
        "complete_prediction_files_verified": 400, "observation_arrays_verified": 440, "source_files_verified": 24,
        "report_sha256": audit.sha256(raw), "script_sha256": audit.sha256((audit.REPOSITORY / "scripts/audit_note_state_factors.py").read_bytes())}
    audit.require_legacy_audit(legacy, raw, metadata, audit.Checks())
    tampered = copy.deepcopy(metadata)
    tampered["report_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        audit.require_legacy_audit(legacy, raw, tampered, audit.Checks())


def test_no_new_reporter_or_model_imports_in_auditor():
    tree = ast.parse(Path(audit.__file__).read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    forbidden = ("note_boundary_readout", "run_note_boundary_readout", "note_boundary_readout_synthetic",
                 "note_state_hmm", "note_state_factors", "dsp_note_probe", "vocadito_reference")
    assert not any(module and module.rsplit(".", 1)[-1] in forbidden for module in imports)
    calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    assert not any(name in calls for name in ("decode_state_path", "infer_recording", "infer_factors", "labels_from_hz"))


def authored_adapter_fixture(tmp_path, monkeypatch):
    """Exercise file/schema integration on one owned example, with no inference."""
    from scripts import dsp_note_probe as dsp
    from scripts import note_boundary_readout as core
    from scripts import run_note_boundary_readout as reporter
    from scripts.audit_note_state_factors import OBSERVATIONS

    work = tmp_path / "private"
    directory = work / "vocadito_1"
    directory.mkdir(parents=True)
    hz, path, duration = frequencies([69] * 10 + [70] * 11), fixed_path(21), .2
    arrays = {name: path.copy() for name in OBSERVATIONS}
    arrays.update(hz=hz, probability=np.ones(len(hz)), rms=np.full(len(hz), .1), attacks=np.empty(0))
    np.savez_compressed(directory / "observations.npz", **arrays)
    notes, diagnostics, trace = core.notes_from_state_path(path, hz, duration)
    old_notes, _ = audit.reconstruct_readout(path, hz, duration)
    dsp.save(directory / "readout-private.json", trace)
    row = {"id": "vocadito_1", "status": "scored", "duration_seconds": duration,
        "observation_sha256": dsp.digest(directory / "observations.npz"),
        "observations": {name: audit.array_identity(value) for name, value in arrays.items()},
        "diagnostics": {}, "reference_sha256": {}, "arms": {}, "readout": diagnostics,
        "readout_private_sha256": dsp.digest(directory / "readout-private.json")}
    reference_bytes = ("0,440,.1\n.1," + str(440 * 2 ** (1 / 12)) + ",.1\n").encode()
    for ann in audit.ANNOTATORS:
        (directory / (ann + ".csv")).write_bytes(reference_bytes)
        row["reference_sha256"][ann] = audit.sha256(reference_bytes)
    for arm in audit.ARMS:
        payload = [asdict(note) for note in notes] if arm == audit.ARM else old_notes
        dsp.save(directory / (arm + ".json"), payload)
        row["arms"][arm] = {"count": len(payload), "event_sha256": dsp.digest(directory / (arm + ".json")), "annotators": {}}
        for ann in audit.ANNOTATORS:
            values, ids = reporter.frozen.matching_metrics([dsp.Note(**n) for n in payload], reference_bytes)
            _, base_ids = reporter.frozen.matching_metrics([dsp.Note(**n) for n in old_notes], reference_bytes)
            for criterion in audit.CRITERIA:
                values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[criterion])
                values[criterion + "_lost_reference_ids"] = sorted(base_ids[criterion] - ids[criterion])
            row["arms"][arm]["annotators"][ann] = values
    reporter.analyze_annotations(row, work)
    details = json.loads((directory / "annotation-private.json").read_text())
    boundary = {"by_annotator": {ann: reporter.summarize_annotations([details[ann]]) for ann in audit.ANNOTATORS},
                "pooled_annotation_judgments": reporter.summarize_annotations([details[ann] for ann in audit.ANNOTATORS])}
    manifest = audit.fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in audit.ARMS}})
    report = {"cases": [row], "aggregate": {"owned_fixture": True}, "primary_result": {"owned_fixture": True},
              "boundary_summary": boundary, "predictions_manifest_sha256": manifest,
              "post_evaluation_predictions_manifest_sha256": manifest}
    legacy = {"cases": reporter.legacy_rows([row])}
    monkeypatch.setattr(audit, "CASES", ("vocadito_1",))
    monkeypatch.setattr(audit, "aggregate_rows", lambda rows: {"owned_fixture": True})
    monkeypatch.setattr(audit, "primary_summary", lambda rows: {"owned_fixture": True})
    return work, report, legacy


def test_private_corpus_adapter_accepts_independent_reporter_schema(tmp_path, monkeypatch):
    pytest.importorskip("mir_eval")
    work, report, legacy = authored_adapter_fixture(tmp_path, monkeypatch)
    result = audit.corpus_from_private(work, report, legacy, audit.Checks())
    assert result["cases"] == [{"id": "vocadito_1", "status": "pass", "prediction_files": 11,
                                "observation_arrays": 11, "parents": 1, "applied_cuts": 1}]


@pytest.mark.parametrize("mutation", ["annotation", "trace", "event", "extra_annotation"])
def test_private_adapter_rejects_mutated_diagnostics_trace_or_event(tmp_path, monkeypatch, mutation):
    pytest.importorskip("mir_eval")
    work, report, legacy = authored_adapter_fixture(tmp_path, monkeypatch)
    row = report["cases"][0]
    if mutation == "annotation":
        row["annotation_diagnostics"]["A1"]["pruning_harm"]["onset"]["lost_references"] += 1
    elif mutation == "trace":
        path = work / "vocadito_1" / "readout-private.json"
        value = json.loads(path.read_text())
        value["candidate_cut_frames"] = []
        path.write_text(json.dumps(value, indent=2) + "\n")
        row["readout_private_sha256"] = audit.sha256(path.read_bytes())
    elif mutation == "event":
        (work / "vocadito_1" / (audit.ARM + ".json")).write_text("[]\n")
    else:
        row["annotation_diagnostics"]["A3"] = row["annotation_diagnostics"]["A1"]
    with pytest.raises(ValueError):
        audit.corpus_from_private(work, report, legacy, audit.Checks())


def preflight_fixture():
    _, previous, _ = audit.load_previous(audit.Checks())
    report = copy.deepcopy(previous)
    report["preflight"] = {"manifest_sha256": audit.NUMERIC_MANIFEST_SHA256,
        "compared_input_arrays": 245, "compared_analytic_rows": 20, "all_equal": True,
        "input_differences": [], "analytic_difference_paths": [], "model_calls_before_preflight": 0}
    return report, previous


def test_input_only_manifest_is_exact_original_metadata_and_preflight_is_bound():
    report, previous = preflight_fixture()
    result = audit.check_numeric_preflight(report, previous, audit.Checks())
    assert result["compared_input_arrays"] == 245
    assert result["compared_analytic_rows"] == 20
    assert result["model_calls_before_preflight"] == 0
    manifest = json.loads((audit.REPOSITORY / audit.NUMERIC_MANIFEST).read_text())
    assert set(manifest) == {"schema", "baseline_zip_sha256", "cases", "emission_analysis"}
    assert all(set(row) == {"id", "duration_seconds", "observation"} for row in manifest["cases"])


@pytest.mark.parametrize("mutation", ["input", "analytic", "missing_case", "models", "extra_gate", "hash", "failed_gate"])
def test_numeric_preflight_rejects_input_or_analytic_drift_and_gate_forgery(mutation):
    report, previous = preflight_fixture()
    if mutation == "input":
        report["cases"][0]["observation"]["sha256"] = "0" * 64
    elif mutation == "analytic":
        report["emission_analysis"][0]["attack_mass"] += 1e-15
    elif mutation == "missing_case":
        report["cases"].pop()
    elif mutation == "models":
        report["preflight"]["model_calls_before_preflight"] = 1
    elif mutation == "extra_gate":
        report["preflight"]["extra"] = True
    elif mutation == "hash":
        report["preflight"]["manifest_sha256"] = "0" * 64
    else:
        report["preflight"]["all_equal"] = False
    with pytest.raises(ValueError):
        audit.check_numeric_preflight(report, previous, audit.Checks())


def numeric_environment_fixture(monkeypatch):
    monkeypatch.setattr(audit, "version", lambda name: audit.EXPECTED_RUNTIME[name])
    actual = audit.observed_numerical_environment()
    actual["python"] = "3.11.99"
    actual["numpy_version"] = "1.26.4"
    monkeypatch.setattr(audit, "observed_numerical_environment", lambda: copy.deepcopy(actual))
    return actual


def test_private_numeric_environment_checks_actual_cpu_dispatch_and_module(monkeypatch):
    actual = numeric_environment_fixture(monkeypatch)
    assert audit.check_numerical_environment(actual, audit.Checks()) == actual


@pytest.mark.parametrize("field", ["python", "executable", "numpy_file", "numpy_version", "cpu_features", "cpu_dispatch", "numpy_disable_cpu_features", "runtime"])
def test_private_numeric_environment_rejects_declared_actual_mismatch(monkeypatch, field):
    actual = numeric_environment_fixture(monkeypatch)
    recorded = copy.deepcopy(actual)
    if field in ("cpu_features", "runtime"):
        recorded[field]["OWNED_EXTRA"] = True
    elif field == "cpu_dispatch":
        recorded[field] = []
    else:
        recorded[field] = "different_owned_value"
    with pytest.raises(ValueError):
        audit.check_numerical_environment(recorded, audit.Checks())
