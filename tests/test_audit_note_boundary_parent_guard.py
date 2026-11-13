"""Owned tiny controls and deliberate evidence corruption; no model grid runs."""
from __future__ import annotations

import ast
import copy
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from scripts import audit_note_boundary_parent_guard as audit


def frequencies(pitches):
    values = np.asarray(pitches, dtype=float)
    return np.where(values < 0, 0., 440 * 2 ** ((values - 69) / 12))


def fixed_path(count):
    result = np.full(count, 325, dtype=np.int16)
    if count:
        result[0] = 324
    return result


@pytest.mark.parametrize("raw,path,duration", [
    ([69] * 10 + [70] * 11, fixed_path(21), .2),
    ([69] * 5 + [70] * 6, fixed_path(11), .1),
    ([69] * 10 + [70] * 5 + [71] * 11, fixed_path(26), .25),
    ([69] * 8 + [70] * 8 + [71] * 9, fixed_path(25), .24),
    ([69] * 9 + [-1] * 2 + [70] * 10, fixed_path(21), .2),
    ([69] * 8 + [70] * 8, fixed_path(16), .155),
    ([69] * 8 + [70] * 8, fixed_path(16), .15999999995),
    ([69] * 8 + [70] * 8, fixed_path(16), .1599999998),
    ([69] * 3 + [70] * 5, fixed_path(8), .07),
    ([-1] * 11, fixed_path(11), .1),
    ([69], fixed_path(1), 0.),
    ([], fixed_path(0), 0.),
])
def test_independent_reconstruction_matches_core_on_tiny_owned_controls(raw, path, duration):
    from scripts import note_boundary_parent_guard as core

    expected, diagnostics, trace = audit.reconstruct_guard(path, frequencies(raw), duration)
    actual, actual_diagnostics, actual_trace = core.notes_from_state_path(path, frequencies(raw), duration)
    audit.exact_equal(audit.Checks(), [asdict(note) for note in actual], expected, "owned_events")
    audit.exact_equal(audit.Checks(), actual_trace, trace, "owned_decisions")
    audit.strict_equal(audit.Checks(), actual_diagnostics, diagnostics, "owned_diagnostics")


def test_one_failed_child_rejects_every_cut_and_does_not_prune_output():
    hz = frequencies([69] * 10 + [70] * 5 + [71] * 11)
    notes, diagnostics, trace = audit.reconstruct_guard(fixed_path(26), hz, .25)
    original, _ = audit.reconstruct_readout(fixed_path(26), hz, .25)
    parent = trace["parents"][0]
    assert notes == original
    assert parent["proposed_cut_frames"] == [10, 15]
    assert parent["accepted_cut_frames"] == []
    assert parent["decision"] == "rejected"
    assert [child["passes_readout"] for child in parent["proposed_children"]] == [True, False, True]
    assert all(not child["emitted"] and child["prediction_index"] is None for child in parent["proposed_children"])
    assert diagnostics["proposed"]["short_segments_discarded"] == 1
    assert diagnostics["proposed"]["emitted_notes"] == 2
    assert diagnostics["proposed"]["emitted_note_seconds"] == pytest.approx(.2)
    assert diagnostics["readout"]["short_segments_discarded"] == 0
    assert diagnostics["restored_original_event_count"] == 1
    assert diagnostics["emitted_seconds_change"] == 0


def test_accepted_children_preserve_intervals_without_preserving_pitch_or_event_count():
    hz = frequencies([69] * 8 + [70] * 8 + [71] * 9)
    notes, diagnostics, trace = audit.reconstruct_guard(fixed_path(25), hz, .24)
    original, _ = audit.reconstruct_readout(fixed_path(25), hz, .24)
    assert [note["pitch"] for note in notes] == [69, 70, 71]
    assert len(original) == 1 and len(notes) == 3
    assert audit.interval_union(notes) == audit.interval_union(original) == [[0., .24]]
    assert trace["parents"][0]["decision"] == "accepted"
    assert diagnostics["accepted_cut_count"] == 2
    assert diagnostics["baseline_interval_union_sha256"] == diagnostics["output_interval_union_sha256"]


