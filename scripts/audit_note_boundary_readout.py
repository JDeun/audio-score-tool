"""Independently verify the fixed raw-pitch split from saved evidence.

This audit imports no readout implementation, runner, acoustic predictor or
decoder. It reconstructs the five-frame rule by walking raw-pitch runs, then
rebuilds every original parent and child, direct matching and paired arithmetic.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

from scripts.audit_note_boundary_diagnostics import (
    SOURCE_PATHS as FROZEN_SOURCE_PATHS,
)
from scripts.audit_note_boundary_diagnostics import (
    arm_details,
    exact_equal,
    fixed_pair_summary,
    strict_equal,
    summary,
    verify_replay,
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
    ARMS as OLD_ARMS,
)
from scripts.audit_note_state_factors import (
    check_observations,
    reconstruct_readout,
)

REPOSITORY = Path(__file__).resolve().parents[1]
CASES = tuple(f"vocadito_{index}" for index in range(1, 41))
ANNOTATORS = ("A1", "A2")
ARM = "gaussian_raw_hysteresis_split"
BASE_ARM = "gaussian_exponent_1"
ARMS = (*OLD_ARMS, ARM)
DIAGNOSTIC_ARMS = ("pitch_runs", BASE_ARM, ARM, "note_state_hmm")
SYNTHETIC_OLD_ARMS = ("pitch_runs", "note_state_hmm", BASE_ARM, "phase_balanced",
                      "positive_voicing_08", "silent_self_099", "hop_unscaled")
SYNTHETIC_ARMS = (*SYNTHETIC_OLD_ARMS, ARM)
CRITERIA = ("onset", "onset_offset")
PARTITIONS = ("retained", "gained", "lost", "neither")
HARM_KEYS = ("lost_references", "lost_matched_parent_cut",
             "lost_matched_parent_with_short_children", "lost_matched_parent_all_children_pruned")
PREVIOUS_RECEIPT = "docs/research/receipts/note-boundary-diagnostics-43370790419.zip"
PREVIOUS_SHA256 = "43b439e665eb470ec1b24179697cc99d2733fecb6122d1da6a77125d8e3ccf31"
NEW_SOURCE_PATHS = (
    "scripts/note_boundary_readout.py", "scripts/run_note_boundary_readout.py",
    "scripts/note_boundary_readout_synthetic.py", "scripts/audit_note_boundary_readout.py",
    "tests/test_note_boundary_readout.py", "tests/test_run_note_boundary_readout.py",
    "tests/test_note_boundary_readout_synthetic.py", "tests/test_audit_note_boundary_readout.py",
    ".github/workflows/cpu-note-boundary-readout.yml",
    "docs/research/NOTE_BOUNDARY_READOUT_PROTOCOL_2026-11-13.md",
    "docs/research/NOTE_BOUNDARY_READOUT_EXECUTION_2026-11-13.md", PREVIOUS_RECEIPT,
)
SOURCE_PATHS = (*FROZEN_SOURCE_PATHS, *NEW_SOURCE_PATHS)
PRIMARY = {"candidate": ARM, "baseline": BASE_ARM, "metric": "onset_offset_f1"}
READOUT_SETTINGS = {
    "candidate": ARM, "baseline": BASE_ARM, "raw_hysteresis_support_frames": 5,
    "candidate_cut": "adjacent_nonnegative_different_global_raw_hysteresis_labels",
    "applied_cut": "strictly_inside_original_G_pitch_segment_and_before_clipped_audio_end",
    "pitch": "original_positive_raw_MIDI_median_then_numpy_rint_per_child",
    "minimum_seconds": .08, "shared_G_path": True, "raw_zero_gate_added": False,
    "existing_boundaries_removed": False, "timestamp_shift_seconds": 0.,
    "bootstrap_seed": 296, "bootstrap_resamples": 10000,
    "private_details": "parent_child_times_pitches_and_annotation_pair_rows",
}


def independent_labels(hz):
    """Process maximal raw-pitch runs, accepting a different run only at five frames."""
    values = np.asarray(hz, dtype=float)
    if values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("invalid raw observations")
    raw = np.full(len(values), -1, dtype=int)
    positive = values > 0
    raw[positive] = np.rint(69 + 12 * np.log2(values[positive] / 440.)).astype(int)
    if np.any(raw[positive] < 0) or np.any(raw[positive] > 127):
        raise ValueError("raw pitch outside MIDI domain")
    result = np.full(len(raw), -1, dtype=int)
    cursor, current = 0, -1
    while cursor < len(raw):
        stop = cursor + 1
        while stop < len(raw) and raw[stop] == raw[cursor]:
            stop += 1
        value = int(raw[cursor])
        if value < 0:
            current = -1
        else:
            if current < 0 or value == current or stop - cursor >= 5:
                current = value
            result[cursor:stop] = current
        cursor = stop
    return result


def _segment(begin, stop, hz, duration, prediction_index):
    values = hz[begin:stop]
    positive = values[values > 0]
    median = float(np.median(69 + 12 * np.log2(positive / 440.))) if len(positive) else None
    pitch = int(np.rint(median)) if median is not None else None
    onset, offset = begin * .01, min(stop * .01, duration)
    reason = ("zero_duration" if offset <= onset else "no_raw_support" if not len(positive)
              else "short" if offset - onset < .08 - 1e-10 else None)
    return {"begin_frame": begin, "stop_frame": stop, "onset_seconds": onset,
            "offset_seconds": offset, "frame_count": stop - begin,
            "raw_voiced_frames": len(positive), "raw_unvoiced_frames": stop - begin - len(positive),
            "raw_positive_midi_median": median, "pitch": pitch,
            "clipped": stop * .01 > duration, "emitted": reason is None,
            "prediction_index": prediction_index if reason is None else None,
            "discard_reason": reason}


def _event(segment):
    return {"pitch": segment["pitch"], "onset": segment["onset_seconds"],
            "offset": segment["offset_seconds"], "is_drum": False}


def _child_diagnostics(children, states, hz, duration):
    phases, raw = states % 3, hz > 0
    voiced = phases != 2
    result = {"frames": len(states), "raw_voiced_frames": int(raw.sum()),
        "decoded_voiced_frames": int(voiced.sum()), "attack_frames": int((phases == 0).sum()),
        "stable_frames": int((phases == 1).sum()), "silent_frames": int((phases == 2).sum()),
        "decoded_voiced_over_raw_unvoiced_frames": int((voiced & ~raw).sum()),
        "raw_voiced_decoded_silent_frames": int((raw & ~voiced).sum()),
        "segments_before_filter": 0, "emitted_notes": 0, "segments_without_raw_voiced_support": 0,
        "zero_duration_segments": 0, "short_segments_discarded": 0,
        "short_segments_discarded_seconds": 0., "attack_only_segments": 0,
        "segments_touching_audio_start": 0, "segments_touching_audio_end": 0,
        "emitted_notes_with_raw_unvoiced_frames": 0, "emitted_raw_unvoiced_frames": 0,
        "emitted_note_seconds": 0.}
    result["segments_before_filter"] = len(children)
    for child in children:
        start, stop = child["begin_frame"], child["stop_frame"]
        result["attack_only_segments"] += int(np.all(states[start:stop] % 3 == 0))
        result["segments_touching_audio_start"] += int(start == 0)
        result["segments_touching_audio_end"] += int(stop * .01 >= duration - 1e-10)
        reason = child["discard_reason"]
        if reason is not None:
            key = {"zero_duration": "zero_duration_segments", "no_raw_support": "segments_without_raw_voiced_support",
                   "short": "short_segments_discarded"}[reason]
            result[key] += 1
        else:
            result["emitted_notes"] += 1
            unvoiced = child["raw_unvoiced_frames"]
            result["emitted_notes_with_raw_unvoiced_frames"] += int(unvoiced > 0)
            result["emitted_raw_unvoiced_frames"] += unvoiced
    result["short_segments_discarded_seconds"] = math.fsum(
        child["offset_seconds"] - child["onset_seconds"] for child in children if child["discard_reason"] == "short")
    result["emitted_note_seconds"] = math.fsum(
        child["offset_seconds"] - child["onset_seconds"] for child in children if child["emitted"])
    return result


def reconstruct_split(path, hz, duration):
    """Build parents and children independently; never run a note decoder."""
    values, states = np.asarray(hz, dtype=float), np.asarray(path)
    if (values.ndim != 1 or not np.isfinite(values).all() or np.any(values < 0)
            or states.shape != values.shape or states.dtype.kind not in "iu"
            or np.any(states < 0) or np.any(states >= 435)
            or not isinstance(duration, (int, float)) or isinstance(duration, bool)
            or not math.isfinite(duration) or duration < 0):
        raise ValueError("invalid saved readout input")
    if ((not len(values) and duration != 0) or (len(values)
            and not max(0., (len(values) - 1) * .01) - 1e-10 <= duration <= len(values) * .01 + 1e-10)):
        raise ValueError("saved readout clock differs")
    positive = values[values > 0]
    midi = 69 + 12 * np.log2(positive / 440.)
    if np.any(midi < 33 - 1e-10) or np.any(midi > 81 + 1e-10):
        raise ValueError("saved raw F0 outside frozen grid")
    labels = independent_labels(values)
    candidates = [index for index in range(1, len(labels))
                  if labels[index - 1] >= 0 and labels[index] >= 0 and labels[index - 1] != labels[index]]
    tokens = [int(state // 3) if int(state) % 3 != 2 else -1 for state in states]
    notes, parents, children, applied = [], [], [], []
    begin, old_index = 0, 0
    while begin < len(tokens):
        stop = begin + 1
        while stop < len(tokens) and tokens[stop] == tokens[begin]:
            stop += 1
        if tokens[begin] >= 0:
            original = _segment(begin, stop, values, duration, old_index)
            old_index += int(original["emitted"])
            cuts = [cut for cut in candidates if begin < cut < stop and cut * .01 < min(stop * .01, duration)]
            edges = [begin, *cuts, stop]
            pieces = []
            for first, end in zip(edges[:-1], edges[1:], strict=True):
                child = _segment(first, end, values, duration, len(notes))
                child["child_id"] = len(children)
                if child["emitted"]:
                    notes.append(_event(child))
                pieces.append(child)
                children.append(child)
            parents.append({"parent_id": len(parents), "begin_frame": begin, "stop_frame": stop,
                            "state_pitch_index": tokens[begin], "applied_cut_frames": cuts,
                            "original": original, "children": pieces})
            applied.extend(cuts)
        begin = stop
    trace = {"schema_version": 1, "candidate_cut_frames": candidates, "parents": parents}
    if len(values):
        baseline_notes, baseline = reconstruct_readout(states, values, duration)
    else:
        baseline_notes, baseline = [], _child_diagnostics([], states, values, duration)
    readout = _child_diagnostics(children, states, values, duration)
    original_emitted = [parent for parent in parents if parent["original"]["emitted"]]
    baseline_seconds, emitted_seconds = baseline["emitted_note_seconds"], readout["emitted_note_seconds"]
    diagnostics = {"schema_version": 1, "candidate_cut_count": len(candidates),
        "applied_cut_count": len(applied), "affected_parent_count": sum(bool(p["applied_cut_frames"]) for p in parents),
        "parent_segment_count": len(parents), "child_segment_count": len(children),
        "originally_emitted_parents_all_children_pruned": sum(not any(c["emitted"] for c in p["children"]) for p in original_emitted),
        "originally_emitted_parents_with_short_children": sum(any(c["discard_reason"] == "short" for c in p["children"]) for p in original_emitted),
        "originally_emitted_parents_with_any_pruned_children": sum(any(not c["emitted"] for c in p["children"]) for p in original_emitted),
        "baseline_emitted_seconds": baseline_seconds, "emitted_seconds": emitted_seconds,
        "emitted_seconds_change": emitted_seconds - baseline_seconds,
        "baseline_emitted_coverage_fraction": baseline_seconds / duration if duration else 0.,
        "emitted_coverage_fraction": emitted_seconds / duration if duration else 0.,
        "clipped_child_count": sum(child["clipped"] for child in children),
        "baseline": baseline, "readout": readout,
        "child_midi_median_summary": summary(child["raw_positive_midi_median"] for child in children if child["raw_positive_midi_median"] is not None),
        "child_raw_voiced_frames_summary": summary(child["raw_voiced_frames"] for child in children),
        "child_seconds_summary": summary(max(0., child["offset_seconds"] - child["onset_seconds"]) for child in children),
        "candidate_cut_frames_sha256": fingerprint(candidates), "applied_cut_frames_sha256": fingerprint(applied),
        "raw_hysteresis_label_identity": {"dtype": str(labels.dtype), "shape": list(labels.shape), "sha256": sha256(labels.tobytes())},
        "trace_sha256": fingerprint(trace)}
    if not applied and notes != baseline_notes:
        raise ValueError("no-cut original event parity failed")
    return notes, diagnostics, trace


def annotation_details(reference, predictions, trace):
    arms = {arm: arm_details(reference, predictions[arm]) for arm in DIAGNOSTIC_ARMS}
    comparisons, pruning = {}, {}
    universe = set(range(len(reference[0])))
    old_parents = {parent["original"]["prediction_index"]: parent for parent in trace["parents"]
                   if parent["original"]["emitted"]}
    for baseline in (BASE_ARM, "pitch_runs"):
        comparisons[baseline] = {}
        for criterion in CRITERIA:
            def ids(arm):
                return ({pair["reference_id"] for pair in arms[arm]["onset_pairs"]} if criterion == "onset"
                        else {pair[0] for pair in arms[arm]["offset_pairs"]})
            old, new = ids(baseline), ids(ARM)
            comparisons[baseline][criterion] = {"retained": sorted(old & new), "gained": sorted(new - old),
                "lost": sorted(old - new), "neither": sorted(universe - old - new)}
            if baseline != BASE_ARM:
                continue
            matched = ({pair["reference_id"]: pair["prediction_id"] for pair in arms[BASE_ARM]["onset_pairs"]}
                       if criterion == "onset" else dict(arms[BASE_ARM]["offset_pairs"]))
            harmed = [old_parents[matched[index]] for index in sorted(old - new)]
            pruning[criterion] = {"lost_references": len(harmed),
                "lost_matched_parent_cut": sum(bool(parent["applied_cut_frames"]) for parent in harmed),
                "lost_matched_parent_with_short_children": sum(any(child["discard_reason"] == "short" for child in parent["children"]) for parent in harmed),
                "lost_matched_parent_all_children_pruned": sum(not any(child["emitted"] for child in parent["children"]) for parent in harmed)}
    return {"reference_notes": len(reference[0]), "arms": arms, "comparisons": comparisons, "pruning_harm": pruning}


def summarize_annotations(details):
    return {"recording_annotations": len(details), "reference_notes": sum(d["reference_notes"] for d in details),
        "arms": {arm: {"predicted_notes": sum(d["arms"][arm]["predicted_notes"] for d in details),
            "onset_matched": sum(len(d["arms"][arm]["onset_pairs"]) for d in details),
            "offset_matched": sum(len(d["arms"][arm]["offset_pairs"]) for d in details),
            "fixed_onset_pairs": fixed_pair_summary([p for d in details for p in d["arms"][arm]["onset_pairs"]])}
            for arm in DIAGNOSTIC_ARMS},
        "comparisons": {base: {criterion: {part: sum(len(d["comparisons"][base][criterion][part]) for d in details)
            for part in PARTITIONS} for criterion in CRITERIA} for base in (BASE_ARM, "pitch_runs")},
        "pruning_harm": {criterion: {key: sum(d["pruning_harm"][criterion][key] for d in details)
            for key in HARM_KEYS} for criterion in CRITERIA}}


def primary_summary(rows):
    if [row.get("id") for row in rows] != list(CASES):
        raise ValueError("paired bootstrap requires all forty recordings")
    deltas = [math.fsum(row["arms"][ARM]["annotators"][ann]["onset_offset_f1"]
              - row["arms"][BASE_ARM]["annotators"][ann]["onset_offset_f1"] for ann in ANNOTATORS) / 2 for row in rows]
    if not all(math.isfinite(delta) and -1 <= delta <= 1 for delta in deltas):
        raise ValueError("invalid recording delta")
    draws = np.random.default_rng(296).integers(0, 40, size=(10000, 40))
    means = sorted(math.fsum(deltas[int(index)] for index in sample) / 40 for sample in draws)
    def quantile(probability):
        location = probability * (len(means) - 1)
        left = math.floor(location)
        return means[left] + (means[math.ceil(location)] - means[left]) * (location - left)
    improved, worse = sum(delta > 1e-8 for delta in deltas), sum(delta < -1e-8 for delta in deltas)
    return {**PRIMARY, "paired_recording_deltas": [{"id": case, "delta": delta} for case, delta in zip(CASES, deltas, strict=True)],
        "mean_delta": math.fsum(deltas) / 40, "recordings_improved": improved, "recordings_worse": worse,
        "recordings_tied": 40 - improved - worse,
        "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2", "seed": 296, "resamples": 10000,
            "confidence_level": .95, "method": "paired_percentile_linear", "low": quantile(.025), "high": quantile(.975)},
        "heldout_generalization": False}


def aggregate_rows(rows):
    if [row.get("id") for row in rows] != list(CASES):
        raise ValueError("complete ordered corpus population required")
    for row in rows:
        if row.get("status") != "scored" or set(row.get("arms", {})) != set(ARMS):
            raise ValueError("complete scored eleven-arm case required")
        if any(set(row["arms"][arm].get("annotators", {})) != set(ANNOTATORS) for arm in ARMS):
            raise ValueError("both annotators required")
    result = {}
    for arm in ARMS:
        value = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in ("onset_f1", "onset_offset_f1"):
            by_annotator = {ann: [row["arms"][arm]["annotators"][ann][metric] for row in rows]
                            for ann in ANNOTATORS}
            if not all(math.isfinite(score) and 0 <= score <= 1 for values in by_annotator.values() for score in values):
                raise ValueError("invalid corpus metric")
            means = [math.fsum(pair) / 2 for pair in zip(by_annotator["A1"], by_annotator["A2"], strict=True)]
            deltas = [mean - math.fsum(row["arms"]["pitch_runs"]["annotators"][ann][metric]
                      for ann in ANNOTATORS) / 2 for mean, row in zip(means, rows, strict=True)]
            improved, worse = sum(delta > 1e-8 for delta in deltas), sum(delta < -1e-8 for delta in deltas)
            value[metric] = {"macro": math.fsum(means) / 40,
                "A1_macro": math.fsum(by_annotator["A1"]) / 40, "A2_macro": math.fsum(by_annotator["A2"]) / 40,
                "delta_vs_runs": math.fsum(deltas) / 40, "recordings_improved": improved,
                "recordings_worse": worse, "recordings_tied": 40 - improved - worse}
        for rate in ("onset_precision", "onset_recall", "offset_precision", "offset_recall"):
            value[rate] = math.fsum(row["arms"][arm]["annotators"][ann][rate]
                                   for row in rows for ann in ANNOTATORS) / 80
        for criterion in CRITERIA:
            for kind in ("gained", "lost"):
                key = criterion + "_" + kind + "_reference_ids"
                value[criterion + "_" + kind + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][key]) for row in rows for ann in ANNOTATORS)
        result[arm] = value
    return result


def load_previous(checks, path=None):
    raw = _read(REPOSITORY / PREVIOUS_RECEIPT if path is None else path, 32_000_000)
    checks.equal(sha256(raw), PREVIOUS_SHA256, "original_boundary_receipt_identity")
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        required = {"vocadito.json", "synthetic.json", "replay-audit.json", "diagnostics.json", "audit.json"}
        if len(package.namelist()) != len(required) or set(package.namelist()) != required:
            raise ValueError("original boundary receipt inventory differs")
        if any(item.file_size > 16_000_000 for item in package.infolist()):
            raise ValueError("oversized boundary receipt member")
        corpus, synthetic, diagnostics = (_json(package.read(name)) for name in
                                         ("vocadito.json", "synthetic.json", "diagnostics.json"))
    checks.equal(corpus.get("status"), "complete", "historical_corpus_complete")
    checks.equal(synthetic.get("status"), "complete", "historical_synthetic_complete")
    checks.equal(diagnostics.get("status"), "complete", "historical_diagnostics_complete")
    return corpus, synthetic, diagnostics


def check_sources(report, previous, checks):
    hashes = report.get("source_sha256")
    if not isinstance(hashes, dict) or set(hashes) != set(SOURCE_PATHS):
        raise ValueError("exact forty-seven-source inventory required")
    if set(previous.get("source_sha256", {})) != set(FROZEN_SOURCE_PATHS):
        raise ValueError("previous thirty-five-source inventory differs")
    for name in SOURCE_PATHS:
        checks.equal(hashes[name], sha256(_read(REPOSITORY / name, 32_000_000)), "frozen_source_identity/" + name)
        if name in FROZEN_SOURCE_PATHS:
            checks.equal(hashes[name], previous["source_sha256"][name], "historical_source_preserved/" + name)


def require_legacy_audit(legacy, legacy_bytes, audit, checks):
    for name, expected in {
        "schema": "note-state-factors-audit-v1", "status": "pass", "audit_completed": True,
        "complete_prediction_files_verified": 400, "observation_arrays_verified": 440,
        "source_files_verified": 24, "report_sha256": sha256(legacy_bytes),
        "script_sha256": sha256(_read(REPOSITORY / "scripts/audit_note_state_factors.py")),
    }.items():
        checks.equal(audit.get(name), expected, "legacy_private_audit_binding/" + name)
    checks.equal(legacy.get("status"), "complete", "legacy_projection_complete")


def corpus_from_private(work, report, legacy, checks):
    if work.is_symlink() or not work.is_dir():
        raise ValueError("private corpus directory unavailable or linked")
    if [row.get("id") for row in report.get("cases", [])] != list(CASES):
        raise ValueError("exact ordered forty-case inventory required")
    if [row.get("id") for row in legacy.get("cases", [])] != list(CASES):
        raise ValueError("exact ordered legacy forty-case inventory required")
    manifest, rescored, annotations, summaries = {}, [], [], []
    new_fields = {"readout", "readout_private_sha256", "annotation_diagnostics", "annotation_private_sha256"}
    for row, old in zip(report["cases"], legacy["cases"], strict=True):
        if row.get("status") != "scored" or set(row.get("arms", {})) != set(ARMS):
            raise ValueError("every case must contain all eleven scored arms")
        if set(row) != set(old) | new_fields:
            raise ValueError("exact public corpus case field inventory required")
        if set(row.get("annotation_diagnostics", {})) != set(ANNOTATORS):
            raise ValueError("exact public annotation inventory required")
        if any(set(item) != {"count", "event_sha256", "annotators"}
               or set(item.get("annotators", {})) != set(ANNOTATORS) for item in row["arms"].values()):
            raise ValueError("exact corpus arm field and annotator inventory required")
        projected = {key: value for key, value in row.items() if key not in new_fields}
        projected["arms"] = {arm: row["arms"][arm] for arm in OLD_ARMS}
        exact_equal(checks, projected, old, "legacy_case_projection_identity")
        directory, duration = work / row["id"], row["duration_seconds"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private case directory unavailable or linked")
        raw_npz = _read(directory / "observations.npz")
        checks.equal(sha256(raw_npz), row["observation_sha256"], "private_corpus_npz_identity")
        arrays = check_observations(raw_npz, row["observations"], duration, checks)
        predictions, payloads, manifest[row["id"]] = {}, {}, {}
        for arm in ARMS:
            raw = _read(directory / (arm + ".json"))
            payload, intervals, hz = parse_notes(raw, duration)
            checks.equal(sha256(raw), row["arms"][arm]["event_sha256"], "private_corpus_prediction_identity")
            checks.equal(len(payload), row["arms"][arm]["count"], "private_corpus_prediction_count")
            predictions[arm], payloads[arm] = (intervals, hz), payload
            manifest[row["id"]][arm] = sha256(raw)
        events, diagnostics, trace = reconstruct_split(arrays[BASE_ARM + "_path"], arrays["hz"], duration)
        exact_equal(checks, payloads[ARM], events, "independent_corpus_split_events")
        strict_equal(checks, row["readout"], diagnostics, "independent_corpus_readout_diagnostics")
        raw_trace = _read(directory / "readout-private.json")
        checks.equal(sha256(raw_trace), row["readout_private_sha256"], "private_corpus_trace_identity")
        exact_equal(checks, _json(raw_trace), trace, "independent_corpus_parent_child_trace")
        if diagnostics["applied_cut_count"] == 0:
            checks.equal(row["arms"][ARM]["event_sha256"], row["arms"][BASE_ARM]["event_sha256"], "no_cut_byte_parity")
        computed = {"id": row["id"], "status": "scored", "arms": {
            arm: {"count": len(payloads[arm]), "annotators": {}} for arm in ARMS}}
        details = {}
        for annotator in ANNOTATORS:
            raw_reference = _read(directory / (annotator + ".csv"))
            checks.equal(sha256(raw_reference), row["reference_sha256"][annotator], "private_reference_identity")
            reference = parse_reference(raw_reference)
            base_ids = None
            for arm in ARMS:
                values, ids = direct_score(reference, predictions[arm])
                if arm == "pitch_runs":
                    base_ids = ids
                for criterion in CRITERIA:
                    values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[criterion])
                    values[criterion + "_lost_reference_ids"] = sorted(base_ids[criterion] - ids[criterion])
                strict_equal(checks, row["arms"][arm]["annotators"][annotator], values, "independent_corpus_note_matching")
                computed["arms"][arm]["annotators"][annotator] = values
            detail = annotation_details(reference, predictions, trace)
            strict_equal(checks, row["annotation_diagnostics"][annotator], summarize_annotations([detail]),
                         "independent_corpus_annotation_diagnostics")
            details[annotator] = detail
        raw_details = _read(directory / "annotation-private.json")
        checks.equal(sha256(raw_details), row["annotation_private_sha256"], "private_annotation_trace_identity")
        strict_equal(checks, _json(raw_details), details, "independent_annotation_pair_and_parent_details")
        rescored.append(computed)
        annotations.append(details)
        summaries.append({"id": row["id"], "status": "pass", "prediction_files": len(ARMS),
                          "observation_arrays": len(arrays), "parents": len(trace["parents"]),
                          "applied_cuts": diagnostics["applied_cut_count"]})
    digest = fingerprint(manifest)
    for key in ("predictions_manifest_sha256", "post_evaluation_predictions_manifest_sha256"):
        checks.equal(report.get(key), digest, "corpus_prediction_barrier_manifest/" + key)
    aggregate, primary = aggregate_rows(rescored), primary_summary(rescored)
    strict_equal(checks, report.get("aggregate"), aggregate, "independent_corpus_aggregate")
    strict_equal(checks, report.get("primary_result"), primary, "independent_recording_bootstrap")
    boundary = {"by_annotator": {ann: summarize_annotations([detail[ann] for detail in annotations]) for ann in ANNOTATORS},
                "pooled_annotation_judgments": summarize_annotations([detail[ann] for detail in annotations for ann in ANNOTATORS])}
    strict_equal(checks, report.get("boundary_summary"), boundary, "independent_pooled_boundary_summary")
    return {"cases": summaries, "aggregate": aggregate, "primary_result": primary,
            "boundary_summary": boundary, "predictions_manifest_sha256": digest}


def synthetic_comparison(row):
    old, new = row["arms"][BASE_ARM], row["arms"][ARM]
    result = {"baseline_arm": BASE_ARM, "candidate_arm": ARM,
        "predicted_notes_change": new["count"] - old["count"],
        "event_identity_unchanged": new["event_sha256"] == old["event_sha256"],
        "no_added_cuts": new["readout"]["applied_cut_count"] == 0,
        "onset_f1_change": None, "onset_offset_f1_change": None,
        "baseline_perfect": None, "candidate_perfect": None}
    if row["accuracy_eligible"]:
        for metric in ("onset_f1", "onset_offset_f1"):
            result[metric + "_change"] = new["metrics"][metric] - old["metrics"][metric]
        result["baseline_perfect"] = old["metrics"]["onset_f1"] == old["metrics"]["onset_offset_f1"] == 1.
        result["candidate_perfect"] = new["metrics"]["onset_f1"] == new["metrics"]["onset_offset_f1"] == 1.
    if result["no_added_cuts"] and not result["event_identity_unchanged"]:
        raise ValueError("no-cut synthetic event identity changed")
    return result


def synthetic_aggregate(rows, arms=SYNTHETIC_ARMS):
    if len(rows) != 245 or any(set(row["arms"]) != set(arms) for row in rows):
        raise ValueError("complete synthetic population required")
    eligible = [row for row in rows if row["accuracy_eligible"]]
    if len(eligible) != 227:
        raise ValueError("fixed synthetic eligible denominator required")
    result = {}
    for arm in arms:
        value = {"all_cases_predicted_notes": sum(row["arms"][arm]["count"] for row in rows),
            "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in rows),
            "silence_false_positive_notes": sum(row["arms"][arm]["count"] for row in rows if row["spec"]["kind"] == "silence"),
            "eligible_cases": len(eligible)}
        for metric in ("onset_f1", "onset_offset_f1"):
            value[metric] = math.fsum(row["arms"][arm]["metrics"][metric] for row in eligible) / len(eligible)
        if arm != "pitch_runs":
            if arm == ARM:
                diagnostics = [row["arms"][arm]["readout"]["readout"] for row in rows]
                dropped_key = "raw_voiced_decoded_silent_frames"
            else:
                diagnostics = [row["arms"][arm]["diagnostics"] for row in rows]
                dropped_key = "raw_voiced_to_silent_frames"
            raw = sum(value["raw_voiced_frames"] for value in diagnostics)
            dropped = sum(value[dropped_key] for value in diagnostics)
            value.update(raw_voiced_frames=raw, raw_voiced_to_silent_frames=dropped, voiced_coverage=1 - dropped / raw)
        result[arm] = value
    return result


def synthetic_comparisons(rows):
    eligible = [row for row in rows if row["accuracy_eligible"]]
    controls = [row for row in rows if row["spec"]["kind"] == "change"
                and row["spec"]["interval"] == 1 and row["spec"]["gap"] == 0]
    expected_ids = ["change_195", "change_197", "change_207", "change_209", "change_219", "change_221"]
    if [row["id"] for row in controls] != expected_ids:
        raise ValueError("fixed joined-semitone control inventory required")
    successes = [row for row in eligible if row["comparison"]["baseline_perfect"]]
    result = {"all_cases": len(rows), "accuracy_eligible_cases": len(eligible),
        "ambiguous_cases": sum(row["spec"]["kind"] == "dropout" or (row["spec"]["kind"] == "repeat" and row["spec"]["gap"] == 0) for row in rows),
        "silence_cases": sum(row["spec"]["kind"] == "silence" for row in rows),
        "baseline_arm": BASE_ARM, "candidate_arm": ARM,
        "previous_gaussian_perfect_cases": len(successes), "previous_gaussian_perfect_case_ids": [row["id"] for row in successes],
        "damaged_previous_success_case_ids": [row["id"] for row in successes if not row["comparison"]["candidate_perfect"]],
        "no_added_cut_cases": sum(row["comparison"]["no_added_cuts"] for row in rows),
        "identical_event_cases": sum(row["comparison"]["event_identity_unchanged"] for row in rows),
        "joined_semitone_controls": [], "eligible_metric_changes": {}}
    if tuple(result[key] for key in ("all_cases", "accuracy_eligible_cases", "ambiguous_cases", "silence_cases", "previous_gaussian_perfect_cases")) != (245, 227, 15, 3, 221):
        raise ValueError("fixed synthetic denominator or baseline success count differs")
    for row in controls:
        old, new = row["arms"][BASE_ARM], row["arms"][ARM]
        result["joined_semitone_controls"].append({"id": row["id"], "reference_notes": len(row["truth"]),
            "baseline_predicted_notes": old["count"], "candidate_predicted_notes": new["count"],
            "baseline_metrics": old["metrics"], "candidate_metrics": new["metrics"],
            "candidate_two_notes_pitch_onset_offset_correct": len(row["truth"]) == new["count"] == 2 and row["comparison"]["candidate_perfect"]})
    for metric in ("onset_f1", "onset_offset_f1"):
        deltas = [row["comparison"][metric + "_change"] for row in eligible]
        result["eligible_metric_changes"][metric] = {"macro_change": math.fsum(deltas) / len(deltas),
            "improved_cases": sum(value > 0 for value in deltas), "worse_cases": sum(value < 0 for value in deltas),
            "tied_cases": sum(value == 0 for value in deltas)}
    return result


def synthetic_from_private(work, report, previous, checks):
    import mir_eval.transcription as transcription

    if work.is_symlink() or not work.is_dir():
        raise ValueError("private synthetic workspace unavailable or linked")
    required = {"schema", "status", "cases", "source_revision", "protocol_head_revision", "source_sha256",
        "planned_cases", "planned_arms", "acoustic_extraction", "quality_approved", "heldout_generalization",
        "product_changes", "emission_analysis", "aggregate", "comparisons", "all_predictions_saved_before_scoring",
        "historical_parity", "predictions_manifest_sha256", "truth_access_started_after_prediction_files",
        "post_evaluation_predictions_manifest_sha256", "elapsed_seconds"}
    if not isinstance(report, dict) or set(report) != required:
        raise ValueError("exact completed synthetic report inventory required")
    for key, expected in {"schema": "note-boundary-readout-synthetic-v1", "status": "complete",
        "planned_cases": 245, "planned_arms": list(SYNTHETIC_ARMS), "acoustic_extraction": False,
        "quality_approved": False, "heldout_generalization": False, "product_changes": False,
        "all_predictions_saved_before_scoring": True, "truth_access_started_after_prediction_files": 1960}.items():
        strict_equal(checks, report.get(key), expected, "synthetic_execution_contract/" + key)
    rows = report.get("cases", [])
    if len(rows) != 245 or [row.get("id") for row in rows] != [row["id"] for row in previous["cases"]]:
        raise ValueError("exact original synthetic case inventory required")
    manifest, old_manifest, projected_rows = {}, {}, []
    for row, old in zip(rows, previous["cases"], strict=True):
        if set(row) != set(old) | {"readout_private_sha256", "comparison"}:
            raise ValueError("exact synthetic case field inventory required")
        if set(row.get("arms", {})) != set(SYNTHETIC_ARMS):
            raise ValueError("exact eight-arm synthetic inventory required")
        projected = {key: value for key, value in row.items() if key in old}
        projected["arms"] = {arm: row["arms"][arm] for arm in SYNTHETIC_OLD_ARMS}
        exact_equal(checks, projected, old, "historical_full_synthetic_case")
        projected_rows.append(projected)
        directory, duration = work / row["id"], row["duration_seconds"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private synthetic case unavailable or linked")
        with np.load(io.BytesIO(_read(directory / "observations.npz")), allow_pickle=False) as package:
            if len(package.files) != 7 or set(package.files) != {"hz", *SYNTHETIC_OLD_ARMS[1:]}:
                raise ValueError("original seven-array synthetic inventory required")
            arrays = {name: package[name] for name in package.files}
        hz = arrays["hz"]
        exact_equal(checks, array_identity(hz), row["observation"], "synthetic_input_array_identity")
        new_notes, diagnostics, trace = reconstruct_split(arrays[BASE_ARM], hz, duration)
        predictions, manifest[row["id"]], old_manifest[row["id"]] = {}, {}, {}
        for arm in SYNTHETIC_ARMS:
            raw = _read(directory / (arm + ".json"))
            notes, intervals, frequencies = parse_notes(raw, duration)
            item = row["arms"][arm]
            checks.equal(sha256(raw), item["event_sha256"], "synthetic_event_file_identity")
            exact_equal(checks, notes, item["events"], "synthetic_public_event_payload")
            checks.equal(len(notes), item["count"], "synthetic_event_count")
            predictions[arm] = intervals, frequencies
            manifest[row["id"]][arm] = sha256(raw)
            if arm in SYNTHETIC_OLD_ARMS:
                old_manifest[row["id"]][arm] = sha256(raw)
            if arm in SYNTHETIC_OLD_ARMS[1:]:
                path = arrays[arm]
                if path.shape != hz.shape or path.dtype.kind not in "iu" or np.any(path < 0) or np.any(path >= 435):
                    raise ValueError("invalid original synthetic path")
                exact_equal(checks, array_identity(path), item["state_path"], "synthetic_state_path_identity")
                expected, counts = reconstruct_readout(path, hz, duration)
                exact_equal(checks, notes, expected, "synthetic_old_path_readout")
                checks.equal(item["diagnostics"], counts, "synthetic_old_readout_diagnostics")
            if arm == ARM:
                if set(item) != {"count", "event_sha256", "readout", "shared_state_path", "shared_state_path_arm", "events", "metrics"}:
                    raise ValueError("exact new synthetic arm field inventory required")
                exact_equal(checks, notes, new_notes, "synthetic_independent_split_events")
                strict_equal(checks, item["readout"], diagnostics, "synthetic_independent_split_diagnostics")
                exact_equal(checks, item["shared_state_path"], array_identity(arrays[BASE_ARM]), "synthetic_shared_G_path_identity")
                checks.equal(item["shared_state_path_arm"], BASE_ARM, "synthetic_shared_G_path_arm")
        private_trace = _read(directory / "readout-private.json")
        checks.equal(sha256(private_trace), row["readout_private_sha256"], "synthetic_trace_file_identity")
        exact_equal(checks, _json(private_trace), trace, "synthetic_independent_parent_child_trace")
        if row["accuracy_eligible"]:
            reference = (np.asarray([(n["onset"], n["offset"]) for n in row["truth"]], dtype=float),
                         np.asarray([440 * 2 ** ((n["pitch"] - 69) / 12) for n in row["truth"]]))
            for arm in SYNTHETIC_ARMS:
                intervals, frequencies = predictions[arm]
                scores = {}
                for metric, ratio in (("onset_f1", None), ("onset_offset_f1", .2)):
                    pairs = transcription.match_notes(*reference, intervals, frequencies, onset_tolerance=.05,
                        pitch_tolerance=50., offset_ratio=ratio, offset_min_tolerance=.05) if len(frequencies) else []
                    scores[metric] = 2 * len(pairs) / (len(reference[1]) + len(frequencies))
                strict_equal(checks, row["arms"][arm]["metrics"], scores, "synthetic_direct_matching")
        else:
            for arm in SYNTHETIC_ARMS:
                checks.equal(row["arms"][arm]["metrics"], None, "synthetic_ambiguity_and_silence_excluded")
        strict_equal(checks, row["comparison"], synthetic_comparison(row), "synthetic_case_comparison")
    digest = fingerprint(manifest)
    for key in ("predictions_manifest_sha256", "post_evaluation_predictions_manifest_sha256"):
        checks.equal(report.get(key), digest, "synthetic_prediction_barrier_manifest/" + key)
    aggregate, comparisons = synthetic_aggregate(rows), synthetic_comparisons(rows)
    strict_equal(checks, report.get("aggregate"), aggregate, "independent_synthetic_aggregate")
    strict_equal(checks, report.get("comparisons"), comparisons, "independent_synthetic_comparisons")
    projected = {key: report[key] for key in previous if key not in (
        "schema", "planned_arms", "cases", "aggregate", "predictions_manifest_sha256")}
    projected.update(schema="note-state-synthetic-v1", planned_arms=list(SYNTHETIC_OLD_ARMS),
        cases=projected_rows, aggregate={arm: report["aggregate"][arm] for arm in SYNTHETIC_OLD_ARMS},
        predictions_manifest_sha256=fingerprint(old_manifest))
    volatile = {"source_revision", "protocol_head_revision", "elapsed_seconds"}
    exact_equal(checks, {k: v for k, v in projected.items() if k not in volatile},
                {k: v for k, v in previous.items() if k not in volatile}, "full_original_synthetic_projection")
    parity = {"baseline_zip_sha256": PREVIOUS_SHA256, "compared_prediction_files": 1715,
        "compared_input_arrays": 245, "compared_state_paths": 1470, "all_equal": True, "differences": []}
    strict_equal(checks, report.get("historical_parity"), parity, "independent_synthetic_historical_parity")
    return {"aggregate": aggregate, "comparisons": comparisons, "predictions_manifest_sha256": digest}, projected


def audit_private(work, report_path, synthetic_work, synthetic_path, legacy_report_path, legacy_audit_path):
    started, checks = time.monotonic(), Checks()
    raw_report, raw_synthetic = _read(report_path, 48_000_000), _read(synthetic_path, 48_000_000)
    raw_legacy, raw_legacy_audit = _read(legacy_report_path, 32_000_000), _read(legacy_audit_path, 32_000_000)
    report, synthetic, legacy, legacy_audit = map(_json, (raw_report, raw_synthetic, raw_legacy, raw_legacy_audit))
    expected_keys = {
        "schema", "status", "cases", "planned_case_ids", "planned_arms", "source_revision", "protocol_head_revision",
        "source_sha256", "python", "platform", "runtime", "f0_settings", "hmm_settings", "factor_settings",
        "readout_settings", "primary_comparison", "quality_approved", "heldout_generalization", "product_changes",
        "all_cases_complete", "reference_used_for_edits", "device", "threads", "aggregate", "boundary_summary",
        "all_predictions_frozen_before_references", "archive_sha256", "predictions_manifest_sha256",
        "reference_access_started_after_predicted_cases", "post_evaluation_predictions_manifest_sha256",
        "legacy_report_sha256", "historical_parity", "primary_result", "elapsed_seconds", "peak_rss_kib",
    }
    if not isinstance(report, dict) or set(report) != expected_keys:
        raise ValueError("exact completed corpus report inventory required")
    for key, expected in {"schema": "note-boundary-readout-v1", "status": "complete", "all_cases_complete": True,
        "planned_case_ids": list(CASES), "planned_arms": list(ARMS), "primary_comparison": PRIMARY,
        "quality_approved": False, "heldout_generalization": False, "product_changes": False,
        "reference_used_for_edits": False, "device": "cpu", "threads": 2,
        "all_predictions_frozen_before_references": True, "reference_access_started_after_predicted_cases": 40,
        "readout_settings": READOUT_SETTINGS, "legacy_report_sha256": sha256(raw_legacy)}.items():
        strict_equal(checks, report.get(key), expected, "readout_execution_contract/" + key)
    for key in ("elapsed_seconds", "peak_rss_kib"):
        if type(report[key]) not in (int, float) or not math.isfinite(report[key]) or report[key] < 0:
            raise ValueError("invalid resource observation")
    for key in ("source_revision", "protocol_head_revision"):
        if not isinstance(report[key], str) or len(report[key]) != 40 or any(c not in "0123456789abcdef" for c in report[key]):
            raise ValueError("complete immutable execution revision required")
        checks.equal(report[key], synthetic.get(key), "common_execution_revision")
        checks.equal(report[key], legacy.get(key), "common_execution_revision")
    for key in ("f0_settings", "hmm_settings", "factor_settings", "runtime", "archive_sha256", "python", "platform"):
        exact_equal(checks, report[key], legacy.get(key), "unchanged_legacy_contract/" + key)
    require_legacy_audit(legacy, raw_legacy, legacy_audit, checks)
    previous_corpus, previous_synthetic, previous_diagnostics = load_previous(checks)
    check_sources(report, previous_diagnostics, checks)
    exact_equal(checks, synthetic.get("source_sha256"), report["source_sha256"], "common_frozen_source_inventory")
    corpus_result = corpus_from_private(work, report, legacy, checks)
    synthetic_result, projected_synthetic = synthetic_from_private(synthetic_work, synthetic, previous_synthetic, checks)
    replay = verify_replay(legacy, projected_synthetic, previous_corpus, previous_synthetic, checks)
    parity = {"baseline_zip_sha256": PREVIOUS_SHA256,
        "source_checks": dict.fromkeys(FROZEN_SOURCE_PATHS, True), "compared_prediction_files": 400,
        "compared_observation_arrays": 440, "all_equal": True, "differences": [],
        "raw_historical_arrays_available": False, "array_identity_available": True}
    strict_equal(checks, report["historical_parity"], parity, "independent_corpus_historical_parity")
    return {
        "schema": "note-boundary-readout-audit-v1", "status": "pass", "audit_completed": True,
        "report_sha256": sha256(raw_report), "synthetic_report_sha256": sha256(raw_synthetic),
        "legacy_report_sha256": sha256(raw_legacy), "legacy_audit_sha256": sha256(raw_legacy_audit),
        "script_sha256": sha256(_read(Path(__file__))), "source_sha256": report["source_sha256"],
        "replay_parity": replay, "corpus_historical_parity": parity,
        "checks_passed": sum(checks.counts.values()), "checks_by_kind": dict(sorted(checks.counts.items())),
        "maximum_numeric_difference": checks.maximum_numeric_difference,
        "source_files_verified": len(SOURCE_PATHS), "corpus_prediction_files_verified": 440,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1960, "synthetic_input_arrays_verified": 245,
        "synthetic_old_state_paths_verified": 1470, "independent_new_readouts_verified": 285,
        "corpus": corpus_result, "synthetic": synthetic_result,
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0,
        "raw_corpus_musical_arrays_published": False, "quality_approved": False,
        "heldout_generalization": False, "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "Independent split reconstruction walks maximal raw-pitch runs and original G parents without importing the new implementation, any runner, or a decoder.",
            "Frozen auditor parsers and original path-readout checks are reused; direct mir_eval is another call to the same matching implementation, not independent human truth.",
            "All 440 corpus and 1960 synthetic event files, private split traces, reference CSVs, observation hashes, metric arithmetic, comparisons and fixed bootstrap are checked.",
            "The prior private factor audit is bound to the exact legacy projection and auditor hashes; it covers WAV metadata and original F0 scores not re-extracted by this auditor.",
            "Pruning-harm descriptors overlap and cannot establish a unique causal explanation for a lost reference match.",
            "File hashes cannot independently prove past reference-access ordering; immutable runner code, barrier tests, workflow and pre/post manifests provide complementary evidence.",
            "The forty recordings and authored grid are development reuse, not an unused generalization test or product approval.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work", "report", "synthetic-work", "synthetic", "legacy-report", "legacy-audit", "audit"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    inputs = (args.report, args.synthetic, args.legacy_report, args.legacy_audit)
    if (args.audit.exists() or args.audit.is_symlink()
            or args.audit.resolve() in {path.resolve() for path in inputs}
            or any(args.audit.resolve().is_relative_to(path.resolve()) for path in (args.work, args.synthetic_work, REPOSITORY))):
        parser.error("new audit output outside private evidence and checkout required")
    try:
        result = audit_private(args.work, args.report, args.synthetic_work, args.synthetic, args.legacy_report, args.legacy_audit)
    except Exception as exc:
        result = {"schema": "note-boundary-readout-audit-v1", "status": "failed", "audit_completed": False,
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
