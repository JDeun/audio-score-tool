"""Independent auditor contracts use invented notes, never the vocadito corpus."""

from __future__ import annotations

import copy
import io
import json
import wave
from pathlib import Path

import numpy as np
import pytest

from scripts import audit_note_state_experiment as audit


def encode(notes):
    return (json.dumps(notes, indent=2, allow_nan=False) + "\n").encode()


def note(pitch=69, onset=0., offset=1.):
    return {"pitch": pitch, "onset": onset, "offset": offset, "is_drum": False}


def test_reference_keeps_original_hz_and_stable_order():
    intervals, hz = audit.parse_reference(b".4,443,.2\n0,439,.3\n.4,442,.1\n")
    np.testing.assert_allclose(intervals, [[0, .3], [.4, .6], [.4, .5]])
    np.testing.assert_array_equal(hz, [439, 443, 442])


@pytest.mark.parametrize("raw", [b"", b"0,440,0\n", b"0,NaN,.1\n", b"-.1,440,.2\n", b"0,440\n"])
def test_reference_invalid_data_fails_closed(raw):
    with pytest.raises(ValueError):
        audit.parse_reference(raw)


def test_empty_prediction_is_valid_and_has_correct_shapes():
    notes, intervals, hz = audit.parse_notes(encode([]), 1.)
    assert notes == [] and intervals.shape == (0, 2) and hz.shape == (0,)


@pytest.mark.parametrize("notes", [
    [note(offset=.079)], [note(onset=-.1)], [note(offset=1.01)],
    [note(pitch=True)], [note(pitch=128)],
    [note(offset=.6), note(onset=.5)],
    [{**note(), "is_drum": True}], [{**note(), "extra": 1}],
])
def test_invalid_prediction_intervals_and_domains_are_rejected(notes):
    with pytest.raises(ValueError):
        audit.parse_notes(encode(notes), 1.)


def test_exact_minimum_note_and_adjacent_repeated_pitches_survive():
    values, intervals, _ = audit.parse_notes(encode([note(offset=.08), note(onset=.08)]), 1.)
    assert len(values) == 2
    np.testing.assert_array_equal(intervals, [[0, .08], [.08, 1.]])


def test_noncanonical_encoding_duplicate_key_and_nan_are_rejected():
    for raw in (json.dumps([note()]).encode(), b'[{"pitch":69,"pitch":70}]', b"[NaN]"):
        with pytest.raises(ValueError):
            audit.parse_notes(raw, 1.)


def observations():
    return {
        "hz": np.full(101, 440.), "probability": np.full(101, .9),
        "attacks": np.array([.5]), "rms": np.full(101, .2),
        "phase_path": np.ones(101, dtype=np.int16),
        "rms_phase_path": np.ones(101, dtype=np.int16),
    }


def npz_bytes(arrays):
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    return stream.getvalue()


def test_observation_hashes_include_shape_dtype_and_all_raw_bytes():
    arrays = observations()
    receipts = {key: audit.array_identity(value) for key, value in arrays.items()}
    checks = audit.Checks()
    assert audit.check_observations(npz_bytes(arrays), receipts, checks) == {"frames": 101, "attacks": 1, "arrays": 6}
    arrays["hz"][50] = 441.
    with pytest.raises(ValueError, match="observation_array_identity"):
        audit.check_observations(npz_bytes(arrays), receipts, checks)


@pytest.mark.parametrize("mutation", ["missing", "short", "invalid_probability", "duplicate_attack", "float_path"])
def test_observation_population_and_domains_are_checked(mutation):
    arrays = observations()
    if mutation == "missing":
        del arrays["rms"]
    elif mutation == "short":
        arrays["rms"] = arrays["rms"][:-1]
    elif mutation == "invalid_probability":
        arrays["probability"][0] = 1.1
    elif mutation == "duplicate_attack":
        arrays["attacks"] = np.array([.5, .5])
    else:
        arrays["phase_path"] = arrays["phase_path"].astype(float)
    receipts = {key: audit.array_identity(value) for key, value in arrays.items()}
    with pytest.raises(ValueError):
        audit.check_observations(npz_bytes(arrays), receipts, audit.Checks())


def test_match_count_conservation_and_empty_prediction():
    assert audit._metrics_for_pairs([(0, 1), (2, 0)], 4, 3) == {
        "matched": 2, "precision": 2 / 3, "recall": .5, "f1": round(4 / 7, 8),
    }
    assert audit._metrics_for_pairs([], 2, 0) == {"matched": 0, "precision": 0., "recall": 0., "f1": 0.}
    for bad in ([(0, 0), (0, 1)], [(0, 0), (1, 0)], [(4, 0)]):
        with pytest.raises(ValueError):
            audit._metrics_for_pairs(bad, 4, 3)


def aggregation_rows():
    rows = []
    for case in audit.CASES:
        arms = {}
        for arm in audit.ARMS:
            annotators = {}
            for ann, value in (("A1", .2), ("A2", .6)):
                annotators[ann] = {metric: value for metric in (*audit.METRICS, *audit.RATES)}
                annotators[ann].update({prefix + "_" + kind + "_reference_ids": []
                                       for prefix in ("onset", "onset_offset") for kind in ("gained", "lost")})
            arms[arm] = {"count": 3, "annotators": annotators}
        rows.append({"id": case, "arms": arms})
    return rows