@pytest.mark.parametrize("raw,duration,reason", [
    ([69] * 3 + [70] * 5, .07, "short"), ([-1] * 11, .1, "no_raw_support"), ([69], 0., "zero_duration"),
])
def test_nonemitted_parents_are_denominators_but_never_proposed_or_resurrected(raw, duration, reason):
    notes, diagnostics, trace = audit.reconstruct_guard(fixed_path(len(raw)), frequencies(raw), duration)
    assert not notes
    assert diagnostics["originally_nonemitted_parent_count"] == 1
    assert diagnostics["proposed_child_count"] == diagnostics["nonemitted_parents_resurrected"] == 0
    parent = trace["parents"][0]
    assert parent["decision"] == "nonemitted" and parent["proposed_cut_frames"] == []
    assert parent["original"]["discard_reason"] == reason
    assert len(parent["final_segments"]) == 1 and not parent["final_segments"][0]["emitted"]


def test_proposed_cut_is_global_backdated_five_frame_hysteresis_not_parent_local():
    hz = frequencies([69] * 8 + [70] * 8)
    path = np.array([324] + [325] * 9 + [333] + [334] * 5, dtype=np.int16)
    _, diagnostics, trace = audit.reconstruct_guard(path, hz, .15)
    assert trace["candidate_cut_frames"] == [8]
    assert trace["parents"][0]["proposed_cut_frames"] == [8]
    assert trace["parents"][1]["proposed_cut_frames"] == []
    assert diagnostics["rejected_parent_count"] == 1


def test_raw_zero_remains_a_bridge_and_does_not_create_a_new_gate():
    hz = frequencies([69] * 9 + [-1] * 2 + [70] * 10)
    notes, diagnostics, trace = audit.reconstruct_guard(fixed_path(21), hz, .2)
    old, _ = audit.reconstruct_readout(fixed_path(21), hz, .2)
    assert notes == old
    assert trace["candidate_cut_frames"] == []
    assert diagnostics["readout"]["emitted_raw_unvoiced_frames"] == 2


@pytest.mark.parametrize("duration,decision", [(.16, "accepted"), (.15999999995, "accepted"), (.1599999998, "rejected"), (.155, "rejected")])
def test_unchanged_80ms_tolerance_is_applied_after_actual_duration_clipping(duration, decision):
    _, _, trace = audit.reconstruct_guard(fixed_path(16), frequencies([69] * 8 + [70] * 8), duration)
    assert trace["parents"][0]["decision"] == decision


def test_interval_union_does_not_rely_on_summed_seconds_or_tolerance_rounding():
    events = [{"onset": 0., "offset": .1}, {"onset": .1, "offset": .2}, {"onset": .20000000000001, "offset": .3}]
    assert audit.interval_union(events) == [[0., .2], [.20000000000001, .3]]
    assert audit.interval_union(list(reversed(events))) == audit.interval_union(events)
    with pytest.raises(ValueError):
        audit.interval_union([{"onset": .1, "offset": .1}])


@pytest.mark.parametrize("path,hz,duration", [
    (np.array([325.]), [440.], 0.), (np.array([-1]), [440.], 0.),
    (np.array([435]), [440.], 0.), (np.array([325]), [float("nan")], 0.),
    (np.array([325]), [-1.], 0.), (np.array([325]), [440.], .1),
    (np.array([325]), [440.], True), (fixed_path(0), [], .1),
])
def test_invalid_saved_input_is_not_interpreted_as_a_successful_empty_output(path, hz, duration):
    with pytest.raises(ValueError):
        audit.reconstruct_guard(path, hz, duration)


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


@pytest.mark.parametrize("baseline", [audit.BASE_ARM, audit.SPLIT_ARM])
def test_bootstrap_pairs_A1_A2_within_forty_recordings_and_uses_seed298(baseline):
    actual = audit.primary_summary(score_rows(), baseline)
    deltas = np.arange(40) / 100
    draws = np.random.default_rng(298).integers(0, 40, size=(10000, 40))
    low, high = np.quantile(deltas[draws].mean(axis=1), [.025, .975], method="linear")
    assert actual["mean_delta"] == pytest.approx(.195)
    assert actual["bootstrap"]["low"] == pytest.approx(low)
    assert actual["bootstrap"]["high"] == pytest.approx(high)
    assert actual["bootstrap"]["seed"] == 298
    assert actual["recordings_improved"] == 39 and actual["recordings_tied"] == 1


