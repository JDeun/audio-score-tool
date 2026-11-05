"""Compare manual Chordify and SheetSage2 events to independent chord/beat references.

Requires optional mir_eval (version 0.8.2 tested). No Chordify API, scraping,
media download, model inference, or competitive output as ground truth.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import mean

import numpy as np

from scripts.score_casd_chords import intervals_from_prediction, score

_HASH = re.compile(r"^[0-9a-f]{64}$")
_METRICS = ("root", "majmin", "thirds", "triads", "sevenths")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event_times(record: dict, key: str, *, duration: float) -> np.ndarray:
    raw = record.get(key, [])
    if not isinstance(raw, list):
        raise ValueError(f"{key} must be an event array")
    output = []
    previous = -1.0
    for event in raw:
        if not isinstance(event, dict):
            raise ValueError(f"{key} events must be objects")
        at = event.get("time_seconds")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            raise ValueError(f"{key} timestamps must be numeric")
        point = float(at)
        if not math.isfinite(point) or not 0 <= point < duration or point <= previous:
            raise ValueError(f"{key} timestamps must be strictly increasing within duration")
        output.append(point)
        previous = point
    return np.asarray(output, dtype=float)


def _compare_prediction(record: dict, *, duration: float, fingerprint: str, label: str) -> None:
    if record.get("schema_version") != 1 or record.get("recording_sha256") != fingerprint:
        raise ValueError(f"{label} lacks a matching recording SHA-256")
    actual = record.get("duration_seconds")
    if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(actual):
        raise ValueError(f"{label} lacks a finite duration_seconds")
    if abs(float(actual) - duration) > 0.001:
        raise ValueError(f"{label} duration_seconds differs from the reference")
    chords = record.get("chords")
    if not isinstance(chords, list) or not chords:
        raise ValueError(f"{label} has no chord timeline; use explicit N events if needed")
    _event_times(record, "chords", duration=duration)
    _event_times(record, "beats", duration=duration)
    _event_times(record, "downbeats", duration=duration)


def _no_chord_recall(reference: dict, prediction: dict, duration: float) -> float | None:
    """Duration-weighted explicit N-label recall against an independent annotator."""
    times, labels = intervals_from_prediction(prediction, duration)
    no_chord_time = 0.0
    recovered_time = 0.0
    segments = reference["intervals"]
    for segment in segments:
        if segment["label"].strip().upper() not in {"N", "N.C.", "NO_CHORD"}:
            continue
        start, end = float(segment["start"]), float(segment["end"])
        no_chord_time += end - start
        for (begin, finish), label in zip(times, labels, strict=True):
            overlap = max(0.0, min(end, finish) - max(start, begin))
            if label.strip().upper() in {"N", "N.C.", "NO_CHORD"}:
                recovered_time += overlap
    return round(recovered_time / no_chord_time, 8) if no_chord_time > 0 else None


def _beat_score(ref: np.ndarray, est: np.ndarray) -> float | None:
    if len(ref) < 2:
        return None
    if len(est) < 2:
        return 0.0
    import mir_eval

    return float(mir_eval.beat.f_measure(ref, est, f_measure_threshold=0.07))


def compare_chord_predictions(
    reference: dict,
    manual: dict,
    sheetsage: dict,
    *,
    inputs: dict[str, str] | None = None,
) -> dict:
    """Score independently annotated chord, beat and downbeat tracks.

    Fails closed on mismatched audio identities. Operator-supplied hashes are
    metadata claims and do not substitute for an audio licensing audit.
    """
    import mir_eval

    fingerprint = reference.get("recording_sha256")
    if not isinstance(fingerprint, str) or not _HASH.fullmatch(fingerprint):
        raise ValueError("independent reference needs recording_sha256")
    duration = reference.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise ValueError("reference duration_seconds must be numeric")
    duration = float(duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("reference duration_seconds must be finite and positive")
    annotators = reference.get("annotators")
    if not isinstance(annotators, list) or not annotators:
        raise ValueError("independent reference needs at least one annotator")

    for label, candidate in (("manual", manual), ("sheetsage2", sheetsage)):
        _compare_prediction(candidate, duration=duration, fingerprint=fingerprint, label=label)

    for ann in annotators:
        if not isinstance(ann, dict) or not isinstance(ann.get("intervals"), list):
            raise ValueError("reference annotator intervals are required")
        last = 0.0
        for interval in ann["intervals"]:
            if not isinstance(interval, dict) or not isinstance(interval.get("label"), str):
                raise ValueError("reference chord annotation must have a label")
            start, end = interval.get("start"), interval.get("end")
            if (
                isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < last or start < 0 or end <= start or end > duration + 1e-6
            ):
                raise ValueError("reference chords must be nonoverlapping valid intervals")
            last = float(end)

    manual_scored = score(reference, manual)
    sheetsage_scored = score(reference, sheetsage)
    # Agreement only: the first candidate is *not* a reference annotation.
    # Convert its predictions to intervals for numeric comparison, keeping the
    # result in a separately named field that cannot be misread as accuracy.
    synthetic_intervals, synthetic_labels = intervals_from_prediction(manual, duration)
    artificial_reference = {
        "annotators": [{
            "index": 0,
            "intervals": [
                {"start": float(start), "end": float(end), "label": chord}
                for (start, end), chord in zip(synthetic_intervals, synthetic_labels, strict=True)
            ],
        }]
    }
    agreement = score(artificial_reference, sheetsage)

    reference_beats = _event_times(reference, "beats", duration=duration)
    reference_downbeats = _event_times(reference, "downbeats", duration=duration)
    by_model = {}
    for name, events, result in (
        ("manual", manual, manual_scored), ("sheetsage2", sheetsage, sheetsage_scored),
    ):
        estimated_beats = _event_times(events, "beats", duration=duration)
        estimated_downbeats = _event_times(events, "downbeats", duration=duration)
        segmentation = []
        nc = []
        est_intervals, _labels = intervals_from_prediction(events, duration)
        for ann in annotators:
            ref_intervals = np.asarray(
                [[x["start"], x["end"]] for x in ann["intervals"]], dtype=float,
            )
            if len(ref_intervals) >= 2 and len(est_intervals) >= 2:
                try:
                    _precision, _recall, f1 = mir_eval.segment.boundary_detection(
                        ref_intervals, est_intervals, window=0.5, trim=True,
                    )
                except ValueError:
                    f1 = None
                segmentation.append(float(f1) if f1 is not None else None)
            nc.append(_no_chord_recall(ann, events, duration))
        by_model[name] = {
            "chords": result,
            "beat_f1": _beat_score(reference_beats, estimated_beats),
            "downbeat_f1": _beat_score(reference_downbeats, estimated_downbeats),
            "chord_boundary_f1_mean": (
                float(mean(item for item in segmentation if item is not None))
                if any(item is not None for item in segmentation) else None
            ),
            "no_chord_recall_mean": (
                float(mean(item for item in nc if item is not None))
                if any(item is not None for item in nc) else None
            ),
        }

    return {
        "schema_version": 1,
        "comparison_type": "independent_reference_vs_two_predictions",
        "recording_sha256": fingerprint,
        "duration_seconds": duration,
        "independent_annotators": len(annotators),
        "reference_annotation_sha256": inputs.get("reference") if inputs else None,
        "input_sha256": inputs,
        "by_model": by_model,
        "inter_model_agreement_not_accuracy": agreement["mean_by_metric"],
        "copyright_and_alignment_verification": "operator-provided; not independently certified",
        "commercial_model_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare independent chords/beat references")
    parser.add_argument("reference", type=Path, help="Independent multi-annotator JSON")
    parser.add_argument("manual", type=Path, help="Normalized user-supplied chord-grid JSON")
    parser.add_argument("sheetsage", type=Path, help="SheetSage2 events JSON with audio identity")
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()
    files = {"reference": args.reference, "manual": args.manual, "sheetsage2": args.sheetsage}
    payloads = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in files.items()}
    result = compare_chord_predictions(
        payloads["reference"], payloads["manual"], payloads["sheetsage2"],
        inputs={name: _sha(path) for name, path in files.items()},
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    if args.output_csv is not None:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        with args.output_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["candidate", *_METRICS, "beat_f1", "downbeat_f1", "boundary_f1", "no_chord_recall"])
            for name, item in result["by_model"].items():
                writer.writerow([
                    name,
                    *(item["chords"]["mean_by_metric"][metric] for metric in _METRICS),
                    item["beat_f1"], item["downbeat_f1"],
                    item["chord_boundary_f1_mean"], item["no_chord_recall_mean"],
                ])
    print(json.dumps({"by_model": {name: item["chords"]["mean_by_metric"]
                                  for name, item in result["by_model"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
