"""Independent factor auditor contracts use owned toy evidence, never corpus inference."""

from __future__ import annotations

import copy
import io
import json
import wave
import zipfile

import numpy as np
import pytest

from scripts import audit_note_state_factors as audit


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def npz_bytes(arrays):
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    return stream.getvalue()


def observations():
    hz = np.full(101, 440.)
    hz[[0, -1]] = 0
    path = np.full(101, 325, dtype=np.int16)
    path[[0, -1]], path[1] = 326, 324
    return {"hz": hz, "probability": np.where(hz > 0, .9, 0.),
            "attacks": np.array([.5]), "rms": np.full(101, .2),
            "phase_path": path, "rms_phase_path": path.copy(),
            **{arm + "_path": path.copy() for arm in audit.FACTOR_ARMS}}


def diagnostic():
    return {
        "frames": 101, "raw_voiced_frames": 99, "decoded_voiced_frames": 99,
        "attack_frames": 1, "stable_frames": 98, "silent_frames": 2,
        "decoded_voiced_over_raw_unvoiced_frames": 0, "raw_voiced_decoded_silent_frames": 0,
        "segments_before_filter": 1, "emitted_notes": 1,
        "segments_without_raw_voiced_support": 0, "zero_duration_segments": 0,
        "short_segments_discarded": 0, "short_segments_discarded_seconds": 0.,
        "attack_only_segments": 0, "segments_touching_audio_start": 0,
        "segments_touching_audio_end": 1, "emitted_notes_with_raw_unvoiced_frames": 0,
        "emitted_raw_unvoiced_frames": 0, "emitted_note_seconds": .99,
    }


def perfect_metrics():
    return {
        "reference_note_count": 1, "onset_f1": 1., "onset_offset_f1": 1.,
        "onset_matched": 1, "onset_offset_matched": 1,
        **dict.fromkeys(audit.RATES, 1.),
        **{prefix + "_unmatched_" + population: 0
           for prefix in ("onset", "onset_offset") for population in ("reference", "prediction")},
        **{prefix + "_" + kind + "_reference_ids": []
           for prefix in ("onset", "onset_offset") for kind in ("gained", "lost")},
    }


def write_zip(path, report, companion):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("vocadito.json", encoded(report))
        archive.writestr(companion, b'{"fixture_only": true}\n')


