"""Describe boundaries in the frozen authored-F0 replay, without inference.

All comparisons use the authored 10 ms integer clock.  A transition is between
observations i-1 and i; clip starts have no predecessor.  The retained terminal
observation is an observation, not an extra audio frame.  Nearest-transition
ties select the earlier transition.  These are exact-frame descriptors, not a
new accuracy metric or a proposed segmentation threshold.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

ARMS = (
    "pitch_runs", "note_state_hmm", "gaussian_exponent_1", "phase_balanced",
    "positive_voicing_08", "silent_self_099", "hop_unscaled",
)
PATH_ARMS = ARMS[1:]
DT = .01
SPEC_KEYS = ("id", "kind", "pitch", "frames", "context", "gap", "interval")


def planned_specs():
    """Independent inventory of the already-frozen 245 inputs; no predictions."""
    result = []

    def add(kind, **kwargs):
        result.append({"id": f"{kind}_{len(result) + 1:03d}", "kind": kind,
                       "pitch": 57, "frames": 120, "context": "interior",
                       "gap": 0, "interval": 0, **kwargs})

    for pitch in (33, 45, 57, 69, 81):
        for frames in (8, 12, 20, 30, 50, 80, 120):
            for context in ("interior", "start", "end", "full"):
                add("single", pitch=pitch, frames=frames, context=context)
    for pitch in (45, 57, 69):
        for frames in (12, 30, 80):
            for gap in (0, 1, 2, 5, 10, 30):
                add("repeat", pitch=pitch, frames=frames, gap=gap)
    for pitch in (45, 57, 69):
        for interval in (1, 7, 12):
            for frames in (12, 50):
                for gap in (0, 5):
                    add("change", pitch=pitch, frames=frames, interval=interval, gap=gap)
    for frames in (20, 100, 200):
        add("silence", frames=frames, context="full")
    for pitch in (45, 57, 69):
        for kind in ("vibrato", "drift"):
            add(kind, pitch=pitch)
    for pitch in (45, 57, 69):
        for gap in (1, 5):
            add("dropout", pitch=pitch, gap=gap)
    return result


def identity(array):
    value = np.ascontiguousarray(array)
    if value.ndim != 1 or value.dtype.kind not in "fiu" or not np.isfinite(value).all():
        raise ValueError("finite one-dimensional numeric observations required")
    return {"dtype": value.dtype.str, "shape": list(value.shape),
            "sha256": hashlib.sha256(value.tobytes()).hexdigest()}


def _frame(seconds):
    if isinstance(seconds, bool) or not np.isfinite(seconds) or seconds < 0:
        raise ValueError("nonnegative finite synthetic timestamp required")
    frame = int(round(seconds / DT))
    if abs(seconds - frame * DT) > 1e-9:
        raise ValueError("authored synthetic time must lie on the fixed clock")
    return frame


def _event_frames(events, duration_frames):
    result = []
    previous = -1
    for event in events:
        if (not isinstance(event, dict) or set(event) != {"pitch", "onset", "offset", "is_drum"}
                or type(event["pitch"]) is not int or event["is_drum"] is not False):
            raise ValueError("canonical synthetic note required")
        first, stop = _frame(event["onset"]), _frame(event["offset"])
        if first >= stop or stop > duration_frames or first < previous:
            raise ValueError("invalid synthetic event interval/order")
        result.append((first, stop))
        previous = first
    return result


def _nearest(indices, frame):
    if not len(indices):
        return None
    selected = min((int(i) for i in indices), key=lambda i: (abs(i - frame), i))
    return selected - frame


def boundary_rows(reference, events_by_arm, hz, paths, duration):
    """Describe every authored endpoint, including alternative interpretations.

    A spanning event has onset < boundary < offset.  Labels are -1 for Silent
    and the decoded pitch-bin index for Attack/Stable.  A phase-only change can
    therefore leave the decoded label unchanged.  Endpoint support is counted
    by time alone and does not imply pitch-correct matching.
    """
    duration_frames = _frame(duration)
    hz = np.asarray(hz)
    if (hz.ndim != 1 or len(hz) != duration_frames + 1 or hz.dtype.kind not in "fiu"
            or not np.isfinite(hz).all() or np.any(hz < 0)):
        raise ValueError("synthetic observations must retain exactly one terminal sample")
    if set(events_by_arm) != set(ARMS) or set(paths) != set(PATH_ARMS):
        raise ValueError("all seven event arms and six HMM paths required")
    event_frames = {arm: _event_frames(events_by_arm[arm], duration_frames) for arm in ARMS}
    reference_frames = _event_frames(reference, duration_frames)
    prepared = {}
    for arm in PATH_ARMS:
        states = np.asarray(paths[arm])
        if (states.ndim != 1 or len(states) != len(hz) or states.dtype.kind not in "iu"
                or np.any(states < 0) or np.any(states >= 435)):
            raise ValueError("invalid frozen synthetic state path")
        phases, bins = states % 3, states // 3
        labels = np.where(phases == 2, -1, bins)
        prepared[arm] = (states, phases, bins, labels,
                         np.flatnonzero(np.diff(labels)) + 1,
                         np.flatnonzero(np.diff(phases)) + 1)
    roles = {}
    for index, (first, stop) in enumerate(reference_frames):
        roles.setdefault(first, {"onset_reference_ids": [], "offset_reference_ids": []})["onset_reference_ids"].append(index)
        roles.setdefault(stop, {"onset_reference_ids": [], "offset_reference_ids": []})["offset_reference_ids"].append(index)
    result = []
    for frame in sorted(roles):
        before = float(hz[frame - 1]) if frame else None
        after = float(hz[frame])
        row = {"frame": frame, "seconds": frame * DT, **roles[frame],
               "at_audio_start": frame == 0, "at_audio_end": frame == duration_frames,
               "raw_before_hz": before, "raw_after_hz": after,
               "raw_midi_step": float(12 * np.log2(after / before))
               if before is not None and before > 0 and after > 0 else None, "arms": {}}
        for arm in ARMS:
            intervals = event_frames[arm]
            descriptor = {
                "emitted_onsets_at_frame": sum(first == frame for first, _ in intervals),
                "emitted_offsets_at_frame": sum(stop == frame for _, stop in intervals),
                "emitted_events_spanning_frame": sum(first < frame < stop for first, stop in intervals),
            }
            if arm in prepared:
                states, phases, bins, labels, label_changes, phase_changes = prepared[arm]
                descriptor.update({
                    "state_before": int(states[frame - 1]) if frame else None,
                    "state_after": int(states[frame]),
                    "phase_before": int(phases[frame - 1]) if frame else None,
                    "phase_after": int(phases[frame]),
                    "pitch_bin_before": int(bins[frame - 1]) if frame else None,
                    "pitch_bin_after": int(bins[frame]),
                    "state_changed": bool(states[frame - 1] != states[frame]) if frame else None,
                    "decoded_label_changed": bool(labels[frame - 1] != labels[frame]) if frame else None,
                    "nearest_label_change_delta_frames": _nearest(label_changes, frame),
                    "nearest_phase_change_delta_frames": _nearest(phase_changes, frame),
                })
            row["arms"][arm] = descriptor
        result.append(row)
    return result


def diagnose_case(row, hz, paths):
    """Describe an already-scored row; do not generate F0 or decode a model."""
    if (set(row.get("arms", {})) != set(ARMS) or row.get("id") != row.get("spec", {}).get("id")
            or set(row.get("spec", {})) != set(SPEC_KEYS)):
        raise ValueError("complete canonical synthetic case required")
    spec = row["spec"]
    eligible = spec["kind"] not in ("silence", "dropout") and not (
        spec["kind"] == "repeat" and spec["gap"] == 0)
    ambiguous = spec["kind"] == "dropout" or (spec["kind"] == "repeat" and spec["gap"] == 0)
    if type(row["accuracy_eligible"]) is not bool or row["accuracy_eligible"] != eligible:
        raise ValueError("synthetic accuracy eligibility changed")
    if identity(hz) != row["observation"]:
        raise ValueError("synthetic F0 identity changed")
    if set(paths) != set(PATH_ARMS):
        raise ValueError("exact frozen path inventory required")
    for arm in PATH_ARMS:
        if identity(paths[arm]) != row["arms"][arm]["state_path"]:
            raise ValueError("synthetic path identity changed")
    if bool(row["alternative_truth"]) != ambiguous:
        raise ValueError("both ambiguous interpretations must be retained")
    events = {arm: row["arms"][arm]["events"] for arm in ARMS}
    summaries = {}
    for arm in ARMS:
        prior = row["arms"][arm]
        if type(prior["count"]) is not int or prior["count"] != len(events[arm]):
            raise ValueError("synthetic event count changed")
        if eligible:
            if (not isinstance(prior["metrics"], dict)
                    or set(prior["metrics"]) != {"onset_f1", "onset_offset_f1"}
                    or any(type(v) not in (int, float) or not np.isfinite(v) or not 0 <= v <= 1
                           for v in prior["metrics"].values())):
                raise ValueError("eligible synthetic score required")
        elif prior["metrics"] is not None:
            raise ValueError("ambiguous/silence cases cannot acquire a score")
        summaries[arm] = {key: prior[key] for key in ("count", "event_sha256", "metrics", "diagnostics")}
        if arm in PATH_ARMS:
            summaries[arm]["state_path"] = prior["state_path"]
    return {"id": row["id"], "spec": dict(spec), "duration_seconds": row["duration_seconds"],
            "accuracy_eligible": eligible, "ambiguous": ambiguous,
            "truth_note_count": len(row["truth"]), "alternative_truth_note_count": len(row["alternative_truth"]),
            "observation": row["observation"], "arms": summaries,
            "boundaries": {key: boundary_rows(row[key], events, hz, paths, row["duration_seconds"])
                           for key in ("truth", "alternative_truth")}}


def _group_summary(rows):
    eligible = [row for row in rows if row["accuracy_eligible"]]
    result = {"cases": len(rows), "accuracy_eligible_cases": len(eligible),
              "ambiguous_cases": sum(row["ambiguous"] for row in rows),
              "silence_cases": sum(row["spec"]["kind"] == "silence" for row in rows), "arms": {}}
    for arm in ARMS:
        joins = [boundary for row in rows if row["spec"]["kind"] == "change" and row["spec"]["gap"] == 0
                 for boundary in row["boundaries"]["truth"]
                 if boundary["onset_reference_ids"] and boundary["offset_reference_ids"]]
        result["arms"][arm] = {
            "predicted_notes": sum(row["arms"][arm]["count"] for row in rows),
            "empty_output_cases": sum(row["arms"][arm]["count"] == 0 for row in rows),
            "onset_f1": float(np.mean([row["arms"][arm]["metrics"]["onset_f1"] for row in eligible])) if eligible else None,
            "onset_offset_f1": float(np.mean([row["arms"][arm]["metrics"]["onset_offset_f1"] for row in eligible])) if eligible else None,
            "joined_pitch_change_boundaries": len(joins),
            "joined_pitch_change_with_event_spanning": sum(
                boundary["arms"][arm]["emitted_events_spanning_frame"] > 0 for boundary in joins),
            "joined_pitch_change_with_both_emitted_endpoints": sum(
                boundary["arms"][arm]["emitted_onsets_at_frame"] > 0
                and boundary["arms"][arm]["emitted_offsets_at_frame"] > 0 for boundary in joins),
        }
    return result


def summarize(rows):
    expected = planned_specs()
    if len(rows) != len(expected) or [row.get("spec") for row in rows] != expected:
        raise ValueError("exact ordered frozen synthetic population required")
    if any(set(row.get("arms", {})) != set(ARMS) for row in rows):
        raise ValueError("incomplete synthetic diagnostic arms")
    result = {"all": _group_summary(rows), "by_kind": {}, "change_cells": [], "repeat_cells": []}
    if (result["all"]["accuracy_eligible_cases"] != 227 or result["all"]["ambiguous_cases"] != 15
            or result["all"]["silence_cases"] != 3):
        raise ValueError("synthetic denominator changed")
    for kind in ("single", "repeat", "change", "silence", "vibrato", "drift", "dropout"):
        result["by_kind"][kind] = _group_summary([row for row in rows if row["spec"]["kind"] == kind])
    # Complete predeclared cells, not a selection based on observed performance.
    for kind, fields, key in (("change", ("pitch", "frames", "gap", "interval"), "change_cells"),
                              ("repeat", ("pitch", "frames", "gap"), "repeat_cells")):
        cells = sorted({tuple(row["spec"][field] for field in fields)
                        for row in rows if row["spec"]["kind"] == kind})
        for values in cells:
            subset = [row for row in rows if row["spec"]["kind"] == kind
                      and tuple(row["spec"][field] for field in fields) == values]
            result[key].append({"cell": dict(zip(fields, values, strict=True)), "summary": _group_summary(subset)})
    result["single_cells"] = [
        {"cell": {"pitch": pitch, "frames": frames, "context": context},
         "summary": _group_summary([row for row in rows if row["spec"]["kind"] == "single"
                                    and row["spec"]["pitch"] == pitch and row["spec"]["frames"] == frames
                                    and row["spec"]["context"] == context])}
        for pitch in (33, 45, 57, 69, 81) for frames in (8, 12, 20, 30, 50, 80, 120)
        for context in ("interior", "start", "end", "full")]
    return result


def diagnose_report(work: Path, replay):
    if (replay.get("status") != "complete" or replay.get("planned_cases") != 245
            or replay.get("planned_arms") != list(ARMS)
            or replay.get("all_predictions_saved_before_scoring") is not True
            or [row.get("spec") for row in replay.get("cases", [])] != planned_specs()):
        raise ValueError("complete frozen synthetic replay required")
    result = {"schema": "note-boundary-synthetic-v1", "status": "started", "cases": [],
              "planned_cases": 245, "planned_arms": list(ARMS), "inference_performed": False,
              "clock_seconds": DT, "nearest_transition_tie": "earlier_frame",
              "quality_approved": False, "heldout_generalization": False, "aggregate": None}
    manifest = {}
    checked_events = checked_paths = checked_inputs = 0
    for row in replay["cases"]:
        directory = work / row["id"]
        manifest[row["id"]] = {}
        for arm in ARMS:
            path = directory / f"{arm}.json"
            if path.is_symlink():
                raise ValueError("synthetic event symlink rejected")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != row["arms"][arm]["event_sha256"] or json.loads(raw) != row["arms"][arm]["events"]:
                raise ValueError("saved synthetic event identity changed")
            manifest[row["id"]][arm] = digest
            checked_events += 1
        observations = directory / "observations.npz"
        if observations.is_symlink():
            raise ValueError("synthetic observation symlink rejected")
        with np.load(observations, allow_pickle=False) as package:
            if len(package.files) != 7 or set(package.files) != {"hz", *PATH_ARMS}:
                raise ValueError("exact synthetic private array inventory required")
            hz = package["hz"]
            paths = {arm: package[arm] for arm in PATH_ARMS}
        result["cases"].append(diagnose_case(row, hz, paths))
        checked_inputs += 1
        checked_paths += len(paths)
    fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if fingerprint != replay.get("predictions_manifest_sha256"):
        raise ValueError("synthetic prediction manifest changed")
    result["identities_checked"] = {"event_files": checked_events, "input_arrays": checked_inputs,
                                    "state_path_arrays": checked_paths}
    result["predictions_manifest_sha256"] = fingerprint
    result["aggregate"] = summarize(result["cases"])
    result["status"] = "complete"
    return result