@pytest.mark.parametrize("mutation", ["missing", "reordered", "missing_arm", "missing_annotator", "failed", "invalid_rate"])
def test_corpus_aggregates_require_every_recording_arm_and_annotator(mutation):
    rows = score_rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "reordered":
        rows.reverse()
    elif mutation == "missing_arm":
        rows[0]["arms"].pop(audit.ARM)
    elif mutation == "missing_annotator":
        rows[0]["arms"][audit.ARM]["annotators"].pop("A2")
    elif mutation == "failed":
        rows[0]["status"] = "failed"
    else:
        rows[0]["arms"][audit.ARM]["annotators"]["A1"]["offset_precision"] = float("nan")
    with pytest.raises(ValueError):
        audit.aggregate_rows(rows)


def test_original_completed_receipt_and_source_inventory_are_fixed():
    corpus, synthetic, previous_audit = audit.load_previous(audit.Checks())
    assert len(corpus["cases"]) == 40 and len(synthetic["cases"]) == 245
    assert previous_audit["corpus_prediction_files_verified"] == 440
    assert previous_audit["synthetic_prediction_files_verified"] == 1960
    assert len(audit.prior.SOURCE_PATHS) == 53
    assert len(audit.SOURCE_PATHS) == len(set(audit.SOURCE_PATHS)) == 66


def test_legacy_audit_is_bound_to_both_exact_reports_and_frozen_auditor():
    raw, synthetic = b'{"status":"complete"}', b'{"status":"complete","cases":[]}'
    metadata = {"schema": "note-boundary-readout-audit-v1", "status": "pass", "audit_completed": True,
        "report_sha256": audit.sha256(raw), "synthetic_report_sha256": audit.sha256(synthetic),
        "script_sha256": audit.sha256((audit.REPOSITORY / "scripts/audit_note_boundary_readout.py").read_bytes()),
        "source_files_verified": 53, "corpus_prediction_files_verified": 440,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1960, "synthetic_input_arrays_verified": 245,
        "synthetic_old_state_paths_verified": 1470, "independent_new_readouts_verified": 285}
    audit.require_legacy_audit(json.loads(raw), raw, synthetic, metadata, audit.Checks())
    mutated = copy.deepcopy(metadata)
    mutated["synthetic_report_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        audit.require_legacy_audit(json.loads(raw), raw, synthetic, mutated, audit.Checks())


def test_auditor_imports_no_new_core_runner_predictor_or_decoder():
    tree = ast.parse(Path(audit.__file__).read_text())
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    forbidden = ("note_boundary_parent_guard", "run_note_boundary_parent_guard", "note_boundary_parent_guard_synthetic",
                 "note_boundary_readout", "run_note_boundary_readout", "note_boundary_readout_synthetic",
                 "note_state_hmm", "note_state_factors", "dsp_note_probe")
    assert not any(module and module.rsplit(".", 1)[-1] in forbidden for module in modules)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in ("infer_recording", "infer_factors", "decode_state_path", "labels_from_hz")
                   for node in ast.walk(tree))


def prediction(events):
    return (np.asarray([(note["onset"], note["offset"]) for note in events], dtype=float).reshape(-1, 2),
            np.asarray([440 * 2 ** ((note["pitch"] - 69) / 12) for note in events]))


def test_parent_harm_crosswalk_counts_lost_references_not_unique_parents():
    pytest.importorskip("mir_eval")
    hz, path, duration = frequencies([69] * 10 + [70] * 5 + [71] * 11), fixed_path(26), .25
    guarded, _, trace = audit.reconstruct_guard(path, hz, duration)
    split, _, split_trace = audit.prior.reconstruct_split(path, hz, duration)
    original, _ = audit.reconstruct_readout(path, hz, duration)
    reference = prediction(split)
    predictions = {arm: prediction(original) for arm in audit.DIAGNOSTIC_ARMS}
    predictions[audit.SPLIT_ARM], predictions[audit.ARM] = prediction(split), prediction(guarded)
    details = audit.annotation_details(reference, predictions, trace, split_trace)
    harm = details["parental_harm"][audit.SPLIT_ARM]["onset_offset"]
    assert details["comparisons"][audit.SPLIT_ARM]["onset_offset"]["lost"] == [0, 1]
    assert harm["lost_references"] == harm["lost_matched_parent_rejected"] == 2
    assert harm["lost_matched_parent_with_proposed_short_children"] == 2
    assert harm["lost_matched_parent_final_empty"] == 0
    assert [row["parent_id"] for row in harm["lost_reference_parents"]] == [0, 0]
    pooled = audit.summarize_annotations([details, details])
    assert pooled["parental_harm"][audit.SPLIT_ARM]["onset_offset"]["lost_references"] == 4
    assert pooled["recording_annotations"] == 2 and pooled["reference_notes"] == 4