def private_fixture(tmp_path, monkeypatch):
    pytest.importorskip("mir_eval")
    pytest.importorskip("soundfile")
    repository, work = tmp_path / "owned-repository", tmp_path / "private"
    repository.mkdir()
    work.mkdir()
    monkeypatch.setattr(audit, "REPOSITORY", repository)
    for relative in audit.SOURCE_PATHS:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("owned fixture source: " + relative).encode())
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(32000))
    audio, arrays = wav.getvalue(), observations()
    npz = npz_bytes(arrays)
    note = {"pitch": 69, "onset": .01, "offset": 1., "is_drum": False}
    notes, reference = encoded([note]), b".01,440,.99\n"
    f0 = "".join(f"{i / 100:.2f},{hz}\n" for i, hz in enumerate(arrays["hz"])).encode()
    f0_metrics = {"Voicing Recall": 1., "Voicing False Alarm": 0., "Raw Pitch Accuracy": 1.,
                  "Raw Chroma Accuracy": 1., "Overall Accuracy": 1.,
                  "octave_errors_per_reference_voiced_frame": 0., "reference_voiced_frames": 99,
                  "reference_voiced_outside_55_880_hz": 0, "predicted_voiced_fraction": 99 / 101}
    legacy_diagnostics = {
        "viterbi_path_log_weight": -1000.,
        "arms": {arm: diagnostic() for arm in audit.LEGACY_ARMS[-2:]},
        "rms": {"rms_rise_candidates": 0, "rms_frames_changed_to_silent": 0,
                "rms_candidates_already_silent": 0},
    }
    rows, manifest = [], {}
    for case in audit.CASES:
        directory = work / case
        directory.mkdir()
        (directory / "source.wav").write_bytes(audio)
        (directory / "observations.npz").write_bytes(npz)
        (directory / "f0.csv").write_bytes(f0)
        for ann in audit.ANNOTATORS:
            (directory / (ann + ".csv")).write_bytes(reference)
        arms, manifest[case] = {}, {}
        for arm in audit.ARMS:
            (directory / (arm + ".json")).write_bytes(notes)
            arms[arm] = {"count": 1, "event_sha256": audit.sha256(notes),
                         "annotators": {ann: perfect_metrics() for ann in audit.ANNOTATORS}}
            manifest[case][arm] = audit.sha256(notes)
        rows.append({
            "id": case, "status": "scored", "arms": arms, "duration_seconds": 1.,
            "audio_sha256": audit.sha256(audio), "observation_sha256": audit.sha256(npz),
            "observations": {key: audit.array_identity(value) for key, value in arrays.items()},
            "diagnostics": {"legacy": copy.deepcopy(legacy_diagnostics),
                            "factors": {arm: diagnostic() for arm in audit.FACTOR_ARMS}},
            "reference_sha256": {ann: audit.sha256(reference) for ann in audit.ANNOTATORS},
            "f0_reference_sha256": audit.sha256(f0), "f0_metrics": copy.deepcopy(f0_metrics),
        })
    archive_sha = "a" * 64
    baseline_rows = copy.deepcopy(rows)
    for row in baseline_rows:
        row["arms"] = {arm: row["arms"][arm] for arm in audit.LEGACY_ARMS[:3]}
        for value in row["arms"].values():
            for ann, metrics in value["annotators"].items():
                value["annotators"][ann] = {key: metrics[key] for key in (
                    "reference_note_count", "onset_f1", "onset_offset_f1", "onset_matched",
                    "onset_precision", "onset_recall")}
                value["annotators"][ann].update(unmatched_reference=0, unmatched_prediction=0)
    baseline = {
        "status": "complete", "all_cases_complete": True, "cases": baseline_rows,
        "archive_sha256": archive_sha,
        "script_sha256": audit.sha256((repository / "scripts/dsp_note_probe.py").read_bytes()),
        "scorer_sha256": audit.sha256((repository / "scripts/vocadito_reference.py").read_bytes()),
        "f0_scorer_sha256": audit.sha256((repository / "scripts/run_cpu_vocadito_candidates.py").read_bytes()),
    }
    baseline_path = repository / audit.BASELINE_RECEIPT
    write_zip(baseline_path, baseline, "synthetic.json")
    monkeypatch.setattr(audit, "BASELINE_ZIP_SHA256", audit.sha256(baseline_path.read_bytes()))
    old_rows = copy.deepcopy(rows)
    for row in old_rows:
        row["arms"] = {arm: row["arms"][arm] for arm in audit.LEGACY_ARMS}
        row["observations"] = {name: row["observations"][name] for name in audit.LEGACY_OBSERVATIONS}
        row["diagnostics"] = row["diagnostics"]["legacy"]
    old = {"status": "complete", "all_cases_complete": True, "cases": old_rows,
           "archive_sha256": archive_sha, "f0_settings": {"fixture_only": True},
           "hmm_settings": {"fixture_only": True},
           "source_sha256": {name: audit.sha256((repository / name).read_bytes())
                             for name in audit.LEGACY_SOURCE_PATHS}}
    previous_path = repository / audit.HMM_RECEIPT
    write_zip(previous_path, old, "audit.json")
    monkeypatch.setattr(audit, "HMM_ZIP_SHA256", audit.sha256(previous_path.read_bytes()))
    aggregate = {}
    for arm in audit.ARMS:
        aggregate[arm] = {"predicted_notes": 40, **dict.fromkeys(audit.RATES, 1.)}
        for metric in audit.METRICS:
            aggregate[arm][metric] = {
                "macro": 1., "A1_macro": 1., "A2_macro": 1., "delta_vs_runs": 0.,
                "recordings_improved": 0, "recordings_worse": 0, "recordings_tied": 40,
            }
        aggregate[arm].update({prefix + "_" + kind + "_reference_count": 0
                               for prefix in ("onset", "onset_offset") for kind in ("gained", "lost")})
    report = {
        "schema": "note-state-factors-v1", "status": "complete", "all_cases_complete": True,
        "all_predictions_frozen_before_references": True,
        "reference_access_started_after_predicted_cases": 40,
        "planned_case_ids": list(audit.CASES), "planned_arms": list(audit.ARMS),
        "primary_comparison": copy.deepcopy(audit.PRIMARY), "quality_approved": False,
        "heldout_generalization": False, "product_changes": False,
        "reference_used_for_edits": False, "device": "cpu", "threads": 2,
        "source_sha256": {name: audit.sha256((repository / name).read_bytes()) for name in audit.SOURCE_PATHS},
        "runtime": audit.EXPECTED_RUNTIME.copy(), "archive_sha256": archive_sha,
        "f0_settings": {"fixture_only": True}, "hmm_settings": {"fixture_only": True},
        "factor_settings": {
            "model": "fixed_one_factor_note_state_diagnostics", "factor_arms": list(audit.FACTOR_ARMS),
            "legacy_config": copy.deepcopy(audit.LEGACY_FACTOR_CONFIG),
            "factor_configs": copy.deepcopy(audit.FACTOR_CONFIGS),
            "legacy_base_settings": {"fixture_only": True}, "rms_postprocess": False,
            "primary_factor": "gaussian_exponent_1", "upstream_reproduction": False,
        }, "cases": rows, "aggregate": aggregate,
        "predictions_manifest_sha256": audit.fingerprint(manifest),
        "post_evaluation_predictions_manifest_sha256": audit.fingerprint(manifest),
        "historical_hmm_parity": {
            "baseline_zip_sha256": audit.HMM_ZIP_SHA256,
            "source_checks": dict.fromkeys((*audit.LEGACY_SOURCE_PATHS, "archive"), True),
            "differences": [], "all_equal": True, "compared_observation_arrays": 240,
            "compared_prediction_files": 200, "raw_historical_arrays_available": False,
            "array_identity_available": True,
        },
        "historical_baseline_parity": {
            "baseline_zip_sha256": audit.BASELINE_ZIP_SHA256,
            "source_checks": dict.fromkeys(("archive", "extractor", "scorer", "f0_scorer"), True),
            "differences": [], "all_equal": True, "raw_historical_f0_bytes_available": False,
        },
        "primary_result": {**audit.PRIMARY,
            "paired_recording_deltas": [{"id": case, "delta": 0.} for case in audit.CASES],
            "mean_delta": 0., "recordings_improved": 0, "recordings_worse": 0, "recordings_tied": 40,
            "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2", "seed": 291,
                          "resamples": 10000, "confidence_level": .95,
                          "method": "paired_percentile_linear", "low": 0., "high": 0.},
            "heldout_generalization": False},
    }
    report_path = tmp_path / "report.json"
    report_path.write_bytes(encoded(report))
    return work, report_path, report