def test_macro_uses_equal_recording_and_annotator_weight_and_paired_deltas():
    rows = aggregation_rows()
    rows[0]["arms"][audit.ARMS[-1]]["annotators"]["A1"]["onset_offset_f1"] = .4
    rows[1]["arms"][audit.ARMS[-1]]["annotators"]["A2"]["onset_offset_f1"] = .2
    value = audit.aggregate_rows(rows)[audit.ARMS[-1]]
    assert value["predicted_notes"] == 120
    assert value["onset_f1"]["macro"] == pytest.approx(.4)
    assert value["onset_offset_f1"] == pytest.approx({
        "macro": .3975, "A1_macro": .205, "A2_macro": .59,
        "delta_vs_runs": -.0025, "recordings_improved": 1,
        "recordings_worse": 1, "recordings_tied": 38,
    })


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "arm", "annotator", "nan"])
def test_aggregate_rejects_partial_duplicate_or_nonfinite_populations(mutation):
    rows = aggregation_rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1] = copy.deepcopy(rows[0])
    elif mutation == "arm":
        del rows[0]["arms"][audit.ARMS[-1]]
    elif mutation == "annotator":
        del rows[0]["arms"][audit.ARMS[0]]["annotators"]["A2"]
    else:
        rows[0]["arms"][audit.ARMS[0]]["annotators"]["A1"]["onset_f1"] = float("nan")
    with pytest.raises(ValueError):
        audit.aggregate_rows(rows)


def test_direct_mir_eval_matches_original_hz_with_separate_endpoint_criterion():
    pytest.importorskip("mir_eval")
    reference = audit.parse_reference(b"0,440,.4\n.5,440,.5\n")
    _, intervals, hz = audit.parse_notes(encode([note(offset=.4), note(onset=.5, offset=.8)]), 1.)
    metrics, ids = audit.direct_score(reference, (intervals, hz))
    assert metrics["onset_f1"] == 1.
    assert metrics["onset_offset_f1"] == .5
    assert metrics["onset_matched"] == 2 and metrics["onset_offset_matched"] == 1
    assert ids == {"onset": {0, 1}, "onset_offset": {0}}


def private_fixture(tmp_path):
    pytest.importorskip("mir_eval")
    pytest.importorskip("soundfile")
    work = tmp_path / "private"
    work.mkdir()
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(16000 * 2))
    source = wav.getvalue()
    arrays = observations()
    observation_raw = npz_bytes(arrays)
    reference_raw = b"0,440,1\n"
    f0_raw = b"0,440\n"
    note_raw = encode([note()])
    values = {
        "reference_note_count": 1, "onset_f1": 1., "onset_offset_f1": 1.,
        "onset_matched": 1, "onset_offset_matched": 1,
        **{rate: 1. for rate in audit.RATES},
        **{prefix + "_unmatched_" + population: 0 for prefix in ("onset", "onset_offset")
           for population in ("reference", "prediction")},
        **{prefix + "_" + kind + "_reference_ids": [] for prefix in ("onset", "onset_offset")
           for kind in ("gained", "lost")},
    }
    rows, manifest = [], {}
    for case in audit.CASES:
        directory = work / case
        directory.mkdir()
        (directory / "source.wav").write_bytes(source)
        (directory / "observations.npz").write_bytes(observation_raw)
        (directory / "f0.csv").write_bytes(f0_raw)
        for ann in audit.ANNOTATORS:
            (directory / (ann + ".csv")).write_bytes(reference_raw)
        arms = {}
        manifest[case] = {}
        for arm in audit.ARMS:
            (directory / (arm + ".json")).write_bytes(note_raw)
            manifest[case][arm] = audit.sha256(note_raw)
            arms[arm] = {"count": 1, "event_sha256": audit.sha256(note_raw),
                         "annotators": {ann: copy.deepcopy(values) for ann in audit.ANNOTATORS}}
        rows.append({"id": case, "status": "scored", "arms": arms, "duration_seconds": 1.,
                     "audio_sha256": audit.sha256(source),
                     "observation_sha256": audit.sha256(observation_raw),
                     "observations": {key: audit.array_identity(value) for key, value in arrays.items()},
                     "reference_sha256": {ann: audit.sha256(reference_raw) for ann in audit.ANNOTATORS},
                     "f0_reference_sha256": audit.sha256(f0_raw)})
    source_path = Path(audit.__file__)
    report = {"status": "complete", "all_cases_complete": True,
              "all_predictions_frozen_before_references": True,
              "reference_access_started_after_predicted_cases": 40,
              "planned_case_ids": list(audit.CASES), "planned_arms": list(audit.ARMS),
              "historical_baseline_parity": {"all_equal": True, "fixture_only": True},
              "source_sha256": {"scripts/audit_note_state_experiment.py": audit.sha256(source_path.read_bytes())},
              "cases": rows, "aggregate": audit.aggregate_rows(rows),
              "predictions_manifest_sha256": audit.fingerprint(manifest),
              "post_evaluation_predictions_manifest_sha256": audit.fingerprint(manifest)}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))
    return work, report_path, report


