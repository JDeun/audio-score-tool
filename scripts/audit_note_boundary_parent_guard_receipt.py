"""Audit the downloaded #298 public receipt without inference or private audio.

The reusable parsers and arithmetic checks come from the prior public auditor.
New guard arithmetic, both comparisons, seed298 bootstrap and stress generation
are independently expressed here. Private parent mappings, G paths and residual
samples remain covered by the hash-bound Actions audits, not this public check.
"""
from __future__ import annotations

import argparse
import io
import itertools
import json
import math
import platform
import time
import zipfile
from pathlib import Path

import mir_eval
import mir_eval.transcription as transcription
import numpy as np

from scripts import audit_note_boundary_readout_receipt as prior

MEMBERS = ("synthetic.json", "legacy-synthetic.json", "vocadito.json",
           "legacy-vocadito.json", "legacy-factor-vocadito.json",
           "legacy-factor-audit.json", "legacy-audit.json", "audit.json")
PREVIOUS = "docs/research/receipts/note-boundary-readout-43381098932-attempt-1.zip"
PREVIOUS_SHA = "f34e88d2b5023df5762fba46b4149167265efbd24a837d30500375b30cd5758f"
NUMERIC_MANIFEST = "docs/research/NOTE_BOUNDARY_PARENT_GUARD_NUMERIC_INPUTS_2026-11-13.json"
NUMERIC_SHA = "faadd9f40129dbc2801c4e283b2d2946112113362d4786cc8be6cb731f8e6e6c"
G, SPLIT = prior.G, prior.NEW
NEW = "gaussian_raw_hysteresis_parent_guard"
ARMS, SYN_ARMS = (*prior.ARMS, NEW), (*prior.SYN_ARMS, NEW)
CASES, ANN, METRICS, CRITERIA = prior.CASES, prior.ANN, prior.METRICS, prior.CRITERIA
DIAGNOSTIC_ARMS = ("pitch_runs", G, SPLIT, "note_state_hmm", NEW)
COHORTS = ("legacy", "single_expression", "adjacent_semitone")
ROW_ADDITIONS = {"guard", "guard_private_sha256", "guard_annotation_diagnostics",
                 "guard_annotation_private_sha256"}
HARM = ("lost_references", "lost_matched_parent_proposed_cut", "lost_matched_parent_accepted",
        "lost_matched_parent_rejected", "lost_matched_parent_with_proposed_short_children",
        "lost_matched_parent_all_proposed_children_fail", "lost_matched_parent_final_empty")
FRAME_FIELDS = ("frames", "raw_voiced_frames", "decoded_voiced_frames", "attack_frames",
                "stable_frames", "silent_frames", "decoded_voiced_over_raw_unvoiced_frames",
                "raw_voiced_decoded_silent_frames")
GUARD_COUNTS = ("candidate_cut_count", "parent_segment_count", "originally_emitted_parent_count",
    "originally_nonemitted_parent_count", "proposed_parent_count", "proposed_cut_count",
    "proposed_child_count", "accepted_parent_count", "accepted_cut_count", "accepted_child_count",
    "rejected_parent_count", "restored_original_event_count", "unchanged_original_event_count",
    "final_segment_count", "originally_emitted_parents_all_children_pruned",
    "nonemitted_parents_resurrected", "baseline_interval_union_count", "output_interval_union_count")
TIMING = {
    "frame_seconds": .01, "leading_silence_frames": 10, "trailing_silence_intervals": 10,
    "sample_count": "voiced_frames + 21", "voiced_frame_interval": "[10, 10 + voiced_frames)",
    "duration_seconds": "(voiced_frames + 20) * 0.01",
    "terminal_sample": "zero Hz at duration; no extra audio interval",
    "modulation_time": "local voiced integer frame * 0.01; phase 0",
    "adjacent_change_frame": "10 + voiced_frames // 2; continuous modulation phase",
    "hz_conversion": "440 * 2 ** ((fractional_midi - 69) / 12)",
    "audio_duration_clipping": "unchanged frozen readout",
}
require, same, exact = prior.require, prior.same, prior.exact
digest, parsed, fingerprint, count = prior.digest, prior.parsed, prior.fingerprint, prior.count


def interval_union(events):
    merged = []
    for event in sorted(events, key=lambda value: (value["onset"], value["offset"])):
        a, b = event["onset"], event["offset"]
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a, b])
    return merged


