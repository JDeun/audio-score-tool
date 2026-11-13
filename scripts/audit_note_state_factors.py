"""Independently audit the saved ten-arm factor experiment, without inference.

Only immutable parsing, hashing and direct mir_eval note matching helpers are
shared with the previous auditor. This module does not import either runner,
decoder, or repository scorer. It reconstructs note readout and diagnostics
from private saved paths, checks both original receipts, and recomputes the
complete corpus aggregates and the paired recording bootstrap.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import sys
import time
import warnings
import zipfile
from importlib.metadata import version
from pathlib import Path

import numpy as np

from scripts.audit_note_state_experiment import (
    Checks,
    _json,
    _read,
    array_identity,
    direct_score,
    fingerprint,
    parse_notes,
    parse_reference,
    sha256,
)

REPOSITORY = Path(__file__).resolve().parents[1]
CASES = tuple(f"vocadito_{i}" for i in range(1, 41))
ANNOTATORS = ("A1", "A2")
LEGACY_ARMS = (
    "pitch_runs", "pitch_hysteresis", "pitch_hysteresis_reattack",
    "note_state_hmm", "note_state_hmm_rms",
)
FACTOR_ARMS = (
    "gaussian_exponent_1", "phase_balanced", "positive_voicing_08",
    "silent_self_099", "hop_unscaled",
)
ARMS = (*LEGACY_ARMS, *FACTOR_ARMS)
LEGACY_OBSERVATIONS = ("hz", "probability", "attacks", "rms", "phase_path", "rms_phase_path")
OBSERVATIONS = (*LEGACY_OBSERVATIONS, *(arm + "_path" for arm in FACTOR_ARMS))
PATHS = {"note_state_hmm": "phase_path", "note_state_hmm_rms": "rms_phase_path",
         **{arm: arm + "_path" for arm in FACTOR_ARMS}}
METRICS = ("onset_f1", "onset_offset_f1")
RATES = ("onset_precision", "onset_recall", "offset_precision", "offset_recall")
BASELINE_RECEIPT = "docs/research/receipts/dsp-note-baseline-42989661618.zip"
HMM_RECEIPT = "docs/research/receipts/note-state-hmm-43336542480.zip"
BASELINE_ZIP_SHA256 = "6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541"
HMM_ZIP_SHA256 = "46ea77a90750172a905750599db3b419f09d70d165ef0be221e0004b8cd61b26"
LEGACY_SOURCE_PATHS = (
    "scripts/dsp_note_probe.py", "scripts/note_state_hmm.py",
    "scripts/run_note_state_experiment.py", "scripts/audit_note_state_experiment.py",
    "scripts/vocadito_reference.py", "scripts/run_cpu_vocadito_candidates.py",
    "tests/test_note_state_hmm.py", "tests/test_run_note_state_experiment.py",
    "tests/test_audit_note_state_experiment.py", ".github/workflows/cpu-note-state-hmm.yml",
    "docs/research/NOTE_STATE_HMM_PROTOCOL_2026-11-13.md", BASELINE_RECEIPT,
)
SOURCE_PATHS = (*LEGACY_SOURCE_PATHS,
    "scripts/note_state_factors.py", "scripts/run_note_state_factors.py",
    "scripts/audit_note_state_factors.py", "scripts/note_state_synthetic.py",
    "tests/test_note_state_factors.py", "tests/test_run_note_state_factors.py",
    "tests/test_audit_note_state_factors.py", "tests/test_note_state_synthetic.py",
    ".github/workflows/cpu-note-state-factors.yml",
    "docs/research/NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md",
    "docs/research/TONY_NOTE_HMM_SOURCE_AUDIT_2026-11-13.md", HMM_RECEIPT,
)
EXPECTED_RUNTIME = {
    "librosa": "0.10.2.post1", "numpy": "1.26.4", "scipy": "1.13.1",
    "mir-eval": "0.8.2", "numba": "0.60.0", "soundfile": "0.13.1",
    "resampy": "0.4.2", "soxr": "1.1.0",
}
PRIMARY = {"candidate": "gaussian_exponent_1", "baseline": "note_state_hmm",
           "metric": "onset_offset_f1"}
LEGACY_FACTOR_CONFIG = {"gaussian_exponent": .1, "balance_phases": False,
                        "positive_voiced_mass": .5, "paper_silent_self": .9999,
                        "rescale_hop": True}
FACTOR_CONFIGS = {arm: {**LEGACY_FACTOR_CONFIG, key: value} for arm, key, value in (
    ("gaussian_exponent_1", "gaussian_exponent", 1.),
    ("phase_balanced", "balance_phases", True),
    ("positive_voicing_08", "positive_voiced_mass", .8),
    ("silent_self_099", "paper_silent_self", .99),
    ("hop_unscaled", "rescale_hop", False),
)}


def _inventory(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + ": exact inventory required")


def _exact(checks, actual, expected, label):
    """Historical identities and serialized results require exact equality."""
    checks.equal(actual == expected, True, label)


def check_observations(raw, recorded, duration, checks):
    _inventory(recorded, OBSERVATIONS, "public observation")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        if len(archive.files) != len(OBSERVATIONS) or set(archive.files) != set(OBSERVATIONS):
            raise ValueError("private observation inventory differs")
        arrays = {key: archive[key] for key in OBSERVATIONS}
    for name, value in arrays.items():
        if value.ndim != 1 or value.dtype.kind not in "fiu" or not np.isfinite(value).all():
            raise ValueError("invalid observation array " + name)
        checks.equal(recorded[name], array_identity(value), "observation_array_identity/" + name)
    frames = len(arrays["hz"])
    if (frames < 2 or any(len(arrays[key]) != frames for key in OBSERVATIONS if key != "attacks")
            or not (max(0., (frames - 1) * .01) - 1e-10 <= duration <= frames * .01 + 1e-10)):
        raise ValueError("observation clock/shape mismatch")
    if (np.any(arrays["hz"] < 0) or np.any(arrays["rms"] < 0)
            or np.any(arrays["probability"] < 0) or np.any(arrays["probability"] > 1)
            or np.any(arrays["attacks"] < 0) or np.any(np.diff(arrays["attacks"]) <= 0)):
        raise ValueError("observation domain mismatch")
    positive = arrays["hz"][arrays["hz"] > 0]
    midi = 69 + 12 * np.log2(positive / 440.)
    if np.any(midi < 33 - 1e-10) or np.any(midi > 81 + 1e-10):
        raise ValueError("raw F0 outside frozen pitch grid")
    for name in PATHS.values():
        states = arrays[name]
        if states.dtype.kind not in "iu" or np.any(states < 0) or np.any(states >= 435):
            raise ValueError("state path integer/domain mismatch")
        if name != "rms_phase_path":
            check_path_transitions(states)
    return arrays


def check_path_transitions(states):
    """Check graph membership only; a legal path need not be Viterbi optimal."""
    if states[0] % 3 == 1:
        raise ValueError("initial Stable state has zero model mass")
    source, target = states[:-1], states[1:]
    a, b = source % 3, target % 3
    same_pitch = source // 3 == target // 3
    distance_steps = np.abs(source.astype(np.int64) // 3 - target.astype(np.int64) // 3)
    ordinary = same_pitch & ((a == b) | ((a == 0) & (b == 1)) | ((a == 1) & (b == 2)))
    jump = ((a == 2) & (b == 0) & ((distance_steps == 0) | (distance_steps >= 2))
            & (distance_steps <= 39))
    if not np.all(ordinary | jump):
        raise ValueError("state path contains an impossible transition")


def reconstruct_readout(states, hz, duration):
    """Independently reconstruct frozen 10 ms support, pruning and raw-median pitch."""
    phases, raw_voiced = states % 3, hz > 0
    voiced = phases != 2
    labels = np.where(voiced, states // 3, -1)
    cuts = np.r_[0, 1 + np.flatnonzero(np.diff(labels)), len(labels)]
    notes, discarded_seconds, emitted_seconds = [], [], []
    result = {
        "frames": len(hz), "raw_voiced_frames": int(np.count_nonzero(raw_voiced)),
        "decoded_voiced_frames": int(np.count_nonzero(voiced)),
        "attack_frames": int(np.count_nonzero(phases == 0)),
        "stable_frames": int(np.count_nonzero(phases == 1)),
        "silent_frames": int(np.count_nonzero(phases == 2)),
        "decoded_voiced_over_raw_unvoiced_frames": int(np.count_nonzero(voiced & ~raw_voiced)),
        "raw_voiced_decoded_silent_frames": int(np.count_nonzero(raw_voiced & ~voiced)),
        "segments_before_filter": 0, "emitted_notes": 0,
        "segments_without_raw_voiced_support": 0, "zero_duration_segments": 0,
        "short_segments_discarded": 0, "short_segments_discarded_seconds": 0.,
        "attack_only_segments": 0, "segments_touching_audio_start": 0,
        "segments_touching_audio_end": 0, "emitted_notes_with_raw_unvoiced_frames": 0,
        "emitted_raw_unvoiced_frames": 0, "emitted_note_seconds": 0.,
    }
    for first, stop in zip(cuts[:-1], cuts[1:], strict=True):
        if labels[first] == -1:
            continue
        first, stop = int(first), int(stop)
        support = hz[first:stop][raw_voiced[first:stop]]
        onset, offset = first * .01, min(stop * .01, duration)
        result["segments_before_filter"] += 1
        result["attack_only_segments"] += int(np.all(phases[first:stop] == 0))
        result["segments_touching_audio_start"] += int(first == 0)
        result["segments_touching_audio_end"] += int(stop * .01 >= duration - 1e-10)
        if offset <= onset:
            result["zero_duration_segments"] += 1
        elif not len(support):
            result["segments_without_raw_voiced_support"] += 1
        elif offset - onset < .08 - 1e-10:
            result["short_segments_discarded"] += 1
            discarded_seconds.append(offset - onset)
        else:
            pitch = int(np.rint(np.median(69 + 12 * np.log2(support / 440.))))
            notes.append({"pitch": pitch, "onset": onset, "offset": offset, "is_drum": False})
            unvoiced_count = stop - first - len(support)
            result["emitted_notes_with_raw_unvoiced_frames"] += int(unvoiced_count > 0)
            result["emitted_raw_unvoiced_frames"] += unvoiced_count
            emitted_seconds.append(offset - onset)
    result["emitted_notes"] = len(notes)
    result["short_segments_discarded_seconds"] = math.fsum(discarded_seconds)
    result["emitted_note_seconds"] = math.fsum(emitted_seconds)
    return notes, result


def reconstruct_rms_path(path, rms):
    edited = path.copy()
    candidates = changed = 0
    for center in range(2, len(path) - 1):
        if rms[center + 1] > 1e-12 and rms[center - 1] / rms[center + 1] < .7:
            candidates += 1
            index = center - 2
            if path[index] % 3 != 2:
                edited[index] = (path[index] // 3) * 3 + 2
                changed += 1
    return edited, {"rms_rise_candidates": candidates,
                    "rms_frames_changed_to_silent": changed,
                    "rms_candidates_already_silent": candidates - changed}


def check_readouts(arrays, duration, notes, diagnostics, checks):
    _inventory(diagnostics, ("legacy", "factors"), "diagnostic groups")
    legacy = diagnostics["legacy"]
    _inventory(legacy.get("arms"), LEGACY_ARMS[-2:], "legacy diagnostic arms")
    _inventory(diagnostics["factors"], FACTOR_ARMS, "factor diagnostic arms")
    log_weight = legacy.get("viterbi_path_log_weight")
    if (not isinstance(log_weight, (int, float)) or isinstance(log_weight, bool)
            or not math.isfinite(log_weight) or log_weight > 0):
        raise ValueError("invalid legacy path log weight")
    rms_path, rms_diagnostics = reconstruct_rms_path(arrays["phase_path"], arrays["rms"])
    checks.equal(bool(np.array_equal(rms_path, arrays["rms_phase_path"])), True, "independent_rms_edit")
    checks.equal(legacy.get("rms"), rms_diagnostics, "independent_rms_diagnostics")
    results = {}
    for arm, key in PATHS.items():
        expected_notes, expected_diagnostics = reconstruct_readout(arrays[key], arrays["hz"], duration)
        _exact(checks, notes[arm], expected_notes, "independent_path_note_readout/" + arm)
        recorded = (legacy["arms"][arm] if arm in LEGACY_ARMS
                    else diagnostics["factors"][arm])
        if isinstance(recorded, dict) and "viterbi_path_log_weight" in recorded:
            weight = recorded["viterbi_path_log_weight"]
            if (not isinstance(weight, (int, float)) or isinstance(weight, bool)
                    or not math.isfinite(weight) or weight > 0):
                raise ValueError("invalid factor path log weight")
        checks.equal(recorded, expected_diagnostics, "independent_path_diagnostics/" + arm)
        results[arm] = expected_diagnostics
    return results, rms_diagnostics


def direct_f0_score(raw, hz):
    """Original CSV parse and direct melody API; no repository F0 scorer call."""
    import mir_eval.melody as melody

    rows = []
    for row in csv.reader(io.StringIO(raw.decode("utf-8"))):
        if len(row) != 2:
            raise ValueError("invalid original F0 CSV columns")
        rows.append(tuple(map(float, row)))
    values = np.asarray(rows, dtype=float)
    if (values.ndim != 2 or values.shape[1] != 2 or len(values) < 2
            or not np.isfinite(values).all() or np.any(values < 0)
            or np.any(np.diff(values[:, 0]) <= 0)):
        raise ValueError("invalid original F0 reference timeline")
    ref_time, ref_hz = values.T
    times = np.arange(len(hz)) * .01
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Estimated melody has no voiced frames.*",
                                category=UserWarning, module="mir_eval.melody")
        scores = melody.evaluate(ref_time, ref_hz, times, hz, cent_tolerance=50, kind="nearest")
    rv, rc, ev, ec = melody.to_cent_voicing(ref_time, ref_hz, times, hz, kind="nearest")
    difference = ec - rc
    octaves = ((rv > 0) & (ev > 0) & (np.abs(difference) >= 1150)
               & (np.abs(difference - 1200 * np.rint(difference / 1200)) < 50))
    return {
        **{key: float(value) for key, value in scores.items()},
        "octave_errors_per_reference_voiced_frame": float(np.count_nonzero(octaves) / max(1, np.count_nonzero(rv > 0))),
        "reference_voiced_frames": int(np.count_nonzero(rv > 0)),
        "reference_voiced_outside_55_880_hz": int(np.count_nonzero((ref_hz > 0) & ((ref_hz < 55) | (ref_hz > 880)))),
        "predicted_voiced_fraction": float(np.count_nonzero(ev > 0) / len(ev)),
    }


def _population(rows):
    if not isinstance(rows, list) or [r.get("id") for r in rows] != list(CASES):
        raise ValueError("exact ordered forty-case population required")
    for row in rows:
        if row.get("status") != "scored":
            raise ValueError("every case must be scored")
        _inventory(row.get("arms"), ARMS, "corpus arms")
        for arm in ARMS:
            _inventory(row["arms"][arm].get("annotators"), ANNOTATORS, "corpus annotators")


def aggregate_rows(rows):
    _population(rows)
    result = {}
    for arm in ARMS:
        summary = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in METRICS:
            values = {ann: [r["arms"][arm]["annotators"][ann][metric] for r in rows]
                      for ann in ANNOTATORS}
            if not all(math.isfinite(v) and 0 <= v <= 1 for scores in values.values() for v in scores):
                raise ValueError("invalid note score in aggregate")
            means = [math.fsum(pair) / 2 for pair in zip(values["A1"], values["A2"], strict=True)]
            changes = [mean - math.fsum(row["arms"][ARMS[0]]["annotators"][ann][metric]
                       for ann in ANNOTATORS) / 2 for mean, row in zip(means, rows, strict=True)]
            better, worse = sum(v > 1e-8 for v in changes), sum(v < -1e-8 for v in changes)
            summary[metric] = {
                "macro": math.fsum(means) / len(rows),
                "A1_macro": math.fsum(values["A1"]) / len(rows),
                "A2_macro": math.fsum(values["A2"]) / len(rows),
                "delta_vs_runs": math.fsum(changes) / len(rows),
                "recordings_improved": better, "recordings_worse": worse,
                "recordings_tied": len(rows) - better - worse,
            }
        for rate in RATES:
            summary[rate] = math.fsum(row["arms"][arm]["annotators"][ann][rate]
                                     for row in rows for ann in ANNOTATORS) / (len(rows) * 2)
        for prefix in ("onset", "onset_offset"):
            for kind in ("gained", "lost"):
                summary[prefix + "_" + kind + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][prefix + "_" + kind + "_reference_ids"])
                    for row in rows for ann in ANNOTATORS)
        result[arm] = summary
    return result


def primary_summary(rows):
    _population(rows)
    differences = [math.fsum(
        row["arms"][PRIMARY["candidate"]]["annotators"][ann][PRIMARY["metric"]]
        - row["arms"][PRIMARY["baseline"]]["annotators"][ann][PRIMARY["metric"]]
        for ann in ANNOTATORS) / 2 for row in rows]
    if not all(math.isfinite(d) and -1 <= d <= 1 for d in differences):
        raise ValueError("invalid paired difference")
    samples = np.random.default_rng(291).integers(0, len(rows), size=(10000, len(rows)))
    # Reproduce the declared random draws, but calculate means and percentile
    # interpolation independently of the runner's NumPy mean/quantile calls.
    means = sorted(math.fsum(differences[int(i)] for i in sample) / len(rows) for sample in samples)

    def percentile(probability):
        position = probability * (len(means) - 1)
        left = math.floor(position)
        return means[left] + (means[math.ceil(position)] - means[left]) * (position - left)

    better, worse = sum(v > 1e-8 for v in differences), sum(v < -1e-8 for v in differences)
    return {**PRIMARY,
        "paired_recording_deltas": [{"id": case, "delta": delta}
                                    for case, delta in zip(CASES, differences, strict=True)],
        "mean_delta": math.fsum(differences) / len(rows),
        "recordings_improved": better, "recordings_worse": worse,
        "recordings_tied": len(rows) - better - worse,
        "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2", "seed": 291,
                      "resamples": 10000, "confidence_level": .95,
                      "method": "paired_percentile_linear",
                      "low": percentile(.025), "high": percentile(.975)},
        "heldout_generalization": False}


def _receipt(path, expected_hash, members, checks):
    raw = _read(path, 32_000_000)
    checks.equal(sha256(raw), expected_hash, "original_receipt_zip_identity")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.namelist()) != len(members) or set(archive.namelist()) != set(members):
            raise ValueError("historical receipt member inventory differs")
        if archive.getinfo("vocadito.json").file_size > 16_000_000:
            raise ValueError("historical receipt JSON oversized")
        value = _json(archive.read("vocadito.json"))
    checks.equal(value.get("status"), "complete", "historical_receipt_complete")
    checks.equal(value.get("all_cases_complete"), True, "historical_receipt_complete")
    checks.equal([r.get("id") for r in value.get("cases", [])], list(CASES), "historical_case_population")
    return value


def verify_history(report, checks):
    old = _receipt(REPOSITORY / HMM_RECEIPT, HMM_ZIP_SHA256, ("vocadito.json", "audit.json"), checks)
    baseline = _receipt(REPOSITORY / BASELINE_RECEIPT, BASELINE_ZIP_SHA256,
                        ("vocadito.json", "synthetic.json"), checks)
    _inventory(old.get("source_sha256"), LEGACY_SOURCE_PATHS, "historical source")
    source_checks = {}
    for name in LEGACY_SOURCE_PATHS:
        source_checks[name] = report["source_sha256"][name] == old["source_sha256"][name]
        checks.equal(source_checks[name], True, "unchanged_legacy_source_identity/" + name)
    source_checks["archive"] = report.get("archive_sha256") == old.get("archive_sha256")
    checks.equal(source_checks["archive"], True, "historical_corpus_archive_identity")
    for key in ("f0_settings", "hmm_settings"):
        _exact(checks, report.get(key), old.get(key), "unchanged_legacy_settings/" + key)
    for row, prior in zip(report["cases"], old["cases"], strict=True):
        _inventory(prior.get("arms"), LEGACY_ARMS, "historical prediction arms")
        _inventory(prior.get("observations"), LEGACY_OBSERVATIONS, "historical observations")
        for key in ("audio_sha256", "duration_seconds", "reference_sha256", "f0_reference_sha256", "f0_metrics"):
            _exact(checks, row[key], prior[key], "historical_input_and_f0_identity/" + key)
        _exact(checks, row["diagnostics"]["legacy"], prior["diagnostics"], "historical_legacy_diagnostics")
        for key in LEGACY_OBSERVATIONS:
            _exact(checks, row["observations"][key], prior["observations"][key], "historical_observation_identity/" + key)
        for arm in LEGACY_ARMS:
            _exact(checks, row["arms"][arm], prior["arms"][arm], "historical_prediction_and_scores/" + arm)
    expected_hmm = {
        "baseline_zip_sha256": HMM_ZIP_SHA256, "source_checks": source_checks,
        "differences": [], "all_equal": True, "compared_observation_arrays": 240,
        "compared_prediction_files": 200, "raw_historical_arrays_available": False,
        "array_identity_available": True,
    }
    gate = report.get("historical_hmm_parity")
    if not isinstance(gate, dict):
        raise ValueError("historical HMM parity gate required")
    _inventory(gate.get("source_checks"), source_checks, "historical HMM source checks")
    checks.equal(gate, expected_hmm, "independent_historical_hmm_parity")

    base_sources = {"archive": report.get("archive_sha256") == baseline.get("archive_sha256"),
        "extractor": report["source_sha256"]["scripts/dsp_note_probe.py"] == baseline.get("script_sha256"),
        "scorer": report["source_sha256"]["scripts/vocadito_reference.py"] == baseline.get("scorer_sha256"),
        "f0_scorer": report["source_sha256"]["scripts/run_cpu_vocadito_candidates.py"] == baseline.get("f0_scorer_sha256")}
    checks.equal(base_sources, dict.fromkeys(base_sources, True), "unchanged_original_dsp_sources")
    for row, prior in zip(report["cases"], baseline["cases"], strict=True):
        _inventory(prior.get("arms"), LEGACY_ARMS[:3], "original DSP arms")
        for key in ("audio_sha256", "reference_sha256", "f0_reference_sha256", "f0_metrics"):
            _exact(checks, row[key], prior[key], "original_dsp_input_and_f0_identity/" + key)
        for arm in LEGACY_ARMS[:3]:
            for key in ("count", "event_sha256"):
                _exact(checks, row["arms"][arm][key], prior["arms"][arm][key], "original_dsp_prediction_identity/" + key)
            _inventory(prior["arms"][arm].get("annotators"), ANNOTATORS, "original DSP annotators")
            for ann in ANNOTATORS:
                for key, value in prior["arms"][arm]["annotators"][ann].items():
                    renamed = "onset_" + key if key in ("unmatched_reference", "unmatched_prediction") else key
                    _exact(checks, row["arms"][arm]["annotators"][ann][renamed], value, "original_dsp_annotation_metric/" + key)
    expected_base = {"baseline_zip_sha256": BASELINE_ZIP_SHA256, "source_checks": base_sources,
                     "differences": [], "all_equal": True, "raw_historical_f0_bytes_available": False}
    gate = report.get("historical_baseline_parity")
    if not isinstance(gate, dict):
        raise ValueError("historical DSP parity gate required")
    _inventory(gate.get("source_checks"), base_sources, "historical DSP source checks")
    checks.equal(gate, expected_base, "independent_historical_dsp_parity")
    return {"historical_hmm_parity": expected_hmm, "historical_baseline_parity": expected_base}


def check_sources(report, checks):
    hashes = report.get("source_sha256")
    _inventory(hashes, SOURCE_PATHS, "frozen source")
    for relative in SOURCE_PATHS:
        path = REPOSITORY / relative
        if not path.resolve().is_relative_to(REPOSITORY.resolve()):
            raise ValueError("frozen source path outside repository")
        checks.equal(sha256(_read(path)), hashes[relative], "frozen_source_identity/" + relative)
    runtime = report.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("recorded pinned runtime required")
    normalized = {key.lower().replace("_", "-"): value for key, value in runtime.items()}
    checks.equal(normalized, EXPECTED_RUNTIME, "recorded_pinned_runtime")
    factors = report.get("factor_settings")
    if not isinstance(factors, dict):
        raise ValueError("declared factor settings required")
    _inventory(factors.get("legacy_config"), LEGACY_FACTOR_CONFIG, "legacy factor parameters")
    _inventory(factors.get("factor_configs"), FACTOR_ARMS, "one-factor settings arms")
    for values in factors["factor_configs"].values():
        _inventory(values, LEGACY_FACTOR_CONFIG, "one-factor parameters")
    checks.equal(factors, {
        "model": "fixed_one_factor_note_state_diagnostics", "factor_arms": list(FACTOR_ARMS),
        "legacy_config": LEGACY_FACTOR_CONFIG, "factor_configs": FACTOR_CONFIGS,
        "legacy_base_settings": report.get("hmm_settings"), "rms_postprocess": False,
        "primary_factor": PRIMARY["candidate"], "upstream_reproduction": False,
    }, "declared_one_factor_settings")


def audit_private(work: Path, report_path: Path):
    import soundfile

    started = time.monotonic()
    if work.is_symlink() or not work.is_dir():
        raise ValueError("private workspace unavailable or linked")
    raw_report = _read(report_path, 32_000_000)
    report = _json(raw_report)
    checks = Checks()
    for key, expected in {
        "schema": "note-state-factors-v1", "status": "complete", "all_cases_complete": True,
        "all_predictions_frozen_before_references": True,
        "reference_access_started_after_predicted_cases": 40,
        "planned_case_ids": list(CASES), "planned_arms": list(ARMS),
        "primary_comparison": PRIMARY, "quality_approved": False,
        "heldout_generalization": False, "product_changes": False,
        "reference_used_for_edits": False, "device": "cpu", "threads": 2,
    }.items():
        checks.equal(report.get(key), expected, "recorded_run_contract/" + key)
    _population(report.get("cases"))
    check_sources(report, checks)
    history = verify_history(report, checks)
    rescored, summaries, manifest = [], [], {}
    for row in report["cases"]:
        case, directory = row["id"], work / row["id"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private case directory unavailable or linked")
        wav = _read(directory / "source.wav", 60_000_000)
        checks.equal(sha256(wav), row["audio_sha256"], "original_source_identity")
        header = soundfile.info(io.BytesIO(wav))
        duration = row["duration_seconds"]
        if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
                or not math.isfinite(duration) or duration <= 0 or header.frames <= 0
                or abs(duration - header.frames / header.samplerate) > 1 / 16000 + 1e-10):
            raise ValueError("recorded duration differs from original audio")
        raw = _read(directory / "observations.npz")
        checks.equal(sha256(raw), row.get("observation_sha256"), "observation_file_identity")
        arrays = check_observations(raw, row["observations"], duration, checks)
        predictions, payloads, manifest[case] = {}, {}, {}
        for arm in ARMS:
            raw = _read(directory / (arm + ".json"))
            notes, intervals, hz = parse_notes(raw, duration)
            checks.equal(sha256(raw), row["arms"][arm]["event_sha256"], "complete_prediction_identity")
            checks.equal(row["arms"][arm]["count"], len(notes), "prediction_count")
            predictions[arm], payloads[arm], manifest[case][arm] = (intervals, hz), notes, sha256(raw)
        diagnostics, rms = check_readouts(arrays, duration, payloads, row["diagnostics"], checks)
        _inventory(row.get("reference_sha256"), ANNOTATORS, "original reference hashes")
        references = {}
        for ann in ANNOTATORS:
            raw = _read(directory / (ann + ".csv"))
            checks.equal(sha256(raw), row["reference_sha256"][ann], "original_reference_identity")
            references[ann] = parse_reference(raw)
        raw = _read(directory / "f0.csv")
        checks.equal(sha256(raw), row["f0_reference_sha256"], "original_f0_reference_identity")
        checks.equal(row["f0_metrics"], direct_f0_score(raw, arrays["hz"]), "independent_f0_matching")
        computed, base_ids = {"id": case, "status": "scored", "arms": {}}, {}
        for arm in ARMS:
            result = {"count": len(payloads[arm]), "annotators": {}}
            for ann in ANNOTATORS:
                values, ids = direct_score(references[ann], predictions[arm])
                if arm == ARMS[0]:
                    base_ids[ann] = ids
                for criterion in ("onset", "onset_offset"):
                    values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[ann][criterion])
                    values[criterion + "_lost_reference_ids"] = sorted(base_ids[ann][criterion] - ids[criterion])
                checks.equal(row["arms"][arm]["annotators"][ann], values, "independent_note_matching")
                result["annotators"][ann] = values
            computed["arms"][arm] = result
        rescored.append(computed)
        summaries.append({"id": case, "status": "pass", "frames": len(arrays["hz"]),
                          "observation_arrays": len(arrays), "prediction_files": len(predictions),
                          "human_references": len(references), "path_readouts": len(PATHS),
                          "diagnostics": diagnostics, "rms": rms})
    for key in ("predictions_manifest_sha256", "post_evaluation_predictions_manifest_sha256"):
        checks.equal(report.get(key), fingerprint(manifest), "prediction_manifest_identity/" + key)
    aggregate = aggregate_rows(rescored)
    _inventory(report.get("aggregate"), ARMS, "aggregate arms")
    checks.equal(report["aggregate"], aggregate, "independent_aggregate")
    primary = primary_summary(rescored)
    checks.equal(report.get("primary_result"), primary, "independent_paired_primary_bootstrap")
    return {
        "schema": "note-state-factors-audit-v1", "status": "pass", "audit_completed": True,
        "scope": "private saved evidence, path readout, direct mir_eval rescoring, historical identities and paired arithmetic",
        "report_sha256": sha256(raw_report), "script_sha256": sha256(Path(__file__).read_bytes()),
        "archive_sha256": report["archive_sha256"], "source_sha256": report["source_sha256"],
        "runtime": {name: version(name) for name in ("numpy", "scipy", "mir_eval", "soundfile")},
        **history, "historical_parity_independently_recomputed": True,
        "predictions_manifest_sha256": fingerprint(manifest),
        "checks_passed": sum(checks.counts.values()), "checks_by_kind": dict(sorted(checks.counts.items())),
        "maximum_numeric_difference": checks.maximum_numeric_difference,
        "cases": summaries, "aggregate": aggregate, "primary_result": primary,
        "source_files_verified": len(SOURCE_PATHS), "audio_source_files_verified": len(CASES),
        "observation_arrays_verified": len(CASES) * len(OBSERVATIONS),
        "complete_prediction_files_verified": len(CASES) * len(ARMS),
        "path_readouts_verified": len(CASES) * len(PATHS),
        "human_reference_files_verified": len(CASES) * len(ANNOTATORS),
        "f0_reference_files_verified_and_rescored": len(CASES),
        "historical_observation_identities_verified": 240,
        "historical_hmm_prediction_files_verified": 200,
        "original_dsp_prediction_files_verified": 120,
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0,
        "source_network_downloads": 0, "raw_musical_arrays_published": False,
        "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "Reads every saved private file and independently reconstructs path readout/RMS edits; does not rerun pYIN or HMM/Viterbi inference or establish path optimality.",
            "Historical arrays/notes are unavailable: old comparisons use archived array identities, serialized note hashes, metrics and diagnostics, with both original ZIP hashes pinned.",
            "Recomputes F0 and note matching with mir_eval; this is independent code and arithmetic, not independent human truth or an independent matching algorithm.",
            "Saved files and declared source/runtime cannot independently prove historical reference-access order, runtime execution identity or that the declared code produced a path.",
            "Reference gain/loss depends on deterministic maximum matching; ambiguous admissible matchings do not establish causal normal-note damage.",
            "The paired percentile interval describes the same forty repeatedly used development recordings; no held-out, interaction, product, notation or human-edit claim is validated.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    if (args.audit.exists() or args.audit.is_symlink()
            or args.audit.resolve() == args.report.resolve()
            or args.audit.resolve().is_relative_to(args.work.resolve())):
        parser.error("a new distinct audit output outside the private evidence is required")
    try:
        result = audit_private(args.work, args.report)
    except Exception as exc:
        result = {"schema": "note-state-factors-audit-v1", "status": "failed", "audit_completed": False,
                  "error_type": type(exc).__name__, "error": str(exc), "planned_case_ids": list(CASES),
                  "aggregate": None, "raw_musical_arrays_published": False}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.audit.with_suffix(args.audit.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.audit)
    print(json.dumps({"status": result["status"], "checks_passed": result.get("checks_passed", 0)}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