def test_complete_private_audit_reconstructs_and_rescores_every_arm(tmp_path, monkeypatch):
    work, report_path, _ = private_fixture(tmp_path, monkeypatch)
    result = audit.audit_private(work, report_path)
    assert result["status"] == "pass"
    assert result["source_files_verified"] == 24
    assert result["observation_arrays_verified"] == 440
    assert result["complete_prediction_files_verified"] == 400
    assert result["path_readouts_verified"] == 280
    assert result["human_reference_files_verified"] == 80
    assert result["f0_reference_files_verified_and_rescored"] == 40
    assert result["historical_parity_independently_recomputed"] is True
    assert result["historical_observation_identities_verified"] == 240
    assert result["historical_hmm_prediction_files_verified"] == 200
    assert result["original_dsp_prediction_files_verified"] == 120
    assert result["segmentation_model_calls"] == result["pyin_calls"] == 0
    assert result["primary_result"]["mean_delta"] == 0
    assert result["maximum_numeric_difference"] < 1e-10


@pytest.mark.parametrize("damage", [
    "prediction", "reference", "missing_arm", "bad_score", "path_count", "path_readout", "factor_log_weight",
    "missing_diagnostic", "array_hash", "array_path", "missing_observation_hash",
    "source_missing", "source_extra", "source_bytes", "legacy_source_changed",
    "hmm_parity_false", "dsp_parity_false", "missing_parity", "missing_parity_count",
    "missing_parity_source", "old_array_identity", "receipt_hash", "missing_rate", "gain_total",
    "unmatched_count", "primary_mean", "bootstrap_bound", "barrier", "f0_score", "runtime", "factor_setting",
])
def test_tampered_private_evidence_or_public_contract_fails_closed(tmp_path, monkeypatch, damage):
    work, report_path, report = private_fixture(tmp_path, monkeypatch)
    row, arm = report["cases"][0], audit.FACTOR_ARMS[-1]
    directory = work / audit.CASES[0]
    if damage == "prediction":
        (directory / (arm + ".json")).write_bytes(encoded([]))
    elif damage == "reference":
        (directory / "A1.csv").write_bytes(b"0,440,1\n")
    elif damage == "missing_arm":
        del row["arms"][arm]
    elif damage == "bad_score":
        row["arms"][arm]["annotators"]["A1"]["onset_f1"] = .9
    elif damage == "path_count":
        row["diagnostics"]["factors"][arm]["decoded_voiced_frames"] -= 1
    elif damage == "factor_log_weight":
        row["diagnostics"]["factors"][arm]["viterbi_path_log_weight"] = True
    elif damage == "path_readout":
        raw = encoded([{ "pitch": 69, "onset": 0., "offset": 1., "is_drum": False}])
        (directory / (arm + ".json")).write_bytes(raw)
        row["arms"][arm]["event_sha256"] = audit.sha256(raw)
    elif damage == "missing_diagnostic":
        del row["diagnostics"]["factors"][arm]["short_segments_discarded"]
    elif damage in ("array_hash", "array_path"):
        arrays = observations()
        arrays[arm + "_path"][-1] = 324
        raw = npz_bytes(arrays)
        (directory / "observations.npz").write_bytes(raw)
        row["observation_sha256"] = audit.sha256(raw)
        if damage == "array_path":
            row["observations"][arm + "_path"] = audit.array_identity(arrays[arm + "_path"])
    elif damage == "missing_observation_hash":
        del row["observation_sha256"]
    elif damage == "source_missing":
        del report["source_sha256"][audit.SOURCE_PATHS[-1]]
    elif damage == "source_extra":
        report["source_sha256"]["unplanned.py"] = "0" * 64
    elif damage in ("source_bytes", "legacy_source_changed"):
        source = "scripts/dsp_note_probe.py"
        (audit.REPOSITORY / source).write_bytes(b"changed extractor")
        if damage == "legacy_source_changed":
            report["source_sha256"][source] = audit.sha256(b"changed extractor")
    elif damage == "hmm_parity_false":
        report["historical_hmm_parity"]["all_equal"] = False
    elif damage == "dsp_parity_false":
        report["historical_baseline_parity"]["all_equal"] = False
    elif damage == "missing_parity":
        del report["historical_hmm_parity"]
    elif damage == "missing_parity_count":
        del report["historical_hmm_parity"]["compared_prediction_files"]
    elif damage == "missing_parity_source":
        del report["historical_hmm_parity"]["source_checks"][audit.LEGACY_SOURCE_PATHS[0]]
    elif damage == "old_array_identity":
        row["observations"]["phase_path"]["sha256"] = "0" * 64
    elif damage == "receipt_hash":
        path = audit.REPOSITORY / audit.HMM_RECEIPT
        path.write_bytes(path.read_bytes() + b"changed receipt bytes")
        report["source_sha256"][audit.HMM_RECEIPT] = audit.sha256(path.read_bytes())
    elif damage == "missing_rate":
        del report["aggregate"][arm]["offset_precision"]
    elif damage == "gain_total":
        report["aggregate"][arm]["onset_gained_reference_count"] += 1
    elif damage == "unmatched_count":
        row["arms"][arm]["annotators"]["A1"]["onset_unmatched_reference"] += 1
    elif damage == "primary_mean":
        report["primary_result"]["mean_delta"] = .1
    elif damage == "bootstrap_bound":
        report["primary_result"]["bootstrap"]["high"] = .1
    elif damage == "barrier":
        report["reference_access_started_after_predicted_cases"] = 39
    elif damage == "f0_score":
        row["f0_metrics"]["Voicing Recall"] = .9
    elif damage == "factor_setting":
        report["factor_settings"]["factor_configs"]["gaussian_exponent_1"]["balance_phases"] = True
    else:
        report["runtime"]["numpy"] = "unexpected-version"
    report_path.write_bytes(encoded(report))
    with pytest.raises(ValueError):
        audit.audit_private(work, report_path)