def check_guard(value, original, duration):
    require(set(value) == set(GUARD_COUNTS) | {
        "schema_version", "rejected_parent_reason_counts", "baseline", "readout", "proposed",
        "baseline_emitted_seconds", "emitted_seconds", "emitted_seconds_change",
        "baseline_emitted_coverage_fraction", "emitted_coverage_fraction",
        "baseline_interval_union_seconds", "output_interval_union_seconds",
        "baseline_interval_union_sha256", "output_interval_union_sha256", "output_interval_union_preserved",
        "proposed_child_seconds_summary", "proposed_child_midi_median_summary",
        "proposed_child_raw_voiced_frames_summary", "final_emitted_seconds_summary",
        "candidate_cut_frames_sha256", "proposed_cut_frames_sha256", "accepted_cut_frames_sha256",
        "raw_hysteresis_label_identity", "trace_sha256"}, "public_guard_exact_field_inventory")
    for key in GUARD_COUNTS:
        count(value[key], "guard_nonnegative_count")
    same(value["schema_version"], 1, "guard_schema")
    same(value["originally_emitted_parent_count"] + value["originally_nonemitted_parent_count"],
         value["parent_segment_count"], "original_parent_partition")
    same(value["accepted_parent_count"] + value["rejected_parent_count"],
         value["proposed_parent_count"], "all_or_nothing_parent_partition")
    same(value["proposed_child_count"], value["proposed_cut_count"] + value["proposed_parent_count"],
         "proposed_children_cut_conservation")
    same(value["accepted_child_count"], value["accepted_cut_count"] + value["accepted_parent_count"],
         "accepted_children_cut_conservation")
    same(value["final_segment_count"], value["parent_segment_count"] + value["accepted_cut_count"],
         "final_parent_child_conservation")
    same(value["restored_original_event_count"], value["rejected_parent_count"], "whole_parent_restoration")
    same(value["unchanged_original_event_count"] + value["proposed_parent_count"],
         value["originally_emitted_parent_count"], "emitted_parent_decision_partition")
    require(value["accepted_cut_count"] <= value["proposed_cut_count"] <= value["candidate_cut_count"],
            "cut_acceptance_subset")
    require(value["accepted_parent_count"] <= value["accepted_cut_count"]
            and value["proposed_parent_count"] <= value["proposed_cut_count"], "nonempty_proposals")
    same(value["originally_emitted_parents_all_children_pruned"], 0, "no_whole_original_parent_loss")
    same(value["nonemitted_parents_resurrected"], 0, "no_nonemitted_parent_resurrection")
    reasons = value["rejected_parent_reason_counts"]
    require(set(reasons) == {"short", "no_raw_support", "zero_duration"}, "rejection_reason_inventory")
    require(all(count(number, "rejection_reason_count") <= value["rejected_parent_count"]
                for number in reasons.values()), "rejection_reason_subset")
    require(sum(reasons.values()) >= value["rejected_parent_count"], "every_rejection_has_reason")
    same(value["baseline"], {key: original[key] for key in value["baseline"]},
         "guard_original_G_readout_preserved")
    baseline, final, proposal = (value[name] for name in ("baseline", "readout", "proposed"))
    same(baseline["segments_before_filter"], value["parent_segment_count"], "baseline_parent_count")
    same(baseline["emitted_notes"], value["originally_emitted_parent_count"], "baseline_emitted_parent_count")
    same(final["segments_before_filter"], value["final_segment_count"], "final_segment_count")
    same(proposal["segments_before_filter"], value["proposed_child_count"], "proposal_segment_count")
    same(final["emitted_notes"], baseline["emitted_notes"] + value["accepted_cut_count"],
         "final_emitted_event_conservation")
    require(proposal["emitted_notes"] >= value["accepted_child_count"], "accepted_children_pass_readout")
    for name, diag in (("baseline", baseline), ("readout", final), ("proposed", proposal)):
        require(set(diag) == set(baseline), "shared_readout_diagnostic_inventory")
        same({key: diag[key] for key in FRAME_FIELDS}, {key: baseline[key] for key in FRAME_FIELDS},
             "unchanged_support_" + name)
        same(sum(diag[key] for key in ("emitted_notes", "short_segments_discarded",
             "zero_duration_segments", "segments_without_raw_voiced_support")),
             diag["segments_before_filter"], "readout_disposition_partition")
        same(diag["attack_frames"] + diag["stable_frames"], diag["decoded_voiced_frames"], "phase_voiced_count")
        same(diag["decoded_voiced_frames"] + diag["silent_frames"], diag["frames"], "phase_frame_count")
        require(diag["emitted_notes_with_raw_unvoiced_frames"] <= diag["emitted_notes"], "raw_bridge_subset")
    for key in ("short_segments_discarded", "short_segments_discarded_seconds",
                "zero_duration_segments", "segments_without_raw_voiced_support"):
        same(final[key], baseline[key], "final_pruning_unchanged_from_original_G")
    same(value["baseline_emitted_seconds"], baseline["emitted_note_seconds"], "baseline_seconds_binding")
    same(value["emitted_seconds"], final["emitted_note_seconds"], "final_seconds_binding")
    same(value["emitted_seconds_change"], value["emitted_seconds"] - value["baseline_emitted_seconds"],
         "emitted_seconds_delta_arithmetic")
    same(value["emitted_seconds"], value["baseline_emitted_seconds"], "interval_conservation_seconds")
    same(value["baseline_emitted_coverage_fraction"],
         value["baseline_emitted_seconds"] / duration if duration else 0., "baseline_coverage_arithmetic")
    same(value["emitted_coverage_fraction"],
         value["emitted_seconds"] / duration if duration else 0., "final_coverage_arithmetic")
    same(value["output_interval_union_preserved"], True, "interval_union_contract")
    same(value["output_interval_union_count"], value["baseline_interval_union_count"], "interval_union_count")
    same(value["output_interval_union_seconds"], value["baseline_interval_union_seconds"], "interval_union_seconds")
    same(value["output_interval_union_sha256"], value["baseline_interval_union_sha256"], "interval_union_hash")
    for key in ("baseline_interval_union_sha256", "output_interval_union_sha256",
                "candidate_cut_frames_sha256", "proposed_cut_frames_sha256",
                "accepted_cut_frames_sha256", "trace_sha256"):
        require(isinstance(value[key], str) and len(value[key]) == 64
                and all(character in "0123456789abcdef" for character in value[key]), "guard_SHA256_domain")
    prior.check_distribution(value["proposed_child_seconds_summary"], value["proposed_child_count"])
    prior.check_distribution(value["proposed_child_raw_voiced_frames_summary"], value["proposed_child_count"])
    prior.check_distribution(value["proposed_child_midi_median_summary"])
    require(value["proposed_child_midi_median_summary"]["count"] <= value["proposed_child_count"],
            "proposed_pitch_support_denominator")
    prior.check_distribution(value["final_emitted_seconds_summary"], final["emitted_notes"])


def guard_totals(values):
    result = {key: sum(value[key] for value in values) for key in GUARD_COUNTS}
    for key in ("baseline_emitted_seconds", "emitted_seconds", "emitted_seconds_change",
                "baseline_interval_union_seconds", "output_interval_union_seconds"):
        result[key] = math.fsum(value[key] for value in values)
    result["rejected_parent_reason_counts"] = {
        key: sum(value["rejected_parent_reason_counts"][key] for value in values)
        for key in ("short", "no_raw_support", "zero_duration")}
    for group in ("baseline", "proposed", "readout"):
        result[group] = {key: sum(value[group][key] for value in values)
            for key in ("segments_before_filter", "emitted_notes", "short_segments_discarded",
                        "zero_duration_segments", "segments_without_raw_voiced_support")}
        for key in ("short_segments_discarded_seconds", "emitted_note_seconds"):
            result[group][key] = math.fsum(value[group][key] for value in values)
    result["empty_final_outputs"] = sum(value["readout"]["emitted_notes"] == 0 for value in values)
    return result


def corpus_partitions(row, annotator):
    reference_count = row["arms"]["pitch_runs"]["annotators"][annotator]["reference_note_count"]
    result = {base: {} for base in (G, SPLIT)}
    for criterion in CRITERIA:
        run_matches = row["arms"]["pitch_runs"]["annotators"][annotator][criterion + "_matched"]
        gains, losses = {}, {}
        for arm in ARMS:
            metrics = row["arms"][arm]["annotators"][annotator]
            gains[arm] = prior.reference_ids(metrics[criterion + "_gained_reference_ids"], reference_count)
            losses[arm] = prior.reference_ids(metrics[criterion + "_lost_reference_ids"], reference_count)
            require(not gains[arm] & losses[arm], "disjoint_runs_relative_gain_loss")
            same(metrics[criterion + "_matched"], run_matches + len(gains[arm]) - len(losses[arm]),
                 "match_count_from_runs_relative_sets")
        require(not gains["pitch_runs"] and not losses["pitch_runs"], "empty_runs_self_difference")
        inside, outside = set().union(*losses.values()), set().union(*gains.values())
        require(not inside & outside and len(inside) <= run_matches
                and len(outside) <= reference_count - run_matches, "common_runs_reference_membership")
        for base in (G, SPLIT):
            retained = run_matches - len(losses[base] | losses[NEW]) + len(gains[base] & gains[NEW])
            gained = len(losses[base] - losses[NEW]) + len(gains[NEW] - gains[base])
            lost = len(losses[NEW] - losses[base]) + len(gains[base] - gains[NEW])
            partition = {"retained": retained, "gained": gained, "lost": lost,
                         "neither": reference_count - retained - gained - lost}
            require(all(number >= 0 for number in partition.values()), "guard_reference_partition_nonnegative")
            same(retained + gained, row["arms"][NEW]["annotators"][annotator][criterion + "_matched"],
                 "guard_reference_partition_matches")
            same(retained + lost, row["arms"][base]["annotators"][annotator][criterion + "_matched"],
                 "baseline_reference_partition_matches")
            result[base][criterion] = partition
    return result


