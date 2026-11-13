"""Audit the boundary diagnosis from saved private evidence, without inference.

The immutable factor auditor supplies only established parsing, array identity
and path-readout checks.  New interval, matching, residual, overlap and frame
summaries are reconstructed here, without importing the boundary runner,
diagnostic modules, decoder or repository scorer.
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

from scripts.audit_note_state_experiment import (
    Checks,
    _json,
    _read,
    array_identity,
    fingerprint,
    parse_notes,
    parse_reference,
    sha256,
)
from scripts.audit_note_state_factors import (
    ARMS as REPLAY_ARMS,
)
from scripts.audit_note_state_factors import (
    SOURCE_PATHS as FROZEN_SOURCE_PATHS,
)
from scripts.audit_note_state_factors import (
    check_observations,
    reconstruct_readout,
)

REPOSITORY = Path(__file__).resolve().parents[1]
CASES = tuple(f"vocadito_{number}" for number in range(1, 41))
ANNOTATORS = ("A1", "A2")
ARMS = ("pitch_runs", "gaussian_exponent_1", "note_state_hmm")
GAUSSIAN = "gaussian_exponent_1"
PREVIOUS_RECEIPT = "docs/research/receipts/note-state-factors-43344373779.zip"
PREVIOUS_ZIP_SHA256 = "b20495c8936f8b4263daf2660fb57ba282264904d6b30dda076463cc6e3881f6"
SYNTHETIC_ARMS = (
    "pitch_runs", "note_state_hmm", "gaussian_exponent_1", "phase_balanced",
    "positive_voicing_08", "silent_self_099", "hop_unscaled",
)
PARTITIONS = ("retained", "gained", "lost", "neither")
PAIR_VALUES = (
    "signed_offset_seconds", "tolerance_seconds", "tolerance_excess_seconds",
    "reference_duration_seconds", "prediction_duration_seconds",
)
NEW_SOURCE_PATHS = (
    "scripts/note_boundary_diagnostics.py", "scripts/note_boundary_synthetic.py",
    "scripts/run_note_boundary_diagnostics.py", "scripts/audit_note_boundary_diagnostics.py",
    "tests/test_note_boundary_diagnostics.py", "tests/test_note_boundary_synthetic.py",
    "tests/test_run_note_boundary_diagnostics.py", "tests/test_audit_note_boundary_diagnostics.py",
    ".github/workflows/cpu-note-boundary-diagnostics.yml",
    "docs/research/NOTE_BOUNDARY_DIAGNOSTICS_PROTOCOL_2026-11-13.md", PREVIOUS_RECEIPT,
)
SOURCE_PATHS = (*FROZEN_SOURCE_PATHS, *NEW_SOURCE_PATHS)
CORPUS_FIELDS = (
    "schema", "status", "planned_case_ids", "planned_arms", "f0_settings",
    "hmm_settings", "factor_settings", "primary_comparison", "quality_approved",
    "heldout_generalization", "product_changes", "all_cases_complete",
    "reference_used_for_edits", "device", "threads", "aggregate",
    "all_predictions_frozen_before_references", "archive_sha256",
    "predictions_manifest_sha256", "reference_access_started_after_predicted_cases",
    "post_evaluation_predictions_manifest_sha256", "historical_baseline_parity",
    "historical_hmm_parity", "primary_result",
)


def strict_equal(checks, actual, expected, label):
    """Compare every key and type; the legacy checker's dict mode is a subset."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError(label + ": exact object inventory required")
        for key in expected:
            strict_equal(checks, actual[key], expected[key], label + "/" + str(key))
    elif isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            raise ValueError(label + ": exact sequence length required")
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            strict_equal(checks, left, right, label + "/" + str(index))
    else:
        checks.equal(actual, expected, label)


def exact_equal(checks, actual, expected, label):
    """Historical identities and frozen serialized values allow no tolerance."""
    left = json.dumps(actual, sort_keys=True, allow_nan=False)
    right = json.dumps(expected, sort_keys=True, allow_nan=False)
    checks.equal(left == right, True, label)


def summary(values):
    """Linear quantiles computed by sorted positions, with an explicit empty set."""
    numbers = sorted(float(value) for value in values)
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError("nonfinite diagnostic sample")
    result = dict.fromkeys(("min", "q25", "median", "q75", "max", "mean"))
    if numbers:
        def quantile(probability):
            position = (len(numbers) - 1) * probability
            lower = math.floor(position)
            fraction = position - lower
            return numbers[lower] + fraction * (numbers[math.ceil(position)] - numbers[lower])

        result.update(min=numbers[0], q25=quantile(.25), median=quantile(.5),
                      q75=quantile(.75), max=numbers[-1], mean=math.fsum(numbers) / len(numbers))
    return {"count": len(numbers), **result}


def load_previous(path, checks):
    raw = _read(path, 32_000_000)
    checks.equal(sha256(raw), PREVIOUS_ZIP_SHA256, "original_factor_receipt_identity")
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        names = package.namelist()
        if len(names) != 3 or set(names) != {"vocadito.json", "synthetic.json", "audit.json"}:
            raise ValueError("factor receipt member inventory differs")
        if any(item.file_size > 16_000_000 for item in package.infolist()):
            raise ValueError("factor receipt member oversized")
        corpus = _json(package.read("vocadito.json"))
        synthetic = _json(package.read("synthetic.json"))
        audit = _json(package.read("audit.json"))
    checks.equal(corpus.get("status"), "complete", "historical_factor_completion")
    checks.equal(synthetic.get("status"), "complete", "historical_factor_completion")
    checks.equal(audit.get("status"), "pass", "historical_factor_completion")
    return corpus, synthetic