def test_readout_counts_short_silent_unsupported_and_zero_duration_segments():
    path = np.full(36, 326, dtype=np.int16)
    path[0], path[1:10] = 324, 325
    path[11:18] = 324
    path[19], path[20:27] = 324, 325
    path[28:36] = 324
    hz = np.zeros(36)
    hz[:10], hz[11:18], hz[19] = 440., 440., 440. * 2 ** (2 / 12)
    notes, result = audit.reconstruct_readout(path, hz, .35)
    assert notes == [{"pitch": 69, "onset": 0., "offset": .1, "is_drum": False},
                     {"pitch": 71, "onset": .19, "offset": .27, "is_drum": False}]
    # One same-pitch Silent gap, one short supported segment, one unsupported
    # segment and a final attack beginning exactly at audio end remain distinct.
    assert result["segments_before_filter"] == 4
    assert result["short_segments_discarded"] == 1
    assert result["short_segments_discarded_seconds"] == pytest.approx(.07)
    assert result["segments_without_raw_voiced_support"] == 1
    assert result["emitted_notes"] == 2
    assert result["emitted_raw_unvoiced_frames"] == 7
    assert result["emitted_notes_with_raw_unvoiced_frames"] == 1
    assert result["emitted_note_seconds"] == pytest.approx(.18)
    zero_path = np.full(36, 326, dtype=np.int16)
    zero_path[-1] = 324
    _, zero = audit.reconstruct_readout(zero_path, hz, .35)
    assert zero["zero_duration_segments"] == 1