def check_corpus_annotation(row, annotator):
    reference_count = count(row["arms"]["pitch_runs"]["annotators"][annotator]["reference_note_count"],
                            "human_reference_count")
    require(reference_count > 0, "nonempty_human_reference")
    for arm in ARMS:
        item, metrics = row["arms"][arm], row["arms"][arm]["annotators"][annotator]
        predictions = count(item["count"], "corpus_prediction_count")
        same(metrics["reference_note_count"], reference_count, "common_reference_denominator")
        onset, offset = (count(metrics[name], "matched_note_count") for name in ("onset_matched", "onset_offset_matched"))
        require(offset <= onset <= min(reference_count, predictions), "matching_cardinality_bounds")
        for criterion, metric, hits in (("onset", "onset_f1", onset), ("onset_offset", "onset_offset_f1", offset)):
            same(metrics[metric], round(2 * hits / (reference_count + predictions), 8), "rounded_file_F1_from_counts")
            same(metrics[criterion + "_unmatched_reference"], reference_count - hits, "unmatched_reference_count")
            same(metrics[criterion + "_unmatched_prediction"], predictions - hits, "unmatched_prediction_count")
        for key, expected in {"onset_precision": onset / predictions if predictions else 0.,
            "onset_recall": onset / reference_count, "offset_precision": offset / predictions if predictions else 0.,
            "offset_recall": offset / reference_count}.items():
            same(metrics[key], expected, "file_precision_recall_from_counts")
    detail = row["guard_annotation_diagnostics"][annotator]
    require(set(detail) == {"recording_annotations", "reference_notes", "arms", "comparisons", "parental_harm"},
            "guard_annotation_schema")
    same(detail["recording_annotations"], 1, "one_recording_annotation")
    same(detail["reference_notes"], reference_count, "guard_annotation_reference_denominator")
    require(set(detail["arms"]) == set(DIAGNOSTIC_ARMS), "guard_diagnostic_arm_inventory")
    for arm in DIAGNOSTIC_ARMS:
        public, metrics = detail["arms"][arm], row["arms"][arm]["annotators"][annotator]
        same(public["predicted_notes"], row["arms"][arm]["count"], "diagnostic_prediction_count")
        same(public["onset_matched"], metrics["onset_matched"], "diagnostic_onset_count")
        same(public["offset_matched"], metrics["onset_offset_matched"], "diagnostic_offset_count")
        prior.check_fixed(public["fixed_onset_pairs"])
        same(public["fixed_onset_pairs"]["matched"], public["onset_matched"], "same_onset_pair_population")
        require(public["fixed_onset_pairs"]["within"] <= public["offset_matched"], "fixed_pairs_bounded_by_max_matching")
        if arm != NEW:
            exact(public, row["annotation_diagnostics"][annotator]["arms"][arm],
                  "old_fixed_pair_diagnostic_unchanged")
    partitions = corpus_partitions(row, annotator)
    same(detail["comparisons"], partitions, "independent_guard_G_and_split_reference_partitions")
    require(set(detail["parental_harm"]) == {G, SPLIT}, "harm_baseline_inventory")
    for base in (G, SPLIT):
        require(set(detail["parental_harm"][base]) == set(CRITERIA), "harm_matching_criteria")
        for criterion in CRITERIA:
            harm = detail["parental_harm"][base][criterion]
            require(set(harm) == set(HARM), "harm_field_inventory")
            for number in harm.values():
                count(number, "overlapping_harm_descriptor_count")
            lost = partitions[base][criterion]["lost"]
            same(harm["lost_references"], lost, "lost_reference_harm_denominator")
            same(harm["lost_matched_parent_accepted"] + harm["lost_matched_parent_rejected"],
                 harm["lost_matched_parent_proposed_cut"], "lost_parent_decision_partition")
            require(harm["lost_matched_parent_proposed_cut"] <= lost
                    and harm["lost_matched_parent_with_proposed_short_children"] <= harm["lost_matched_parent_rejected"]
                    and harm["lost_matched_parent_all_proposed_children_fail"] <= harm["lost_matched_parent_rejected"]
                    and harm["lost_matched_parent_final_empty"] <= lost, "harm_subset_bounds")
            if base == G:
                same(harm["lost_matched_parent_final_empty"], 0, "original_G_parent_cannot_lose_all_final_children")
    return partitions


def aggregate_corpus(rows):
    result = {}
    for arm in ARMS:
        item = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in METRICS:
            scores = {ann: [row["arms"][arm]["annotators"][ann][metric] for row in rows] for ann in ANN}
            means = [math.fsum(pair) / 2 for pair in zip(scores["A1"], scores["A2"], strict=True)]
            changes = [mean - math.fsum(row["arms"]["pitch_runs"]["annotators"][ann][metric] for ann in ANN) / 2
                       for mean, row in zip(means, rows, strict=True)]
            better, worse = sum(change > 1e-8 for change in changes), sum(change < -1e-8 for change in changes)
            item[metric] = {"macro": math.fsum(means) / 40, "A1_macro": math.fsum(scores["A1"]) / 40,
                "A2_macro": math.fsum(scores["A2"]) / 40, "delta_vs_runs": math.fsum(changes) / 40,
                "recordings_improved": better, "recordings_worse": worse, "recordings_tied": 40 - better - worse}
        for rate in ("onset_precision", "onset_recall", "offset_precision", "offset_recall"):
            item[rate] = math.fsum(row["arms"][arm]["annotators"][ann][rate] for row in rows for ann in ANN) / 80
        for criterion in CRITERIA:
            for change in ("gained", "lost"):
                item[criterion + "_" + change + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][criterion + "_" + change + "_reference_ids"])
                    for row in rows for ann in ANN)
        result[arm] = item
    return result


def paired_contrast(rows, baseline):
    differences = [math.fsum(row["arms"][NEW]["annotators"][ann]["onset_offset_f1"]
                   - row["arms"][baseline]["annotators"][ann]["onset_offset_f1"] for ann in ANN) / 2 for row in rows]
    draws = np.random.default_rng(298).integers(0, 40, size=(10000, 40))
    means = sorted(math.fsum(differences[int(index)] for index in draw) / 40 for draw in draws)

    def percentile(probability):
        position = probability * (len(means) - 1)
        lower = math.floor(position)
        return means[lower] + (means[math.ceil(position)] - means[lower]) * (position - lower)

    better, worse = sum(value > 1e-8 for value in differences), sum(value < -1e-8 for value in differences)
    return {"candidate": NEW, "baseline": baseline, "metric": "onset_offset_f1",
        "paired_recording_deltas": [{"id": case, "delta": value} for case, value in zip(CASES, differences, strict=True)],
        "mean_delta": math.fsum(differences) / 40, "recordings_improved": better, "recordings_worse": worse,
        "recordings_tied": 40 - better - worse,
        "bootstrap": {"resampling_unit": "recording_mean_of_A1_A2", "seed": 298, "resamples": 10000,
            "confidence_level": .95, "method": "paired_percentile_linear",
            "low": percentile(.025), "high": percentile(.975)}, "heldout_generalization": False}


def stress_specs():
    result = []
    grid = tuple(itertools.product((45, 57, 69), (-.4, 0., .4), (.3, .6), (3, 6), (24, 48, 96)))
    for kind in COHORTS[1:]:
        for number, (pitch, detuning, amplitude, frequency, frames) in enumerate(grid, 1):
            result.append({"id": f"stress_{kind}_{number:03d}", "kind": kind, "pitch": pitch,
                           "detuning": detuning, "amplitude": amplitude, "frequency_hz": frequency, "frames": frames})
    return result


