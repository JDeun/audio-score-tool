"""Describe frozen note endpoints and interval relations; never edit predictions.

All corpus event/reference times and per-note rows stay private. Public summaries
retain both annotators, every recording, original maximum matchings, and offsets
measured on the *same* onset-only pairs. Overlap and support descriptors are not
human labels of merges, splits or causes.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np

from scripts.audit_note_state_experiment import _read, parse_notes, parse_reference, sha256

CASES = tuple(f"vocadito_{i}" for i in range(1, 41))
ANNOTATORS = ("A1", "A2")
ARMS = ("pitch_runs", "gaussian_exponent_1", "note_state_hmm")
PARTITIONS = ("retained", "gained", "lost", "neither")
PAIR_NUMBERS = ("signed_offset_seconds", "tolerance_seconds", "tolerance_excess_seconds",
                "reference_duration_seconds", "prediction_duration_seconds")
SETTINGS = {
    "arms": list(ARMS), "annotators": list(ANNOTATORS), "partitions": list(PARTITIONS),
    "onset_tolerance_seconds": .05, "pitch_tolerance_cents": 50.,
    "offset_ratio": .2, "offset_min_tolerance_seconds": .05,
    "distance_rounding_decimals": 4, "strict_matching": False,
    "offset_pairing": "same_onset_only_maximum_matching_pairs",
    "offset_residual_sign": "prediction_offset_minus_reference_offset",
    "overlap": "strictly_positive_time_intersection_ignoring_pitch",
    "reference_onset_coverage": "prediction_start <= reference_start < prediction_end_ignoring_pitch",
    "reference_frame_window": "ref_start <= i*0.01 < min(ref_end,audio_duration)",
    "internal_raw_unvoiced_run": "zero_Hz_run_bracketed_by_positive_Hz_inside_reference_window",
    "short_pruning": "decoded_pitch_segment_with_raw_support_and_0<duration<0.08-1e-10",
    "distribution_quantiles": "linear_25_50_75_percentiles_of_original_pair_samples",
    "pooled_unit": "recording_annotator_reference_judgment_not_unique_physical_note",
    "causal_error_labels": False, "new_predictions": False,
}


def numeric_summary(values):
    """Pool original values, not per-recording medians; empty is explicitly null."""
    values = [float(v) for v in values]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("finite summary values required")
    if not values:
        return {"count": 0, **dict.fromkeys(("min", "q25", "median", "q75", "max", "mean"))}
    q25, median, q75 = np.quantile(values, [.25, .5, .75], method="linear")
    return {"count": len(values), "min": min(values), "q25": float(q25),
            "median": float(median), "q75": float(q75), "max": max(values),
            "mean": math.fsum(values) / len(values)}


def fixed_pair_summary(pairs):
    result = {"matched": len(pairs),
              **{category: sum(p["category"] == category for p in pairs)
                 for category in ("early", "within", "late")},
              "within_with_raw_excess": sum(p["category"] == "within"
                                            and p["tolerance_excess_seconds"] > 0 for p in pairs)}
    result.update({key: numeric_summary(p[key] for p in pairs) for key in PAIR_NUMBERS})
    return result


def _prediction_arrays(notes, duration):
    intervals, frequencies = [], []
    previous_end = 0.
    for note in notes:
        if not isinstance(note, dict) or set(note) != {"pitch", "onset", "offset", "is_drum"}:
            raise ValueError("canonical note objects required")
        pitch, start, end = note["pitch"], note["onset"], note["offset"]
        if (isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 127
                or note["is_drum"] is not False
                or any(isinstance(v, bool) or not isinstance(v, (int, float))
                       or not math.isfinite(v) for v in (start, end))
                or start < 0 or start < previous_end - 1e-10
                or not start < end <= duration + 1e-10):
            raise ValueError("invalid frozen note")
        intervals.append((start, end))
        frequencies.append(440. * 2 ** ((pitch - 69) / 12))
        previous_end = end
    return np.asarray(intervals, dtype=float).reshape(-1, 2), np.asarray(frequencies, dtype=float)


def _reference_arrays(reference):
    intervals, frequencies = (np.asarray(v, dtype=float) for v in reference)
    if (intervals.ndim != 2 or intervals.shape[1:] != (2,) or not len(intervals)
            or frequencies.shape != (len(intervals),)
            or not np.isfinite(intervals).all() or not np.isfinite(frequencies).all()
            or np.any(intervals[:, 0] < 0) or np.any(intervals[:, 1] <= intervals[:, 0])
            or np.any(np.diff(intervals[:, 0]) < 0) or np.any(frequencies <= 0)):
        raise ValueError("nonempty original-Hz onset-ordered reference required")
    return intervals, frequencies


def candidate_graphs(reference, prediction):
    """Mirror mir_eval 0.8.2's compatibility graph, including distance rounding."""
    ref, ref_hz = reference
    pred, pred_hz = prediction
    onset = np.around(np.abs(ref[:, None, 0] - pred[None, :, 0]), 4) <= .05
    pitch = np.abs(1200 * (np.log2(ref_hz)[:, None] - np.log2(pred_hz)[None, :])) <= 50.
    onset &= pitch
    tolerance = np.maximum(.2 * (ref[:, 1] - ref[:, 0]), .05)
    offset = onset & (np.around(np.abs(ref[:, None, 1] - pred[None, :, 1]), 4) <= tolerance[:, None])
    overlap = np.minimum(ref[:, None, 1], pred[None, :, 1]) > np.maximum(ref[:, None, 0], pred[None, :, 0])
    return onset, offset, overlap


