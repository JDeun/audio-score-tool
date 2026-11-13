"""Audit downloaded #296 public evidence without inference or private contours.

This standalone post-run checker regenerates owned raw inputs and truth, never
predictions. Corpus match cardinalities are checked from published counts and
set differences; original human notes, individual residuals and G paths remain
private and are not claimed to be independently reconstructed here.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import time
import zipfile
from collections import Counter
from pathlib import Path

import mir_eval
import mir_eval.transcription as transcription
import numpy as np

OLD_SHA = "43b439e665eb470ec1b24179697cc99d2733fecb6122d1da6a77125d8e3ccf31"
NUMERIC_MANIFEST = "docs/research/NOTE_BOUNDARY_READOUT_NUMERIC_INPUTS_2026-11-13.json"
NUMERIC_MANIFEST_SHA = "e5349cfb3a65e076fab607287b69e71c9e4298157614160439128e00b6b14428"
EXPECTED_RUNTIME = {"librosa": "0.10.2.post1", "numpy": "1.26.4", "scipy": "1.13.1",
                    "mir-eval": "0.8.2", "numba": "0.60.0", "soundfile": "0.13.1",
                    "resampy": "0.4.2", "soxr": "1.1.0"}
MEMBERS = ("synthetic.json", "legacy-synthetic.json", "vocadito.json", "legacy-vocadito.json", "legacy-audit.json", "audit.json")
CASES = tuple(f"vocadito_{index}" for index in range(1, 41))
ANN = ("A1", "A2")
NEW = "gaussian_raw_hysteresis_split"
G = "gaussian_exponent_1"
OLD_ARMS = ("pitch_runs", "pitch_hysteresis", "pitch_hysteresis_reattack", "note_state_hmm", "note_state_hmm_rms",
            G, "phase_balanced", "positive_voicing_08", "silent_self_099", "hop_unscaled")
ARMS = (*OLD_ARMS, NEW)
SYN_OLD = ("pitch_runs", "note_state_hmm", G, "phase_balanced", "positive_voicing_08", "silent_self_099", "hop_unscaled")
SYN_ARMS = (*SYN_OLD, NEW)
DIAGNOSTIC_ARMS = ("pitch_runs", G, "note_state_hmm", NEW)
METRICS = ("onset_f1", "onset_offset_f1")
CRITERIA = ("onset", "onset_offset")
PARTS = ("retained", "gained", "lost", "neither")
HARM = ("lost_references", "lost_matched_parent_cut", "lost_matched_parent_with_short_children", "lost_matched_parent_all_children_pruned")
DIST = ("signed_offset_seconds", "tolerance_seconds", "tolerance_excess_seconds", "reference_duration_seconds", "prediction_duration_seconds")
SEMITONE_IDS = ("change_195", "change_197", "change_207", "change_209", "change_219", "change_221")
CHECKS = Counter()
MAX_DIFF = 0.


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parsed(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def require(condition, label):
    CHECKS[label] += 1
    if not condition:
        raise ValueError(label)


def same(actual, expected, label):
    global MAX_DIFF
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), label + "/keys")
        for key, value in expected.items():
            same(actual[key], value, label)
    elif isinstance(expected, (list, tuple)):
        require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), label + "/length")
        for left, right in zip(actual, expected, strict=True):
            same(left, right, label)
    elif type(expected) is bool:
        require(type(actual) is bool and actual is expected, label)
    elif type(expected) is int:
        require(type(actual) is int and actual == expected, label)
    elif type(expected) is float:
        require(type(actual) in (int, float) and math.isfinite(actual), label + "/finite")
        MAX_DIFF = max(MAX_DIFF, abs(actual - expected))
        require(abs(actual - expected) <= 1e-10, label)
    else:
        require(type(actual) is type(expected) and actual == expected, label)


def exact(actual, expected, label):
    require(json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False), label)


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def count(value, label):
    require(type(value) is int and value >= 0, label)
    return value


def canonical_events(events):
    return (json.dumps(events, indent=2, allow_nan=False) + "\n").encode()


def check_distribution(value, number=None):
    require(set(value) == {"count", "min", "q25", "median", "q75", "max", "mean"}, "distribution_keys")
    n = count(value["count"], "distribution_count")
    if number is not None:
        same(n, number, "distribution_sample_count")
    if not n:
        require(all(value[key] is None for key in value if key != "count"), "empty_distribution_null")
        return
    ordered = [value[key] for key in ("min", "q25", "median", "q75", "max")]
    require(all(type(v) in (int, float) and math.isfinite(v) for v in (*ordered, value["mean"])), "distribution_finite")
    require(all(a <= b + 1e-12 for a, b in zip(ordered[:-1], ordered[1:], strict=True)), "distribution_order")
    require(value["min"] - 1e-12 <= value["mean"] <= value["max"] + 1e-12, "distribution_mean_bounds")


def check_fixed(value):
    require(set(value) == {"matched", "early", "within", "late", "within_with_raw_excess", *DIST}, "fixed_pair_fields")
    n = count(value["matched"], "fixed_match_count")
    same(sum(count(value[key], "fixed_category_count") for key in ("early", "within", "late")), n, "fixed_category_partition")
    require(0 <= count(value["within_with_raw_excess"], "rounding_count") <= value["within"], "rounding_subset")
    for key in DIST:
        check_distribution(value[key], n)
    if n:
        require(value["tolerance_seconds"]["min"] >= .05 - 1e-12, "minimum_offset_tolerance")
        require(value["tolerance_excess_seconds"]["min"] >= 0, "nonnegative_tolerance_excess")
        require(value["reference_duration_seconds"]["min"] > 0, "positive_reference_duration")
        require(value["prediction_duration_seconds"]["min"] >= .08 - 1e-10, "minimum_prediction_duration")


def combine_public(actual, parts):
    """Recompute counts, extrema and means; raw quantile samples are unavailable."""
    if isinstance(actual, dict) and set(actual) == {"count", "min", "q25", "median", "q75", "max", "mean"}:
        n = sum(value["count"] for value in parts)
        check_distribution(actual, n)
        nonempty = [value for value in parts if value["count"]]
        if n:
            same(actual["min"], min(value["min"] for value in nonempty), "pooled_extrema")
            same(actual["max"], max(value["max"] for value in nonempty), "pooled_extrema")
            same(actual["mean"], math.fsum(value["mean"] * value["count"] for value in nonempty) / n, "pooled_weighted_sample_mean")
        return
    if isinstance(actual, dict):
        require(all(isinstance(value, dict) and set(value) == set(actual) for value in parts), "pooled_schema")
        for key, value in actual.items():
            combine_public(value, [part[key] for part in parts])
    elif type(actual) is int:
        same(actual, sum(count(value, "pooled_nonnegative_count") for value in parts), "pooled_additive_count")
    else:
        raise ValueError("unexpected public aggregate leaf")


def reference_ids(values, reference_count):
    require(isinstance(values, list) and values == sorted(set(values))
            and all(type(value) is int and 0 <= value < reference_count for value in values), "reference_ID_domain")
    return set(values)


def derived_comparisons(row, annotator):
    nref = row["arms"]["pitch_runs"]["annotators"][annotator]["reference_note_count"]
    result = {base: {} for base in ("pitch_runs", G)}
    for criterion in CRITERIA:
        run_matches = row["arms"]["pitch_runs"]["annotators"][annotator][criterion + "_matched"]
        gains, losses = {}, {}
        for arm in ARMS:
            metrics = row["arms"][arm]["annotators"][annotator]
            gains[arm] = reference_ids(metrics[criterion + "_gained_reference_ids"], nref)
            losses[arm] = reference_ids(metrics[criterion + "_lost_reference_ids"], nref)
            require(not gains[arm] & losses[arm], "gain_loss_disjoint")
            same(metrics[criterion + "_matched"], run_matches + len(gains[arm]) - len(losses[arm]), "matched_count_from_runs_sets")
        require(not gains["pitch_runs"] and not losses["pitch_runs"], "runs_self_difference_empty")
        known_in = set().union(*losses.values())
        known_out = set().union(*gains.values())
        require(not known_in & known_out and len(known_in) <= run_matches
                and len(known_out) <= nref - run_matches, "cross_arm_reference_membership_consistency")
        for base in ("pitch_runs", G):
            retained = run_matches - len(losses[base] | losses[NEW]) + len(gains[base] & gains[NEW])
            gained = len(losses[base] - losses[NEW]) + len(gains[NEW] - gains[base])
            lost = len(losses[NEW] - losses[base]) + len(gains[base] - gains[NEW])
            neither = nref - retained - gained - lost
            result[base][criterion] = {"retained": retained, "gained": gained, "lost": lost, "neither": neither}
            require(all(value >= 0 for value in result[base][criterion].values()), "reference_partition_nonnegative")
            same(retained + gained, row["arms"][NEW]["annotators"][annotator][criterion + "_matched"], "new_match_partition")
            same(retained + lost, row["arms"][base]["annotators"][annotator][criterion + "_matched"], "baseline_match_partition")
    return result


def check_corpus_counts(row, annotator):
    r = count(row["arms"]["pitch_runs"]["annotators"][annotator]["reference_note_count"], "reference_count")
    require(r > 0, "nonempty_human_reference")
    for arm in ARMS:
        item = row["arms"][arm]
        p = count(item["count"], "prediction_count")
        value = item["annotators"][annotator]
        same(value["reference_note_count"], r, "common_reference_count")
        onset = count(value["onset_matched"], "onset_match_count")
        offset = count(value["onset_offset_matched"], "offset_match_count")
        require(0 <= offset <= onset <= min(r, p), "matching_cardinality_bounds")
        for criterion, metric, hits in (("onset", "onset_f1", onset), ("onset_offset", "onset_offset_f1", offset)):
            same(value[metric], round(2 * hits / (r + p), 8), "F1_from_published_counts")
            same(value[criterion + "_unmatched_reference"], r - hits, "unmatched_reference_count")
            same(value[criterion + "_unmatched_prediction"], p - hits, "unmatched_prediction_count")
        for key, expected in {"onset_precision": onset / p if p else 0., "onset_recall": onset / r,
                              "offset_precision": offset / p if p else 0., "offset_recall": offset / r}.items():
            same(value[key], expected, "precision_recall_from_counts")
    summary = row["annotation_diagnostics"][annotator]
    require(set(summary) == {"recording_annotations", "reference_notes", "arms", "comparisons", "pruning_harm"}, "annotation_schema")
    same(summary["recording_annotations"], 1, "per_case_annotation_denominator")
    same(summary["reference_notes"], r, "annotation_reference_count")
    require(set(summary["arms"]) == set(DIAGNOSTIC_ARMS), "diagnostic_arm_inventory")
    for arm in DIAGNOSTIC_ARMS:
        details, metrics = summary["arms"][arm], row["arms"][arm]["annotators"][annotator]
        require(set(details) == {"predicted_notes", "onset_matched", "offset_matched", "fixed_onset_pairs"}, "arm_summary_fields")
        same(details["predicted_notes"], row["arms"][arm]["count"], "diagnostic_prediction_count")
        same(details["onset_matched"], metrics["onset_matched"], "diagnostic_onset_count")
        same(details["offset_matched"], metrics["onset_offset_matched"], "diagnostic_offset_count")
        check_fixed(details["fixed_onset_pairs"])
        same(details["fixed_onset_pairs"]["matched"], details["onset_matched"], "same_onset_pair_count")
        require(details["fixed_onset_pairs"]["within"] <= details["offset_matched"], "valid_fixed_pairs_bounded_by_offset_maximum")
    comparisons = derived_comparisons(row, annotator)
    same(summary["comparisons"], comparisons, "independent_G_and_runs_reference_partitions")
    require(set(summary["pruning_harm"]) == set(CRITERIA), "pruning_harm_criteria")
    for criterion in CRITERIA:
        value = summary["pruning_harm"][criterion]
        require(set(value) == set(HARM), "pruning_harm_fields")
        for number in value.values():
            count(number, "pruning_harm_count")
        same(value["lost_references"], comparisons[G][criterion]["lost"], "pruning_harm_lost_denominator")
        require(value["lost_matched_parent_all_children_pruned"] <= value["lost_matched_parent_with_short_children"]
                <= value["lost_matched_parent_cut"] <= value["lost_references"], "pruning_harm_subset_bounds")
    return comparisons


def aggregate_corpus(rows):
    result = {}
    for arm in ARMS:
        item = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in METRICS:
            scores = {ann: [row["arms"][arm]["annotators"][ann][metric] for row in rows] for ann in ANN}
            means = [math.fsum(pair) / 2 for pair in zip(scores["A1"], scores["A2"], strict=True)]
            deltas = [mean - math.fsum(row["arms"]["pitch_runs"]["annotators"][ann][metric] for ann in ANN) / 2
                      for mean, row in zip(means, rows, strict=True)]
            better, worse = sum(value > 1e-8 for value in deltas), sum(value < -1e-8 for value in deltas)
            item[metric] = {"macro": math.fsum(means) / 40, "A1_macro": math.fsum(scores["A1"]) / 40,
                "A2_macro": math.fsum(scores["A2"]) / 40, "delta_vs_runs": math.fsum(deltas) / 40,
                "recordings_improved": better, "recordings_worse": worse, "recordings_tied": 40 - better - worse}
        for rate in ("onset_precision", "onset_recall", "offset_precision", "offset_recall"):
            item[rate] = math.fsum(row["arms"][arm]["annotators"][ann][rate] for row in rows for ann in ANN) / 80
        for criterion in CRITERIA:
            for kind in ("gained", "lost"):
                item[criterion + "_" + kind + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][criterion + "_" + kind + "_reference_ids"]) for row in rows for ann in ANN)
        result[arm] = item
    return result


def primary_corpus(rows):
    differences = [math.fsum(row["arms"][NEW]["annotators"][ann]["onset_offset_f1"]
                   - row["arms"][G]["annotators"][ann]["onset_offset_f1"] for ann in ANN) / 2 for row in rows]
    draws = np.random.default_rng(296).integers(0, 40, size=(10000, 40))
    means = sorted(math.fsum(differences[int(index)] for index in draw) / 40 for draw in draws)
    def percentile(probability):
        position = probability * (len(means) - 1)
        left = math.floor(position)
        return means[left] + (means[math.ceil(position)] - means[left]) * (position - left)
    better, worse = sum(value > 1e-8 for value in differences), sum(value < -1e-8 for value in differences)
    return {"candidate": NEW, "baseline": G, "metric": "onset_offset_f1",
        "paired_recording_deltas": [{"id": case, "delta": value} for case, value in zip(CASES, differences, strict=True)],
        "mean_delta": math.fsum(differences) / 40, "recordings_improved": better, "recordings_worse": worse,
        "recordings_tied": 40 - better - worse, "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2",
            "seed": 296, "resamples": 10000, "confidence_level": .95, "method": "paired_percentile_linear",
            "low": percentile(.025), "high": percentile(.975)}, "heldout_generalization": False}


def check_readout(value, baseline, duration):
    for key in ("candidate_cut_count", "applied_cut_count", "affected_parent_count", "parent_segment_count", "child_segment_count",
                "originally_emitted_parents_all_children_pruned", "originally_emitted_parents_with_short_children",
                "originally_emitted_parents_with_any_pruned_children", "clipped_child_count"):
        count(value[key], "readout_count")
    same(value["schema_version"], 1, "readout_schema")
    same(value["child_segment_count"], value["parent_segment_count"] + value["applied_cut_count"], "child_parent_cut_conservation")
    require(value["affected_parent_count"] <= value["applied_cut_count"] <= value["candidate_cut_count"], "candidate_applied_bounds")
    require(value["affected_parent_count"] <= value["parent_segment_count"], "affected_parent_bounds")
    require(value["originally_emitted_parents_all_children_pruned"] <= value["originally_emitted_parents_with_short_children"]
            <= value["originally_emitted_parents_with_any_pruned_children"] <= value["affected_parent_count"], "pruned_parent_subset_bounds")
    same(value["baseline"], {key: baseline[key] for key in value["baseline"]}, "original_G_readout_preserved")
    same(value["baseline"]["segments_before_filter"], value["parent_segment_count"], "original_parent_denominator")
    same(value["readout"]["segments_before_filter"], value["child_segment_count"], "child_denominator")
    for key in ("frames", "raw_voiced_frames", "decoded_voiced_frames", "attack_frames", "stable_frames", "silent_frames",
                "decoded_voiced_over_raw_unvoiced_frames", "raw_voiced_decoded_silent_frames"):
        same(value["readout"][key], value["baseline"][key], "unchanged_raw_and_decoded_support")
    for name in ("baseline", "readout"):
        diag = value[name]
        same(sum(diag[key] for key in ("emitted_notes", "short_segments_discarded", "zero_duration_segments", "segments_without_raw_voiced_support")),
             diag["segments_before_filter"], "readout_segment_disposition_partition")
        same(diag["attack_frames"] + diag["stable_frames"], diag["decoded_voiced_frames"], "voiced_phase_partition")
        same(diag["decoded_voiced_frames"] + diag["silent_frames"], diag["frames"], "phase_frame_partition")
        require(diag["emitted_notes_with_raw_unvoiced_frames"] <= diag["emitted_notes"], "bridging_event_bounds")
    same(value["baseline_emitted_seconds"], value["baseline"]["emitted_note_seconds"], "baseline_emitted_seconds")
    same(value["emitted_seconds"], value["readout"]["emitted_note_seconds"], "candidate_emitted_seconds")
    same(value["emitted_seconds_change"], value["emitted_seconds"] - value["baseline_emitted_seconds"], "emitted_seconds_change")
    require(0 <= value["emitted_seconds"] <= value["baseline_emitted_seconds"] + 1e-10 <= duration + 1e-9, "coverage_can_only_shrink")
    for prefix, seconds in (("baseline_emitted", value["baseline_emitted_seconds"]), ("emitted", value["emitted_seconds"])):
        same(value[prefix + "_coverage_fraction"], seconds / duration if duration else 0., "emitted_coverage_arithmetic")
    for key in ("child_raw_voiced_frames_summary", "child_seconds_summary"):
        check_distribution(value[key], value["child_segment_count"])
    check_distribution(value["child_midi_median_summary"])
    require(value["readout"]["emitted_notes"] + value["readout"]["short_segments_discarded"]
            <= value["child_midi_median_summary"]["count"] <= value["child_segment_count"], "raw_median_support_denominator")
    for key in ("candidate_cut_frames_sha256", "applied_cut_frames_sha256", "trace_sha256"):
        require(isinstance(value[key], str) and len(value[key]) == 64, "private_fingerprint_shape")


def readout_totals(values):
    count_fields = ("candidate_cut_count", "applied_cut_count", "affected_parent_count", "parent_segment_count", "child_segment_count",
        "originally_emitted_parents_all_children_pruned", "originally_emitted_parents_with_short_children",
        "originally_emitted_parents_with_any_pruned_children", "clipped_child_count")
    result = {key: sum(value[key] for value in values) for key in count_fields}
    for key in ("baseline_emitted_seconds", "emitted_seconds", "emitted_seconds_change"):
        result[key] = math.fsum(value[key] for value in values)
    result["baseline_short_segments"] = sum(value["baseline"]["short_segments_discarded"] for value in values)
    result["child_short_segments"] = sum(value["readout"]["short_segments_discarded"] for value in values)
    result["baseline_short_seconds"] = math.fsum(value["baseline"]["short_segments_discarded_seconds"] for value in values)
    result["child_short_seconds"] = math.fsum(value["readout"]["short_segments_discarded_seconds"] for value in values)
    result["empty_candidate_outputs"] = sum(value["readout"]["emitted_notes"] == 0 for value in values)
    return result


def authored(spec):
    left = 30 if spec["context"] in ("interior", "end") else 0
    right = 30 if spec["context"] in ("interior", "start") else 0
    length = 2 * spec["frames"] + spec["gap"] if spec["kind"] in ("repeat", "change") else spec["frames"]
    end, total = left + length, left + length + right
    midi = np.full(total + 1, np.nan)
    if spec["kind"] != "silence":
        midi[left:end] = spec["pitch"]
    if spec["kind"] in ("repeat", "change"):
        midi[left + spec["frames"]:left + spec["frames"] + spec["gap"]] = np.nan
        midi[left + spec["frames"] + spec["gap"]:end] = spec["pitch"] + spec["interval"]
    elif spec["kind"] == "vibrato":
        midi[left:end] += .3 * np.sin(2 * np.pi * 6 * np.arange(spec["frames"]) * .01)
    elif spec["kind"] == "drift":
        midi[left:end] += np.linspace(-.3, .3, spec["frames"])
    elif spec["kind"] == "dropout":
        middle = left + spec["frames"] // 2
        midi[middle:middle + spec["gap"]] = np.nan
    if spec["context"] in ("end", "full") and spec["kind"] != "silence":
        midi[-1] = midi[-2]
    hz = np.where(np.isfinite(midi), 440 * 2 ** ((midi - 69) / 12), 0.)
    def note(pitch, first, stop):
        return {"pitch": pitch, "onset": first * .01, "offset": stop * .01, "is_drum": False}
    truth, alternative = [], []
    if spec["kind"] in ("repeat", "change"):
        truth = [note(spec["pitch"], left, left + spec["frames"]),
                 note(spec["pitch"] + spec["interval"], left + spec["frames"] + spec["gap"], end)]
    elif spec["kind"] != "silence":
        truth = [note(spec["pitch"], left, end)]
    if spec["kind"] == "repeat" and not spec["gap"]:
        alternative = [note(spec["pitch"], left, end)]
    elif spec["kind"] == "dropout":
        middle = left + spec["frames"] // 2
        alternative = [note(spec["pitch"], left, middle), note(spec["pitch"], middle + spec["gap"], end)]
    return hz, total * .01, truth, alternative


def raw_labels(hz):
    raw = np.full(len(hz), -1, dtype=int)
    positive = hz > 0
    raw[positive] = np.rint(69 + 12 * np.log2(hz[positive] / 440.)).astype(int)
    result = np.full(len(hz), -1, dtype=int)
    index, state = 0, -1
    while index < len(hz):
        stop = index + 1
        while stop < len(hz) and raw[stop] == raw[index]:
            stop += 1
        pitch = int(raw[index])
        if pitch < 0:
            state = -1
        else:
            if state < 0 or pitch == state or stop - index >= 5:
                state = pitch
            result[index:stop] = state
        index = stop
    return result


def check_events(events, duration):
    previous_end = 0.
    for event in events:
        require(set(event) == {"pitch", "onset", "offset", "is_drum"}, "event_canonical_keys")
        require(type(event["pitch"]) is int and 0 <= event["pitch"] <= 127 and event["is_drum"] is False, "event_pitch_domain")
        require(all(type(event[key]) in (int, float) and math.isfinite(event[key]) for key in ("onset", "offset")), "event_finite_times")
        require(event["onset"] >= 0 and event["onset"] >= previous_end - 1e-10
                and event["offset"] <= duration + 1e-10
                and event["offset"] - event["onset"] >= .08 - 1e-10, "event_monophonic_duration")
        previous_end = event["offset"]


def direct_synthetic(events, truth):
    reference_intervals = np.asarray([(event["onset"], event["offset"]) for event in truth], dtype=float).reshape(-1, 2)
    reference_hz = np.asarray([440 * 2 ** ((event["pitch"] - 69) / 12) for event in truth])
    intervals = np.asarray([(event["onset"], event["offset"]) for event in events], dtype=float).reshape(-1, 2)
    hz = np.asarray([440 * 2 ** ((event["pitch"] - 69) / 12) for event in events])
    result = {}
    for metric, ratio in (("onset_f1", None), ("onset_offset_f1", .2)):
        pairs = transcription.match_notes(reference_intervals, reference_hz, intervals, hz,
            onset_tolerance=.05, pitch_tolerance=50., offset_ratio=ratio, offset_min_tolerance=.05) if events else []
        result[metric] = 2 * len(pairs) / (len(truth) + len(events))
    return result


def synthetic_comparison(row):
    old, new = row["arms"][G], row["arms"][NEW]
    result = {"baseline_arm": G, "candidate_arm": NEW,
        "predicted_notes_change": new["count"] - old["count"],
        "event_identity_unchanged": new["event_sha256"] == old["event_sha256"],
        "no_added_cuts": new["readout"]["applied_cut_count"] == 0,
        "onset_f1_change": None, "onset_offset_f1_change": None,
        "baseline_perfect": None, "candidate_perfect": None}
    if row["accuracy_eligible"]:
        for metric in METRICS:
            result[metric + "_change"] = new["metrics"][metric] - old["metrics"][metric]
        result["baseline_perfect"] = all(old["metrics"][metric] == 1. for metric in METRICS)
        result["candidate_perfect"] = all(new["metrics"][metric] == 1. for metric in METRICS)
    require(not result["no_added_cuts"] or result["event_identity_unchanged"], "synthetic_no_cut_byte_parity")
    return result


def synthetic_aggregate(rows):
    eligible = [row for row in rows if row["accuracy_eligible"]]
    result = {}
    for arm in SYN_ARMS:
        value = {"all_cases_predicted_notes": sum(row["arms"][arm]["count"] for row in rows),
            "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in rows),
            "silence_false_positive_notes": sum(row["arms"][arm]["count"] for row in rows if row["spec"]["kind"] == "silence"),
            "eligible_cases": len(eligible)}
        for metric in METRICS:
            value[metric] = math.fsum(row["arms"][arm]["metrics"][metric] for row in eligible) / len(eligible)
        if arm != "pitch_runs":
            diagnostics = [row["arms"][arm]["readout"]["readout"] if arm == NEW else row["arms"][arm]["diagnostics"] for row in rows]
            raw = sum(d["raw_voiced_frames"] for d in diagnostics)
            dropped = sum(d["raw_voiced_decoded_silent_frames" if arm == NEW else "raw_voiced_to_silent_frames"] for d in diagnostics)
            value.update(raw_voiced_frames=raw, raw_voiced_to_silent_frames=dropped, voiced_coverage=1 - dropped / raw)
        result[arm] = value
    return result


def synthetic_comparisons(rows):
    eligible = [row for row in rows if row["accuracy_eligible"]]
    controls = [row for row in rows if row["spec"]["kind"] == "change" and row["spec"]["interval"] == 1 and row["spec"]["gap"] == 0]
    same([row["id"] for row in controls], list(SEMITONE_IDS), "fixed_six_semitone_control_IDs")
    successes = [row for row in eligible if row["comparison"]["baseline_perfect"]]
    same(len(successes), 221, "frozen_221_G_success_population")
    result = {"all_cases": len(rows), "accuracy_eligible_cases": len(eligible),
        "ambiguous_cases": sum(row["spec"]["kind"] == "dropout" or (row["spec"]["kind"] == "repeat" and row["spec"]["gap"] == 0) for row in rows),
        "silence_cases": sum(row["spec"]["kind"] == "silence" for row in rows),
        "baseline_arm": G, "candidate_arm": NEW, "previous_gaussian_perfect_cases": len(successes),
        "previous_gaussian_perfect_case_ids": [row["id"] for row in successes],
        "damaged_previous_success_case_ids": [row["id"] for row in successes if not row["comparison"]["candidate_perfect"]],
        "no_added_cut_cases": sum(row["comparison"]["no_added_cuts"] for row in rows),
        "identical_event_cases": sum(row["comparison"]["event_identity_unchanged"] for row in rows),
        "joined_semitone_controls": [], "eligible_metric_changes": {}}
    same([result[key] for key in ("all_cases", "accuracy_eligible_cases", "ambiguous_cases", "silence_cases")], [245, 227, 15, 3], "synthetic_full_denominators")
    for row in controls:
        old, new = row["arms"][G], row["arms"][NEW]
        result["joined_semitone_controls"].append({"id": row["id"], "reference_notes": len(row["truth"]),
            "baseline_predicted_notes": old["count"], "candidate_predicted_notes": new["count"],
            "baseline_metrics": old["metrics"], "candidate_metrics": new["metrics"],
            "candidate_two_notes_pitch_onset_offset_correct": len(row["truth"]) == new["count"] == 2 and row["comparison"]["candidate_perfect"]})
    for metric in METRICS:
        values = [row["comparison"][metric + "_change"] for row in eligible]
        result["eligible_metric_changes"][metric] = {"macro_change": math.fsum(values) / len(values),
            "improved_cases": sum(value > 0 for value in values), "worse_cases": sum(value < 0 for value in values),
            "tied_cases": sum(value == 0 for value in values)}
    return result


def check_synthetic(report):
    rows = report["cases"]
    same(len(rows), 245, "synthetic_case_count")
    for row in rows:
        spec = row["spec"]
        hz, duration, truth, alternative = authored(spec)
        exact(truth, row["truth"], "regenerated_owned_truth")
        exact(alternative, row["alternative_truth"], "regenerated_ambiguous_truth")
        same(duration, row["duration_seconds"], "owned_input_duration")
        same({"dtype": hz.dtype.str, "shape": list(hz.shape), "sha256": digest(hz.tobytes())}, row["observation"], "regenerated_245_raw_input_hashes")
        ambiguous = spec["kind"] == "dropout" or (spec["kind"] == "repeat" and spec["gap"] == 0)
        same(row["accuracy_eligible"], not ambiguous and spec["kind"] != "silence", "synthetic_eligibility")
        require(set(row["arms"]) == set(SYN_ARMS), "synthetic_all_eight_arms")
        for arm in SYN_ARMS:
            item = row["arms"][arm]
            check_events(item["events"], duration)
            same(len(item["events"]), item["count"], "synthetic_event_count")
            same(digest(canonical_events(item["events"])), item["event_sha256"], "synthetic_canonical_event_hash")
            same(item["metrics"], direct_synthetic(item["events"], truth) if row["accuracy_eligible"] else None, "synthetic_direct_mir_eval_scores")
        new, old = row["arms"][NEW], row["arms"][G]
        check_readout(new["readout"], old["diagnostics"], duration)
        same(new["shared_state_path"], old["state_path"], "synthetic_shared_G_path_hash")
        same(new["shared_state_path_arm"], G, "synthetic_shared_G_path_name")
        labels = raw_labels(hz)
        cuts = [i for i in range(1, len(labels)) if labels[i - 1] >= 0 and labels[i] >= 0 and labels[i - 1] != labels[i]]
        same(new["readout"]["candidate_cut_count"], len(cuts), "independent_owned_candidate_cut_count")
        same(new["readout"]["candidate_cut_frames_sha256"], fingerprint(cuts), "independent_owned_candidate_cut_hash")
        same(new["readout"]["raw_hysteresis_label_identity"], {"dtype": str(labels.dtype), "shape": list(labels.shape), "sha256": digest(labels.tobytes())}, "independent_owned_raw_hysteresis_hash")
        for event in new["events"]:
            require(sum(parent["onset"] <= event["onset"] + 1e-10 and event["offset"] <= parent["offset"] + 1e-10
                        for parent in old["events"]) == 1, "new_emitted_interval_inside_one_G_event")
        same(row["comparison"], synthetic_comparison(row), "independent_synthetic_case_comparison")
    aggregate, comparisons = synthetic_aggregate(rows), synthetic_comparisons(rows)
    same(report["aggregate"], aggregate, "independent_eight_arm_synthetic_aggregate")
    same(report["comparisons"], comparisons, "independent_synthetic_control_and_harm_summary")
    manifest = fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in SYN_ARMS} for row in rows})
    same(report["predictions_manifest_sha256"], manifest, "synthetic_all_1960_pretruth_manifest")
    same(report["post_evaluation_predictions_manifest_sha256"], manifest, "synthetic_all_1960_postscore_manifest")
    return aggregate, comparisons


def check_historical(corpus, synthetic, legacy_corpus, legacy_synthetic, old_reports, frozen_map):
    old_corpus, old_synthetic, old_diagnostics = (old_reports[name] for name in ("vocadito.json", "synthetic.json", "diagnostics.json"))
    ignored = {"python", "platform", "runtime", "source_revision", "protocol_head_revision", "elapsed_seconds", "peak_rss_kib", "cases"}
    exact({key: value for key, value in legacy_corpus.items() if key not in ignored},
          {key: value for key, value in old_corpus.items() if key not in ignored}, "old_corpus_scientific_contract_exact")
    same([row["id"] for row in legacy_corpus["cases"]], list(CASES), "old_corpus_ordered_population")
    for current, projected, old in zip(corpus["cases"], legacy_corpus["cases"], old_corpus["cases"], strict=True):
        stripped = {key: value for key, value in current.items() if key not in
                    {"readout", "readout_private_sha256", "annotation_diagnostics", "annotation_private_sha256"}}
        stripped["arms"] = {arm: current["arms"][arm] for arm in OLD_ARMS}
        exact(stripped, projected, "all_400_legacy_arm_projection_file_bound")
        volatile = {"observation_sha256", "inference_seconds"}
        exact({key: value for key, value in projected.items() if key not in volatile},
              {key: value for key, value in old.items() if key not in volatile}, "all_400_events_440_arrays_and_scores_historical_exact")
    volatile = {"source_revision", "protocol_head_revision", "elapsed_seconds"}
    exact({key: value for key, value in legacy_synthetic.items() if key not in volatile},
          {key: value for key, value in old_synthetic.items() if key not in volatile}, "all_1715_events_245_inputs_1470_paths_historical_exact")
    projected_rows = []
    for row, old in zip(synthetic["cases"], old_synthetic["cases"], strict=True):
        projected = {key: row[key] for key in old if key != "arms"}
        projected["arms"] = {arm: row["arms"][arm] for arm in SYN_OLD}
        projected_rows.append(projected)
    projected = {key: synthetic[key] for key in legacy_synthetic if key not in
                 {"schema", "planned_arms", "cases", "aggregate", "predictions_manifest_sha256", "elapsed_seconds"}}
    projected.update(schema="note-state-synthetic-v1", planned_arms=list(SYN_OLD), cases=projected_rows,
        aggregate={arm: synthetic["aggregate"][arm] for arm in SYN_OLD},
        predictions_manifest_sha256=fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in SYN_OLD} for row in synthetic["cases"]}))
    exact(projected, {key: value for key, value in legacy_synthetic.items() if key != "elapsed_seconds"}, "actual_legacy_synthetic_file_bound_to_projection")
    require(type(legacy_synthetic["elapsed_seconds"]) in (int, float) and legacy_synthetic["elapsed_seconds"] >= 0, "legacy_synthetic_elapsed")
    same(len(old_diagnostics["source_sha256"]), 35, "previous_35_source_inventory")
    for name, sha in old_diagnostics["source_sha256"].items():
        same(frozen_map[name], sha, "all_35_previously_frozen_sources_unchanged")
    expected_corpus_parity = {"baseline_zip_sha256": OLD_SHA,
        "source_checks": {name: True for name in old_diagnostics["source_sha256"]},
        "compared_prediction_files": 400, "compared_observation_arrays": 440,
        "all_equal": True, "differences": [], "raw_historical_arrays_available": False, "array_identity_available": True}
    same(corpus["historical_parity"], expected_corpus_parity, "corpus_historical_parity_recomputed")
    same(synthetic["historical_parity"], {"baseline_zip_sha256": OLD_SHA, "compared_prediction_files": 1715,
        "compared_input_arrays": 245, "compared_state_paths": 1470, "all_equal": True, "differences": []}, "synthetic_historical_parity_recomputed")
    counts = {"corpus_prediction_identities": sum(len(row["arms"]) for row in legacy_corpus["cases"]),
        "corpus_observation_identities": sum(len(row["observations"]) for row in legacy_corpus["cases"]),
        "synthetic_prediction_identities": sum(len(row["arms"]) for row in legacy_synthetic["cases"]),
        "synthetic_input_identities": len(legacy_synthetic["cases"]),
        "synthetic_path_identities": sum("state_path" in item for row in legacy_synthetic["cases"] for item in row["arms"].values())}
    same(list(counts.values()), [400, 440, 1715, 245, 1470], "complete_historical_identity_denominators")
    return counts


def check_numerical_preflight(corpus, synthetic, private_audit, previous, repository, frozen_map):
    """Bind declared Actions process facts; do not substitute this host's CPU."""
    recorded = corpus["numerical_environment"]
    require(set(recorded) == {"python", "executable", "platform", "numpy_version", "numpy_file", "runtime",
                              "cpu_features", "cpu_baseline", "cpu_dispatch", "numpy_disable_cpu_features"}, "numeric_environment_fields")
    same(synthetic["numerical_environment"], recorded, "same_corpus_synthetic_numeric_environment")
    same(private_audit["numerical_environment"], recorded, "private_audit_observed_numeric_environment_binding")
    require(type(recorded["python"]) is str and recorded["python"].startswith("3.11."), "Actions_python311_declared")
    same(recorded["numpy_version"], "1.26.4", "Actions_numpy1264_declared")
    same(recorded["runtime"], EXPECTED_RUNTIME, "Actions_eight_pinned_versions_declared")
    for key in ("executable", "numpy_file"):
        require(isinstance(recorded[key], str) and recorded[key].startswith("/"), "Actions_module_path_declared")
    require(isinstance(recorded["platform"], str) and bool(recorded["platform"]), "Actions_platform_declared")
    require(isinstance(recorded["cpu_features"], dict) and recorded["cpu_features"]
            and all(type(key) is str and type(value) is bool for key, value in recorded["cpu_features"].items()), "Actions_CPU_feature_types")
    for key in ("cpu_baseline", "cpu_dispatch"):
        require(isinstance(recorded[key], list) and all(type(value) is str for value in recorded[key])
                and len(recorded[key]) == len(set(recorded[key])), "Actions_CPU_dispatch_list")
    require(recorded["numpy_disable_cpu_features"] is None or type(recorded["numpy_disable_cpu_features"]) is str,
            "Actions_raw_disable_environment_type")
    raw_manifest = (repository / NUMERIC_MANIFEST).read_bytes()
    same(digest(raw_manifest), NUMERIC_MANIFEST_SHA, "fixed_input_only_manifest_SHA256")
    same(frozen_map[NUMERIC_MANIFEST], NUMERIC_MANIFEST_SHA, "frozen_input_only_manifest_binding")
    manifest = parsed(raw_manifest)
    expected = {"schema": "note-boundary-readout-numeric-inputs-v1", "baseline_zip_sha256": OLD_SHA,
        "cases": [{key: row[key] for key in ("id", "duration_seconds", "observation")} for row in previous["cases"]],
        "emission_analysis": previous["emission_analysis"]}
    exact(manifest, expected, "input_only_manifest_exact_original_receipt_projection")
    same(len(manifest["cases"]), 245, "input_only_245_case_denominator")
    same(len(manifest["emission_analysis"]), 20, "input_only_20_analytic_denominator")
    exact([{key: row[key] for key in ("id", "duration_seconds", "observation")} for row in synthetic["cases"]],
          manifest["cases"], "predictions_used_preflight_input_identities")
    exact(synthetic["emission_analysis"], manifest["emission_analysis"], "predictions_used_preflight_analytic_table")
    preflight = {"manifest_sha256": NUMERIC_MANIFEST_SHA, "compared_input_arrays": 245,
        "compared_analytic_rows": 20, "all_equal": True, "input_differences": [],
        "analytic_difference_paths": [], "model_calls_before_preflight": 0}
    same(synthetic["preflight"], preflight, "input_only_preflight_success_contract")
    same(private_audit["preflight"], preflight, "private_audit_preflight_binding")
    return recorded, preflight