def authored_stress(spec):
    """Direct formula and independent authored intent; no predictor import."""
    n = spec["frames"]
    phase = np.arange(n, dtype=np.float64) * .01
    # Retain the declared operation order of the input-only floating contract.
    angle = 2 * np.pi * spec["frequency_hz"] * np.arange(n, dtype=np.float64) * .01
    center = spec["pitch"] + spec["detuning"]
    pitches = center + spec["amplitude"] * np.sin(angle)
    if spec["kind"] == "adjacent_semitone":
        pitches[n // 2:] += 1.
    hz = np.zeros(n + 21, dtype=np.float64)
    hz[10:10 + n] = 440 * 2 ** ((pitches - 69) / 12)
    require(phase[0] == 0. and hz[-1] == 0., "stress_phase_and_terminal_sample")
    duration = (n + 20) * .01

    def note(pitch, first, end):
        return {"pitch": pitch, "onset": first * .01, "offset": end * .01, "is_drum": False}

    truth = [note(center, 10, 10 + n)]
    if spec["kind"] == "adjacent_semitone":
        truth = [note(center, 10, 10 + n // 2), note(center + 1., 10 + n // 2, 10 + n)]
    return hz, duration, truth, []


def note_evaluation(events, truth):
    reference_times = np.array([(item["onset"], item["offset"]) for item in truth], dtype=float)
    predicted_times = np.array([(item["onset"], item["offset"]) for item in events], dtype=float).reshape(-1, 2)
    reference_hz = np.array([440 * 2 ** ((item["pitch"] - 69) / 12) for item in truth])
    predicted_hz = np.array([440 * 2 ** ((item["pitch"] - 69) / 12) for item in events])

    def pairs(pitch_tolerance, ratio):
        return transcription.match_notes(reference_times, reference_hz, predicted_times, predicted_hz,
            pitch_tolerance=pitch_tolerance, onset_tolerance=.05, offset_ratio=ratio, offset_min_tolerance=.05) if events else []

    result = {"reference_notes": len(truth), "predicted_notes": len(events), "note_count_change": len(events) - len(truth)}
    for name, ratio in (("onset", None), ("onset_offset", .2)):
        hits = len(pairs(50., ratio))
        result[name] = {"matched_notes": hits, "precision": hits / len(events) if events else 0., "recall": hits / len(truth)}
    timing = pairs(np.inf, .2)
    cents = sorted(float(abs(1200 * np.log2(predicted_hz[j] / reference_hz[i]))) for i, j in timing)
    median = (cents[(len(cents) - 1) // 2] + cents[len(cents) // 2]) / 2 if cents else None
    result.update(timing_only_matched_pairs=len(timing),
        timing_only_unmatched_reference_notes=len(truth) - len(timing),
        timing_only_unmatched_prediction_notes=len(events) - len(timing),
        timing_matched_pitch_correct_pairs=sum(value <= 50. for value in cents),
        timing_matched_pitch_wrong_pairs=sum(value > 50. for value in cents),
        timing_matched_absolute_pitch_cents={"count": len(cents), "minimum": cents[0] if cents else None,
                                           "median": median, "maximum": cents[-1] if cents else None})
    return result


def synthetic_case_comparison(row, baseline):
    old, new = row["arms"][baseline], row["arms"][NEW]
    result = {"baseline_arm": baseline, "candidate_arm": NEW,
        "predicted_notes_change": new["count"] - old["count"],
        "event_identity_unchanged": new["event_sha256"] == old["event_sha256"],
        "no_accepted_cuts": new["readout"]["accepted_cut_count"] == 0,
        "onset_f1_change": None, "onset_offset_f1_change": None,
        "baseline_perfect": None, "candidate_perfect": None}
    if row["accuracy_eligible"]:
        for metric in METRICS:
            result[metric + "_change"] = new["metrics"][metric] - old["metrics"][metric]
        result["baseline_perfect"] = all(old["metrics"][metric] == 1. for metric in METRICS)
        result["candidate_perfect"] = all(new["metrics"][metric] == 1. for metric in METRICS)
    if baseline == G and result["no_accepted_cuts"]:
        same(result["event_identity_unchanged"], True, "synthetic_no_accepted_cut_exact_G_event")
    return result


def synthetic_population(rows):
    same(len(rows), 461, "complete_461_authored_population")
    groups = {name: [row for row in rows if row["cohort"] == name] for name in COHORTS}
    same([len(groups[name]) for name in COHORTS], [245, 108, 108], "separate_245_108_108_cohorts")
    result = {}
    for name, selected in groups.items():
        value = {"all_cases": len(selected), "accuracy_eligible_cases": sum(row["accuracy_eligible"] for row in selected)}
        if name == "legacy":
            value.update(ambiguous_cases=sum(row["spec"]["kind"] == "dropout" or (
                row["spec"]["kind"] == "repeat" and row["spec"]["gap"] == 0) for row in selected),
                silence_cases=sum(row["spec"]["kind"] == "silence" for row in selected))
            same(list(value.values()), [245, 227, 15, 3], "legacy_227_15_3_populations")
        else:
            same(value["accuracy_eligible_cases"], 108, "new_stress_eligible_population")
        result[name] = value
    return result


def synthetic_aggregate(rows):
    result = {}
    for cohort in COHORTS:
        group = [row for row in rows if row["cohort"] == cohort]
        eligible = [row for row in group if row["accuracy_eligible"]]
        arms = {}
        for arm in SYN_ARMS:
            item = {"all_cases_predicted_notes": sum(row["arms"][arm]["count"] for row in group),
                "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in group),
                "eligible_cases": len(eligible),
                "silence_false_positive_notes": sum(row["arms"][arm]["count"] for row in group if row["spec"]["kind"] == "silence"),
                "too_many_note_cases": sum(row["arms"][arm]["count"] > len(row["truth"]) for row in eligible),
                "too_few_note_cases": sum(row["arms"][arm]["count"] < len(row["truth"]) for row in eligible),
                "equal_note_count_cases": sum(row["arms"][arm]["count"] == len(row["truth"]) for row in eligible),
                "timing_only_matched_pairs": sum(row["note_evaluation"][arm]["timing_only_matched_pairs"] for row in eligible),
                "timing_matched_pitch_wrong_pairs": sum(row["note_evaluation"][arm]["timing_matched_pitch_wrong_pairs"] for row in eligible)}
            for metric in METRICS:
                item[metric] = math.fsum(row["arms"][arm]["metrics"][metric] for row in eligible) / len(eligible)
            arms[arm] = item
        result[cohort] = arms
    return result


def synthetic_comparisons(rows, populations):
    result = {}
    for cohort in COHORTS:
        group = [row for row in rows if row["cohort"] == cohort]
        eligible = [row for row in group if row["accuracy_eligible"]]
        contrasts = {}
        for baseline in (G, SPLIT):
            changes = {}
            for metric in METRICS:
                values = [row["arms"][NEW]["metrics"][metric] - row["arms"][baseline]["metrics"][metric] for row in eligible]
                changes[metric] = {"macro_change": math.fsum(values) / len(values),
                    "improved_cases": sum(value > 0 for value in values), "worse_cases": sum(value < 0 for value in values),
                    "tied_cases": sum(value == 0 for value in values)}
            contrasts[baseline] = {"baseline_arm": baseline, "candidate_arm": NEW,
                "identical_event_cases": sum(row["arms"][NEW]["event_sha256"] == row["arms"][baseline]["event_sha256"] for row in group),
                "eligible_metric_changes": changes}
        result[cohort] = {**populations[cohort], "baseline_comparisons": contrasts,
            "no_accepted_cut_cases": sum(row["arms"][NEW]["readout"]["accepted_cut_count"] == 0 for row in group)}
    old = [row for row in rows if row["cohort"] == "legacy"]
    successes = [row for row in old if row["accuracy_eligible"]
                 and all(row["arms"][G]["metrics"][metric] == 1. for metric in METRICS)]
    controls = [row for row in old if row["id"] in prior.SEMITONE_IDS]
    same(len(successes), 221, "frozen_221_G_successes")
    same(tuple(row["id"] for row in controls), prior.SEMITONE_IDS, "fixed_six_recovered_controls")
    result["legacy"].update(previous_gaussian_perfect_cases=221,
        previous_gaussian_perfect_case_ids=[row["id"] for row in successes],
        damaged_previous_success_case_ids=[row["id"] for row in successes if not all(
            row["arms"][NEW]["metrics"][metric] == 1. for metric in METRICS)],
        joined_semitone_controls=[{"id": row["id"], "reference_notes": len(row["truth"]),
            "baseline_predicted_notes": row["arms"][G]["count"], "split_predicted_notes": row["arms"][SPLIT]["count"],
            "candidate_predicted_notes": row["arms"][NEW]["count"], "baseline_metrics": row["arms"][G]["metrics"],
            "split_metrics": row["arms"][SPLIT]["metrics"], "candidate_metrics": row["arms"][NEW]["metrics"],
            "candidate_two_notes_pitch_onset_offset_correct": len(row["truth"]) == row["arms"][NEW]["count"] == 2
                and all(row["arms"][NEW]["metrics"][metric] == 1. for metric in METRICS)} for row in controls])
    return result


def check_synthetic(report, previous):
    rows = report["cases"]
    same([row["id"] for row in rows], [row["id"] for row in previous["cases"]] + [spec["id"] for spec in stress_specs()],
         "ordered_461_case_IDs")
    populations = synthetic_population(rows)
    same(report["cohorts"], populations, "separate_report_cohorts")
    for index, row in enumerate(rows):
        if index < 245:
            exact(row["spec"], previous["cases"][index]["spec"], "original_authored_case_specification")
            same(row["cohort"], "legacy", "legacy_cohort")
            hz, duration, truth, alternative = prior.authored(row["spec"])
            ambiguous = row["spec"]["kind"] == "dropout" or (
                row["spec"]["kind"] == "repeat" and row["spec"]["gap"] == 0)
            eligible = not ambiguous and row["spec"]["kind"] != "silence"
        else:
            spec = stress_specs()[index - 245]
            exact(row["spec"], spec, "fixed_factorial_stress_specification")
            same(row["cohort"], spec["kind"], "stress_cohort")
            hz, duration, truth, alternative = authored_stress(spec)
            eligible = True
        exact(row["truth"], truth, "independently_authored_fractional_center_truth")
        exact(row["alternative_truth"], alternative, "preserved_ambiguous_alternatives")
        exact(row["accuracy_eligible"], eligible, "exact_synthetic_eligibility")
        exact(row["duration_seconds"], duration, "synthetic_audio_duration_clock")
        exact(row["observation"], {"dtype": hz.dtype.str, "shape": list(hz.shape), "sha256": digest(hz.tobytes())},
              "all_461_owned_raw_input_identities")
        require(set(row["arms"]) == set(SYN_ARMS), "all_nine_synthetic_arms")
        if not eligible:
            same(row["note_evaluation"], None, "ambiguity_silence_not_scored")
        else:
            require(set(row["note_evaluation"]) == set(SYN_ARMS), "all_nine_owned_diagnostics")
        for arm in SYN_ARMS:
            item = row["arms"][arm]
            prior.check_events(item["events"], duration)
            same(len(item["events"]), item["count"], "owned_event_count")
            same(digest(prior.canonical_events(item["events"])), item["event_sha256"], "all4149_owned_event_file_hashes")
            same(item["metrics"], prior.direct_synthetic(item["events"], truth) if eligible else None,
                 "direct_owned_pitch_onset_offset_score")
            if eligible:
                same(row["note_evaluation"][arm], note_evaluation(item["events"], truth),
                     "direct_owned_timing_only_pitch_diagnostic")
        baseline, split, new = (row["arms"][arm] for arm in (G, SPLIT, NEW))
        prior.check_readout(split["readout"], baseline["diagnostics"], duration)
        check_guard(new["readout"], baseline["diagnostics"], duration)
        same(new["readout"]["readout"]["emitted_notes"], new["count"], "guard_owned_event_count_binding")
        for arm in (SPLIT, NEW):
            exact(row["arms"][arm]["shared_state_path"], baseline["state_path"], "owned_shared_G_path_identity")
            same(row["arms"][arm]["shared_state_path_arm"], G, "owned_shared_G_path_name")
        exact(interval_union(new["events"]), interval_union(baseline["events"]), "owned_output_interval_union")
        same(fingerprint(interval_union(baseline["events"])), new["readout"]["baseline_interval_union_sha256"],
             "owned_baseline_interval_hash")
        same(fingerprint(interval_union(new["events"])), new["readout"]["output_interval_union_sha256"],
             "owned_final_interval_hash")
        labels = prior.raw_labels(hz)
        cuts = [index for index in range(1, len(labels))
                if labels[index - 1] >= 0 and labels[index] >= 0 and labels[index - 1] != labels[index]]
        for arm in (SPLIT, NEW):
            diag = row["arms"][arm]["readout"]
            same(diag["candidate_cut_count"], len(cuts), "owned_candidate_cut_count")
            same(diag["candidate_cut_frames_sha256"], fingerprint(cuts), "owned_candidate_cut_hash")
            exact(diag["raw_hysteresis_label_identity"],
                  {"dtype": str(labels.dtype), "shape": list(labels.shape), "sha256": digest(labels.tobytes())},
                  "owned_global_hysteresis_identity")
        same(row["comparison"], prior.synthetic_comparison(row), "unchanged_unconditional_split_comparison")
        same(row["guard_comparisons"], {base: synthetic_case_comparison(row, base) for base in (G, SPLIT)},
             "new_guard_per_case_comparisons")
    aggregate = synthetic_aggregate(rows)
    comparisons = synthetic_comparisons(rows, populations)
    same(report["aggregate"], aggregate, "independent_three_cohort_nine_arm_aggregate")
    same(report["comparisons"], comparisons, "independent_control_damage_and_stress_comparisons")
    manifest = fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in SYN_ARMS} for row in rows})
    same(report["predictions_manifest_sha256"], manifest, "all4149_pretruth_manifest")
    same(report["post_evaluation_predictions_manifest_sha256"], manifest, "all4149_postscore_manifest")
    return aggregate, comparisons


def check_historical(corpus, synthetic, legacy_corpus, legacy_synthetic, original, frozen):
    old_corpus, old_synthetic = original["vocadito.json"], original["synthetic.json"]
    same(len(old_corpus["source_sha256"]), 53, "original_53_source_inventory")
    exact(old_corpus["source_sha256"], old_synthetic["source_sha256"], "original_common_source_map")
    for name, sha in old_corpus["source_sha256"].items():
        same(frozen[name], sha, "all53_original_sources_immutable")
    require(set(legacy_corpus) == set(old_corpus), "complete_legacy_corpus_schema")
    ignored = {"source_revision", "protocol_head_revision", "python", "platform", "runtime",
               "numerical_environment", "elapsed_seconds", "peak_rss_kib", "legacy_report_sha256", "cases"}
    exact({key: value for key, value in legacy_corpus.items() if key not in ignored},
          {key: value for key, value in old_corpus.items() if key not in ignored}, "old11_arm_full_scientific_metadata")
    for current, projected, old in zip(corpus["cases"], legacy_corpus["cases"], old_corpus["cases"], strict=True):
        stripped = {key: value for key, value in current.items() if key not in ROW_ADDITIONS}
        stripped["arms"] = {arm: current["arms"][arm] for arm in prior.ARMS}
        exact(stripped, projected, "actual11_arm_projection_case_binding")
        ignored_case = {"inference_seconds", "observation_sha256"}
        exact({key: value for key, value in projected.items() if key not in ignored_case},
              {key: value for key, value in old.items() if key not in ignored_case},
              "all440_old_event_440_array_score_and_diagnostic_identities")
    volatile = {"source_revision", "protocol_head_revision", "elapsed_seconds", "numerical_environment"}
    exact({key: value for key, value in legacy_synthetic.items() if key not in volatile},
          {key: value for key, value in old_synthetic.items() if key not in volatile},
          "all1960_old_event_245_input_1470_path_and_metric_identities")
    projection_rows = []
    for row, old in zip(synthetic["cases"][:245], old_synthetic["cases"], strict=True):
        projected = {key: row[key] for key in old if key != "arms"}
        projected["arms"] = {arm: row["arms"][arm] for arm in prior.SYN_ARMS}
        exact(projected, old, "exact_original_245_scientific_case_payloads")
        projection_rows.append(projected)
    projected = {key: synthetic[key] for key in legacy_synthetic if key not in {
        "schema", "planned_cases", "planned_arms", "cases", "aggregate", "comparisons",
        "predictions_manifest_sha256", "post_evaluation_predictions_manifest_sha256",
        "truth_access_started_after_prediction_files", "elapsed_seconds", "source_sha256", "preflight", "historical_parity"}}
    manifest = fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in prior.SYN_ARMS}
                            for row in projection_rows})
    projected.update(schema="note-boundary-readout-synthetic-v1", planned_cases=245,
        planned_arms=list(prior.SYN_ARMS), cases=projection_rows,
        source_sha256={name: frozen[name] for name in old_synthetic["source_sha256"]},
        preflight=synthetic["preflight"]["legacy"], predictions_manifest_sha256=manifest,
        post_evaluation_predictions_manifest_sha256=manifest, truth_access_started_after_prediction_files=1960,
        aggregate=prior.synthetic_aggregate(projection_rows), comparisons=prior.synthetic_comparisons(projection_rows),
        historical_parity=old_synthetic["historical_parity"])
    same(projected, {key: value for key, value in legacy_synthetic.items() if key != "elapsed_seconds"},
         "actual_eight_arm_synthetic_projection_file")
    require(0 <= legacy_synthetic["elapsed_seconds"] <= synthetic["elapsed_seconds"], "legacy_synthetic_elapsed_snapshot")
    for key in ("elapsed_seconds", "peak_rss_kib"):
        require(0 <= legacy_corpus[key] <= corpus[key], "legacy_corpus_resource_snapshot")
    corpus_parity = {"baseline_zip_sha256": PREVIOUS_SHA,
        "source_checks": {name: True for name in old_corpus["source_sha256"]},
        "compared_prediction_files": 440, "compared_observation_arrays": 440,
        "all_equal": True, "differences": [], "raw_historical_arrays_available": False, "array_identity_available": True}
    synthetic_parity = {"baseline_zip_sha256": PREVIOUS_SHA, "compared_prediction_files": 1960,
        "compared_input_arrays": 245, "compared_state_paths": 1470, "all_equal": True, "differences": []}
    same(corpus["historical_parity"], corpus_parity, "corpus_exact_historical_parity_receipt")
    same(synthetic["historical_parity"], synthetic_parity, "synthetic_exact_historical_parity_receipt")
    return {"corpus_prediction_identities": 440, "corpus_observation_identities": 440,
            "synthetic_prediction_identities": 1960, "synthetic_input_identities": 245, "synthetic_path_identities": 1470}