def fixed_pair_summary(pairs):
    result = {"matched": len(pairs)}
    result.update({label: sum(pair["category"] == label for pair in pairs)
                   for label in ("early", "within", "late")})
    result["within_with_raw_excess"] = sum(
        pair["category"] == "within" and pair["tolerance_excess_seconds"] > 0 for pair in pairs)
    result.update({name: summary(pair[name] for pair in pairs) for name in PAIR_VALUES})
    return result


def short_intervals(path, hz, duration):
    """Walk decoded pitch runs, retaining only positive-support sub-80 ms runs."""
    result = []
    start = 0
    labels = [int(state // 3) if int(state) % 3 != 2 else -1 for state in path]
    while start < len(labels):
        stop = start + 1
        while stop < len(labels) and labels[stop] == labels[start]:
            stop += 1
        begin, end = start * .01, min(stop * .01, duration)
        if (labels[start] >= 0 and any(value > 0 for value in hz[start:stop])
                and 0 < end - begin < .08 - 1e-10):
            result.append((begin, end))
        start = stop
    return result


def reference_profiles(intervals, hz, path, duration):
    short = short_intervals(path, hz, duration)
    times = np.arange(len(hz)) * .01
    profiles = []
    for begin, end in intervals:
        indices = np.flatnonzero((times >= begin) & (times < end) & (times < duration))
        voiced = [bool(hz[index] > 0) for index in indices]
        decoded = [bool(path[index] % 3 != 2) for index in indices]
        internal, cursor = 0, 0
        while cursor < len(voiced):
            if voiced[cursor]:
                cursor += 1
                continue
            start = cursor
            while cursor < len(voiced) and not voiced[cursor]:
                cursor += 1
            internal += int(start > 0 and cursor < len(voiced))
        overlaps = [min(end, stop) - max(begin, start) for start, stop in short
                    if min(end, stop) > max(begin, start)]
        profiles.append({
            "frames": len(indices), "raw_voiced_frames": sum(voiced),
            "raw_unvoiced_frames": len(voiced) - sum(voiced),
            "internal_raw_unvoiced_runs": internal,
            "raw_voiced_g_silent_frames": sum(v and not d for v, d in zip(voiced, decoded, strict=True)),
            "raw_unvoiced_g_voiced_frames": sum(not v and d for v, d in zip(voiced, decoded, strict=True)),
            "short_segment_overlap_count": len(overlaps),
            "short_segment_overlap_seconds": math.fsum(overlaps),
        })
    return profiles


def arm_details(reference, prediction):
    """Match directly, then keep the same onset pairs for all residual statistics."""
    import mir_eval.transcription as transcription

    ref_intervals, ref_hz = reference
    pred_intervals, pred_hz = prediction
    onset = transcription.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
        onset_tolerance=.05, pitch_tolerance=50., offset_ratio=None,
        offset_min_tolerance=.05) if len(pred_hz) else []
    offset = transcription.match_notes(ref_intervals, ref_hz, pred_intervals, pred_hz,
        onset_tolerance=.05, pitch_tolerance=50., offset_ratio=.2,
        offset_min_tolerance=.05) if len(pred_hz) else []
    onset_pairs = []
    for ref_index, pred_index in onset:
        ref_index, pred_index = int(ref_index), int(pred_index)
        ref_duration = float(ref_intervals[ref_index, 1] - ref_intervals[ref_index, 0])
        pred_duration = float(pred_intervals[pred_index, 1] - pred_intervals[pred_index, 0])
        delta = float(pred_intervals[pred_index, 1] - ref_intervals[ref_index, 1])
        tolerance = max(.05, .2 * ref_duration)
        category = ("within" if np.around(abs(delta), decimals=4) <= tolerance
                    else "early" if delta < 0 else "late")
        onset_pairs.append({"reference_id": ref_index, "prediction_id": pred_index,
            "signed_offset_seconds": delta, "tolerance_seconds": tolerance,
            "tolerance_excess_seconds": max(0., abs(delta) - tolerance),
            "reference_duration_seconds": ref_duration,
            "prediction_duration_seconds": pred_duration, "category": category})

    # An admissible graph has more information than one deterministic maximum
    # matching.  Degrees are descriptors, not proof that optimal matchings differ.
    onset_graph = np.zeros((len(ref_hz), len(pred_hz)), dtype=bool)
    offset_graph = onset_graph.copy()
    overlap_graph = onset_graph.copy()
    for i in range(len(ref_hz)):
        for j in range(len(pred_hz)):
            onset_hit = (np.around(abs(ref_intervals[i, 0] - pred_intervals[j, 0]), 4) <= .05
                         and abs(1200 * (np.log2(ref_hz[i]) - np.log2(pred_hz[j]))) <= 50.)
            onset_graph[i, j] = onset_hit
            tolerance = max(.05, .2 * (ref_intervals[i, 1] - ref_intervals[i, 0]))
            offset_graph[i, j] = onset_hit and np.around(
                abs(ref_intervals[i, 1] - pred_intervals[j, 1]), 4) <= tolerance
            overlap_graph[i, j] = (min(ref_intervals[i, 1], pred_intervals[j, 1])
                                    > max(ref_intervals[i, 0], pred_intervals[j, 0]))
    pred_degree = overlap_graph.sum(axis=0)
    onset_covered = [[bool(pred_intervals[j, 0] <= ref_intervals[i, 0] < pred_intervals[j, 1])
                     for j in range(len(pred_hz))] for i in range(len(ref_hz))]
    onset_counts = [sum(onset_covered[i][j] for i in range(len(ref_hz))) for j in range(len(pred_hz))]
    return {
        "predicted_notes": len(pred_hz), "onset_pairs": onset_pairs,
        "offset_pairs": [[int(i), int(j)] for i, j in offset],
        "onset_ref_degrees": onset_graph.sum(axis=1).astype(int).tolist(),
        "onset_pred_degrees": onset_graph.sum(axis=0).astype(int).tolist(),
        "offset_ref_degrees": offset_graph.sum(axis=1).astype(int).tolist(),
        "offset_pred_degrees": offset_graph.sum(axis=0).astype(int).tolist(),
        "overlap_ref_degrees": overlap_graph.sum(axis=1).astype(int).tolist(),
        "overlap_pred_degrees": pred_degree.astype(int).tolist(),
        "reference_overlaps_multi_reference_prediction": [
            bool(any(overlap_graph[i, j] and pred_degree[j] > 1 for j in range(len(pred_hz))))
            for i in range(len(ref_hz))],
        "prediction_covered_reference_onsets": onset_counts,
        "reference_onset_in_multi_onset_prediction": [
            any(onset_covered[i][j] and onset_counts[j] >= 2 for j in range(len(pred_hz)))
            for i in range(len(ref_hz))],
    }


def annotation_details(reference, predictions, hz, g_path, duration):
    arms = {arm: arm_details(reference, predictions[arm]) for arm in ARMS}
    runs = {pair[0] for pair in arms["pitch_runs"]["offset_pairs"]}
    gaussian = {pair[0] for pair in arms[GAUSSIAN]["offset_pairs"]}
    partitions = {"retained": runs & gaussian, "gained": gaussian - runs,
                  "lost": runs - gaussian, "neither": set(range(len(reference[0]))) - runs - gaussian}
    return {"reference_notes": len(reference[0]), "arms": arms,
            "offset_partition_ids": {name: sorted(partitions[name]) for name in PARTITIONS},
            "raw_reference_profiles": reference_profiles(reference[0], hz, g_path, duration)}


def summarize_annotations(details):
    reference_count = sum(detail["reference_notes"] for detail in details)
    result = {"recording_annotations": len(details), "reference_notes": reference_count,
              "arms": {}, "offset_reference_partitions": {}}
    for arm in ARMS:
        data = [detail["arms"][arm] for detail in details]
        pairs = [pair for value in data for pair in value["onset_pairs"]]
        predicted = sum(value["predicted_notes"] for value in data)
        offsets = sum(len(value["offset_pairs"]) for value in data)
        assignment = dict.fromkeys(("offset_reference_without_fixed_onset_pair",
            "offset_reference_with_different_prediction", "offset_reference_with_fixed_pair_failing_offset"), 0)
        for value in data:
            fixed = {pair["reference_id"]: pair for pair in value["onset_pairs"]}
            for ref_index, pred_index in value["offset_pairs"]:
                previous = fixed.get(ref_index)
                assignment["offset_reference_without_fixed_onset_pair"] += int(previous is None)
                if previous is not None:
                    assignment["offset_reference_with_different_prediction"] += int(previous["prediction_id"] != pred_index)
                    assignment["offset_reference_with_fixed_pair_failing_offset"] += int(previous["category"] != "within")
        overlap = {
            "edges": sum(sum(value["overlap_ref_degrees"]) for value in data),
            "references_without_overlap": sum(degree == 0 for value in data for degree in value["overlap_ref_degrees"]),
            "references_with_multiple_predictions": sum(degree > 1 for value in data for degree in value["overlap_ref_degrees"]),
            "references_overlapping_prediction_with_multiple_references": sum(
                sum(value["reference_overlaps_multi_reference_prediction"]) for value in data),
            "predictions_without_overlap": sum(degree == 0 for value in data for degree in value["overlap_pred_degrees"]),
            "predictions_with_multiple_references": sum(degree > 1 for value in data for degree in value["overlap_pred_degrees"]),
            "predictions_covering_multiple_reference_onsets": sum(
                count >= 2 for value in data for count in value["prediction_covered_reference_onsets"]),
            "references_with_onset_in_multi_onset_prediction": sum(
                sum(value["reference_onset_in_multi_onset_prediction"]) for value in data),
        }
        graph = {"onset_edges": sum(sum(value["onset_ref_degrees"]) for value in data),
                 "offset_edges": sum(sum(value["offset_ref_degrees"]) for value in data)}
        for prefix in ("onset", "offset"):
            graph["references_with_multiple_" + prefix + "_candidates"] = sum(
                degree > 1 for value in data for degree in value[prefix + "_ref_degrees"])
            graph["predictions_with_multiple_" + prefix + "_candidates"] = sum(
                degree > 1 for value in data for degree in value[prefix + "_pred_degrees"])
        result["arms"][arm] = {
            "predicted_notes": predicted, "onset_matched": len(pairs), "offset_matched": offsets,
            "onset_precision": len(pairs) / predicted if predicted else 0.,
            "onset_recall": len(pairs) / reference_count if reference_count else 0.,
            "offset_precision": offsets / predicted if predicted else 0.,
            "offset_recall": offsets / reference_count if reference_count else 0.,
            "fixed_onset_pairs": fixed_pair_summary(pairs), "offset_assignment": assignment,
            "overlap": overlap, "candidate_graph": graph,
        }
    for name in PARTITIONS:
        selected = [(detail, index) for detail in details for index in detail["offset_partition_ids"][name]]
        pairs = [pair for detail in details for pair in detail["arms"][GAUSSIAN]["onset_pairs"]
                 if pair["reference_id"] in detail["offset_partition_ids"][name]]
        profiles = [detail["raw_reference_profiles"][index] for detail, index in selected]
        overlap = {
            "edges": sum(detail["arms"][GAUSSIAN]["overlap_ref_degrees"][index] for detail, index in selected),
            "references_without_overlap": sum(detail["arms"][GAUSSIAN]["overlap_ref_degrees"][index] == 0
                                               for detail, index in selected),
            "references_with_multiple_predictions": sum(detail["arms"][GAUSSIAN]["overlap_ref_degrees"][index] > 1
                                                         for detail, index in selected),
            "references_overlapping_prediction_with_multiple_references": sum(
                detail["arms"][GAUSSIAN]["reference_overlaps_multi_reference_prediction"][index]
                for detail, index in selected),
            "references_with_onset_in_multi_onset_prediction": sum(
                detail["arms"][GAUSSIAN]["reference_onset_in_multi_onset_prediction"][index]
                for detail, index in selected),
        }
        support = {"sampled_reference_frames": sum(p["frames"] for p in profiles)}
        for key in ("raw_voiced_frames", "raw_unvoiced_frames", "internal_raw_unvoiced_runs",
                    "raw_voiced_g_silent_frames", "raw_unvoiced_g_voiced_frames",
                    "short_segment_overlap_count"):
            support[key] = sum(p[key] for p in profiles)
        for name_key, profile_key in (
            ("references_with_raw_unvoiced_frames", "raw_unvoiced_frames"),
            ("references_with_internal_raw_unvoiced_runs", "internal_raw_unvoiced_runs"),
            ("references_with_raw_voiced_g_silent_frames", "raw_voiced_g_silent_frames"),
            ("references_with_raw_unvoiced_g_voiced_frames", "raw_unvoiced_g_voiced_frames"),
            ("references_with_short_segment_overlap", "short_segment_overlap_count"),
        ):
            support[name_key] = sum(p[profile_key] > 0 for p in profiles)
        support["short_segment_overlap_seconds"] = math.fsum(p["short_segment_overlap_seconds"] for p in profiles)
        result["offset_reference_partitions"][name] = {
            "references": len(selected), "g_onset_unmatched": len(selected) - len(pairs),
            "g_fixed_onset_pairs": fixed_pair_summary(pairs), "g_overlap": overlap, "raw_support": support,
        }
    return result


def corpus_from_private(work, replay, checks):
    if [row.get("id") for row in replay.get("cases", [])] != list(CASES):
        raise ValueError("exact ordered forty-case replay required")
    rows, details = [], []
    for row in replay["cases"]:
        if row.get("status") != "scored" or set(row.get("arms", {})) != set(REPLAY_ARMS):
            raise ValueError("every replay case and arm must be scored")
        directory, duration = work / row["id"], row["duration_seconds"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private corpus directory unavailable or linked")
        raw_observations = _read(directory / "observations.npz")
        checks.equal(sha256(raw_observations), row["observation_sha256"], "private_observation_container")
        arrays = check_observations(raw_observations, row["observations"], duration, checks)
        predictions = {}
        for arm in REPLAY_ARMS:
            raw = _read(directory / (arm + ".json"))
            payload, intervals, hz = parse_notes(raw, duration)
            checks.equal(sha256(raw), row["arms"][arm]["event_sha256"], "private_prediction_identity")
            checks.equal(len(payload), row["arms"][arm]["count"], "private_prediction_count")
            if arm in ARMS:
                predictions[arm] = (intervals, hz)
        detail = {"id": row["id"], "annotators": {}}
        public = {"id": row["id"], "status": "complete", "annotators": {}}
        for annotator in ANNOTATORS:
            raw = _read(directory / (annotator + ".csv"))
            checks.equal(sha256(raw), row["reference_sha256"][annotator], "private_reference_identity")
            reference = parse_reference(raw)
            value = annotation_details(reference, predictions, arrays["hz"], arrays[GAUSSIAN + "_path"], duration)
            detail["annotators"][annotator] = value
            public["annotators"][annotator] = summarize_annotations([value])
        rows.append(public)
        details.append(detail)
    return {"cases": rows, "aggregate": {
        "recordings": len(CASES), "recording_annotations": len(CASES) * len(ANNOTATORS),
        "by_annotator": {ann: summarize_annotations([d["annotators"][ann] for d in details]) for ann in ANNOTATORS},
        "pooled_annotation_judgments": summarize_annotations(
            [d["annotators"][ann] for d in details for ann in ANNOTATORS]),
    }}


def frame_number(seconds):
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds):
        raise ValueError("invalid authored time")
    frame = round(seconds / .01)
    if frame < 0 or abs(seconds - frame * .01) > 1e-9:
        raise ValueError("authored time is outside the ten-millisecond clock")
    return frame


def authored_boundaries(reference, payloads, hz, paths, duration):
    """Walk authored endpoints and locate transitions without the reporter code."""
    terminal = frame_number(duration)
    if len(hz) != terminal + 1:
        raise ValueError("authored terminal sample missing")
    endpoints = {}
    for index, note in enumerate(reference):
        for label, time_value in (("onset_reference_ids", note["onset"]),
                                  ("offset_reference_ids", note["offset"])):
            frame = frame_number(time_value)
            value = endpoints.setdefault(frame, {"onset_reference_ids": [], "offset_reference_ids": []})
            value[label].append(index)
    intervals = {arm: [(frame_number(note["onset"]), frame_number(note["offset"])) for note in payloads[arm]]
                 for arm in SYNTHETIC_ARMS}
    transitions = {}
    for arm in SYNTHETIC_ARMS[1:]:
        states = paths[arm]
        labels = [int(value // 3) if int(value) % 3 != 2 else -1 for value in states]
        transitions[arm] = {
            "label": [i for i in range(1, len(states)) if labels[i - 1] != labels[i]],
            "phase": [i for i in range(1, len(states)) if int(states[i - 1]) % 3 != int(states[i]) % 3],
            "labels": labels,
        }
    result = []
    for frame, roles in sorted(endpoints.items()):
        if frame > terminal:
            raise ValueError("authored endpoint outside clip")
        before, after = (float(hz[frame - 1]) if frame > 0 else None), float(hz[frame])
        row = {"frame": frame, "seconds": frame * .01, **roles,
               "at_audio_start": frame == 0, "at_audio_end": frame == terminal,
               "raw_before_hz": before, "raw_after_hz": after,
               "raw_midi_step": float(12 * np.log2(after / before))
               if before is not None and before > 0 and after > 0 else None, "arms": {}}
        for arm in SYNTHETIC_ARMS:
            value = {
                "emitted_onsets_at_frame": sum(start == frame for start, stop in intervals[arm]),
                "emitted_offsets_at_frame": sum(stop == frame for start, stop in intervals[arm]),
                "emitted_events_spanning_frame": sum(start < frame < stop for start, stop in intervals[arm]),
            }
            if arm in paths:
                states = paths[arm]
                old, new = (int(states[frame - 1]) if frame else None), int(states[frame])
                labels = transitions[arm]["labels"]
                value.update({
                    "state_before": old, "state_after": new,
                    "phase_before": old % 3 if old is not None else None, "phase_after": new % 3,
                    "pitch_bin_before": old // 3 if old is not None else None, "pitch_bin_after": new // 3,
                    "state_changed": old != new if old is not None else None,
                    "decoded_label_changed": labels[frame - 1] != labels[frame] if frame else None,
                })
                for kind in ("label", "phase"):
                    positions = transitions[arm][kind]
                    # Sorted transitions and first-min selection resolve ties early.
                    position = min(positions, key=lambda index: abs(index - frame)) if positions else None
                    value["nearest_" + kind + "_change_delta_frames"] = position - frame if position is not None else None
            row["arms"][arm] = value
        result.append(row)
    return result


def synthetic_group(rows):
    eligible = [row for row in rows if row["accuracy_eligible"]]
    joined = [boundary for row in rows if row["spec"]["kind"] == "change" and row["spec"]["gap"] == 0
              for boundary in row["boundaries"]["truth"]
              if boundary["onset_reference_ids"] and boundary["offset_reference_ids"]]
    result = {"cases": len(rows), "accuracy_eligible_cases": len(eligible),
              "ambiguous_cases": sum(row["ambiguous"] for row in rows),
              "silence_cases": sum(row["spec"]["kind"] == "silence" for row in rows), "arms": {}}
    for arm in SYNTHETIC_ARMS:
        values = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows),
                  "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in rows)}
        for metric in ("onset_f1", "onset_offset_f1"):
            values[metric] = (math.fsum(row["arms"][arm]["metrics"][metric] for row in eligible) / len(eligible)
                              if eligible else None)
        values.update({
            "joined_pitch_change_boundaries": len(joined),
            "joined_pitch_change_with_event_spanning": sum(
                boundary["arms"][arm]["emitted_events_spanning_frame"] > 0 for boundary in joined),
            "joined_pitch_change_with_both_emitted_endpoints": sum(
                boundary["arms"][arm]["emitted_onsets_at_frame"] > 0
                and boundary["arms"][arm]["emitted_offsets_at_frame"] > 0 for boundary in joined),
        })
        result["arms"][arm] = values
    return result


def synthetic_aggregate(rows):
    result = {"all": synthetic_group(rows), "by_kind": {
        kind: synthetic_group([row for row in rows if row["spec"]["kind"] == kind])
        for kind in ("single", "repeat", "change", "silence", "vibrato", "drift", "dropout")}}
    for kind, fields, key in (("change", ("pitch", "frames", "gap", "interval"), "change_cells"),
                              ("repeat", ("pitch", "frames", "gap"), "repeat_cells")):
        groups = {}
        for row in rows:
            if row["spec"]["kind"] == kind:
                groups.setdefault(tuple(row["spec"][field] for field in fields), []).append(row)
        result[key] = [{"cell": dict(zip(fields, key_value, strict=True)), "summary": synthetic_group(group)}
                       for key_value, group in sorted(groups.items())]
    # The historical single-note plan has a declared context order, not sorting
    # alphabetically.  Its first 140 rows each form one complete declared cell.
    result["single_cells"] = [{"cell": {name: row["spec"][name] for name in ("pitch", "frames", "context")},
                                "summary": synthetic_group([row])}
                               for row in rows if row["spec"]["kind"] == "single"]
    return result


def synthetic_from_private(work, replay, checks):
    import mir_eval.transcription as transcription

    if (replay.get("status") != "complete" or replay.get("planned_cases") != 245
            or replay.get("planned_arms") != list(SYNTHETIC_ARMS)
            or len(replay.get("cases", [])) != 245):
        raise ValueError("complete 245-case synthetic replay required")
    rows, manifest = [], {}
    for old in replay["cases"]:
        directory, duration = work / old["id"], old["duration_seconds"]
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private synthetic directory unavailable or linked")
        raw_npz = _read(directory / "observations.npz")
        with np.load(io.BytesIO(raw_npz), allow_pickle=False) as package:
            if len(package.files) != 7 or set(package.files) != {"hz", *SYNTHETIC_ARMS[1:]}:
                raise ValueError("synthetic array inventory differs")
            arrays = {name: package[name] for name in package.files}
        hz, paths = arrays["hz"], {name: arrays[name] for name in SYNTHETIC_ARMS[1:]}
        if hz.ndim != 1 or not np.isfinite(hz).all() or np.any(hz < 0):
            raise ValueError("invalid synthetic input")
        exact_equal(checks, array_identity(hz), old["observation"], "synthetic_input_identity")
        payloads, predictions, manifest[old["id"]] = {}, {}, {}
        for arm in SYNTHETIC_ARMS:
            raw = _read(directory / (arm + ".json"))
            payload, intervals, frequencies = parse_notes(raw, duration)
            checks.equal(sha256(raw), old["arms"][arm]["event_sha256"], "synthetic_prediction_identity")
            exact_equal(checks, payload, old["arms"][arm]["events"], "synthetic_event_payload")
            checks.equal(len(payload), old["arms"][arm]["count"], "synthetic_prediction_count")
            payloads[arm], predictions[arm] = payload, (intervals, frequencies)
            manifest[old["id"]][arm] = sha256(raw)
            if arm in paths:
                states = paths[arm]
                if (states.ndim != 1 or len(states) != len(hz) or states.dtype.kind not in "iu"
                        or np.any(states < 0) or np.any(states >= 435)):
                    raise ValueError("invalid synthetic state path")
                exact_equal(checks, array_identity(states), old["arms"][arm]["state_path"], "synthetic_path_identity")
                reconstructed, diagnostic = reconstruct_readout(states, hz, duration)
                exact_equal(checks, payload, reconstructed, "synthetic_path_readout")
                recorded = old["arms"][arm]["diagnostics"]
                checks.equal(recorded, diagnostic, "synthetic_path_diagnostics")
                raw_voiced = int(np.count_nonzero(hz > 0))
                lost = int(np.count_nonzero((hz > 0) & (states % 3 == 2)))
                checks.equal(recorded.get("raw_voiced_to_silent_frames"), lost, "synthetic_voicing")
                checks.equal(recorded.get("raw_unvoiced_to_voiced_frames"),
                    int(np.count_nonzero((hz == 0) & (states % 3 != 2))), "synthetic_voicing")
                checks.equal(recorded.get("voiced_coverage"), 1 - lost / raw_voiced if raw_voiced else None,
                             "synthetic_voicing")
        spec = old["spec"]
        ambiguous = spec["kind"] == "dropout" or (spec["kind"] == "repeat" and spec["gap"] == 0)
        eligible = not ambiguous and spec["kind"] != "silence"
        checks.equal(old["accuracy_eligible"], eligible, "synthetic_denominator")
        checks.equal(bool(old["alternative_truth"]), ambiguous, "synthetic_interpretations")
        if eligible:
            ref_intervals = np.asarray([(n["onset"], n["offset"]) for n in old["truth"]], dtype=float)
            ref_hz = np.asarray([440 * 2 ** ((n["pitch"] - 69) / 12) for n in old["truth"]])
            for arm in SYNTHETIC_ARMS:
                intervals, frequencies = predictions[arm]
                for metric, ratio in (("onset_f1", None), ("onset_offset_f1", .2)):
                    matching = transcription.match_notes(ref_intervals, ref_hz, intervals, frequencies,
                        onset_tolerance=.05, pitch_tolerance=50., offset_ratio=ratio,
                        offset_min_tolerance=.05) if len(frequencies) else []
                    value = 2 * len(matching) / (len(ref_hz) + len(frequencies))
                    checks.equal(old["arms"][arm]["metrics"][metric], value, "synthetic_direct_matching")
        summaries = {arm: {name: old["arms"][arm][name] for name in
                     (("count", "event_sha256", "metrics", "diagnostics", "state_path")
                      if arm in paths else ("count", "event_sha256", "metrics", "diagnostics"))}
                     for arm in SYNTHETIC_ARMS}
        rows.append({"id": old["id"], "spec": spec, "duration_seconds": duration,
            "accuracy_eligible": eligible, "ambiguous": ambiguous,
            "truth_note_count": len(old["truth"]), "alternative_truth_note_count": len(old["alternative_truth"]),
            "observation": array_identity(hz), "arms": summaries,
            "boundaries": {key: authored_boundaries(old[key], payloads, hz, paths, duration)
                           for key in ("truth", "alternative_truth")}})
    aggregate = synthetic_aggregate(rows)
    for key, count in (("cases", 245), ("accuracy_eligible_cases", 227), ("ambiguous_cases", 15), ("silence_cases", 3)):
        checks.equal(aggregate["all"][key], count, "synthetic_complete_population")
    digest = fingerprint(manifest)
    checks.equal(digest, replay.get("predictions_manifest_sha256"), "synthetic_prediction_manifest")
    return {"schema": "note-boundary-synthetic-v1", "status": "complete", "cases": rows,
        "planned_cases": 245, "planned_arms": list(SYNTHETIC_ARMS), "inference_performed": False,
        "clock_seconds": .01, "nearest_transition_tie": "earlier_frame",
        "quality_approved": False, "heldout_generalization": False,
        "identities_checked": {"event_files": 1715, "input_arrays": 245, "state_path_arrays": 1470},
        "predictions_manifest_sha256": digest, "aggregate": aggregate}


def verify_replay(corpus, synthetic, previous_corpus, previous_synthetic, checks):
    if set(corpus.get("source_sha256", {})) != set(FROZEN_SOURCE_PATHS):
        raise ValueError("frozen source inventory differs")
    if set(previous_corpus.get("source_sha256", {})) != set(FROZEN_SOURCE_PATHS):
        raise ValueError("historical frozen source inventory differs")
    source_checks = {}
    for name in FROZEN_SOURCE_PATHS:
        digest = previous_corpus["source_sha256"][name]
        checks.equal(corpus["source_sha256"][name], digest, "unchanged_replay_source")
        checks.equal(sha256(_read(REPOSITORY / name, 32_000_000)), digest, "unchanged_local_frozen_source")
        source_checks[name] = True
    for field in CORPUS_FIELDS:
        exact_equal(checks, corpus.get(field), previous_corpus[field], "full_corpus_replay/" + field)
    checks.equal([row.get("id") for row in corpus.get("cases", [])], list(CASES), "full_corpus_population")
    checks.equal([row.get("id") for row in previous_corpus.get("cases", [])], list(CASES), "historical_corpus_population")
    for row, previous in zip(corpus["cases"], previous_corpus["cases"], strict=True):
        current = {key: value for key, value in row.items() if key not in ("observation_sha256", "inference_seconds")}
        historical = {key: value for key, value in previous.items() if key not in ("observation_sha256", "inference_seconds")}
        exact_equal(checks, current, historical, "full_corpus_case_replay")
    volatile = {"source_revision", "protocol_head_revision", "elapsed_seconds"}
    exact_equal(checks, {key: value for key, value in synthetic.items() if key not in volatile},
                {key: value for key, value in previous_synthetic.items() if key not in volatile},
                "full_synthetic_replay")
    counts = {
        "compared_corpus_prediction_files": sum(len(row["arms"]) for row in corpus["cases"]),
        "compared_corpus_observation_arrays": sum(len(row["observations"]) for row in corpus["cases"]),
        "compared_synthetic_prediction_files": sum(len(row["arms"]) for row in synthetic["cases"]),
        "compared_synthetic_input_arrays": sum("observation" in row for row in synthetic["cases"]),
        "compared_synthetic_state_paths": sum("state_path" in arm for row in synthetic["cases"]
                                              for arm in row["arms"].values()),
    }
    checks.equal(list(counts.values()), [400, 440, 1715, 245, 1470], "complete_replayed_evidence_counts")
    return {"baseline_zip_sha256": PREVIOUS_ZIP_SHA256, "source_checks": source_checks, **counts,
            "all_equal": True, "differences": [], "raw_historical_arrays_available": False,
            "array_identity_available": True}


def audit_private(work, replay_path, synthetic_work, synthetic_path, replay_audit_path, report_path):
    started, checks = time.monotonic(), Checks()
    raw_report, raw_replay = _read(report_path, 48_000_000), _read(replay_path, 32_000_000)
    raw_synthetic, raw_replay_audit = _read(synthetic_path, 32_000_000), _read(replay_audit_path, 32_000_000)
    report, corpus = _json(raw_report), _json(raw_replay)
    synthetic, replay_audit = _json(raw_synthetic), _json(raw_replay_audit)
    expected_keys = {
        "schema", "status", "source_revision", "protocol_head_revision", "source_sha256",
        "input_reports_sha256", "replay_parity", "corpus", "synthetic", "quality_approved",
        "heldout_generalization", "product_changes", "reference_used_for_edits",
        "all_cases_complete", "elapsed_seconds",
    }
    if not isinstance(report, dict) or set(report) != expected_keys:
        raise ValueError("exact completed boundary report inventory required")
    for name, expected in {
        "schema": "note-boundary-diagnostics-v1", "status": "complete", "all_cases_complete": True,
        "quality_approved": False, "heldout_generalization": False, "product_changes": False,
        "reference_used_for_edits": False,
    }.items():
        checks.equal(report[name], expected, "boundary_run_contract")
    if (type(report["elapsed_seconds"]) not in (int, float) or not math.isfinite(report["elapsed_seconds"])
            or report["elapsed_seconds"] < 0):
        raise ValueError("invalid recorded duration")
    for name in ("source_revision", "protocol_head_revision"):
        checks.equal(report[name], corpus.get(name), "common_execution_revision")
        checks.equal(report[name], synthetic.get(name), "common_execution_revision")
    if set(report["source_sha256"]) != set(SOURCE_PATHS):
        raise ValueError("exact frozen and new source inventory required")
    for name in SOURCE_PATHS:
        checks.equal(report["source_sha256"][name], sha256(_read(REPOSITORY / name, 32_000_000)),
                     "boundary_source_identity")
    expected_inputs = {"vocadito": sha256(raw_replay), "synthetic": sha256(raw_synthetic),
                       "replay_audit": sha256(raw_replay_audit)}
    strict_equal(checks, report["input_reports_sha256"], expected_inputs, "input_report_identity")
    for name, expected in {
        "schema": "note-state-factors-audit-v1", "status": "pass", "audit_completed": True,
        "complete_prediction_files_verified": 400, "observation_arrays_verified": 440,
        "source_files_verified": 24, "report_sha256": sha256(raw_replay),
        "script_sha256": sha256(_read(REPOSITORY / "scripts/audit_note_state_factors.py")),
    }.items():
        checks.equal(replay_audit.get(name), expected, "prior_private_audit_binding")
    previous_corpus, previous_synthetic = load_previous(REPOSITORY / PREVIOUS_RECEIPT, checks)
    replay_parity = verify_replay(corpus, synthetic, previous_corpus, previous_synthetic, checks)
    strict_equal(checks, report["replay_parity"], replay_parity, "independent_replay_parity")
    calculated_corpus = corpus_from_private(work, corpus, checks)
    strict_equal(checks, report["corpus"], calculated_corpus, "independent_corpus_diagnostics")
    calculated_synthetic = synthetic_from_private(synthetic_work, synthetic, checks)
    strict_equal(checks, report["synthetic"], calculated_synthetic, "independent_synthetic_boundaries")
    return {
        "schema": "note-boundary-diagnostics-audit-v1", "status": "pass", "audit_completed": True,
        "report_sha256": sha256(raw_report), "script_sha256": sha256(Path(__file__).read_bytes()),
        "source_sha256": report["source_sha256"], "input_reports_sha256": expected_inputs,
        "replay_parity": replay_parity,
        "checks_passed": sum(checks.counts.values()), "checks_by_kind": dict(sorted(checks.counts.items())),
        "maximum_numeric_difference": checks.maximum_numeric_difference,
        "source_files_verified": len(SOURCE_PATHS), "corpus_prediction_files_verified": 400,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1715, "synthetic_input_arrays_verified": 245,
        "synthetic_path_arrays_and_readouts_verified": 1470,
        "corpus_aggregate": calculated_corpus["aggregate"],
        "synthetic_aggregate": calculated_synthetic["aggregate"],
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0,
        "raw_corpus_musical_arrays_published": False, "quality_approved": False,
        "heldout_generalization": False, "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "Reconstructs newly declared residual, matching graph, temporal overlap, frame support and synthetic boundary descriptors from saved evidence; no inference or new model condition.",
            "Imports immutable strict parsing/array/path-readout helpers from prior auditors; new diagnostic computations do not import the runner, reporter, model or repository scorer.",
            "The original factor private audit is bound by its report and source hashes; this second auditor directly rereads notes, observation arrays and note references, not WAV or original human F0 files.",
            "Direct mir_eval matching is an independent call, not an independent matching algorithm or independent human truth. Candidate degrees do not prove multiple maximum assignments exist.",
            "Overlap, onset coverage and raw-voicing/pruning intersections are operational descriptors. They are not causal merge/split labels or proof that one mechanism caused an offset loss.",
            "Pooled counts are A1/A2 annotation judgments, and quantiles pool original matched-pair samples. The repeatedly reused forty-recording cohort does not establish generalization.",
            "File hashes and source inspection cannot independently prove historical access order or runtime execution; barrier tests and the immutable replay workflow supply complementary evidence.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("work", "replay", "synthetic-work", "synthetic", "replay-audit", "report", "audit"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if (args.audit.exists() or args.audit.is_symlink()
            or args.audit.resolve() in {args.report.resolve(), args.replay.resolve(), args.synthetic.resolve(), args.replay_audit.resolve()}
            or args.audit.resolve().is_relative_to(args.work.resolve())
            or args.audit.resolve().is_relative_to(args.synthetic_work.resolve())
            or args.audit.resolve().is_relative_to(REPOSITORY)):
        parser.error("a new audit file outside private evidence and checkout is required")
    try:
        result = audit_private(args.work, args.replay, args.synthetic_work, args.synthetic, args.replay_audit, args.report)
    except Exception as exc:
        result = {"schema": "note-boundary-diagnostics-audit-v1", "status": "failed", "audit_completed": False,
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