def test_rms_edit_uses_declared_two_frame_lookback_and_preserves_already_silent():
    path = np.full(10, 325, dtype=np.int16)
    path[0] = 326
    rms = np.r_[np.full(3, .1), np.ones(7)]
    edited, counts = audit.reconstruct_rms_path(path, rms)
    expected = path.copy()
    expected[1] = 326
    np.testing.assert_array_equal(edited, expected)
    assert counts == {"rms_rise_candidates": 2, "rms_frames_changed_to_silent": 1,
                      "rms_candidates_already_silent": 1}
    original = path.copy()
    np.testing.assert_array_equal(path, original)


@pytest.mark.parametrize("states", [
    [325, 325], [324, 326], [326, 325], [324, 327], [326, 327], [326, 447],
])
def test_graph_membership_rejects_impossible_non_rms_paths(states):
    with pytest.raises(ValueError):
        audit.check_path_transitions(np.asarray(states, dtype=np.int16))


def metric_rows():
    return [{"id": case, "status": "scored", "arms": {
        arm: {"count": 1, "annotators": {ann: perfect_metrics() for ann in audit.ANNOTATORS}}
        for arm in audit.ARMS}} for case in audit.CASES]


def test_bootstrap_resamples_paired_recordings_after_annotator_average():
    rows = metric_rows()
    candidate, baseline = audit.PRIMARY["candidate"], audit.PRIMARY["baseline"]
    for row in rows:
        row["arms"][baseline]["annotators"]["A1"]["onset_offset_f1"] = .4
        row["arms"][baseline]["annotators"]["A2"]["onset_offset_f1"] = .6
        row["arms"][candidate]["annotators"]["A1"]["onset_offset_f1"] = .6
        row["arms"][candidate]["annotators"]["A2"]["onset_offset_f1"] = .4
    result = audit.primary_summary(rows)
    assert result["mean_delta"] == 0
    assert result["bootstrap"]["low"] == result["bootstrap"]["high"] == 0
    assert result["recordings_tied"] == 40
    assert result["heldout_generalization"] is False