def test_accepted_false_split_can_lose_G_match_despite_exact_coverage():
    pytest.importorskip("mir_eval")
    hz, path, duration = frequencies([69] * 10 + [70] * 11), fixed_path(21), .2
    guarded, _, trace = audit.reconstruct_guard(path, hz, duration)
    split, _, split_trace = audit.prior.reconstruct_split(path, hz, duration)
    original, _ = audit.reconstruct_readout(path, hz, duration)
    reference = prediction(original)
    predictions = {arm: prediction(original) for arm in audit.DIAGNOSTIC_ARMS}
    predictions[audit.SPLIT_ARM], predictions[audit.ARM] = prediction(split), prediction(guarded)
    details = audit.annotation_details(reference, predictions, trace, split_trace)
    harm = details["parental_harm"][audit.BASE_ARM]["onset_offset"]
    assert harm["lost_references"] == harm["lost_matched_parent_accepted"] == 1
    assert harm["lost_matched_parent_with_proposed_short_children"] == harm["lost_matched_parent_rejected"] == 0
    assert audit.interval_union(guarded) == audit.interval_union(original)


def authored_corpus_fixture(tmp_path, monkeypatch):
    from scripts import dsp_note_probe as dsp
    from scripts import note_boundary_parent_guard as core
    from scripts import note_boundary_readout as split_core
    from scripts import run_note_boundary_parent_guard as reporter
    from scripts.audit_note_state_factors import OBSERVATIONS

    work, duration = tmp_path / "private", .25
    directory = work / "vocadito_1"
    directory.mkdir(parents=True)
    hz, path = frequencies([69] * 10 + [70] * 5 + [71] * 11), fixed_path(26)
    arrays = {name: path.copy() for name in OBSERVATIONS}
    arrays.update(hz=hz, probability=np.ones(len(hz)), rms=np.full(len(hz), .1), attacks=np.empty(0))
    np.savez_compressed(directory / "observations.npz", **arrays)
    original, _ = audit.reconstruct_readout(path, hz, duration)
    split, readout, split_trace = split_core.notes_from_state_path(path, hz, duration)
    guarded, guard, trace = core.notes_from_state_path(path, hz, duration)
    dsp.save(directory / "readout-private.json", split_trace)
    dsp.save(directory / "guard-private.json", trace)
    row = {"id": "vocadito_1", "status": "scored", "duration_seconds": duration,
        "observation_sha256": dsp.digest(directory / "observations.npz"),
        "observations": {name: audit.array_identity(value) for name, value in arrays.items()},
        "diagnostics": {}, "reference_sha256": {}, "arms": {}, "readout": readout,
        "readout_private_sha256": dsp.digest(directory / "readout-private.json"), "guard": guard,
        "guard_private_sha256": dsp.digest(directory / "guard-private.json")}
    reference = f"0,{440},.1\n.15,{440 * 2 ** (2 / 12)},.1\n".encode()
    for ann in audit.ANNOTATORS:
        (directory / (ann + ".csv")).write_bytes(reference)
        row["reference_sha256"][ann] = audit.sha256(reference)
    payloads = {arm: original for arm in audit.ARMS}
    payloads["pitch_runs"] = audit.reconstruct_pitch_runs(hz, duration)
    payloads[audit.SPLIT_ARM], payloads[audit.ARM] = [asdict(note) for note in split], [asdict(note) for note in guarded]
    for arm in audit.ARMS:
        payload = payloads[arm]
        dsp.save(directory / (arm + ".json"), payload)
        row["arms"][arm] = {"count": len(payload), "event_sha256": dsp.digest(directory / (arm + ".json")), "annotators": {}}
        for ann in audit.ANNOTATORS:
            values, ids = reporter.frozen.matching_metrics([dsp.Note(**note) for note in payload], reference)
            _, base_ids = reporter.frozen.matching_metrics([dsp.Note(**note) for note in payloads["pitch_runs"]], reference)
            for criterion in audit.CRITERIA:
                values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[criterion])
                values[criterion + "_lost_reference_ids"] = sorted(base_ids[criterion] - ids[criterion])
            row["arms"][arm]["annotators"][ann] = values
    reporter.previous_study.analyze_annotations(row, work)
    reporter.analyze_annotations(row, work)
    details = json.loads((directory / "guard-annotation-private.json").read_text())
    boundary = {"by_annotator": {ann: reporter.summarize_annotations([details[ann]]) for ann in audit.ANNOTATORS},
                "pooled_annotation_judgments": reporter.summarize_annotations([details[ann] for ann in audit.ANNOTATORS])}
    manifest = audit.fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in audit.ARMS}})
    report = {"cases": [row], "aggregate": {"owned_fixture": True}, "primary_result": {"owned_fixture": True},
        "secondary_result": {"owned_fixture": True}, "boundary_summary": boundary,
        "predictions_manifest_sha256": manifest, "post_evaluation_predictions_manifest_sha256": manifest}
    legacy = {"cases": reporter.legacy_rows([row])}
    monkeypatch.setattr(audit, "CASES", ("vocadito_1",))
    monkeypatch.setattr(audit, "aggregate_rows", lambda rows: {"owned_fixture": True})
    monkeypatch.setattr(audit, "primary_summary", lambda rows, baseline=audit.BASE_ARM: {"owned_fixture": True})
    return work, report, legacy