def check_preflight(corpus, synthetic, legacy_corpus, legacy_synthetic, old_audit, private_audit, original, repository, frozen):
    numerical, old_gate = prior.check_numerical_preflight(
        legacy_corpus, legacy_synthetic, old_audit, original["synthetic.json"], repository, frozen)
    for report in (corpus, synthetic, private_audit):
        exact(report["numerical_environment"], numerical, "new_execution_numerical_environment_binding")
    raw = (repository / NUMERIC_MANIFEST).read_bytes()
    same(digest(raw), NUMERIC_SHA, "new216_input_manifest_SHA256")
    same(frozen[NUMERIC_MANIFEST], NUMERIC_SHA, "new216_manifest_frozen_source_binding")
    manifest = parsed(raw)
    require(set(manifest) == {"schema", "baseline_zip_sha256", "legacy_numeric_manifest_sha256",
                             "timing_semantics", "generation_environment", "cases"}, "new_input_only_manifest_schema")
    same(manifest["schema"], "note-boundary-parent-guard-numeric-inputs-v1", "new_numeric_manifest_schema")
    same(manifest["baseline_zip_sha256"], PREVIOUS_SHA, "new_manifest_original_artifact_binding")
    same(manifest["legacy_numeric_manifest_sha256"], prior.NUMERIC_MANIFEST_SHA, "unchanged_old_numeric_manifest")
    exact(manifest["timing_semantics"], TIMING, "new_input_clock_semantics")
    exact(synthetic["stress_timing_semantics"], TIMING, "report_input_clock_semantics")
    require(set(manifest["generation_environment"]) == set(numerical), "generation_runtime_metadata_inventory")
    same(manifest["generation_environment"]["numpy_version"], "1.26.4", "input_generation_numpy_pin")
    inputs = []
    for spec in stress_specs():
        hz, duration, _truth, _alternative = authored_stress(spec)
        inputs.append({"id": spec["id"], "duration_seconds": duration,
                       "observation": {"dtype": hz.dtype.str, "shape": list(hz.shape), "sha256": digest(hz.tobytes())}})
    exact(manifest["cases"], inputs, "independent216_input_only_identities")
    exact([{key: row[key] for key in ("id", "duration_seconds", "observation")} for row in synthetic["cases"][245:]],
          inputs, "new_predictions_use_preflight216_inputs")
    expected = {"schema": "note-boundary-parent-guard-preflight-v1", "legacy": old_gate,
        "stress": {"manifest_sha256": NUMERIC_SHA, "compared_input_arrays": 216, "all_equal": True,
                   "input_differences": [], "model_calls_before_preflight": 0},
        "compared_input_arrays": 461, "compared_analytic_rows": 20, "all_equal": True, "model_calls_before_preflight": 0}
    same(synthetic["preflight"], expected, "combined_input_preflight_receipt")
    same(private_audit["preflight"], expected, "private_audit_input_preflight_binding")
    return numerical, expected