def endpoint_pair(reference_id, prediction_id, ref, pred):
    """Use raw signed residuals, but mir_eval-rounded distance for the category."""
    residual = float(pred[1] - ref[1])
    ref_duration, pred_duration = float(ref[1] - ref[0]), float(pred[1] - pred[0])
    tolerance = max(.05, .2 * ref_duration)
    within = np.around(abs(residual), 4) <= tolerance
    return {"reference_id": int(reference_id), "prediction_id": int(prediction_id),
            "signed_offset_seconds": residual, "tolerance_seconds": tolerance,
            "tolerance_excess_seconds": max(0., abs(residual) - tolerance),
            "reference_duration_seconds": ref_duration,
            "prediction_duration_seconds": pred_duration,
            "category": "within" if within else "early" if residual < 0 else "late"}


def _arm_detail(reference, prediction):
    import mir_eval.transcription as mt

    ref, ref_hz = reference
    pred, pred_hz = prediction
    onset_graph, offset_graph, overlap = candidate_graphs(reference, prediction)
    matchings = {}
    for label, ratio in (("onset", None), ("offset", .2)):
        pairs = mt.match_notes(ref, ref_hz, pred, pred_hz, onset_tolerance=.05,
                               pitch_tolerance=50., offset_ratio=ratio,
                               offset_min_tolerance=.05, strict=False) if len(pred) else []
        graph = onset_graph if label == "onset" else offset_graph
        if (any(not graph[i, j] for i, j in pairs)
                or len({i for i, _ in pairs}) != len(pairs)
                or len({j for _, j in pairs}) != len(pairs)):
            raise ValueError("matching differs from declared compatibility graph")
        matchings[label] = pairs
    multi_ref = overlap.sum(axis=0) > 1
    onset_coverage = (pred[None, :, 0] <= ref[:, None, 0]) & (ref[:, None, 0] < pred[None, :, 1])
    onset_counts = onset_coverage.sum(axis=0)
    return {"predicted_notes": len(pred),
            "onset_pairs": [endpoint_pair(i, j, ref[i], pred[j]) for i, j in matchings["onset"]],
            "offset_pairs": [[int(i), int(j)] for i, j in matchings["offset"]],
            "onset_ref_degrees": onset_graph.sum(axis=1).tolist(),
            "onset_pred_degrees": onset_graph.sum(axis=0).tolist(),
            "offset_ref_degrees": offset_graph.sum(axis=1).tolist(),
            "offset_pred_degrees": offset_graph.sum(axis=0).tolist(),
            "overlap_ref_degrees": overlap.sum(axis=1).tolist(),
            "overlap_pred_degrees": overlap.sum(axis=0).tolist(),
            "reference_overlaps_multi_reference_prediction": np.any(overlap & multi_ref[None, :], axis=1).tolist(),
            "prediction_covered_reference_onsets": onset_counts.tolist(),
            "reference_onset_in_multi_onset_prediction": np.any(onset_coverage & (onset_counts > 1)[None, :], axis=1).tolist()}