def test_complete_private_audit_rescores_all_files_without_inference(tmp_path):
    work, report_path, _ = private_fixture(tmp_path)
    result = audit.audit_private(work, report_path)
    assert result["status"] == "pass"
    assert result["complete_prediction_files_verified"] == 200
    assert result["human_reference_files_verified"] == 80
    assert result["observation_arrays_verified"] == 240
    assert result["segmentation_model_calls"] == result["pyin_calls"] == 0
    assert result["maximum_numeric_difference"] == 0


@pytest.mark.parametrize("mutation", ["prediction", "reference", "array", "metric", "aggregate", "gain_ids", "gain_total", "unmatched", "barrier", "parity", "missing_parity", "missing_rate"])
def test_changed_private_evidence_or_public_arithmetic_is_rejected(tmp_path, mutation):
    work, report_path, report = private_fixture(tmp_path)
    directory = work / audit.CASES[0]
    if mutation == "prediction":
        (directory / (audit.ARMS[-1] + ".json")).write_bytes(encode([note(offset=.9)]))
    elif mutation == "reference":
        (directory / "A1.csv").write_bytes(b"0,441,1\n")
    elif mutation == "array":
        arrays = observations()
        arrays["hz"][0] = 441.
        raw = npz_bytes(arrays)
        (directory / "observations.npz").write_bytes(raw)
        report["cases"][0]["observation_sha256"] = audit.sha256(raw)
    elif mutation == "metric":
        report["cases"][0]["arms"][audit.ARMS[-1]]["annotators"]["A1"]["onset_f1"] = .9
    elif mutation == "aggregate":
        report["aggregate"][audit.ARMS[-1]]["onset_f1"]["macro"] = .9
    elif mutation == "gain_ids":
        report["cases"][0]["arms"][audit.ARMS[-1]]["annotators"]["A1"]["onset_gained_reference_ids"] = [0]
    elif mutation == "gain_total":
        report["aggregate"][audit.ARMS[-1]]["onset_gained_reference_count"] = 1
    elif mutation == "unmatched":
        report["cases"][0]["arms"][audit.ARMS[-1]]["annotators"]["A1"]["onset_unmatched_reference"] = 1
    elif mutation == "parity":
        report["historical_baseline_parity"] = {"all_equal": False}
    elif mutation == "missing_parity":
        del report["historical_baseline_parity"]
    elif mutation == "missing_rate":
        del report["aggregate"][audit.ARMS[-1]]["offset_precision"]
    else:
        report["all_predictions_frozen_before_references"] = False
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        audit.audit_private(work, report_path)


def test_runner_to_auditor_with_real_matching_and_no_audio_inference(tmp_path, monkeypatch):
    """Real private-file/scoring interface, with a deliberately invented predictor."""
    pytest.importorskip("mir_eval")
    pytest.importorskip("soundfile")
    from scripts import run_note_state_experiment as study

    work = tmp_path / "runner-private"
    work.mkdir()
    report_path = tmp_path / "runner-report.json"
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(bytes(16000 * 2))
    audio = wav.getvalue()
    arrays = observations()
    arrays["hz"][[0, -1]] = 0.
    f0 = "".join(f"{i / 100:.2f},{hz}\n" for i, hz in enumerate(arrays["hz"])).encode()
    opened = []

    class OwnedPackage:
        def read(self, member):
            opened.append(member)
            if member.startswith("Audio/"):
                assert not any(name.startswith("Annotations/") for name in opened)
                return audio
            assert len(list(work.glob("vocadito_*/*.json"))) == 200
            return f0 if member.startswith("Annotations/F0/") else b"0,440,1\n"

    def owned_predictor(_audio):
        return arrays, {arm: [study.dsp.Note(69, 0., 1.)] for arm in study.ARMS}, {}, 1.

    monkeypatch.setattr(study, "infer_recording", owned_predictor)
    # The invented corpus has no historical baseline; that gate has separate contracts.
    monkeypatch.setattr(study, "baseline_parity", lambda *_: {"all_equal": True, "fixture_only": True})
    report = {"status": "started", "cases": [], "planned_case_ids": list(study.CASES),
              "planned_arms": list(study.ARMS),
              "source_sha256": {"scripts/audit_note_state_experiment.py": audit.sha256(Path(audit.__file__).read_bytes()),
                                "scripts/run_note_state_experiment.py": audit.sha256(Path(study.__file__).read_bytes())}}
    package = OwnedPackage()
    study.predict_all(package, work, report, report_path)
    assert len(opened) == 40
    study.evaluate_all(package, work, report, report_path)
    study.finalize_results(report, None)
    study.dsp.save(report_path, report)
    assert report["status"] == "complete"
    result = audit.audit_private(work, report_path)
    assert result["status"] == "pass"
    assert result["complete_prediction_files_verified"] == 200
    assert result["aggregate"][audit.ARMS[-1]]["onset_offset_f1"]["macro"] == 1.