def check_private_audit_bindings(reports, payloads, frozen):
    factor, old, current = (reports[name] for name in ("legacy-factor-audit.json", "legacy-audit.json", "audit.json"))
    for audit in (factor, old, current):
        same(audit["status"], "pass", "private_audit_pass")
        same(audit["audit_completed"], True, "private_audit_completed")
        require(count(audit["checks_passed"], "private_check_count") > 0, "private_audit_nonempty")
    same(factor["schema"], "note-state-factors-audit-v1", "factor_audit_schema")
    same(old["schema"], "note-boundary-readout-audit-v1", "readout_audit_schema")
    same(current["schema"], "note-boundary-parent-guard-audit-v1", "guard_audit_schema")
    same(factor["report_sha256"], digest(payloads["legacy-factor-vocadito.json"]), "factor_audit_exact_report_binding")
    same(factor["script_sha256"], frozen["scripts/audit_note_state_factors.py"], "factor_auditor_source_binding")
    same(factor["complete_prediction_files_verified"], 400, "factor400_event_scope")
    same(factor["observation_arrays_verified"], 440, "factor440_array_scope")
    same(factor["source_files_verified"], 24, "factor24_source_scope")
    for key, name in {"report_sha256": "legacy-vocadito.json", "synthetic_report_sha256": "legacy-synthetic.json",
                      "legacy_report_sha256": "legacy-factor-vocadito.json", "legacy_audit_sha256": "legacy-factor-audit.json"}.items():
        same(old[key], digest(payloads[name]), "old_readout_audit_exact_file_binding")
    same(old["script_sha256"], frozen["scripts/audit_note_boundary_readout.py"], "old_readout_auditor_source_binding")
    for key, number in {"source_files_verified": 53, "corpus_prediction_files_verified": 440,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 1960, "synthetic_input_arrays_verified": 245,
        "synthetic_old_state_paths_verified": 1470, "independent_new_readouts_verified": 285}.items():
        same(old[key], number, "old_readout_audit_complete_scope")
    for key, name in {"report_sha256": "vocadito.json", "synthetic_report_sha256": "synthetic.json",
        "legacy_report_sha256": "legacy-vocadito.json", "legacy_synthetic_report_sha256": "legacy-synthetic.json",
        "legacy_audit_sha256": "legacy-audit.json"}.items():
        same(current[key], digest(payloads[name]), "new_private_audit_exact_file_binding")
    same(current["script_sha256"], frozen["scripts/audit_note_boundary_parent_guard.py"], "new_private_auditor_source_binding")
    for key, number in {"source_files_verified": 66, "corpus_prediction_files_verified": 480,
        "corpus_observation_arrays_verified": 440, "human_reference_files_verified": 80,
        "synthetic_prediction_files_verified": 4149, "synthetic_input_arrays_verified": 461,
        "synthetic_old_state_paths_verified": 2766, "stress_input_arrays_independently_regenerated": 216,
        "independent_guard_readouts_verified": 501, "independent_unconditional_readouts_verified": 501,
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0}.items():
        same(current[key], number, "new_private_audit_complete_scope")
    for report_name, key, member in (
        ("vocadito.json", "legacy_report_sha256", "legacy-vocadito.json"),
        ("vocadito.json", "legacy_factor_report_sha256", "legacy-factor-vocadito.json"),
        ("legacy-vocadito.json", "legacy_report_sha256", "legacy-factor-vocadito.json")):
        same(reports[report_name][key], digest(payloads[member]), "projection_file_identity_binding")
    return factor, old, current