def test_private_corpus_adapter_accepts_actual_reporter_file_schema(tmp_path, monkeypatch):
    pytest.importorskip("mir_eval")
    work, report, legacy = authored_corpus_fixture(tmp_path, monkeypatch)
    result = audit.corpus_from_private(work, report, legacy, audit.Checks())
    assert result["cases"] == [{"id": "vocadito_1", "status": "pass", "prediction_files": 12,
        "observation_arrays": 11, "parents": 1, "proposed_cuts": 2, "accepted_cuts": 0,
        "rejected_parents": 1, "interval_union_preserved": True}]


@pytest.mark.parametrize("mutation", ["proposal_count", "trace", "event", "crosswalk", "extra_annotation", "manifest"])
def test_private_corpus_adapter_rejects_rehashed_semantic_corruption(tmp_path, monkeypatch, mutation):
    pytest.importorskip("mir_eval")
    work, report, legacy = authored_corpus_fixture(tmp_path, monkeypatch)
    row, directory = report["cases"][0], work / "vocadito_1"
    if mutation == "proposal_count":
        row["guard"]["proposed"]["emitted_notes"] = row["guard"]["readout"]["emitted_notes"]
    elif mutation == "trace":
        path = directory / "guard-private.json"
        payload = json.loads(path.read_text())
        payload["parents"][0]["decision"] = "accepted"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        row["guard_private_sha256"] = audit.sha256(path.read_bytes())
    elif mutation == "event":
        path = directory / (audit.ARM + ".json")
        path.write_text("[]\n")
        row["arms"][audit.ARM].update(count=0, event_sha256=audit.sha256(path.read_bytes()))
        manifest = audit.fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in audit.ARMS}})
        report["predictions_manifest_sha256"] = report["post_evaluation_predictions_manifest_sha256"] = manifest
    elif mutation == "crosswalk":
        path = directory / "guard-annotation-private.json"
        payload = json.loads(path.read_text())
        payload["A1"]["parental_harm"][audit.SPLIT_ARM]["onset_offset"]["lost_reference_parents"][0]["parent_id"] = 1
        path.write_text(json.dumps(payload, indent=2) + "\n")
        row["guard_annotation_private_sha256"] = audit.sha256(path.read_bytes())
    elif mutation == "extra_annotation":
        row["guard_annotation_diagnostics"]["A3"] = row["guard_annotation_diagnostics"]["A1"]
    else:
        report["predictions_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        audit.corpus_from_private(work, report, legacy, audit.Checks())


def preflight_fixture():
    _, previous, _ = audit.load_previous(audit.Checks())
    rows = copy.deepcopy(previous["cases"])
    for spec in audit.stress_specs():
        hz, duration = audit.stress_observations(spec)
        rows.append({"id": spec["id"], "duration_seconds": duration, "observation": audit.array_identity(hz)})
    report = {"cases": rows, "emission_analysis": copy.deepcopy(previous["emission_analysis"]),
        "stress_timing_semantics": audit.TIMING_SEMANTICS,
        "preflight": {"schema": "note-boundary-parent-guard-preflight-v1", "legacy": copy.deepcopy(previous["preflight"]),
            "stress": {"manifest_sha256": audit.NUMERIC_MANIFEST_SHA256, "compared_input_arrays": 216,
                "all_equal": True, "input_differences": [], "model_calls_before_preflight": 0},
            "compared_input_arrays": 461, "compared_analytic_rows": 20, "all_equal": True, "model_calls_before_preflight": 0}}
    return report, previous


def test_both_input_only_manifests_bind_original245_and_new216_without_inference():
    report, previous = preflight_fixture()
    result = audit.check_numeric_preflight(report, previous, audit.Checks())
    assert result["compared_input_arrays"] == 461 and result["model_calls_before_preflight"] == 0
    assert result["legacy"]["compared_input_arrays"] == 245
    assert result["stress"]["compared_input_arrays"] == 216


@pytest.mark.parametrize("mutation", ["stress_input", "legacy_input", "missing", "models", "stress_models", "extra_gate", "legacy_analytic"])
def test_numeric_preflight_rejects_drift_or_unfrozen_extra_fields(mutation):
    report, previous = preflight_fixture()
    if mutation in ("stress_input", "legacy_input"):
        report["cases"][245 if mutation == "stress_input" else 0]["observation"]["sha256"] = "0" * 64
    elif mutation == "missing":
        report["cases"].pop()
    elif mutation == "models":
        report["preflight"]["model_calls_before_preflight"] = 1
    elif mutation == "stress_models":
        report["preflight"]["stress"]["model_calls_before_preflight"] = 1
    elif mutation == "extra_gate":
        report["preflight"]["new_parameter"] = .075
    else:
        report["emission_analysis"][0]["attack_mass"] += 1e-15
    with pytest.raises(ValueError):
        audit.check_numeric_preflight(report, previous, audit.Checks())


@pytest.mark.parametrize("index", [0, 17, 53, 107, 108, 161, 215])
def test_new_grid_inputs_and_truth_match_the_authored_specification(index):
    from scripts import note_boundary_parent_guard_synthetic as authored

    spec, case = audit.stress_specs()[index], authored.stress_cases()[index]
    actual_hz, actual_duration = authored.observations(case)
    hz, duration = audit.stress_observations(spec)
    assert actual_duration == duration and np.array_equal(actual_hz, hz)
    assert hz.shape == (spec["frames"] + 21,)
    assert np.count_nonzero(hz) == spec["frames"] and hz[-1] == 0
    assert [asdict(note) for note in authored.truth(case)] == audit.stress_truth(spec)
    assert audit.stress_truth(spec)[0]["pitch"] == spec["pitch"] + spec["detuning"]


def test_source_contract_matches_runner_and_keeps_all53_previous_sources():
    from scripts import run_note_boundary_parent_guard as reporter

    previous, _, _ = audit.load_previous(audit.Checks())
    assert audit.SOURCE_PATHS == reporter.SOURCE_PATHS
    assert audit.GUARD_SETTINGS == reporter.SETTINGS
    assert audit.HARM_KEYS == reporter.HARM_KEYS
    for name in audit.prior.SOURCE_PATHS:
        assert audit.sha256((audit.REPOSITORY / name).read_bytes()) == previous["source_sha256"][name]


def authored_synthetic_fixture(tmp_path, monkeypatch):
    """Two tiny saved cases exercise adapter plumbing, not a performance grid."""
    from scripts import dsp_note_probe as dsp
    from scripts import note_boundary_parent_guard as core
    from scripts import note_boundary_parent_guard_synthetic as reporter
    from scripts import note_boundary_readout as split_core

    work = tmp_path / "owned-synthetic"
    work.mkdir()
    _, previous, _ = audit.load_previous(audit.Checks())
    stress = reporter.stress_cases()[0]
    plans = [("owned_legacy", {"id": "owned_legacy", "kind": "single", "pitch": 70, "frames": 25},
        frequencies([69] * 10 + [70] * 5 + [71] * 11), .25, [dsp.Note(70, 0., .25)], "legacy"),
        (stress.id, asdict(stress), *reporter.observations(stress), reporter.truth(stress), stress.kind)]
    rows = []
    for case_id, spec, hz, duration, reference, cohort in plans:
        directory = work / case_id
        directory.mkdir()
        path = fixed_path(len(hz))
        arrays = {name: path.copy() for name in audit.prior.SYNTHETIC_OLD_ARMS[1:]}
        np.savez_compressed(directory / "observations.npz", hz=hz, **arrays)
        old, counts = audit.reconstruct_readout(path, hz, duration)
        split, readout, split_trace = split_core.notes_from_state_path(path, hz, duration)
        guard, guard_public, guard_trace = core.notes_from_state_path(path, hz, duration)
        dsp.save(directory / "readout-private.json", split_trace)
        dsp.save(directory / "guard-private.json", guard_trace)
        raw, voiced = hz > 0, path % 3 != 2
        path_diagnostics = {**counts, "viterbi_path_log_weight": 0.,
            "raw_voiced_to_silent_frames": int((raw & ~voiced).sum()),
            "raw_unvoiced_to_voiced_frames": int((~raw & voiced).sum()),
            "voiced_coverage": float((raw & voiced).sum() / raw.sum())}
        row = {"id": case_id, "spec": spec, "duration_seconds": duration, "accuracy_eligible": True,
            "observation": audit.array_identity(hz), "readout_private_sha256": dsp.digest(directory / "readout-private.json"),
            "arms": {}, "truth": [asdict(note) for note in reference], "alternative_truth": [],
            "cohort": cohort, "guard_private_sha256": dsp.digest(directory / "guard-private.json"), "note_evaluation": {}}
        for arm in audit.SYNTHETIC_ARMS:
            events = ([asdict(note) for note in guard] if arm == audit.ARM
                      else [asdict(note) for note in split] if arm == audit.SPLIT_ARM
                      else audit.reconstruct_pitch_runs(hz, duration) if arm == "pitch_runs" else old)
            dsp.save(directory / (arm + ".json"), events)
            item = {"count": len(events), "event_sha256": dsp.digest(directory / (arm + ".json")), "events": events}
            if arm in (audit.ARM, audit.SPLIT_ARM):
                item.update(readout=guard_public if arm == audit.ARM else readout,
                    shared_state_path=audit.array_identity(path), shared_state_path_arm=audit.BASE_ARM)
            elif arm == "pitch_runs":
                item["diagnostics"] = {"predicted_notes": len(events)}
            else:
                item.update(diagnostics=copy.deepcopy(path_diagnostics), state_path=audit.array_identity(path))
            notes = [dsp.Note(**event) for event in events]
            item["metrics"] = reporter.frozen.score(notes, reference)
            row["arms"][arm] = item
            row["note_evaluation"][arm] = reporter.note_evaluation(notes, reference)
        row["comparison"] = reporter.previous.compare_case(row)
        row["guard_comparisons"] = {base: reporter.compare_case(row, base) for base in (audit.BASE_ARM, audit.SPLIT_ARM)}
        rows.append(row)
    additions = {"cohort", "guard_private_sha256", "guard_comparisons", "note_evaluation"}
    old_row = {key: copy.deepcopy(value) for key, value in rows[0].items() if key not in additions}
    old_row["arms"] = {arm: copy.deepcopy(rows[0]["arms"][arm]) for arm in audit.SYNTHETIC_OLD_ARMS}
    old_manifest = audit.fingerprint({old_row["id"]: {arm: old_row["arms"][arm]["event_sha256"] for arm in audit.SYNTHETIC_OLD_ARMS}})
    previous.update(cases=[old_row], aggregate={"owned_legacy": True}, comparisons={"owned_legacy": True},
        predictions_manifest_sha256=old_manifest, post_evaluation_predictions_manifest_sha256=old_manifest, elapsed_seconds=.1)
    legacy = copy.deepcopy(previous)
    manifest = audit.fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in audit.SYNTHETIC_ARMS} for row in rows})
    report = copy.deepcopy(previous)
    report.update(schema="note-boundary-parent-guard-synthetic-v1", planned_cases=461,
        planned_arms=list(audit.SYNTHETIC_ARMS), cases=rows, stress_timing_semantics=audit.TIMING_SEMANTICS,
        cohorts={"owned_population": True}, aggregate={"owned_new": True}, comparisons={"owned_new": True},
        source_sha256={**previous["source_sha256"], **dict.fromkeys(audit.NEW_SOURCE_PATHS, "0" * 64)},
        preflight={"legacy": previous["preflight"]}, predictions_manifest_sha256=manifest,
        post_evaluation_predictions_manifest_sha256=manifest, truth_access_started_after_prediction_files=4149,
        elapsed_seconds=.2, historical_parity={"baseline_zip_sha256": audit.PREVIOUS_SHA256,
            "compared_prediction_files": 1960, "compared_input_arrays": 245, "compared_state_paths": 1470,
            "all_equal": True, "differences": []})
    monkeypatch.setattr(audit, "synthetic_population", lambda rows, previous: {"owned_population": True})
    monkeypatch.setattr(audit, "synthetic_aggregate", lambda rows, previous: {"owned_new": True})
    monkeypatch.setattr(audit, "synthetic_comparisons", lambda rows, previous: {"owned_new": True})
    monkeypatch.setattr(audit.prior, "synthetic_aggregate", lambda rows: {"owned_legacy": True})
    monkeypatch.setattr(audit.prior, "synthetic_comparisons", lambda rows: {"owned_legacy": True})
    return work, report, legacy, previous


