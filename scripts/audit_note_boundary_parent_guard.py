"""Independently audit whole-parent approvals from saved inputs and predictions.

The implementation under test, its runners and all model predictors are absent
from this module. Frozen independent parsers and raw-run reconstruction are
reused; approval, restoration, coverage and the new comparisons are rebuilt.
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

from scripts import audit_note_boundary_readout as prior
from scripts.audit_note_boundary_diagnostics import (
    arm_details,
    exact_equal,
    fixed_pair_summary,
    strict_equal,
    summary,
)
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
from scripts.audit_note_state_factors import (
    check_observations,
    check_path_transitions,
    reconstruct_readout,
)

REPOSITORY = Path(__file__).resolve().parents[1]
CASES, ANNOTATORS = prior.CASES, prior.ANNOTATORS
BASE_ARM, SPLIT_ARM = prior.BASE_ARM, prior.ARM
ARM = "gaussian_raw_hysteresis_parent_guard"
OLD_ARMS, ARMS = prior.ARMS, (*prior.ARMS, ARM)
SYNTHETIC_OLD_ARMS = prior.SYNTHETIC_ARMS
SYNTHETIC_ARMS = (*SYNTHETIC_OLD_ARMS, ARM)
DIAGNOSTIC_ARMS = ("pitch_runs", BASE_ARM, SPLIT_ARM, ARM, "note_state_hmm")
CRITERIA, PARTITIONS = prior.CRITERIA, prior.PARTITIONS
PREVIOUS_RECEIPT = "docs/research/receipts/note-boundary-readout-43381098932-attempt-1.zip"
PREVIOUS_SHA256 = "f34e88d2b5023df5762fba46b4149167265efbd24a837d30500375b30cd5758f"
NUMERIC_MANIFEST = "docs/research/NOTE_BOUNDARY_PARENT_GUARD_NUMERIC_INPUTS_2026-11-13.json"
NUMERIC_MANIFEST_SHA256 = "faadd9f40129dbc2801c4e283b2d2946112113362d4786cc8be6cb731f8e6e6c"
NEW_SOURCE_PATHS = (
    "scripts/note_boundary_parent_guard.py", "scripts/run_note_boundary_parent_guard.py",
    "scripts/note_boundary_parent_guard_synthetic.py", "scripts/audit_note_boundary_parent_guard.py",
    "tests/test_note_boundary_parent_guard.py", "tests/test_run_note_boundary_parent_guard.py",
    "tests/test_note_boundary_parent_guard_synthetic.py", "tests/test_audit_note_boundary_parent_guard.py",
    ".github/workflows/cpu-note-boundary-parent-guard.yml",
    "docs/research/NOTE_BOUNDARY_PARENT_GUARD_PROTOCOL_2026-11-13.md",
    "docs/research/NOTE_BOUNDARY_PARENT_GUARD_EXECUTION_2026-11-13.md",
    PREVIOUS_RECEIPT, NUMERIC_MANIFEST,
)
SOURCE_PATHS = (*prior.SOURCE_PATHS, *NEW_SOURCE_PATHS)
ROW_ADDITIONS = frozenset(("guard", "guard_private_sha256", "guard_annotation_diagnostics",
                           "guard_annotation_private_sha256"))
PRIMARY = {"candidate": ARM, "baseline": BASE_ARM, "metric": "onset_offset_f1"}
HARM_KEYS = ("lost_references", "lost_matched_parent_proposed_cut", "lost_matched_parent_accepted",
             "lost_matched_parent_rejected", "lost_matched_parent_with_proposed_short_children",
             "lost_matched_parent_all_proposed_children_fail", "lost_matched_parent_final_empty")
GUARD_SETTINGS = {
    "arm": ARM, "base_arm": BASE_ARM, "secondary_baseline": SPLIT_ARM, "change_support_frames": 5,
    "candidate_cut": "adjacent_nonnegative_unequal_global_raw_hysteresis_labels",
    "cut_scope": "strictly_inside_original_emitted_G_parent_before_clipped_audio_end",
    "hysteresis_backdate": "first_evidence_frame", "parent_source": "same_gaussian_exponent_1_path",
    "event_pitch": "rint(median(raw_positive_fractional_midi_in_child))", "minimum_note_seconds": .08,
    "approval": "all_proposed_children_pass_original_readout_or_restore_original_Note",
    "nonemitted_parent_resurrection": False, "partial_cut_selection": False,
    "raw_unvoiced_posthoc_split": False, "time_shift_seconds": 0., "reference_informed_cuts": False,
    "candidate": ARM, "baseline": BASE_ARM, "shared_G_path": True, "bootstrap_seed": 298,
    "bootstrap_resamples": 10000, "private_details": "original_proposed_final_segments_and_annotation_pair_rows",
    "pruning_harm_descriptors_are_overlapping_not_causal": True,
}
COHORTS = ("legacy", "single_expression", "adjacent_semitone")
TIMING_SEMANTICS = {
    "frame_seconds": .01, "leading_silence_frames": 10, "trailing_silence_intervals": 10,
    "sample_count": "voiced_frames + 21", "voiced_frame_interval": "[10, 10 + voiced_frames)",
    "duration_seconds": "(voiced_frames + 20) * 0.01",
    "terminal_sample": "zero Hz at duration; no extra audio interval",
    "modulation_time": "local voiced integer frame * 0.01; phase 0",
    "adjacent_change_frame": "10 + voiced_frames // 2; continuous modulation phase",
    "hz_conversion": "440 * 2 ** ((fractional_midi - 69) / 12)",
    "audio_duration_clipping": "unchanged frozen readout",
}


def interval_union(events):
    """Merge touching intervals using exact endpoints, independent of their pitch."""
    result = []
    for note in sorted(events, key=lambda item: (item["onset"], item["offset"])):
        begin, stop = note["onset"], note["offset"]
        if not math.isfinite(begin) or not math.isfinite(stop) or stop <= begin:
            raise ValueError("invalid interval in coverage union")
        if result and begin <= result[-1][1]:
            result[-1][1] = max(result[-1][1], stop)
        else:
            result.append([begin, stop])
    return result


def reconstruct_guard(path, hz, duration):
    """Approve complete proposals over independently rebuilt, frozen G parents.

    The preceding independent audit obtains raw labels by walking maximal raw
    pitch runs rather than calling the implementation's hysteresis function.
    Its split trace is only a source of independently derived parent bounds and
    unfiltered child readouts; every whole-parent decision is made here.
    """
    _, split_diagnostics, split_trace = prior.reconstruct_split(path, hz, duration)
    states, values = np.asarray(path), np.asarray(hz, dtype=float)
    notes, parents, proposals = [], [], []
    originals, proposed_cuts, accepted_cuts = [], [], []
    for parent in split_trace["parents"]:
        original = dict(parent["original"])
        if original["emitted"]:
            originals.append(prior._event(original))
        cuts = list(parent["applied_cut_frames"]) if original["emitted"] else []
        children = []
        if cuts:
            proposed_cuts.extend(cuts)
            for raw in parent["children"]:
                child = {**raw, "child_id": len(proposals), "passes_readout": raw["discard_reason"] is None,
                         "emitted": False, "prediction_index": None}
                children.append(child)
                proposals.append(child)
        reasons = sorted({child["discard_reason"] for child in children if not child["passes_readout"]})
        decision = ("nonemitted" if not original["emitted"] else "no_cut" if not cuts
                    else "rejected" if reasons else "accepted")
        final = []
        if decision == "accepted":
            accepted_cuts.extend(cuts)
            for child in children:
                child["emitted"], child["prediction_index"] = True, len(notes)
                final.append({key: value for key, value in child.items() if key != "passes_readout"})
                notes.append(prior._event(child))
        else:
            final.append({**original, "prediction_index": len(notes) if original["emitted"] else None})
            if original["emitted"]:
                notes.append(prior._event(original))
        parents.append({key: parent[key] for key in ("parent_id", "begin_frame", "stop_frame", "state_pitch_index")}
                       | {"original": original, "proposed_cut_frames": cuts,
                          "accepted_cut_frames": list(cuts) if decision == "accepted" else [],
                          "decision": decision, "rejection_reasons": reasons,
                          "proposed_children": children, "final_segments": final})
    trace = {"schema_version": 1, "candidate_cut_frames": split_trace["candidate_cut_frames"], "parents": parents}
    final_segments = [segment for parent in parents for segment in parent["final_segments"]]
    original_segments = [parent["original"] for parent in parents]
    baseline = prior._child_diagnostics(original_segments, states, values, duration)
    readout = prior._child_diagnostics(final_segments, states, values, duration)
    proposed = prior._child_diagnostics(
        [{**child, "emitted": child["passes_readout"]} for child in proposals], states, values, duration)
    original_union, output_union = interval_union(originals), interval_union(notes)
    if original_union != output_union:
        raise ValueError("independent guard interval union is not preserved")
    rejected = [parent for parent in parents if parent["decision"] == "rejected"]
    accepted = [parent for parent in parents if parent["decision"] == "accepted"]
    for parent in parents:
        emitted = [segment for segment in parent["final_segments"] if segment["emitted"]]
        if parent["decision"] == "nonemitted" and (emitted or parent["proposed_children"]):
            raise ValueError("nonemitted original parent resurrected")
        if parent["decision"] in ("rejected", "no_cut"):
            if [prior._event(segment) for segment in emitted] != [prior._event(parent["original"])]:
                raise ValueError("original event was not restored exactly")
        if parent["decision"] == "accepted":
            if not all(child["passes_readout"] for child in parent["proposed_children"]):
                raise ValueError("partial proposal approval")
            if interval_union([prior._event(segment) for segment in emitted]) != interval_union([prior._event(parent["original"])]):
                raise ValueError("accepted children changed parent interval union")
    baseline_seconds, output_seconds = baseline["emitted_note_seconds"], readout["emitted_note_seconds"]
    diagnostics = {"schema_version": 1,
        "candidate_cut_count": len(trace["candidate_cut_frames"]), "parent_segment_count": len(parents),
        "originally_emitted_parent_count": len(originals),
        "originally_nonemitted_parent_count": len(parents) - len(originals),
        "proposed_parent_count": sum(bool(parent["proposed_cut_frames"]) for parent in parents),
        "proposed_cut_count": len(proposed_cuts), "proposed_child_count": len(proposals),
        "accepted_parent_count": len(accepted), "accepted_cut_count": len(accepted_cuts),
        "accepted_child_count": sum(len(parent["final_segments"]) for parent in accepted),
        "rejected_parent_count": len(rejected), "restored_original_event_count": len(rejected),
        "unchanged_original_event_count": sum(parent["decision"] == "no_cut" for parent in parents),
        "rejected_parent_reason_counts": {reason: sum(reason in parent["rejection_reasons"] for parent in rejected)
            for reason in ("short", "no_raw_support", "zero_duration")},
        "final_segment_count": len(final_segments),
        "originally_emitted_parents_all_children_pruned": sum(
            parent["original"]["emitted"] and not any(segment["emitted"] for segment in parent["final_segments"])
            for parent in parents),
        "nonemitted_parents_resurrected": sum(
            not parent["original"]["emitted"] and any(segment["emitted"] for segment in parent["final_segments"])
            for parent in parents),
        "baseline": baseline, "readout": readout, "proposed": proposed,
        "baseline_emitted_seconds": baseline_seconds, "emitted_seconds": output_seconds,
        "emitted_seconds_change": output_seconds - baseline_seconds,
        "baseline_emitted_coverage_fraction": baseline_seconds / duration if duration else 0.,
        "emitted_coverage_fraction": output_seconds / duration if duration else 0.,
        "baseline_interval_union_count": len(original_union), "output_interval_union_count": len(output_union),
        "baseline_interval_union_seconds": math.fsum(stop - start for start, stop in original_union),
        "output_interval_union_seconds": math.fsum(stop - start for start, stop in output_union),
        "baseline_interval_union_sha256": fingerprint(original_union),
        "output_interval_union_sha256": fingerprint(output_union), "output_interval_union_preserved": True,
        "proposed_child_seconds_summary": summary(max(0., child["offset_seconds"] - child["onset_seconds"]) for child in proposals),
        "proposed_child_midi_median_summary": summary(child["raw_positive_midi_median"] for child in proposals
                                                       if child["raw_positive_midi_median"] is not None),
        "proposed_child_raw_voiced_frames_summary": summary(child["raw_voiced_frames"] for child in proposals),
        "final_emitted_seconds_summary": summary(note["offset"] - note["onset"] for note in notes),
        "candidate_cut_frames_sha256": fingerprint(trace["candidate_cut_frames"]),
        "proposed_cut_frames_sha256": fingerprint(proposed_cuts), "accepted_cut_frames_sha256": fingerprint(accepted_cuts),
        "raw_hysteresis_label_identity": split_diagnostics["raw_hysteresis_label_identity"],
        "trace_sha256": fingerprint(trace)}
    return notes, diagnostics, trace


def primary_summary(rows, baseline=BASE_ARM):
    """Rebuild the fixed recording-paired bootstrap without runner arithmetic."""
    if [row.get("id") for row in rows] != list(CASES) or len(rows) != 40:
        raise ValueError("paired bootstrap requires all forty ordered recordings")
    if baseline not in (BASE_ARM, SPLIT_ARM):
        raise ValueError("undeclared comparison baseline")
    deltas = [math.fsum(row["arms"][ARM]["annotators"][ann]["onset_offset_f1"]
              - row["arms"][baseline]["annotators"][ann]["onset_offset_f1"]
              for ann in ANNOTATORS) / 2 for row in rows]
    if not all(math.isfinite(delta) and -1 <= delta <= 1 for delta in deltas):
        raise ValueError("invalid paired recording delta")
    draws = np.random.default_rng(298).integers(0, 40, size=(10000, 40))
    values = sorted(math.fsum(deltas[int(index)] for index in sample) / 40 for sample in draws)

    def quantile(probability):
        position = probability * (len(values) - 1)
        lower = math.floor(position)
        return values[lower] + (values[math.ceil(position)] - values[lower]) * (position - lower)

    improved, worse = sum(delta > 1e-8 for delta in deltas), sum(delta < -1e-8 for delta in deltas)
    return {"candidate": ARM, "baseline": baseline, "metric": "onset_offset_f1",
        "paired_recording_deltas": [{"id": case, "delta": delta}
                                    for case, delta in zip(CASES, deltas, strict=True)],
        "mean_delta": math.fsum(deltas) / 40, "recordings_improved": improved,
        "recordings_worse": worse, "recordings_tied": 40 - improved - worse,
        "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2", "seed": 298,
            "resamples": 10000, "confidence_level": .95, "method": "paired_percentile_linear",
            "low": quantile(.025), "high": quantile(.975)}, "heldout_generalization": False}


def aggregate_rows(rows):
    """Compute every arm, empty cases included, from the independently rescored rows."""
    if [row.get("id") for row in rows] != list(CASES) or len(rows) != 40:
        raise ValueError("complete ordered corpus population required")
    for row in rows:
        if row.get("status") != "scored" or set(row.get("arms", {})) != set(ARMS):
            raise ValueError("complete scored twelve-arm case required")
        if any(set(row["arms"][arm].get("annotators", {})) != set(ANNOTATORS) for arm in ARMS):
            raise ValueError("both annotators required for every arm")
    result = {}
    for arm in ARMS:
        value = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in ("onset_f1", "onset_offset_f1"):
            by_annotator = {ann: [row["arms"][arm]["annotators"][ann][metric] for row in rows]
                            for ann in ANNOTATORS}
            if not all(math.isfinite(score) and 0 <= score <= 1
                       for scores in by_annotator.values() for score in scores):
                raise ValueError("invalid corpus score")
            means = [math.fsum(pair) / 2 for pair in zip(by_annotator["A1"], by_annotator["A2"], strict=True)]
            deltas = [mean - math.fsum(row["arms"]["pitch_runs"]["annotators"][ann][metric]
                      for ann in ANNOTATORS) / 2 for mean, row in zip(means, rows, strict=True)]
            improved, worse = sum(delta > 1e-8 for delta in deltas), sum(delta < -1e-8 for delta in deltas)
            value[metric] = {"macro": math.fsum(means) / 40,
                "A1_macro": math.fsum(by_annotator["A1"]) / 40, "A2_macro": math.fsum(by_annotator["A2"]) / 40,
                "delta_vs_runs": math.fsum(deltas) / 40, "recordings_improved": improved,
                "recordings_worse": worse, "recordings_tied": 40 - improved - worse}
        for rate in ("onset_precision", "onset_recall", "offset_precision", "offset_recall"):
            rates = [row["arms"][arm]["annotators"][ann][rate] for row in rows for ann in ANNOTATORS]
            if not all(math.isfinite(rate) and 0 <= rate <= 1 for rate in rates):
                raise ValueError("invalid corpus precision or recall")
            value[rate] = math.fsum(rates) / 80
        for criterion in CRITERIA:
            for kind in ("gained", "lost"):
                field = criterion + "_" + kind + "_reference_ids"
                value[criterion + "_" + kind + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][field]) for row in rows for ann in ANNOTATORS)
        result[arm] = value
    return result


def load_previous(checks, path=None):
    raw = _read(REPOSITORY / PREVIOUS_RECEIPT if path is None else path, 32_000_000)
    checks.equal(sha256(raw), PREVIOUS_SHA256, "original_readout_receipt_identity")
    required = {"vocadito.json", "synthetic.json", "legacy-vocadito.json",
                "legacy-synthetic.json", "legacy-audit.json", "audit.json"}
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        if len(package.namelist()) != len(required) or set(package.namelist()) != required:
            raise ValueError("original six-member readout receipt inventory differs")
        if any(item.file_size > 32_000_000 for item in package.infolist()):
            raise ValueError("oversized original readout receipt member")
        members = {name: package.read(name) for name in required}
    corpus, synthetic, audit = (_json(members[name]) for name in ("vocadito.json", "synthetic.json", "audit.json"))
    checks.equal(corpus.get("status"), "complete", "historical_corpus_complete")
    checks.equal(synthetic.get("status"), "complete", "historical_synthetic_complete")
    checks.equal(audit.get("status"), "pass", "historical_readout_audit_pass")
    checks.equal(audit.get("audit_completed"), True, "historical_readout_audit_complete")
    checks.equal(audit.get("report_sha256"), sha256(members["vocadito.json"]), "historical_corpus_audit_binding")
    checks.equal(audit.get("synthetic_report_sha256"), sha256(members["synthetic.json"]), "historical_synthetic_audit_binding")
    return corpus, synthetic, audit


def check_sources(report, previous, checks):
    hashes = report.get("source_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(SOURCE_PATHS):
        raise ValueError("exact sixty-six-source inventory required")
    if set(previous.get("source_sha256", {})) != set(prior.SOURCE_PATHS):
        raise ValueError("historical fifty-three-source inventory differs")
    for name in SOURCE_PATHS:
        checks.equal(hashes[name], sha256(_read(REPOSITORY / name, 32_000_000)), "frozen_source_identity/" + name)
        if name in prior.SOURCE_PATHS:
            checks.equal(hashes[name], previous["source_sha256"][name], "historical_source_preserved/" + name)


def require_legacy_audit(legacy, raw_legacy, raw_synthetic, audit, checks):
    expected = {"schema": "note-boundary-readout-audit-v1", "status": "pass", "audit_completed": True,
        "report_sha256": sha256(raw_legacy), "synthetic_report_sha256": sha256(raw_synthetic),
        "script_sha256": sha256(_read(REPOSITORY / "scripts/audit_note_boundary_readout.py")),
        "source_files_verified": 53, "corpus_prediction_files_verified": 440,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1960, "synthetic_input_arrays_verified": 245,
        "synthetic_old_state_paths_verified": 1470, "independent_new_readouts_verified": 285}
    for key, value in expected.items():
        strict_equal(checks, audit.get(key), value, "legacy_private_audit_binding/" + key)
    checks.equal(legacy.get("status"), "complete", "legacy_projection_complete")


def stress_specs():
    """The complete predeclared product, with no selected subset or predictions."""
    axes = ((45, 57, 69), (-.4, 0., .4), (.3, .6), (3, 6), (24, 48, 96))
    rows = []
    for kind in COHORTS[1:]:
        for index, values in enumerate(itertools.product(*axes), 1):
            rows.append(dict(zip(("pitch", "detuning", "amplitude", "frequency_hz", "frames"), values, strict=True))
                        | {"id": f"stress_{kind}_{index:03d}", "kind": kind})
    return rows


def stress_observations(spec):
    """Recreate the fixed input expression; truth never enters this function."""
    if spec not in stress_specs():
        raise ValueError("undeclared authored stress specification")
    length = spec["frames"]
    midi = spec["pitch"] + spec["detuning"] + spec["amplitude"] * np.sin(
        2 * np.pi * spec["frequency_hz"] * np.arange(length, dtype=np.float64) * .01)
    if spec["kind"] == "adjacent_semitone":
        midi[length // 2:] += 1.
    values = np.zeros(length + 21, dtype=np.float64)
    values[10:10 + length] = 440 * 2 ** ((midi - 69) / 12)
    return values, (length + 20) * .01


def stress_truth(spec):
    if spec not in stress_specs():
        raise ValueError("undeclared authored stress truth")
    pitch = spec["pitch"] + spec["detuning"]
    begin, stop = .1, (10 + spec["frames"]) * .01
    if spec["kind"] == "single_expression":
        return [{"pitch": pitch, "onset": begin, "offset": stop, "is_drum": False}]
    middle = (10 + spec["frames"] // 2) * .01
    return [{"pitch": pitch, "onset": begin, "offset": middle, "is_drum": False},
            {"pitch": pitch + 1., "onset": middle, "offset": stop, "is_drum": False}]


def check_numeric_preflight(report, previous_synthetic, checks, manifest_path=None):
    """Bind both input-only gates to the exact arrays reused by prediction."""
    legacy_gate = prior.check_numeric_preflight({"cases": report["cases"][:245],
        "emission_analysis": report["emission_analysis"], "preflight": report["preflight"]["legacy"]},
        previous_synthetic, checks)
    raw = _read(REPOSITORY / NUMERIC_MANIFEST if manifest_path is None else manifest_path, 4_000_000)
    checks.equal(sha256(raw), NUMERIC_MANIFEST_SHA256, "stress_input_manifest_identity")
    manifest = _json(raw)
    expected_keys = {"schema", "baseline_zip_sha256", "legacy_numeric_manifest_sha256",
                     "timing_semantics", "generation_environment", "cases"}
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ValueError("exact input-only stress manifest inventory required")
    for key, expected in {"schema": "note-boundary-parent-guard-numeric-inputs-v1",
        "baseline_zip_sha256": PREVIOUS_SHA256, "legacy_numeric_manifest_sha256": prior.NUMERIC_MANIFEST_SHA256,
        "timing_semantics": TIMING_SEMANTICS}.items():
        exact_equal(checks, manifest[key], expected, "stress_input_only_manifest/" + key)
    environment = manifest["generation_environment"]
    if not isinstance(environment, dict) or set(environment) != {
        "python", "executable", "platform", "numpy_version", "numpy_file", "runtime",
        "cpu_features", "cpu_baseline", "cpu_dispatch", "numpy_disable_cpu_features"}:
        raise ValueError("exact generation environment inventory required")
    checks.equal(environment["numpy_version"], "1.26.4", "stress_generation_numpy_pin")
    expected_inputs = []
    for spec in stress_specs():
        hz, duration = stress_observations(spec)
        expected_inputs.append({"id": spec["id"], "duration_seconds": duration, "observation": array_identity(hz)})
    exact_equal(checks, manifest["cases"], expected_inputs, "independent_stress_input_regeneration")
    current = [{key: row[key] for key in ("id", "duration_seconds", "observation")} for row in report["cases"][245:]]
    exact_equal(checks, current, expected_inputs, "same_stress_preflight_inputs_used")
    stress_gate = {"manifest_sha256": NUMERIC_MANIFEST_SHA256, "compared_input_arrays": 216,
                   "all_equal": True, "input_differences": [], "model_calls_before_preflight": 0}
    receipt = {"schema": "note-boundary-parent-guard-preflight-v1", "legacy": legacy_gate,
        "stress": stress_gate, "compared_input_arrays": 461, "compared_analytic_rows": 20,
        "all_equal": True, "model_calls_before_preflight": 0}
    strict_equal(checks, report["preflight"], receipt, "independent_combined_input_only_preflight")
    exact_equal(checks, report["stress_timing_semantics"], TIMING_SEMANTICS, "frozen_stress_clock")
    return receipt


def note_evaluation(reference, prediction):
    """Recompute separate timing-pair pitch diagnostics using direct mir_eval."""
    import mir_eval.transcription as transcription

    ref_intervals, ref_hz = reference
    pred_intervals, pred_hz = prediction
    if not len(ref_hz):
        raise ValueError("eligible nonempty authored truth required")
    result = {"reference_notes": len(ref_hz), "predicted_notes": len(pred_hz),
              "note_count_change": len(pred_hz) - len(ref_hz)}

    def matched(pitch_tolerance, offset_ratio):
        return transcription.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
            onset_tolerance=.05, pitch_tolerance=pitch_tolerance, offset_ratio=offset_ratio,
            offset_min_tolerance=.05) if len(pred_hz) else []

    for name, ratio in (("onset", None), ("onset_offset", .2)):
        pairs = matched(50., ratio)
        result[name] = {"matched_notes": len(pairs), "precision": len(pairs) / len(pred_hz) if len(pred_hz) else 0.,
                        "recall": len(pairs) / len(ref_hz)}
    timed = matched(np.inf, .2)
    cents = sorted(float(abs(1200 * np.log2(pred_hz[j] / ref_hz[i]))) for i, j in timed)
    median = ((cents[(len(cents) - 1) // 2] + cents[len(cents) // 2]) / 2) if cents else None
    result.update(timing_only_matched_pairs=len(timed),
        timing_only_unmatched_reference_notes=len(ref_hz) - len(timed),
        timing_only_unmatched_prediction_notes=len(pred_hz) - len(timed),
        timing_matched_pitch_correct_pairs=sum(value <= 50. for value in cents),
        timing_matched_pitch_wrong_pairs=sum(value > 50. for value in cents),
        timing_matched_absolute_pitch_cents={"count": len(cents), "minimum": cents[0] if cents else None,
                                           "median": median, "maximum": cents[-1] if cents else None})
    return result


def synthetic_population(rows, previous_rows):
    if len(rows) != 461 or len(previous_rows) != 245:
        raise ValueError("all 245 legacy and 216 stress cases required")
    specs = [row["spec"] for row in previous_rows] + stress_specs()
    eligible = [row["accuracy_eligible"] for row in previous_rows] + [True] * 216
    for index, (row, spec, accuracy) in enumerate(zip(rows, specs, eligible, strict=True)):
        cohort = "legacy" if index < 245 else spec["kind"]
        if (row.get("id") != spec["id"] or row.get("spec") != spec or row.get("cohort") != cohort
                or type(row.get("accuracy_eligible")) is not bool or row["accuracy_eligible"] != accuracy
                or set(row.get("arms", {})) != set(SYNTHETIC_ARMS)):
            raise ValueError("exact ordered nine-arm synthetic specifications required")
    legacy = rows[:245]
    populations = {"legacy": {"all_cases": len(legacy), "accuracy_eligible_cases": sum(row["accuracy_eligible"] for row in legacy),
        "ambiguous_cases": sum(row["spec"]["kind"] == "dropout" or (row["spec"]["kind"] == "repeat" and row["spec"]["gap"] == 0) for row in legacy),
        "silence_cases": sum(row["spec"]["kind"] == "silence" for row in legacy)}}
    for cohort in COHORTS[1:]:
        selected = [row for row in rows if row["cohort"] == cohort]
        populations[cohort] = {"all_cases": len(selected), "accuracy_eligible_cases": sum(row["accuracy_eligible"] for row in selected)}
    if populations != {"legacy": {"all_cases": 245, "accuracy_eligible_cases": 227, "ambiguous_cases": 15, "silence_cases": 3},
                       "single_expression": {"all_cases": 108, "accuracy_eligible_cases": 108},
                       "adjacent_semitone": {"all_cases": 108, "accuracy_eligible_cases": 108}}:
        raise ValueError("fixed cohort denominators differ")
    return populations


def synthetic_case_comparison(row, baseline):
    old, new = row["arms"][baseline], row["arms"][ARM]
    result = {"baseline_arm": baseline, "candidate_arm": ARM,
        "predicted_notes_change": new["count"] - old["count"],
        "event_identity_unchanged": new["event_sha256"] == old["event_sha256"],
        "no_accepted_cuts": new["readout"]["accepted_cut_count"] == 0,
        "onset_f1_change": None, "onset_offset_f1_change": None, "baseline_perfect": None, "candidate_perfect": None}
    if row["accuracy_eligible"]:
        for metric in ("onset_f1", "onset_offset_f1"):
            result[metric + "_change"] = new["metrics"][metric] - old["metrics"][metric]
        result["baseline_perfect"] = old["metrics"]["onset_f1"] == old["metrics"]["onset_offset_f1"] == 1.
        result["candidate_perfect"] = new["metrics"]["onset_f1"] == new["metrics"]["onset_offset_f1"] == 1.
    if baseline == BASE_ARM and result["no_accepted_cuts"] and not result["event_identity_unchanged"]:
        raise ValueError("no-accepted-cut original event bytes differ")
    return result


def synthetic_aggregate(rows, previous_rows):
    synthetic_population(rows, previous_rows)
    result = {}
    for cohort in COHORTS:
        selected = [row for row in rows if row["cohort"] == cohort]
        eligible = [row for row in selected if row["accuracy_eligible"]]
        result[cohort] = {}
        for arm in SYNTHETIC_ARMS:
            value = {"all_cases_predicted_notes": sum(row["arms"][arm]["count"] for row in selected),
                "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in selected),
                "eligible_cases": len(eligible),
                "silence_false_positive_notes": sum(row["arms"][arm]["count"] for row in selected if row["spec"]["kind"] == "silence"),
                "too_many_note_cases": sum(row["arms"][arm]["count"] > len(row["truth"]) for row in eligible),
                "too_few_note_cases": sum(row["arms"][arm]["count"] < len(row["truth"]) for row in eligible),
                "equal_note_count_cases": sum(row["arms"][arm]["count"] == len(row["truth"]) for row in eligible),
                "timing_only_matched_pairs": sum(row["note_evaluation"][arm]["timing_only_matched_pairs"] for row in eligible),
                "timing_matched_pitch_wrong_pairs": sum(row["note_evaluation"][arm]["timing_matched_pitch_wrong_pairs"] for row in eligible)}
            for metric in ("onset_f1", "onset_offset_f1"):
                value[metric] = math.fsum(row["arms"][arm]["metrics"][metric] for row in eligible) / len(eligible)
            result[cohort][arm] = value
    return result


def synthetic_comparisons(rows, previous_rows):
    populations = synthetic_population(rows, previous_rows)
    result = {}
    for cohort in COHORTS:
        selected = [row for row in rows if row["cohort"] == cohort]
        eligible = [row for row in selected if row["accuracy_eligible"]]
        comparisons = {}
        for baseline in (BASE_ARM, SPLIT_ARM):
            changes = {}
            for metric in ("onset_f1", "onset_offset_f1"):
                deltas = [row["guard_comparisons"][baseline][metric + "_change"] for row in eligible]
                changes[metric] = {"macro_change": math.fsum(deltas) / len(deltas),
                    "improved_cases": sum(value > 0 for value in deltas), "worse_cases": sum(value < 0 for value in deltas),
                    "tied_cases": sum(value == 0 for value in deltas)}
            comparisons[baseline] = {"baseline_arm": baseline, "candidate_arm": ARM,
                "identical_event_cases": sum(row["guard_comparisons"][baseline]["event_identity_unchanged"] for row in selected),
                "eligible_metric_changes": changes}
        result[cohort] = {**populations[cohort], "baseline_comparisons": comparisons,
            "no_accepted_cut_cases": sum(row["arms"][ARM]["readout"]["accepted_cut_count"] == 0 for row in selected)}
    successes = [row for row in rows[:245] if row["guard_comparisons"][BASE_ARM]["baseline_perfect"]]
    control_ids = ["change_195", "change_197", "change_207", "change_209", "change_219", "change_221"]
    controls = [row for row in rows[:245] if row["id"] in control_ids]
    if len(successes) != 221 or [row["id"] for row in controls] != control_ids:
        raise ValueError("fixed six controls and 221 previous successes required")
    result["legacy"].update(previous_gaussian_perfect_cases=len(successes),
        previous_gaussian_perfect_case_ids=[row["id"] for row in successes],
        damaged_previous_success_case_ids=[row["id"] for row in successes if not row["guard_comparisons"][BASE_ARM]["candidate_perfect"]],
        joined_semitone_controls=[{"id": row["id"], "reference_notes": len(row["truth"]),
            "baseline_predicted_notes": row["arms"][BASE_ARM]["count"], "split_predicted_notes": row["arms"][SPLIT_ARM]["count"],
            "candidate_predicted_notes": row["arms"][ARM]["count"], "baseline_metrics": row["arms"][BASE_ARM]["metrics"],
            "split_metrics": row["arms"][SPLIT_ARM]["metrics"], "candidate_metrics": row["arms"][ARM]["metrics"],
            "candidate_two_notes_pitch_onset_offset_correct": len(row["truth"]) == row["arms"][ARM]["count"] == 2
                and row["guard_comparisons"][BASE_ARM]["candidate_perfect"]} for row in controls])
    return result


def reconstruct_pitch_runs(hz, duration):
    labels = np.full(len(hz), -1, dtype=int)
    voiced = hz > 0
    labels[voiced] = np.rint(69 + 12 * np.log2(hz[voiced] / 440.)).astype(int)
    notes = []
    start = 0
    for stop in range(1, len(labels) + 1):
        if stop < len(labels) and labels[stop] == labels[start]:
            continue
        begin_time, stop_time = start * .01, min(stop * .01, duration)
        if labels[start] >= 0 and stop_time - begin_time >= .08 - 1e-10:
            notes.append({"pitch": int(labels[start]), "onset": begin_time, "offset": stop_time, "is_drum": False})
        start = stop
    return notes


def annotation_details(reference, predictions, trace, split_trace):
    arms = {arm: arm_details(reference, predictions[arm]) for arm in DIAGNOSTIC_ARMS}
    parents = {parent["parent_id"]: parent for parent in trace["parents"]}
    if (len(parents) != len(trace["parents"]) or set(parents) != set(range(len(parents)))
            or [parent["original"] for parent in trace["parents"]] != [parent["original"] for parent in split_trace["parents"]]):
        raise ValueError("guard and split original parent crosswalk differs")
    mappings = {BASE_ARM: {parent["original"]["prediction_index"]: parent["parent_id"]
                          for parent in trace["parents"] if parent["original"]["emitted"]},
        SPLIT_ARM: {child["prediction_index"]: parent["parent_id"] for parent in split_trace["parents"]
                    for child in parent["children"] if child["emitted"]}}
    for baseline in (BASE_ARM, SPLIT_ARM):
        if set(mappings[baseline]) != set(range(len(predictions[baseline][1]))):
            raise ValueError("baseline prediction-to-parent mapping incomplete")
    universe, comparisons, harm = set(range(len(reference[0]))), {}, {}
    for baseline in (BASE_ARM, SPLIT_ARM):
        comparisons[baseline], harm[baseline] = {}, {}
        for criterion in CRITERIA:
            def pairs(arm):
                return ({pair["reference_id"]: pair["prediction_id"] for pair in arms[arm]["onset_pairs"]}
                        if criterion == "onset" else dict(arms[arm]["offset_pairs"]))

            before, after = pairs(baseline), pairs(ARM)
            old_ids, new_ids = set(before), set(after)
            lost = sorted(old_ids - new_ids)
            comparisons[baseline][criterion] = {"retained": sorted(old_ids & new_ids), "gained": sorted(new_ids - old_ids),
                "lost": lost, "neither": sorted(universe - old_ids - new_ids)}
            affected = [parents[mappings[baseline][before[index]]] for index in lost]
            harm[baseline][criterion] = {"lost_references": len(lost),
                "lost_matched_parent_proposed_cut": sum(bool(parent["proposed_cut_frames"]) for parent in affected),
                "lost_matched_parent_accepted": sum(parent["decision"] == "accepted" for parent in affected),
                "lost_matched_parent_rejected": sum(parent["decision"] == "rejected" for parent in affected),
                "lost_matched_parent_with_proposed_short_children": sum(any(child["discard_reason"] == "short" for child in parent["proposed_children"]) for parent in affected),
                "lost_matched_parent_all_proposed_children_fail": sum(bool(parent["proposed_children"])
                    and not any(child["passes_readout"] for child in parent["proposed_children"]) for parent in affected),
                "lost_matched_parent_final_empty": sum(not any(child["emitted"] for child in parent["final_segments"]) for parent in affected),
                "lost_reference_parents": [{"reference_id": reference_id, "baseline_prediction_id": before[reference_id],
                    "parent_id": parent["parent_id"], "decision": parent["decision"],
                    "proposed_cut_frames": parent["proposed_cut_frames"], "accepted_cut_frames": parent["accepted_cut_frames"],
                    "proposed_child_discard_reasons": [child["discard_reason"] for child in parent["proposed_children"]],
                    "final_prediction_indices": [segment["prediction_index"] for segment in parent["final_segments"] if segment["emitted"]]}
                    for reference_id, parent in zip(lost, affected, strict=True)]}
    return {"reference_notes": len(reference[0]), "arms": arms, "comparisons": comparisons, "parental_harm": harm}


def summarize_annotations(details):
    return {"recording_annotations": len(details), "reference_notes": sum(detail["reference_notes"] for detail in details),
        "arms": {arm: {"predicted_notes": sum(detail["arms"][arm]["predicted_notes"] for detail in details),
            "onset_matched": sum(len(detail["arms"][arm]["onset_pairs"]) for detail in details),
            "offset_matched": sum(len(detail["arms"][arm]["offset_pairs"]) for detail in details),
            "fixed_onset_pairs": fixed_pair_summary([pair for detail in details for pair in detail["arms"][arm]["onset_pairs"]])}
            for arm in DIAGNOSTIC_ARMS},
        "comparisons": {base: {criterion: {part: sum(len(detail["comparisons"][base][criterion][part]) for detail in details)
            for part in PARTITIONS} for criterion in CRITERIA} for base in (BASE_ARM, SPLIT_ARM)},
        "parental_harm": {base: {criterion: {key: sum(detail["parental_harm"][base][criterion][key] for detail in details)
            for key in HARM_KEYS} for criterion in CRITERIA} for base in (BASE_ARM, SPLIT_ARM)}}


def verify_prediction_files(work, rows, arms, checks, phase):
    """Read every planned file before scoring, then repeat after all comparisons."""
    manifest = {}
    for row in rows:
        directory = work / row["id"]
        if directory.is_symlink() or not directory.is_dir() or set(row.get("arms", {})) != set(arms):
            raise ValueError("incomplete private prediction directory or arm inventory")
        manifest[row["id"]] = {}
        for arm in arms:
            raw = _read(directory / (arm + ".json"))
            checks.equal(sha256(raw), row["arms"][arm]["event_sha256"], "all_predictions_" + phase + "/" + arm)
            manifest[row["id"]][arm] = sha256(raw)
    return fingerprint(manifest)


def corpus_from_private(work, report, legacy, checks):
    if work.is_symlink() or not work.is_dir():
        raise ValueError("private corpus directory unavailable or linked")
    if [row.get("id") for row in report.get("cases", [])] != list(CASES):
        raise ValueError("exact ordered forty-case inventory required")
    if [row.get("id") for row in legacy.get("cases", [])] != list(CASES):
        raise ValueError("exact ordered legacy forty-case inventory required")
    initial_manifest = verify_prediction_files(work, report["cases"], ARMS, checks, "before_references")
    checks.equal(report.get("predictions_manifest_sha256"), initial_manifest, "corpus_complete_barrier_manifest")
    rescored, annotations, summaries = [], [], []
    for row, old in zip(report["cases"], legacy["cases"], strict=True):
        if row.get("status") != "scored" or set(row.get("arms", {})) != set(ARMS):
            raise ValueError("every case must contain all twelve scored arms")
        if set(row) != set(old) | ROW_ADDITIONS:
            raise ValueError("exact public guard corpus case inventory required")
        if set(row.get("guard_annotation_diagnostics", {})) != set(ANNOTATORS):
            raise ValueError("exact guard annotation inventory required")
        if any(set(item) != {"count", "event_sha256", "annotators"}
               or set(item.get("annotators", {})) != set(ANNOTATORS) for item in row["arms"].values()):
            raise ValueError("exact corpus arm field and annotator inventory required")
        projected = {key: value for key, value in row.items() if key not in ROW_ADDITIONS}
        projected["arms"] = {arm: row["arms"][arm] for arm in OLD_ARMS}
        exact_equal(checks, projected, old, "actual_legacy_corpus_case_projection")
        directory, duration = work / row["id"], row["duration_seconds"]
        raw_npz = _read(directory / "observations.npz")
        checks.equal(sha256(raw_npz), row["observation_sha256"], "private_corpus_npz_identity")
        arrays = check_observations(raw_npz, row["observations"], duration, checks)
        predictions, payloads = {}, {}
        for arm in ARMS:
            raw = _read(directory / (arm + ".json"))
            notes, intervals, hz = parse_notes(raw, duration)
            checks.equal(sha256(raw), row["arms"][arm]["event_sha256"], "private_corpus_prediction_identity")
            checks.equal(len(notes), row["arms"][arm]["count"], "private_corpus_prediction_count")
            predictions[arm], payloads[arm] = (intervals, hz), notes
        notes, diagnostics, trace = reconstruct_guard(arrays[BASE_ARM + "_path"], arrays["hz"], duration)
        split_notes, split_diagnostics, split_trace = prior.reconstruct_split(arrays[BASE_ARM + "_path"], arrays["hz"], duration)
        original_notes = [prior._event(parent["original"]) for parent in trace["parents"] if parent["original"]["emitted"]]
        exact_equal(checks, payloads[BASE_ARM], original_notes, "independent_original_G_events")
        exact_equal(checks, payloads[SPLIT_ARM], split_notes, "independent_original_split_events")
        strict_equal(checks, row["readout"], split_diagnostics, "independent_original_split_diagnostics")
        exact_equal(checks, payloads[ARM], notes, "independent_guard_events")
        strict_equal(checks, row["guard"], diagnostics, "independent_guard_diagnostics")
        for name, key, expected in (("guard-private.json", "guard_private_sha256", trace),
                                    ("readout-private.json", "readout_private_sha256", split_trace)):
            raw = _read(directory / name)
            checks.equal(sha256(raw), row[key], "private_corpus_trace_identity/" + name)
            exact_equal(checks, _json(raw), expected, "independent_corpus_trace/" + name)
        exact_equal(checks, interval_union(payloads[ARM]), interval_union(payloads[BASE_ARM]), "corpus_final_interval_union_parity")
        if diagnostics["accepted_cut_count"] == 0:
            checks.equal(row["arms"][ARM]["event_sha256"], row["arms"][BASE_ARM]["event_sha256"], "corpus_no_accepted_cut_bytes")
        computed = {"id": row["id"], "status": "scored", "arms": {
            arm: {"count": len(payloads[arm]), "annotators": {}} for arm in ARMS}}
        details = {}
        for annotator in ANNOTATORS:
            raw_reference = _read(directory / (annotator + ".csv"))
            checks.equal(sha256(raw_reference), row["reference_sha256"][annotator], "private_human_reference_identity")
            reference = parse_reference(raw_reference)
            _, base_ids = direct_score(reference, predictions["pitch_runs"])
            for arm in ARMS:
                values, ids = direct_score(reference, predictions[arm])
                for criterion in CRITERIA:
                    values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[criterion])
                    values[criterion + "_lost_reference_ids"] = sorted(base_ids[criterion] - ids[criterion])
                strict_equal(checks, row["arms"][arm]["annotators"][annotator], values, "independent_all12_corpus_matching")
                computed["arms"][arm]["annotators"][annotator] = values
            detail = annotation_details(reference, predictions, trace, split_trace)
            strict_equal(checks, row["guard_annotation_diagnostics"][annotator], summarize_annotations([detail]),
                         "independent_corpus_guard_annotation_summary")
            details[annotator] = detail
        raw_details = _read(directory / "guard-annotation-private.json")
        checks.equal(sha256(raw_details), row["guard_annotation_private_sha256"], "private_guard_annotation_identity")
        strict_equal(checks, _json(raw_details), details, "independent_guard_matching_and_parent_crosswalk")
        raw_old_details = _read(directory / "annotation-private.json")
        checks.equal(sha256(raw_old_details), row["annotation_private_sha256"], "unchanged_old_annotation_file_identity")
        old_details = _json(raw_old_details)
        for annotator in ANNOTATORS:
            strict_equal(checks, old_details[annotator]["arms"],
                {arm: details[annotator]["arms"][arm] for arm in prior.DIAGNOSTIC_ARMS}, "unchanged_old_fixed_pair_details")
        rescored.append(computed)
        annotations.append(details)
        summaries.append({"id": row["id"], "status": "pass", "prediction_files": len(ARMS),
            "observation_arrays": len(arrays), "parents": len(trace["parents"]),
            "proposed_cuts": diagnostics["proposed_cut_count"], "accepted_cuts": diagnostics["accepted_cut_count"],
            "rejected_parents": diagnostics["rejected_parent_count"], "interval_union_preserved": True})
    final_manifest = verify_prediction_files(work, report["cases"], ARMS, checks, "after_scoring")
    checks.equal(final_manifest, initial_manifest, "corpus_predictions_unchanged_during_audit")
    checks.equal(report.get("post_evaluation_predictions_manifest_sha256"), final_manifest, "corpus_postscore_manifest")
    aggregate, primary, secondary = aggregate_rows(rescored), primary_summary(rescored), primary_summary(rescored, SPLIT_ARM)
    strict_equal(checks, report.get("aggregate"), aggregate, "independent_corpus_all12_aggregate")
    strict_equal(checks, report.get("primary_result"), primary, "independent_primary_seed298_bootstrap")
    strict_equal(checks, report.get("secondary_result"), secondary, "independent_secondary_seed298_bootstrap")
    boundary = {"by_annotator": {ann: summarize_annotations([detail[ann] for detail in annotations]) for ann in ANNOTATORS},
                "pooled_annotation_judgments": summarize_annotations([detail[ann] for detail in annotations for ann in ANNOTATORS])}
    strict_equal(checks, report.get("boundary_summary"), boundary, "independent_guard_pooled_boundaries")
    return {"cases": summaries, "aggregate": aggregate, "primary_result": primary, "secondary_result": secondary,
            "boundary_summary": boundary, "predictions_manifest_sha256": final_manifest}


def synthetic_from_private(work, report, legacy, previous, checks):
    """Verify all 4,149 saved events and both truth-independent readouts."""
    if work.is_symlink() or not work.is_dir():
        raise ValueError("private synthetic workspace unavailable or linked")
    expected_keys = set(previous) | {"stress_timing_semantics", "cohorts"}
    if not isinstance(report, dict) or set(report) != expected_keys:
        raise ValueError("exact completed guard synthetic report inventory required")
    for key, expected in {"schema": "note-boundary-parent-guard-synthetic-v1", "status": "complete",
        "planned_cases": 461, "planned_arms": list(SYNTHETIC_ARMS), "acoustic_extraction": False,
        "quality_approved": False, "heldout_generalization": False, "product_changes": False,
        "all_predictions_saved_before_scoring": True, "truth_access_started_after_prediction_files": 4149,
        "stress_timing_semantics": TIMING_SEMANTICS}.items():
        strict_equal(checks, report.get(key), expected, "synthetic_execution_contract/" + key)
    rows = report["cases"]
    populations = synthetic_population(rows, previous["cases"])
    strict_equal(checks, report["cohorts"], populations, "fixed_separate_synthetic_cohorts")
    legacy_count = len(previous["cases"])
    if len(legacy.get("cases", [])) != legacy_count:
        raise ValueError("complete legacy synthetic projection required")
    initial_manifest = verify_prediction_files(work, rows, SYNTHETIC_ARMS, checks, "before_synthetic_truth")
    checks.equal(report["predictions_manifest_sha256"], initial_manifest, "synthetic_complete_initial_manifest")
    manifest, old_manifest, projected = {}, {}, []
    additions = {"cohort", "guard_private_sha256", "guard_comparisons", "note_evaluation"}
    path_arms = prior.SYNTHETIC_OLD_ARMS[1:]
    for index, row in enumerate(rows):
        if set(row) != set(previous["cases"][0]) | additions:
            raise ValueError("exact synthetic case field inventory required")
        if index < legacy_count:
            old = previous["cases"][index]
            item = {key: value for key, value in row.items() if key not in additions}
            item["arms"] = {arm: row["arms"][arm] for arm in SYNTHETIC_OLD_ARMS}
            exact_equal(checks, item, old, "historical_full_synthetic_case")
            exact_equal(checks, item, legacy["cases"][index], "actual_legacy_synthetic_file_projection")
            projected.append(item)
            old_manifest[row["id"]] = {arm: row["arms"][arm]["event_sha256"] for arm in SYNTHETIC_OLD_ARMS}
        else:
            hz, duration = stress_observations(row["spec"])
            exact_equal(checks, row["observation"], array_identity(hz), "independent_stress_input_identity")
            exact_equal(checks, row["duration_seconds"], duration, "independent_stress_duration")
            exact_equal(checks, row["truth"], stress_truth(row["spec"]), "independent_fractional_stress_truth")
            exact_equal(checks, row["alternative_truth"], [], "unambiguous_authored_stress_intent")
        directory, duration = work / row["id"], row["duration_seconds"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private synthetic case unavailable or linked")
        with np.load(io.BytesIO(_read(directory / "observations.npz")), allow_pickle=False) as package:
            if len(package.files) != 7 or set(package.files) != {"hz", *path_arms}:
                raise ValueError("exact original seven-array synthetic inventory required")
            arrays = {name: package[name] for name in package.files}
        hz = arrays["hz"]
        exact_equal(checks, array_identity(hz), row["observation"], "private_synthetic_input_array_identity")
        expected_notes, guard_diagnostics, guard_trace = reconstruct_guard(arrays[BASE_ARM], hz, duration)
        split_notes, split_diagnostics, split_trace = prior.reconstruct_split(arrays[BASE_ARM], hz, duration)
        predictions, payloads, manifest[row["id"]] = {}, {}, {}
        for arm in SYNTHETIC_ARMS:
            raw = _read(directory / (arm + ".json"))
            notes, intervals, frequencies = parse_notes(raw, duration)
            item = row["arms"][arm]
            base_fields = {"count", "event_sha256", "events", "metrics"}
            fields = ({"readout", "shared_state_path", "shared_state_path_arm"} if arm in (SPLIT_ARM, ARM)
                      else {"diagnostics", "state_path"} if arm in path_arms else {"diagnostics"})
            if set(item) != base_fields | fields:
                raise ValueError("exact synthetic arm field inventory required")
            checks.equal(sha256(raw), item["event_sha256"], "private_synthetic_prediction_identity")
            exact_equal(checks, notes, item["events"], "public_owned_prediction_payload")
            checks.equal(len(notes), item["count"], "synthetic_prediction_count")
            manifest[row["id"]][arm] = sha256(raw)
            predictions[arm], payloads[arm] = (intervals, frequencies), notes
            if arm == "pitch_runs":
                exact_equal(checks, notes, reconstruct_pitch_runs(hz, duration), "independent_raw_pitch_runs")
                strict_equal(checks, item["diagnostics"], {"predicted_notes": len(notes)}, "raw_runs_diagnostics")
            elif arm in path_arms:
                path = arrays[arm]
                if path.shape != hz.shape or path.dtype.kind not in "iu" or np.any(path < 0) or np.any(path >= 435):
                    raise ValueError("invalid original synthetic path")
                check_path_transitions(path)
                exact_equal(checks, array_identity(path), item["state_path"], "synthetic_saved_state_path_identity")
                expected, counts = reconstruct_readout(path, hz, duration)
                exact_equal(checks, notes, expected, "synthetic_original_path_readout")
                raw_voiced, decoded_voiced = hz > 0, path % 3 != 2
                extra = {"raw_voiced_to_silent_frames": int((raw_voiced & ~decoded_voiced).sum()),
                    "raw_unvoiced_to_voiced_frames": int((~raw_voiced & decoded_voiced).sum()),
                    "voiced_coverage": float((raw_voiced & decoded_voiced).sum() / raw_voiced.sum()) if raw_voiced.any() else None}
                weight = item["diagnostics"].get("viterbi_path_log_weight")
                if type(weight) not in (int, float) or not math.isfinite(weight):
                    raise ValueError("invalid reported path weight")
                strict_equal(checks, item["diagnostics"], {**counts, **extra, "viterbi_path_log_weight": weight},
                             "synthetic_original_readout_diagnostics")
            else:
                expected, diagnostics = ((expected_notes, guard_diagnostics) if arm == ARM else (split_notes, split_diagnostics))
                exact_equal(checks, notes, expected, "independent_saved_readout_events/" + arm)
                strict_equal(checks, item["readout"], diagnostics, "independent_saved_readout_diagnostics/" + arm)
                exact_equal(checks, item["shared_state_path"], array_identity(arrays[BASE_ARM]), "shared_G_path_identity")
                checks.equal(item["shared_state_path_arm"], BASE_ARM, "shared_G_path_arm")
        for filename, key, trace in (("readout-private.json", "readout_private_sha256", split_trace),
                                     ("guard-private.json", "guard_private_sha256", guard_trace)):
            raw = _read(directory / filename)
            checks.equal(sha256(raw), row[key], "private_synthetic_trace_identity/" + filename)
            exact_equal(checks, _json(raw), trace, "independent_synthetic_parent_child_trace/" + filename)
        exact_equal(checks, interval_union(payloads[ARM]), interval_union(payloads[BASE_ARM]), "synthetic_final_interval_union_parity")
        if guard_diagnostics["accepted_cut_count"] == 0:
            checks.equal(row["arms"][ARM]["event_sha256"], row["arms"][BASE_ARM]["event_sha256"], "synthetic_restored_original_bytes")
        if row["accuracy_eligible"]:
            if not isinstance(row["note_evaluation"], dict) or set(row["note_evaluation"]) != set(SYNTHETIC_ARMS):
                raise ValueError("all eligible diagnostic arms required")
            reference = (np.asarray([(note["onset"], note["offset"]) for note in row["truth"]], dtype=float).reshape(-1, 2),
                         np.asarray([440 * 2 ** ((note["pitch"] - 69) / 12) for note in row["truth"]]))
            for arm in SYNTHETIC_ARMS:
                detail = note_evaluation(reference, predictions[arm])
                metrics = {criterion + "_f1": 2 * detail[criterion]["matched_notes"] / (len(reference[1]) + len(predictions[arm][1]))
                           for criterion in CRITERIA}
                strict_equal(checks, row["arms"][arm]["metrics"], metrics, "synthetic_direct_pitch_aware_scores")
                strict_equal(checks, row["note_evaluation"][arm], detail, "synthetic_direct_timing_pair_pitch_diagnostics")
        else:
            checks.equal(row["note_evaluation"], None, "excluded_ambiguous_and_silent_diagnostics")
            for arm in SYNTHETIC_ARMS:
                checks.equal(row["arms"][arm]["metrics"], None, "excluded_ambiguous_and_silent_scores")
        strict_equal(checks, row["comparison"], prior.synthetic_comparison(row), "unchanged_split_comparison")
        strict_equal(checks, row["guard_comparisons"], {base: synthetic_case_comparison(row, base) for base in (BASE_ARM, SPLIT_ARM)},
                     "independent_guard_case_comparisons")
    digest = fingerprint(manifest)
    checks.equal(digest, initial_manifest, "synthetic_all4149_initial_file_binding")
    checks.equal(verify_prediction_files(work, rows, SYNTHETIC_ARMS, checks, "after_synthetic_scoring"), digest,
                 "synthetic_predictions_unchanged_during_audit")
    for key in ("predictions_manifest_sha256", "post_evaluation_predictions_manifest_sha256"):
        checks.equal(report[key], digest, "synthetic_all4149_barrier_manifest/" + key)
    aggregate, comparisons = synthetic_aggregate(rows, previous["cases"]), synthetic_comparisons(rows, previous["cases"])
    strict_equal(checks, report["aggregate"], aggregate, "independent_stratified_synthetic_aggregate")
    strict_equal(checks, report["comparisons"], comparisons, "independent_stratified_synthetic_comparisons")
    expected_legacy = {key: report[key] for key in previous if key in report}
    expected_legacy.update(schema="note-boundary-readout-synthetic-v1", planned_cases=245,
        planned_arms=list(SYNTHETIC_OLD_ARMS), cases=projected,
        source_sha256={name: report["source_sha256"][name] for name in prior.SOURCE_PATHS},
        preflight=report["preflight"]["legacy"], predictions_manifest_sha256=fingerprint(old_manifest),
        post_evaluation_predictions_manifest_sha256=fingerprint(old_manifest), truth_access_started_after_prediction_files=1960,
        aggregate=prior.synthetic_aggregate(projected), comparisons=prior.synthetic_comparisons(projected),
        historical_parity=previous["historical_parity"])
    strict_equal(checks, {key: value for key, value in legacy.items() if key != "elapsed_seconds"},
                 {key: value for key, value in expected_legacy.items() if key != "elapsed_seconds"}, "actual_full_legacy_synthetic_projection")
    if (type(legacy.get("elapsed_seconds")) not in (int, float) or not math.isfinite(legacy["elapsed_seconds"])
            or not 0 <= legacy["elapsed_seconds"] <= report["elapsed_seconds"]):
        raise ValueError("legacy synthetic timing observation inconsistent")
    volatile = {"source_revision", "protocol_head_revision", "elapsed_seconds", "numerical_environment"}
    exact_equal(checks, {key: value for key, value in legacy.items() if key not in volatile},
                {key: value for key, value in previous.items() if key not in volatile}, "full_historical_synthetic_projection")
    parity = {"baseline_zip_sha256": PREVIOUS_SHA256, "compared_prediction_files": 1960,
        "compared_input_arrays": 245, "compared_state_paths": 1470, "all_equal": True, "differences": []}
    strict_equal(checks, report["historical_parity"], parity, "synthetic_full_historical_parity")
    return {"aggregate": aggregate, "comparisons": comparisons, "cohorts": populations,
            "predictions_manifest_sha256": digest, "historical_parity": parity}


def historical_corpus(report, legacy, previous, checks):
    """Every old public event, array, score and diagnostic must match exactly."""
    volatile = {"source_revision", "protocol_head_revision", "python", "platform", "runtime",
                "numerical_environment", "elapsed_seconds", "peak_rss_kib", "legacy_report_sha256"}
    if set(legacy) != set(previous):
        raise ValueError("complete historical corpus report inventory required")
    exact_equal(checks, {key: value for key, value in legacy.items() if key not in volatile | {"cases"}},
                {key: value for key, value in previous.items() if key not in volatile | {"cases"}},
                "complete_historical_corpus_metadata_and_aggregates")
    if ([row.get("id") for row in legacy["cases"]] != list(CASES)
            or [row.get("id") for row in previous["cases"]] != list(CASES)):
        raise ValueError("exact historical ordered forty-case inventory required")
    for actual, old in zip(legacy["cases"], previous["cases"], strict=True):
        ignored = {"observation_sha256", "inference_seconds"}
        exact_equal(checks, {key: value for key, value in actual.items() if key not in ignored},
                    {key: value for key, value in old.items() if key not in ignored}, "complete_historical_corpus_case")
    predictions = sum(len(row["arms"]) for row in legacy["cases"])
    arrays = sum(len(row["observations"]) for row in legacy["cases"])
    checks.equal(predictions, 440, "historical_corpus_event_population")
    checks.equal(arrays, 440, "historical_corpus_array_population")
    source_checks = {name: report["source_sha256"].get(name) == digest
                     and sha256(_read(REPOSITORY / name, 32_000_000)) == digest
                     for name, digest in previous["source_sha256"].items()}
    if set(source_checks) != set(prior.SOURCE_PATHS) or not all(source_checks.values()):
        raise ValueError("all historical fifty-three sources must remain unchanged")
    parity = {"baseline_zip_sha256": PREVIOUS_SHA256, "source_checks": source_checks,
        "compared_prediction_files": 440, "compared_observation_arrays": 440,
        "all_equal": True, "differences": [], "raw_historical_arrays_available": False,
        "array_identity_available": True}
    strict_equal(checks, report.get("historical_parity"), parity, "independent_full_corpus_historical_parity")
    return parity


def audit_private(work, report_path, synthetic_work, synthetic_path,
                  legacy_report_path, legacy_synthetic_path, legacy_audit_path):
    started, checks = time.monotonic(), Checks()
    raw_report, raw_synthetic = _read(report_path, 64_000_000), _read(synthetic_path, 96_000_000)
    raw_legacy, raw_legacy_synthetic = _read(legacy_report_path, 48_000_000), _read(legacy_synthetic_path, 48_000_000)
    raw_legacy_audit = _read(legacy_audit_path, 48_000_000)
    report, synthetic, legacy, legacy_synthetic, legacy_audit = map(
        _json, (raw_report, raw_synthetic, raw_legacy, raw_legacy_synthetic, raw_legacy_audit))
    previous_corpus, previous_synthetic, _ = load_previous(checks)
    expected_keys = set(previous_corpus) | {"guard_settings", "secondary_comparison", "secondary_result", "legacy_factor_report_sha256"}
    if not isinstance(report, dict) or set(report) != expected_keys:
        raise ValueError("exact completed guard corpus report inventory required")
    for key, expected in {"schema": "note-boundary-parent-guard-v1", "status": "complete",
        "planned_case_ids": list(CASES), "planned_arms": list(ARMS), "all_cases_complete": True,
        "primary_comparison": PRIMARY, "secondary_comparison": {**PRIMARY, "baseline": SPLIT_ARM},
        "quality_approved": False, "heldout_generalization": False, "product_changes": False,
        "reference_used_for_edits": False, "device": "cpu", "threads": 2,
        "all_predictions_frozen_before_references": True, "reference_access_started_after_predicted_cases": 40,
        "readout_settings": prior.READOUT_SETTINGS, "guard_settings": GUARD_SETTINGS,
        "legacy_report_sha256": sha256(raw_legacy), "legacy_factor_report_sha256": legacy.get("legacy_report_sha256")}.items():
        strict_equal(checks, report.get(key), expected, "guard_execution_contract/" + key)
    for key in ("elapsed_seconds", "peak_rss_kib"):
        if type(report[key]) not in (int, float) or not math.isfinite(report[key]) or report[key] < 0:
            raise ValueError("invalid corpus resource observation")
        if (type(legacy.get(key)) not in (int, float) or not math.isfinite(legacy[key])
                or not 0 <= legacy[key] <= report[key]):
            raise ValueError("legacy corpus resource observation inconsistent")
    if (type(synthetic.get("elapsed_seconds")) not in (int, float)
            or not math.isfinite(synthetic["elapsed_seconds"]) or synthetic["elapsed_seconds"] < 0):
        raise ValueError("invalid synthetic elapsed time")
    for key in ("source_revision", "protocol_head_revision"):
        revision = report[key]
        if not isinstance(revision, str) or len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise ValueError("complete immutable execution revision required")
        for other in (synthetic, legacy, legacy_synthetic):
            checks.equal(other.get(key), revision, "common_execution_revision/" + key)
    for key in ("f0_settings", "hmm_settings", "factor_settings", "runtime", "archive_sha256", "python", "platform", "numerical_environment"):
        exact_equal(checks, report[key], legacy.get(key), "unchanged_current_legacy_contract/" + key)
    require_legacy_audit(legacy, raw_legacy, raw_legacy_synthetic, legacy_audit, checks)
    checks.equal(report["legacy_factor_report_sha256"], legacy_audit.get("legacy_report_sha256"), "same_factor_report_under_both_audits")
    check_sources(report, previous_corpus, checks)
    exact_equal(checks, synthetic.get("source_sha256"), report["source_sha256"], "common_frozen_source_inventory")
    exact_equal(checks, legacy.get("source_sha256"), {name: report["source_sha256"][name] for name in prior.SOURCE_PATHS},
                "complete_legacy_source_subset")
    numerical_environment = prior.check_numerical_environment(report.get("numerical_environment"), checks)
    exact_equal(checks, synthetic.get("numerical_environment"), numerical_environment, "common_observed_numeric_environment")
    exact_equal(checks, legacy_synthetic.get("numerical_environment"), numerical_environment, "same_legacy_numeric_environment")
    preflight = check_numeric_preflight(synthetic, previous_synthetic, checks)
    corpus_result = corpus_from_private(work, report, legacy, checks)
    synthetic_result = synthetic_from_private(synthetic_work, synthetic, legacy_synthetic, previous_synthetic, checks)
    corpus_parity = historical_corpus(report, legacy, previous_corpus, checks)
    return {"schema": "note-boundary-parent-guard-audit-v1", "status": "pass", "audit_completed": True,
        "report_sha256": sha256(raw_report), "synthetic_report_sha256": sha256(raw_synthetic),
        "legacy_report_sha256": sha256(raw_legacy), "legacy_synthetic_report_sha256": sha256(raw_legacy_synthetic),
        "legacy_audit_sha256": sha256(raw_legacy_audit), "script_sha256": sha256(_read(Path(__file__))),
        "source_sha256": report["source_sha256"], "numerical_environment": numerical_environment, "preflight": preflight,
        "corpus_historical_parity": corpus_parity, "synthetic_historical_parity": synthetic_result["historical_parity"],
        "checks_passed": sum(checks.counts.values()), "checks_by_kind": dict(sorted(checks.counts.items())),
        "maximum_numeric_difference": checks.maximum_numeric_difference,
        "source_files_verified": len(SOURCE_PATHS), "corpus_prediction_files_verified": 480,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 4149, "synthetic_input_arrays_verified": 461,
        "synthetic_old_state_paths_verified": 2766, "stress_input_arrays_independently_regenerated": 216,
        "independent_guard_readouts_verified": 501, "independent_unconditional_readouts_verified": 501,
        "corpus": corpus_result, "synthetic": synthetic_result,
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0,
        "raw_corpus_musical_arrays_published": False, "quality_approved": False, "heldout_generalization": False,
        "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "Guard approvals, complete restoration, original nonemitted parents and exact interval unions are independently reconstructed from saved raw F0 and the original G paths; no new core, runner or decoder is imported.",
            "The fixed independent split auditor supplies raw-run hysteresis, parent segmentation and frozen scalar parsers. Direct mir_eval uses the same documented matcher, not independent human truth.",
            "All 480 corpus and 4149 synthetic event files, private traces, 80 references, path hashes, scores, distributions, both seed298 bootstraps and separate synthetic denominators are checked.",
            "Both input-only preflights are bound to the original immutable manifests and actual prediction inputs. The 216 new inputs and unrounded authored truth are also independently reconstructed.",
            "The fresh prior private audit is bound to both exact legacy report files and its frozen auditor hash. It covers old WAV/F0 checks; model optimality and acoustic observations are not re-inferred here.",
            "Historical corpus observations are available as exact array identities, not as public musical arrays; original source/event/score/diagnostic parity is exact apart from explicitly volatile metadata.",
            "Coverage means equality of exact normalized interval unions. It does not imply identical floating sums, child pitches, match assignments or accuracy.",
            "Proposal passing counts are separate from final emitted counts. Parent harm descriptors overlap and are not exclusive causal attributions.",
            "Timing-only synthetic pitch-error pairs form a separate matching population and cannot establish unique intended note correspondences.",
            "File hashes cannot independently prove past truth/reference-access ordering. Frozen runner code, barrier tests and before/after manifests provide complementary evidence.",
            "The forty recordings are development reuse and the 216 added cases are authored stress; neither is unused real-data generalization or product approval.",
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work", "report", "synthetic-work", "synthetic", "legacy-report", "legacy-synthetic", "legacy-audit", "audit"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    inputs = (args.report, args.synthetic, args.legacy_report, args.legacy_synthetic, args.legacy_audit)
    if (args.audit.exists() or args.audit.is_symlink()
            or args.audit.resolve() in {path.resolve() for path in inputs}
            or any(args.audit.resolve().is_relative_to(path.resolve()) for path in (args.work, args.synthetic_work, REPOSITORY))):
        parser.error("new audit output outside private evidence and checkout required")
    try:
        result = audit_private(args.work, args.report, args.synthetic_work, args.synthetic,
            args.legacy_report, args.legacy_synthetic, args.legacy_audit)
    except Exception as exc:
        result = {"schema": "note-boundary-parent-guard-audit-v1", "status": "failed", "audit_completed": False,
                  "error_type": type(exc).__name__, "error": str(exc), "aggregate": None,
                  "raw_corpus_musical_arrays_published": False}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.audit.with_suffix(args.audit.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.audit)
    print(json.dumps({"status": result["status"], "checks_passed": result.get("checks_passed", 0)}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