def audit_zip(artifact, expected_sha, expected_bytes, repository, frozen_head, source_map, run_id):
    started = time.monotonic()
    prior.CHECKS.clear()
    prior.MAX_DIFF = 0.
    same(np.__version__, "1.26.4", "postrun_numpy_pin_for_owned_input_identity")
    same(mir_eval.__version__, "0.8.2", "postrun_mir_eval_pin")
    require(not artifact.is_symlink() and artifact.is_file(), "original_zip_regular_file")
    raw = artifact.read_bytes()
    same(len(raw), expected_bytes, "original_zip_byte_length")
    same(digest(raw), expected_sha, "original_zip_SHA256")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        same(sorted(archive.namelist()), sorted(MEMBERS), "exact_eight_public_members")
        require(all(not item.is_dir() and 0 < item.file_size < 96_000_000 for item in archive.infolist()),
                "bounded_public_members")
        payloads = {name: archive.read(name) for name in MEMBERS}
    reports = {name: parsed(value) for name, value in payloads.items()}
    corpus, synthetic = reports["vocadito.json"], reports["synthetic.json"]
    legacy, legacy_synthetic = reports["legacy-vocadito.json"], reports["legacy-synthetic.json"]
    for name in ("vocadito.json", "synthetic.json", "legacy-vocadito.json", "legacy-synthetic.json", "legacy-factor-vocadito.json"):
        report = reports[name]
        same(report["status"], "complete", "complete_execution_report")
        same(report["protocol_head_revision"], frozen_head, "fixed_protocol_head")
        same(report["source_revision"], corpus["source_revision"], "common_actual_checkout")
        same(report["quality_approved"], False, "no_quality_approval")
        same(report["heldout_generalization"], False, "no_heldout_claim")
    for key in ("source_revision", "protocol_head_revision"):
        require(isinstance(corpus[key], str) and len(corpus[key]) == 40
                and all(char in "0123456789abcdef" for char in corpus[key]), "full_git_revision")
    same(corpus["schema"], "note-boundary-parent-guard-v1", "new_corpus_schema")
    same(synthetic["schema"], "note-boundary-parent-guard-synthetic-v1", "new_synthetic_schema")
    same(corpus["planned_case_ids"], list(CASES), "fixed40_recording_plan")
    same(corpus["planned_arms"], list(ARMS), "fixed12_corpus_arms")
    same(synthetic["planned_arms"], list(SYN_ARMS), "fixed9_synthetic_arms")
    for key, value in {"all_cases_complete": True, "reference_used_for_edits": False, "product_changes": False,
        "all_predictions_frozen_before_references": True, "reference_access_started_after_predicted_cases": 40,
        "device": "cpu", "threads": 2}.items():
        same(corpus[key], value, "corpus_prediction_barrier_contract")
    for key, value in {"planned_cases": 461, "acoustic_extraction": False, "product_changes": False,
        "all_predictions_saved_before_scoring": True, "truth_access_started_after_prediction_files": 4149}.items():
        same(synthetic[key], value, "synthetic_prediction_barrier_contract")
    source_bytes = source_map.read_bytes()
    frozen = parsed(source_bytes)
    same(len(frozen), 66, "frozen66_source_inventory")
    for report in (corpus, synthetic, reports["audit.json"]):
        exact(report["source_sha256"], frozen, "independently_supplied_frozen_source_map")
    for name, sha in frozen.items():
        path = repository / name
        require(not path.is_symlink() and path.is_file()
                and path.resolve().is_relative_to(repository.resolve()), "frozen_source_file_domain")
        same(digest(path.read_bytes()), sha, "all66_frozen_source_file_hashes")
    factor_audit, old_audit, private_audit = check_private_audit_bindings(reports, payloads, frozen)
    old_raw = (repository / PREVIOUS).read_bytes()
    same(len(old_raw), 775843, "original297_zip_size")
    same(digest(old_raw), PREVIOUS_SHA, "original297_zip_SHA256")
    with zipfile.ZipFile(io.BytesIO(old_raw)) as archive:
        same(sorted(archive.namelist()), sorted(prior.MEMBERS), "original297_six_member_inventory")
        original = {name: parsed(archive.read(name)) for name in prior.MEMBERS}
    numerical, preflight = check_preflight(corpus, synthetic, legacy, legacy_synthetic, old_audit,
                                          private_audit, original, repository, frozen)
    history = check_historical(corpus, synthetic, legacy, legacy_synthetic, original, frozen)
    exact(old_audit["source_sha256"], legacy["source_sha256"], "legacy_audit53_source_map")
    same(private_audit["corpus_historical_parity"], corpus["historical_parity"], "private_corpus_history_binding")
    same(private_audit["synthetic_historical_parity"], synthetic["historical_parity"], "private_synthetic_history_binding")
    rows = corpus["cases"]
    same([row["id"] for row in rows], list(CASES), "complete_ordered40_corpus_cases")
    for row in rows:
        same(row["status"], "scored", "all40_corpus_cases_scored")
        require(set(row["arms"]) == set(ARMS), "all12_corpus_arms")
        require(set(row["guard_annotation_diagnostics"]) == set(ANN), "both_guard_annotation_rows")
        for arm in ARMS:
            require(set(row["arms"][arm]["annotators"]) == set(ANN), "both_annotator_metrics")
        for ann in ANN:
            check_corpus_annotation(row, ann)
        check_guard(row["guard"], row["diagnostics"]["factors"][G], row["duration_seconds"])
        same(row["guard"]["readout"]["emitted_notes"], row["arms"][NEW]["count"], "corpus_guard_event_count")
        same(row["guard"]["baseline"]["emitted_notes"], row["arms"][G]["count"], "corpus_G_event_count")
        if row["guard"]["accepted_cut_count"] == 0:
            same(row["arms"][NEW]["event_sha256"], row["arms"][G]["event_sha256"], "corpus_no_accepted_cut_event_identity")
    manifest = fingerprint({row["id"]: {arm: row["arms"][arm]["event_sha256"] for arm in ARMS} for row in rows})
    same(corpus["predictions_manifest_sha256"], manifest, "all480_pre_reference_manifest")
    same(corpus["post_evaluation_predictions_manifest_sha256"], manifest, "all480_postscore_manifest")
    aggregate = aggregate_corpus(rows)
    primary, secondary = paired_contrast(rows, G), paired_contrast(rows, SPLIT)
    same(corpus["aggregate"], aggregate, "independent12_arm_corpus_aggregate")
    same(corpus["primary_result"], primary, "independent_guard_vs_G_seed298_bootstrap")
    same(corpus["secondary_result"], secondary, "independent_guard_vs_split_seed298_bootstrap")
    for key, expected in (("aggregate", aggregate), ("primary_result", primary), ("secondary_result", secondary)):
        same(private_audit["corpus"][key], expected, "private_corpus_result_binding")
    boundary = corpus["boundary_summary"]
    for ann in ANN:
        prior.combine_public(boundary["by_annotator"][ann], [row["guard_annotation_diagnostics"][ann] for row in rows])
    pooled = boundary["pooled_annotation_judgments"]
    prior.combine_public(pooled, [row["guard_annotation_diagnostics"][ann] for row in rows for ann in ANN])
    same(private_audit["corpus"]["boundary_summary"], boundary, "private_boundary_summary_binding")
    synthetic_aggregate_value, comparisons = check_synthetic(synthetic, original["synthetic.json"])
    same(private_audit["synthetic"]["aggregate"], synthetic_aggregate_value, "private_stratified_synthetic_aggregate")
    same(private_audit["synthetic"]["comparisons"], comparisons, "private_synthetic_comparison_binding")
    same(private_audit["synthetic"]["cohorts"], synthetic["cohorts"], "private_synthetic_cohort_binding")
    same(private_audit["synthetic"]["predictions_manifest_sha256"], synthetic["predictions_manifest_sha256"],
         "private_all4149_manifest_binding")
    self_path = Path(__file__)
    return {"schema": "note-boundary-parent-guard-public-postrun-audit-v1", "status": "pass", "audit_completed": True,
        "run_id": run_id, "frozen_protocol_head": frozen_head, "execution_checkout": corpus["source_revision"],
        "artifact_sha256": expected_sha, "artifact_bytes": expected_bytes,
        "members": {name: {"bytes": len(value), "sha256": digest(value)} for name, value in payloads.items()},
        "frozen_source_map_sha256": digest(source_bytes), "frozen_source_files_verified": 66,
        "script_sha256": digest(self_path.read_bytes()),
        "audit_implementation_files": {str(self_path.resolve().relative_to(repository.resolve())): digest(self_path.read_bytes()),
            "scripts/audit_note_boundary_readout_receipt.py": digest(Path(prior.__file__).read_bytes())},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "mir_eval": mir_eval.__version__},
        "checks_passed": sum(prior.CHECKS.values()), "checks_by_kind": dict(sorted(prior.CHECKS.items())),
        "maximum_numeric_difference": prior.MAX_DIFF, "historical_identity_counts": history,
        "Actions_numerical_environment_bound_to_private_audit": numerical, "input_only_preflight": preflight,
        "corpus_prediction_identities_checked": 480, "corpus_annotation_score_rows_checked": 960,
        "synthetic_event_payloads_and_hashes_checked": 4149,
        "synthetic_eligible_score_pairs_recomputed": 3987, "owned_raw_input_arrays_regenerated_and_hashed": 461,
        "primary_result": primary, "secondary_result": secondary,
        "corpus_macro": {arm: {"predicted_notes": aggregate[arm]["predicted_notes"],
            **{metric: aggregate[arm][metric]["macro"] for metric in METRICS}} for arm in ARMS},
        "corpus_matched_annotation_judgments": {arm: {key: pooled["arms"][arm][key]
            for key in ("onset_matched", "offset_matched")} for arm in DIAGNOSTIC_ARMS},
        "corpus_reference_partitions_recomputed": pooled["comparisons"],
        "corpus_parental_harm_public_counts_summed": pooled["parental_harm"],
        "corpus_guard_public_counts_summed": guard_totals([row["guard"] for row in rows]),
        "synthetic_aggregate": synthetic_aggregate_value,
        "synthetic_comparisons": {name: {key: value for key, value in part.items()
            if key != "previous_gaussian_perfect_case_ids"} for name, part in comparisons.items()},
        "previous_221_success_IDs_sha256": fingerprint(comparisons["legacy"]["previous_gaussian_perfect_case_ids"]),
        "synthetic_guard_public_counts_summed": {cohort: guard_totals([
            row["arms"][NEW]["readout"] for row in synthetic["cases"] if row["cohort"] == cohort]) for cohort in COHORTS},
        "private_audit_checks_bound": {"factor": factor_audit["checks_passed"],
            "readout": old_audit["checks_passed"], "guard": private_audit["checks_passed"]},
        "neural_model_calls": 0, "pyin_calls": 0, "decoder_calls": 0, "new_prediction_files_generated": 0,
        "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "The original eight-member Actions ZIP is checked byte-for-byte and never recompressed.",
            "All66 frozen scientific files are checked. This separately authored postrun checker and its prior public-helper dependency are recorded by hash outside that inference inventory.",
            "Both exact input-only manifests and actual prediction input identities are bound. The old245 and new216 owned inputs are regenerated without running any predictor.",
            "Actions runtime/CPU metadata are bound to the private auditor. This postrun host is different; no CPU feature is forced or disabled.",
            "Corpus F1, precision/recall, macros and both seed298 recording bootstraps are recomputed from public counts and file scores, not private human note CSVs.",
            "G/split versus guard reference partitions are reconstructed from runs-relative reference-ID gains/losses and the runs matched count.",
            "Private corpus event arrays, G paths, parent-child trace and annotation-parent links are unavailable here; their reconstruction is covered by three exact hash-bound Actions audit receipts.",
            "Public guard proposal/final pruning arithmetic and interval-union hashes are checked. Owned event payloads also permit direct interval-union comparison. Private parent decisions cannot be reconstructed from public summaries alone.",
            "Pooled residual counts, extrema and means are recomputed; pooled quantiles cannot be recovered without private residual samples.",
            "All4149 owned event payloads are hashed and 443x9 eligible scores are directly recomputed with mir_eval0.8.2. The15 ambiguous and3 silence controls stay outside accuracy averages.",
            "Timing-only pitch-damage matching is a different assignment population from pitch-aware matching; it does not uniquely identify intended notes.",
            "The new108 single-expression and108 adjacent-semitone cases encode authored intent, not a claim of universally identifiable human intent from F0.",
            "Direct mir_eval uses the same matching implementation. Development reuse, synthetic success and audit completion do not approve heldout generalization or product readiness.",
            "Hashes cannot independently prove past reference-access ordering; frozen runner code, barrier tests and workflow supply complementary evidence.",
        ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("artifact", "repository", "source-map", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    parser.add_argument("--frozen-head", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("new postrun receipt path required")
    try:
        result = audit_zip(args.artifact, args.expected_sha256, args.expected_bytes,
                           args.repository, args.frozen_head, args.source_map, args.run_id)
    except Exception as exc:
        result = {"schema": "note-boundary-parent-guard-public-postrun-audit-v1", "status": "failed",
            "audit_completed": False, "error_type": type(exc).__name__, "error": str(exc),
            "checks_passed": sum(prior.CHECKS.values()), "maximum_numeric_difference": prior.MAX_DIFF,
            "script_sha256": digest(Path(__file__).read_bytes())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": result["status"], "checks_passed": result["checks_passed"],
                      "maximum_numeric_difference": result["maximum_numeric_difference"], "error": result.get("error")}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