def test_private_synthetic_adapter_accepts_owned_files_and_real_scoring_schema(tmp_path, monkeypatch):
    pytest.importorskip("mir_eval")
    work, report, legacy, previous = authored_synthetic_fixture(tmp_path, monkeypatch)
    result = audit.synthetic_from_private(work, report, legacy, previous, audit.Checks())
    assert result["predictions_manifest_sha256"] == report["predictions_manifest_sha256"]
    assert result["historical_parity"]["all_equal"] is True


@pytest.mark.parametrize("mutation", ["rounded_truth", "guard_diagnostic", "pitch_pairs", "legacy_payload", "cut_trace"])
def test_synthetic_adapter_rejects_truth_diagnostic_or_projection_corruption(tmp_path, monkeypatch, mutation):
    pytest.importorskip("mir_eval")
    work, report, legacy, previous = authored_synthetic_fixture(tmp_path, monkeypatch)
    row = report["cases"][1]
    if mutation == "rounded_truth":
        row["truth"][0]["pitch"] = int(round(row["truth"][0]["pitch"]))
    elif mutation == "guard_diagnostic":
        row["arms"][audit.ARM]["readout"]["output_interval_union_preserved"] = False
    elif mutation == "pitch_pairs":
        row["note_evaluation"][audit.ARM]["timing_only_unmatched_reference_notes"] += 1
    elif mutation == "legacy_payload":
        legacy["cases"][0]["comparison"]["predicted_notes_change"] += 1
    else:
        path = work / row["id"] / "guard-private.json"
        payload = json.loads(path.read_text())
        payload["candidate_cut_frames"].append(12)
        path.write_text(json.dumps(payload, indent=2) + "\n")
        row["guard_private_sha256"] = audit.sha256(path.read_bytes())
    with pytest.raises(ValueError):
        audit.synthetic_from_private(work, report, legacy, previous, audit.Checks())


