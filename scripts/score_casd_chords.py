"""Score independent, fully annotated chord references with mir_eval.

Usage: python scripts/score_casd_chords.py reference.json prediction.json result.json
Requires the optional mir_eval package. The script does not fetch audio or
validate the legal rights of the operator-provided source.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

_TOLERANCE = 1e-5
_METRICS = ("root", "majmin", "thirds", "triads", "sevenths")


def _time(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} time must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} time must be finite")
    return result


def _duration(reference: dict) -> float:
    raw = reference.get("duration_seconds")
    if raw is None:
        try:
            raw = reference["annotators"][0]["intervals"][-1]["end"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("reference has no complete annotation duration") from exc
    duration = _time(raw, "reference duration")
    if duration <= 0:
        raise ValueError("reference duration must be positive")
    return duration


def intervals_from_prediction(prediction: dict, end: float) -> tuple[np.ndarray, list[str]]:
    """Create one ordered prediction timeline; leading silence is predicted N."""
    end = _time(end, "recording end")
    if end <= 0 or not isinstance(prediction, dict):
        raise ValueError("recording end and prediction must be valid")
    events = prediction.get("chords")
    if not isinstance(events, list) or not events:
        raise ValueError("Prediction contains no chord events")
    starts = []
    labels = []
    previous = -1.0
    for entry in events:
        if not isinstance(entry, dict):
            raise ValueError("prediction chord events must be objects")
        at = _time(entry.get("time_seconds"), "chord")
        if not 0 <= at < end or at <= previous:
            raise ValueError("chord events must be ordered and within recording duration")
        chord = entry.get("label")
        if not isinstance(chord, str) or not chord.strip():
            raise ValueError("prediction chord must have a nonempty label")
        starts.append(at)
        labels.append(chord.strip())
        previous = at
    boundaries = starts + [end]
    intervals = [[starts[i], boundaries[i + 1]] for i in range(len(starts))]
    if starts[0] > 0:
        intervals.insert(0, [0.0, starts[0]])
        labels.insert(0, "N")
    return np.asarray(intervals, dtype=float), labels


def _validated_reference(reference: dict) -> tuple[list[tuple[int, np.ndarray, list[str]]], float]:
    if not isinstance(reference, dict):
        raise ValueError("reference must be a JSON object")
    annotations = reference.get("annotators")
    if not isinstance(annotations, list) or not annotations:
        raise ValueError("reference needs at least one annotator")
    duration = _duration(reference)
    verified = []
    seen: set[int] = set()
    for ann in annotations:
        if not isinstance(ann, dict) or not isinstance(ann.get("intervals"), list):
            raise ValueError("reference annotator intervals must be an array")
        index = ann.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index in seen:
            raise ValueError("reference annotator indices must be unique nonnegative integers")
        seen.add(index)
        segments = ann["intervals"]
        if not segments:
            raise ValueError("reference annotator cannot be empty")
        last = 0.0
        intervals = []
        labels = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("reference chord interval must be an object")
            start = _time(segment.get("start"), "reference start")
            finish = _time(segment.get("end"), "reference end")
            label = segment.get("label")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("reference labels must be nonempty")
            if (abs(start - last) > _TOLERANCE or start < 0
                    or finish <= start or finish > duration + _TOLERANCE):
                raise ValueError("reference must completely cover recording without gaps or overlaps")
            intervals.append([start, finish])
            labels.append(label.strip())
            last = finish
        if abs(last - duration) > _TOLERANCE:
            raise ValueError("reference must completely cover recording duration")
        verified.append((index, np.asarray(intervals, dtype=float), labels))
    return verified, duration


def score(reference: dict, prediction: dict) -> dict:
    """Evaluate every independent annotator; never treat model agreement as truth."""
    import mir_eval

    annotators, duration = _validated_reference(reference)
    if not isinstance(prediction, dict):
        raise ValueError("prediction must be a JSON object")
    ref_sha, pred_sha = reference.get("recording_sha256"), prediction.get("recording_sha256")
    if ref_sha is not None and pred_sha is not None and ref_sha != pred_sha:
        raise ValueError("reference/prediction recording SHA-256 differs")
    predicted_duration = prediction.get("duration_seconds")
    if predicted_duration is not None and abs(_time(predicted_duration, "prediction duration")
                                             - duration) > 0.001:
        raise ValueError("prediction duration differs from the independent reference")
    est_intervals, est_labels = intervals_from_prediction(prediction, duration)
    results = []
    for index, ref_intervals, ref_labels in annotators:
        est_adjusted, labels_adjusted = mir_eval.util.adjust_intervals(
            est_intervals, est_labels, float(ref_intervals[0, 0]), duration, "N", "N",
        )
        merged, ref_aligned, est_aligned = mir_eval.util.merge_labeled_intervals(
            ref_intervals, ref_labels, est_adjusted, labels_adjusted,
        )
        weights = mir_eval.util.intervals_to_durations(merged)
        metrics = {}
        for name in _METRICS:
            comparator = getattr(mir_eval.chord, name)(ref_aligned, est_aligned)
            metrics[name] = float(mir_eval.chord.weighted_accuracy(comparator, weights))
        results.append({"annotator_index": index, "metrics": metrics})
    return {
        "schema_version": 1,
        "dataset": reference.get("dataset", "unspecified"),
        "metric": "duration_weighted_chord_recall",
        "reference_duration_seconds": duration,
        "annotators": results,
        "mean_by_metric": {
            name: float(np.mean([item["metrics"][name] for item in results]))
            for name in _METRICS
        },
        "warning": (
            "Scores require aligned licensed recording and full independent reference; "
            "model agreement is not ground truth."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score independent chord annotations")
    parser.add_argument("reference", type=Path)
    parser.add_argument("prediction", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = score(
        json.loads(args.reference.read_text(encoding="utf-8")),
        json.loads(args.prediction.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["mean_by_metric"], indent=2))


if __name__ == "__main__":
    main()