def test_manual_bootstrap_interpolation_matches_declared_linear_percentile():
    rows = metric_rows()
    candidate, baseline = audit.PRIMARY["candidate"], audit.PRIMARY["baseline"]
    expected = []
    for index, row in enumerate(rows):
        change = (index - 20) / 100
        expected.append(change)
        for ann in audit.ANNOTATORS:
            row["arms"][baseline]["annotators"][ann]["onset_offset_f1"] = .5
            row["arms"][candidate]["annotators"][ann]["onset_offset_f1"] = .5 + change
    result = audit.primary_summary(rows)
    indices = np.random.default_rng(291).integers(0, 40, size=(10000, 40))
    low, high = np.quantile(np.asarray(expected)[indices].mean(axis=1), [.025, .975], method="linear")
    assert result["bootstrap"]["low"] == pytest.approx(low, abs=1e-15)
    assert result["bootstrap"]["high"] == pytest.approx(high, abs=1e-15)
    assert result["mean_delta"] == pytest.approx(-.005)
    assert result["recordings_improved"] == 19
    assert result["recordings_worse"] == 20
    assert result["recordings_tied"] == 1


def test_source_inventory_and_primary_contract_match_runner_without_calling_inference():
    from scripts import run_note_state_factors as study

    assert study.SOURCE_PATHS == audit.SOURCE_PATHS
    assert study.ARMS == audit.ARMS
    rows = metric_rows()
    audit.Checks().equal(study.aggregate(rows), audit.aggregate_rows(rows), "fixture_aggregate")
    audit.Checks().equal(study.primary_summary(rows), audit.primary_summary(rows), "fixture_primary")


def test_official_receipt_history_contract_accepts_unchanged_legacy_metadata():
    """Read public old metadata only: no new observation, note or factor inference."""
    with zipfile.ZipFile(audit.REPOSITORY / audit.HMM_RECEIPT) as archive:
        report = json.loads(archive.read("vocadito.json"))
    for row in report["cases"]:
        row["diagnostics"] = {"legacy": row["diagnostics"]}
    report["historical_hmm_parity"] = {
        "baseline_zip_sha256": audit.HMM_ZIP_SHA256,
        "source_checks": dict.fromkeys((*audit.LEGACY_SOURCE_PATHS, "archive"), True),
        "differences": [], "all_equal": True, "compared_observation_arrays": 240,
        "compared_prediction_files": 200, "raw_historical_arrays_available": False,
        "array_identity_available": True,
    }
    checks = audit.Checks()
    result = audit.verify_history(report, checks)
    assert result["historical_hmm_parity"]["all_equal"] is True
    assert result["historical_baseline_parity"]["all_equal"] is True
    assert checks.counts["historical_observation_identity"] == 240
    assert checks.counts["historical_prediction_and_scores"] == 200