def synthetic_population_fixture():
    _, previous, _ = audit.load_previous(audit.Checks())
    rows = [dict(row, cohort="legacy", arms={**row["arms"], audit.ARM: {}}) for row in previous["cases"]]
    rows.extend({"id": spec["id"], "spec": spec, "cohort": spec["kind"], "accuracy_eligible": True,
                 "arms": dict.fromkeys(audit.SYNTHETIC_ARMS, {})} for spec in audit.stress_specs())
    return rows, previous["cases"]


def test_full_synthetic_population_contract_uses_exact_separate_denominators():
    rows, previous = synthetic_population_fixture()
    result = audit.synthetic_population(rows, previous)
    assert result == {"legacy": {"all_cases": 245, "accuracy_eligible_cases": 227, "ambiguous_cases": 15, "silence_cases": 3},
        "single_expression": {"all_cases": 108, "accuracy_eligible_cases": 108},
        "adjacent_semitone": {"all_cases": 108, "accuracy_eligible_cases": 108}}


@pytest.mark.parametrize("mutation", ["missing", "reordered", "missing_arm", "cohort", "nonboolean", "spec"])
def test_full_population_rejects_subset_selection_or_spec_changes(mutation):
    rows, previous = synthetic_population_fixture()
    if mutation == "missing":
        rows.pop()
    elif mutation == "reordered":
        rows[245], rows[246] = rows[246], rows[245]
    elif mutation == "missing_arm":
        rows[-1]["arms"].pop(audit.ARM)
    elif mutation == "cohort":
        rows[-1]["cohort"] = "single_expression"
    elif mutation == "nonboolean":
        rows[-1]["accuracy_eligible"] = 1
    else:
        rows[-1]["spec"]["amplitude"] = .7
    with pytest.raises(ValueError):
        audit.synthetic_population(rows, previous)