def audit_zip(artifact, expected_sha, expected_bytes, repository, frozen_head, source_map, run_id):
    started = time.monotonic()
    same(np.__version__, "1.26.4", "pinned_numpy_for_owned_input_hashes")
    same(mir_eval.__version__, "0.8.2", "pinned_mir_eval")
    raw = artifact.read_bytes()
    same(len(raw), expected_bytes, "original_Actions_ZIP_byte_count")
    same(digest(raw), expected_sha, "original_Actions_ZIP_SHA256")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        same(sorted(archive.namelist()), sorted(MEMBERS), "exact_six_public_ZIP_members")
        require(all(not member.is_dir() and member.file_size < 64_000_000 for member in archive.infolist()), "bounded_public_ZIP_members")
        payloads = {name: archive.read(name) for name in MEMBERS}
    reports = {name: parsed(payload) for name, payload in payloads.items()}
    corpus, synthetic = reports["vocadito.json"], reports["synthetic.json"]
    legacy_corpus, legacy_synthetic = reports["legacy-vocadito.json"], reports["legacy-synthetic.json"]
    old_audit, private_audit = reports["legacy-audit.json"], reports["audit.json"]
    for report in (corpus, synthetic, legacy_corpus, legacy_synthetic):
        same(report["status"], "complete", "complete_execution_report")
        same(report["protocol_head_revision"], frozen_head, "frozen_PR_head_binding")
        same(report["source_revision"], corpus["source_revision"], "common_execution_checkout")
        same(report["quality_approved"], False, "no_product_approval")
        same(report["heldout_generalization"], False, "development_reuse_declared")
    for report in (old_audit, private_audit):
        same(report["status"], "pass", "completed_private_audit")
        same(report["audit_completed"], True, "completed_private_audit")
    same(corpus["schema"], "note-boundary-readout-v1", "corpus_schema")
    same(synthetic["schema"], "note-boundary-readout-synthetic-v1", "synthetic_schema")
    same(corpus["planned_case_ids"], list(CASES), "planned_forty_recordings")
    same(corpus["planned_arms"], list(ARMS), "planned_eleven_arms")
    same(synthetic["planned_arms"], list(SYN_ARMS), "planned_eight_synthetic_arms")
    for key, value in {"all_cases_complete": True, "reference_used_for_edits": False, "product_changes": False,
                       "all_predictions_frozen_before_references": True, "reference_access_started_after_predicted_cases": 40,
                       "device": "cpu", "threads": 2}.items():
        same(corpus[key], value, "corpus_frozen_execution_contract")
    for key, value in {"planned_cases": 245, "acoustic_extraction": False, "product_changes": False,
                       "all_predictions_saved_before_scoring": True, "truth_access_started_after_prediction_files": 1960}.items():
        same(synthetic[key], value, "synthetic_frozen_execution_contract")
    source_bytes = source_map.read_bytes()
    frozen = parsed(source_bytes)
    same(len(frozen), 53, "independently_recorded_frozen_source_count")
    for report in (corpus, synthetic, private_audit):
        exact(report["source_sha256"], frozen, "independently_recorded_source_map_binding")
    for name, sha in frozen.items():
        file = repository / name
        require(not file.is_symlink() and file.is_file() and file.resolve().is_relative_to(repository.resolve()), "frozen_source_path_domain")
        same(digest(file.read_bytes()), sha, "frozen_source_file_identity")
    same(old_audit["report_sha256"], digest(payloads["legacy-vocadito.json"]), "legacy_private_audit_exact_file_binding")
    same(corpus["legacy_report_sha256"], digest(payloads["legacy-vocadito.json"]), "corpus_legacy_projection_file_binding")
    for key, name in {"report_sha256": "vocadito.json", "synthetic_report_sha256": "synthetic.json",
                      "legacy_report_sha256": "legacy-vocadito.json", "legacy_audit_sha256": "legacy-audit.json"}.items():
        same(private_audit[key], digest(payloads[name]), "new_private_audit_exact_input_binding")
    same(private_audit["script_sha256"], frozen["scripts/audit_note_boundary_readout.py"], "new_private_auditor_source_binding")
    same(old_audit["script_sha256"], frozen["scripts/audit_note_state_factors.py"], "legacy_private_auditor_source_binding")
    for key, value in {"source_files_verified": 53, "corpus_prediction_files_verified": 440,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1960, "synthetic_input_arrays_verified": 245,
        "synthetic_old_state_paths_verified": 1470, "independent_new_readouts_verified": 285,
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0}.items():
        same(private_audit[key], value, "private_audit_scope_binding")
    old_bytes = (repository / "docs/research/receipts/note-boundary-diagnostics-43370790419.zip").read_bytes()
    same(digest(old_bytes), OLD_SHA, "original_295_artifact_identity")
    with zipfile.ZipFile(io.BytesIO(old_bytes)) as archive:
        old_reports = {name: parsed(archive.read(name)) for name in ("vocadito.json", "synthetic.json", "diagnostics.json")}
    numerical_environment, preflight = check_numerical_preflight(
        corpus, synthetic, private_audit, old_reports["synthetic.json"], repository, frozen)
    history = check_historical(corpus, synthetic, legacy_corpus, legacy_synthetic, old_reports, frozen)
    rows = corpus["cases"]
    same([row["id"] for row in rows], list(CASES), "complete_ordered_forty_recordings")
    old_diagnostics = {row["id"]: row for row in old_reports["diagnostics.json"]["corpus"]["cases"]}
    for row in rows:
        same(row["status"], "scored", "all_corpus_cases_scored")
        require(set(row["arms"]) == set(ARMS), "all_eleven_corpus_arms_present")
        require(set(row["annotation_diagnostics"]) == set(ANN), "both_annotation_diagnostics_present")
        for arm in ARMS:
            require(set(row["arms"][arm]["annotators"]) == set(ANN), "both_annotation_metrics_present")
        for ann in ANN:
            check_corpus_counts(row, ann)
            for arm in ("pitch_runs", G, "note_state_hmm"):
                current = row["annotation_diagnostics"][ann]["arms"][arm]
                old = old_diagnostics[row["id"]]["annotators"][ann]["arms"][arm]
                exact(current, {key: old[key] for key in current}, "unchanged_old_fixed_pair_diagnostics")
        check_readout(row["readout"], row["diagnostics"]["factors"][G], row["duration_seconds"])
        same(row["readout"]["readout"]["emitted_notes"], row["arms"][NEW]["count"], "new_readout_event_count")
        if row["readout"]["applied_cut_count"] == 0:
            same(row["arms"][NEW]["event_sha256"], row["arms"][G]["event_sha256"], "corpus_no_cut_event_identity")
    manifest = fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in ARMS} for row in rows})
    same(corpus["predictions_manifest_sha256"], manifest, "corpus_all440_pre_reference_manifest")
    same(corpus["post_evaluation_predictions_manifest_sha256"], manifest, "corpus_all440_post_evaluation_manifest")
    aggregate, primary = aggregate_corpus(rows), primary_corpus(rows)
    same(corpus["aggregate"], aggregate, "independent_all_eleven_corpus_aggregates")
    same(corpus["primary_result"], primary, "independent_seed296_recording_bootstrap")
    same(private_audit["corpus"]["aggregate"], aggregate, "private_corpus_aggregate_binding")
    same(private_audit["corpus"]["primary_result"], primary, "private_primary_result_binding")
    boundary = corpus["boundary_summary"]
    for ann in ANN:
        combine_public(boundary["by_annotator"][ann], [row["annotation_diagnostics"][ann] for row in rows])
    pooled = boundary["pooled_annotation_judgments"]
    combine_public(pooled, [row["annotation_diagnostics"][ann] for row in rows for ann in ANN])
    same(private_audit["corpus"]["boundary_summary"], boundary, "private_pooled_diagnostic_binding")
    synthetic_aggregate_value, comparisons = check_synthetic(synthetic)
    same(private_audit["synthetic"]["aggregate"], synthetic_aggregate_value, "private_synthetic_aggregate_binding")
    same(private_audit["synthetic"]["comparisons"], comparisons, "private_synthetic_comparison_binding")
    return {"schema": "note-boundary-readout-public-postrun-audit-v1", "status": "pass", "audit_completed": True,
        "run_id": run_id, "frozen_protocol_head": frozen_head, "execution_checkout": corpus["source_revision"],
        "artifact_sha256": expected_sha, "artifact_bytes": expected_bytes,
        "members": {name: {"bytes": len(payload), "sha256": digest(payload)} for name, payload in payloads.items()},
        "frozen_source_map_sha256": digest(source_bytes), "frozen_source_files_verified": 53,
        "Actions_numerical_environment_bound_to_private_audit": numerical_environment, "input_only_preflight": preflight,
        "script_sha256": digest(Path(__file__).read_bytes()),
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "mir_eval": mir_eval.__version__},
        "checks_passed": sum(CHECKS.values()), "checks_by_kind": dict(sorted(CHECKS.items())),
        "maximum_numeric_difference": MAX_DIFF, "historical_identity_counts": history,
        "corpus_prediction_identities_checked": 440, "corpus_annotation_score_rows_checked": 880,
        "synthetic_event_payloads_and_hashes_checked": 1960, "synthetic_eligible_score_pairs_recomputed": 1816,
        "owned_raw_input_arrays_regenerated_and_hashed": 245,
        "primary_result": primary,
        "corpus_macro": {arm: {"predicted_notes": aggregate[arm]["predicted_notes"],
            **{metric: aggregate[arm][metric]["macro"] for metric in METRICS}} for arm in ARMS},
        "corpus_matched_annotation_judgments": {arm: {key: pooled["arms"][arm][key] for key in ("onset_matched", "offset_matched")} for arm in DIAGNOSTIC_ARMS},
        "corpus_reference_partitions_recomputed": pooled["comparisons"],
        "corpus_pruning_harm_public_counts_summed": pooled["pruning_harm"],
        "corpus_readout_public_counts_summed": readout_totals([row["readout"] for row in rows]),
        "synthetic_aggregate": synthetic_aggregate_value,
        "synthetic_comparisons": {key: value for key, value in comparisons.items() if key != "previous_gaussian_perfect_case_ids"},
        "previous_221_success_IDs_sha256": fingerprint(comparisons["previous_gaussian_perfect_case_ids"]),
        "synthetic_readout_public_counts_summed": readout_totals([row["arms"][NEW]["readout"] for row in synthetic["cases"]]),
        "private_audit_checks_bound": {"legacy": old_audit["checks_passed"], "new": private_audit["checks_passed"]},
        "neural_model_calls": 0, "pyin_calls": 0, "decoder_calls": 0, "new_prediction_files_generated": 0,
        "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "The original six-member Actions ZIP is checked byte-for-byte and every member is hashed; it is never recompressed.",
            "The recovery input-only manifest is verified as an exact projection of the original245 input identities and20 analytic rows. It contains no event predictions, truth, metrics or private human references.",
            "Actions Python, pinned versions, module paths and NumPy CPU dispatch are checked as declared metadata and bound to the private auditor's observed process facts. This postrun machine is not claimed to be the Actions machine, and no CPU feature is forced or disabled.",
            "Corpus F1, precision/recall, macro and paired bootstrap are recomputed from public match counts and scores, not from private human note CSVs or audio.",
            "G-versus-new and runs-versus-new retained/gained/lost counts are reconstructed from each arm's published runs-relative reference-ID sets and the runs matched count.",
            "Actual corpus event arrays, parent/child traces, matched-pair residuals and raw G paths are private. Their independent reconstruction is supplied by the hash-bound private Actions audit, not this public checker.",
            "Pooled residual counts, extrema and means are checked from per-case summaries; pooled quantiles cannot be independently recovered without original private samples.",
            "Pruning totals and harm count sums are checked for arithmetic and subset consistency; the individual reference-to-parent damage links cannot be recomputed from public summaries.",
            "All 245 owned raw inputs and truth variants are regenerated in NumPy1.26.4 and input hashes checked. All1960 owned event payloads are hashed; 227x8 eligible score pairs are directly rescored with mir_eval0.8.2.",
            "Synthetic global raw hysteresis labels and candidate-cut hashes are reconstructed. Complete G paths and prefilter parent traces are not public, so the full new path-to-event readout is not reconstructed here.",
            "Direct mir_eval is another invocation of the same matching implementation. Neither reused development material nor these audits establish heldout generalization or product readiness.",
            "Metadata and hashes cannot independently prove past reference-access order; the frozen runner, barrier tests and workflow provide complementary evidence.",
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact", "repository", "source-map", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", required=True, type=int)
    parser.add_argument("--frozen-head", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("new postrun receipt path required")
    try:
        result = audit_zip(args.artifact, args.expected_sha256, args.expected_bytes,
                           args.repository, args.frozen_head, args.source_map, args.run_id)
    except Exception as exc:
        result = {"schema": "note-boundary-readout-public-postrun-audit-v1", "status": "failed", "audit_completed": False,
                  "error_type": type(exc).__name__, "error": str(exc), "checks_passed": sum(CHECKS.values()),
                  "maximum_numeric_difference": MAX_DIFF, "script_sha256": digest(Path(__file__).read_bytes())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"],
                      "maximum_numeric_difference": result["maximum_numeric_difference"], "error": result.get("error")}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
