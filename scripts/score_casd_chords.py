"""Score SheetSage2 chord predictions against every CASD expert annotation.

Usage: python scripts/score_casd_chords.py reference.json prediction.json result.json
Requires: pip install mir_eval
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def intervals_from_prediction(prediction: dict, end: float) -> tuple[np.ndarray, list[str]]:
    events = prediction.get("chords", [])
    if not events:
        raise ValueError("Prediction contains no chord events")
    events = sorted(events, key=lambda x: x["time_seconds"])
    if events[0]["time_seconds"] < 0:
        raise ValueError("Negative chord start")
    starts = [float(x["time_seconds"]) for x in events]
    if len(set(starts)) != len(starts):
        raise ValueError("Duplicate chord timestamps")
    boundaries = starts + [end]
    intervals = []
    labels = []
    if starts[0] > 0:
        intervals.append([0., starts[0]])
        labels.append("N")
    for i, event in enumerate(events):
        if boundaries[i] >= boundaries[i + 1]:
            if boundaries[i] >= end:
                break
            raise ValueError("Invalid prediction intervals")
        intervals.append([boundaries[i], boundaries[i + 1]])
        labels.append(str(event["label"]))
    return np.asarray(intervals, dtype=float), labels


def score(reference: dict, prediction: dict) -> dict:
    import mir_eval
    results = []
    for ann in reference["annotators"]:
        segments = ann["intervals"]
        if not segments:
            continue
        ref_intervals = np.asarray([[x["start"], x["end"]] for x in segments], dtype=float)
        ref_labels = [x["label"] for x in segments]
        end = float(ref_intervals[-1, 1])
        est_intervals, est_labels = intervals_from_prediction(prediction, end)
        est_intervals, est_labels = mir_eval.util.adjust_intervals(
            est_intervals, est_labels, ref_intervals[0, 0], end, "N", "N"
        )
        merged, ref_aligned, est_aligned = mir_eval.util.merge_labeled_intervals(
            ref_intervals, ref_labels, est_intervals, est_labels
        )
        weights = mir_eval.util.intervals_to_durations(merged)
        metrics = {}
        for name in ("root", "majmin", "thirds", "triads", "sevenths"):
            comparison = getattr(mir_eval.chord, name)(ref_aligned, est_aligned)
            metrics[name] = float(mir_eval.chord.weighted_accuracy(comparison, weights))
        results.append({"annotator_index": ann["index"], "metrics": metrics})
    if not results:
        raise ValueError("Reference contains no nonempty chord annotations")
    return {
        "schema_version": 1, "dataset": "CASD", "metric": "duration_weighted_chord_recall",
        "annotators": results,
        "mean_by_metric": {
            name: float(np.mean([r["metrics"][name] for r in results]))
            for name in results[0]["metrics"]
        },
        "warning": "Scores require exactly aligned audio and annotations; model agreement is not ground truth.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
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