def short_segment_intervals(hz, path, duration):
    """Reconstruct only positive-support segments rejected by the frozen 80 ms filter."""
    labels = np.where(path % 3 != 2, path // 3, -1)
    cuts = np.r_[0, 1 + np.flatnonzero(np.diff(labels)), len(labels)]
    result = []
    for first, stop in zip(cuts[:-1], cuts[1:], strict=True):
        if labels[first] < 0:
            continue
        start, end = float(first * .01), min(float(stop * .01), duration)
        if 0 < end - start < .08 - 1e-10 and np.any(hz[first:stop] > 0):
            result.append((start, end))
    return result


def raw_reference_profiles(ref, hz, path, duration):
    """Count observable support within half-open reference windows, without pitch labels."""
    timeline = np.arange(len(hz)) * .01
    short = short_segment_intervals(hz, path, duration)
    profiles = []
    for start, end in ref:
        window = (timeline >= start) & (timeline < end) & (timeline < duration)
        voiced = hz[window] > 0
        decoded = path[window] % 3 != 2
        boundaries = np.r_[0, 1 + np.flatnonzero(np.diff(voiced)), len(voiced)] if len(voiced) else np.array([0])
        internal_runs = sum(first > 0 and stop < len(voiced) and not voiced[first]
                            for first, stop in zip(boundaries[:-1], boundaries[1:], strict=True))
        overlaps = [min(float(end), b) - max(float(start), a) for a, b in short
                    if min(float(end), b) > max(float(start), a)]
        profiles.append({"frames": int(window.sum()), "raw_voiced_frames": int(voiced.sum()),
                         "raw_unvoiced_frames": int((~voiced).sum()),
                         "internal_raw_unvoiced_runs": int(internal_runs),
                         "raw_voiced_g_silent_frames": int((voiced & ~decoded).sum()),
                         "raw_unvoiced_g_voiced_frames": int((~voiced & decoded).sum()),
                         "short_segment_overlap_count": len(overlaps),
                         "short_segment_overlap_seconds": math.fsum(overlaps)})
    return profiles


def _overlap_summary(details, subsets=None, predictions=True):
    if subsets is None:
        subsets = [range(len(d["overlap_ref_degrees"])) for d in details]
    degrees = [d["overlap_ref_degrees"][i] for d, ids in zip(details, subsets, strict=True) for i in ids]
    multi = [d["reference_overlaps_multi_reference_prediction"][i]
             for d, ids in zip(details, subsets, strict=True) for i in ids]
    onset_multi = [d["reference_onset_in_multi_onset_prediction"][i]
                   for d, ids in zip(details, subsets, strict=True) for i in ids]
    result = {"edges": sum(degrees), "references_without_overlap": sum(x == 0 for x in degrees),
              "references_with_multiple_predictions": sum(x > 1 for x in degrees),
              "references_overlapping_prediction_with_multiple_references": sum(multi),
              "references_with_onset_in_multi_onset_prediction": sum(onset_multi)}
    if predictions:
        pred_degrees = [x for d in details for x in d["overlap_pred_degrees"]]
        result.update(predictions_without_overlap=sum(x == 0 for x in pred_degrees),
                      predictions_with_multiple_references=sum(x > 1 for x in pred_degrees),
                      predictions_covering_multiple_reference_onsets=sum(
                          x > 1 for d in details for x in d["prediction_covered_reference_onsets"]))
    return result


def _raw_summary(profiles):
    result = {"sampled_reference_frames": sum(p["frames"] for p in profiles)}
    for field in ("raw_voiced_frames", "raw_unvoiced_frames", "internal_raw_unvoiced_runs",
                  "raw_voiced_g_silent_frames", "raw_unvoiced_g_voiced_frames"):
        result[field] = sum(p[field] for p in profiles)
        if field != "raw_voiced_frames":
            result["references_with_" + field] = sum(p[field] > 0 for p in profiles)
    result["references_with_short_segment_overlap"] = sum(p["short_segment_overlap_count"] > 0 for p in profiles)
    result["short_segment_overlap_count"] = sum(p["short_segment_overlap_count"] for p in profiles)
    result["short_segment_overlap_seconds"] = math.fsum(p["short_segment_overlap_seconds"] for p in profiles)
    return result


def summarize_annotations(annotations):
    """Same schema for one annotation or a pool of original annotation judgments."""
    reference_count = sum(a["reference_notes"] for a in annotations)
    arms = {}
    for arm in ARMS:
        detail = [a["arms"][arm] for a in annotations]
        pairs = [p for d in detail for p in d["onset_pairs"]]
        predictions = sum(d["predicted_notes"] for d in detail)
        offsets = sum(len(d["offset_pairs"]) for d in detail)
        assignment = dict.fromkeys(("offset_reference_without_fixed_onset_pair",
                                    "offset_reference_with_different_prediction",
                                    "offset_reference_with_fixed_pair_failing_offset"), 0)
        for d in detail:
            onset_map = {p["reference_id"]: p for p in d["onset_pairs"]}
            for ref_id, pred_id in d["offset_pairs"]:
                pair = onset_map.get(ref_id)
                if pair is None:
                    assignment["offset_reference_without_fixed_onset_pair"] += 1
                else:
                    assignment["offset_reference_with_different_prediction"] += pair["prediction_id"] != pred_id
                    assignment["offset_reference_with_fixed_pair_failing_offset"] += pair["category"] != "within"
        graph = {}
        for prefix in ("onset", "offset"):
            refs = [v for d in detail for v in d[prefix + "_ref_degrees"]]
            preds = [v for d in detail for v in d[prefix + "_pred_degrees"]]
            graph[prefix + "_edges"] = sum(refs)
            graph["references_with_multiple_" + prefix + "_candidates"] = sum(v > 1 for v in refs)
            graph["predictions_with_multiple_" + prefix + "_candidates"] = sum(v > 1 for v in preds)
        arms[arm] = {"predicted_notes": predictions, "onset_matched": len(pairs), "offset_matched": offsets,
                     "onset_precision": len(pairs) / predictions if predictions else 0.,
                     "onset_recall": len(pairs) / reference_count if reference_count else 0.,
                     "offset_precision": offsets / predictions if predictions else 0.,
                     "offset_recall": offsets / reference_count if reference_count else 0.,
                     "fixed_onset_pairs": fixed_pair_summary(pairs), "offset_assignment": assignment,
                     "overlap": _overlap_summary(detail), "candidate_graph": graph}
    partitions = {}
    g_details = [a["arms"]["gaussian_exponent_1"] for a in annotations]
    for partition in PARTITIONS:
        ids = [a["offset_partition_ids"][partition] for a in annotations]
        pair_groups = [[p for p in d["onset_pairs"] if p["reference_id"] in set(group)]
                       for d, group in zip(g_details, ids, strict=True)]
        pairs = [p for group in pair_groups for p in group]
        count = sum(len(group) for group in ids)
        profiles = [a["raw_reference_profiles"][i]
                    for a, group in zip(annotations, ids, strict=True) for i in group]
        partitions[partition] = {"references": count, "g_onset_unmatched": count - len(pairs),
                                 "g_fixed_onset_pairs": fixed_pair_summary(pairs),
                                 "g_overlap": _overlap_summary(g_details, ids, predictions=False),
                                 "raw_support": _raw_summary(profiles)}
    return {"recording_annotations": len(annotations), "reference_notes": reference_count,
            "arms": arms, "offset_reference_partitions": partitions}


def analyze_case(case_id, notes_by_arm, references, hz, g_path, duration):
    """Return metadata-only public row and private details; no mutation or model call."""
    if set(notes_by_arm) != set(ARMS) or set(references) != set(ANNOTATORS):
        raise ValueError("all declared arms and both annotators required")
    hz, g_path = np.asarray(hz), np.asarray(g_path)
    if (not math.isfinite(duration) or duration <= 0 or hz.ndim != 1 or len(hz) < 2
            or hz.dtype.kind not in "fiu" or not np.isfinite(hz).all() or np.any(hz < 0)
            or g_path.shape != hz.shape or g_path.dtype.kind not in "iu"
            or np.any(g_path < 0) or np.any(g_path >= 435)):
        raise ValueError("finite same-clock raw F0 and integer Gaussian path required")
    predictions = {arm: _prediction_arrays(notes_by_arm[arm], duration) for arm in ARMS}
    public, private = {"id": case_id, "status": "complete", "annotators": {}}, {"id": case_id, "annotators": {}}
    for annotator in ANNOTATORS:
        reference = _reference_arrays(references[annotator])
        arms = {arm: _arm_detail(reference, prediction) for arm, prediction in predictions.items()}
        baseline = {i for i, _ in arms["pitch_runs"]["offset_pairs"]}
        gaussian = {i for i, _ in arms["gaussian_exponent_1"]["offset_pairs"]}
        universe = set(range(len(reference[0])))
        detail = {"reference_notes": len(reference[0]), "arms": arms,
                  "offset_partition_ids": {"retained": sorted(baseline & gaussian),
                                           "gained": sorted(gaussian - baseline),
                                           "lost": sorted(baseline - gaussian),
                                           "neither": sorted(universe - (baseline | gaussian))},
                  "raw_reference_profiles": raw_reference_profiles(reference[0], hz, g_path, duration)}
        private["annotators"][annotator] = detail
        public["annotators"][annotator] = summarize_annotations([detail])
    return public, private


def aggregate_cases(rows, private_details):
    """Fail closed on missing, duplicated or failed recordings; never shrink the cohort."""
    if (len(rows) != len(CASES) or len(private_details) != len(CASES)
            or {row.get("id") for row in rows} != set(CASES)
            or {row.get("id") for row in private_details} != set(CASES)
            or any(row.get("status") != "complete" or set(row.get("annotators", {})) != set(ANNOTATORS)
                   for row in rows)
            or any(set(row.get("annotators", {})) != set(ANNOTATORS)
                   or any(set(row["annotators"][a].get("arms", {})) != set(ARMS) for a in ANNOTATORS)
                   for row in private_details)):
        return None
    by_id = {row["id"]: row for row in private_details}
    for row in rows:
        expected = {a: summarize_annotations([by_id[row["id"]]["annotators"][a]]) for a in ANNOTATORS}
        if row["annotators"] != expected:
            raise ValueError("public case summary differs from original private samples")
    groups = {a: [by_id[case]["annotators"][a] for case in CASES] for a in ANNOTATORS}
    pooled = [by_id[case]["annotators"][a] for case in CASES for a in ANNOTATORS]
    return {"recordings": len(CASES), "recording_annotations": len(CASES) * len(ANNOTATORS),
            "by_annotator": {a: summarize_annotations(groups[a]) for a in ANNOTATORS},
            "pooled_annotation_judgments": summarize_annotations(pooled)}


def analyze_private(work, replay_report):
    """Analyze already-gated private files; caller enforces frozen identities first."""
    work = Path(work)
    cases = replay_report.get("cases", [])
    if (replay_report.get("status") != "complete" or replay_report.get("all_cases_complete") is not True
            or len(cases) != len(CASES) or {r.get("id") for r in cases} != set(CASES)
            or any(r.get("status") != "scored" for r in cases)):
        raise ValueError("complete frozen forty-recording replay required")
    by_id = {row["id"]: row for row in cases}
    rows, details = [], []
    for case in CASES:
        row = by_id[case]
        directory, duration = work / case, row["duration_seconds"]
        notes, references = {}, {}
        for arm in ARMS:
            raw = _read(directory / (arm + ".json"))
            if sha256(raw) != row["arms"][arm]["event_sha256"]:
                raise ValueError("prediction identity changed before diagnostics")
            notes[arm] = parse_notes(raw, duration)[0]
        for annotator in ANNOTATORS:
            raw = _read(directory / (annotator + ".csv"))
            if sha256(raw) != row["reference_sha256"][annotator]:
                raise ValueError("reference identity changed before diagnostics")
            references[annotator] = parse_reference(raw)
        raw = _read(directory / "observations.npz")
        if sha256(raw) != row["observation_sha256"]:
            raise ValueError("observation identity changed before diagnostics")
        # Parse exactly the bytes whose digest was checked, not a second file read.
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            hz, path = archive["hz"], archive["gaussian_exponent_1_path"]
        row, detail = analyze_case(case, notes, references, hz, path, duration)
        rows.append(row)
        details.append(detail)
    aggregate = aggregate_cases(rows, details)
    if aggregate is None:
        raise ValueError("all case diagnostics required")
    return {"cases": rows, "aggregate": aggregate}, details
