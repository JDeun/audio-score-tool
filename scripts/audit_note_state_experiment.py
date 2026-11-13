"""Independently rescore saved note-state predictions without running inference.

The auditor reads the original private WAV/observation/note/reference files,
checks their public hashes, parses the original-Hz references independently and
calls mir_eval directly. It imports neither the experiment runner, its model nor
the shared repository scorer. All forty recordings and both annotators remain
required. A successful post-hoc audit verifies saved data and arithmetic, not the
historical order of file creation or an independent annotation/model.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

CASES = tuple(f"vocadito_{i}" for i in range(1, 41))
ARMS = (
    "pitch_runs", "pitch_hysteresis", "pitch_hysteresis_reattack",
    "note_state_hmm", "note_state_hmm_rms",
)
ANNOTATORS = ("A1", "A2")
OBSERVATIONS = ("hz", "probability", "attacks", "rms", "phase_path", "rms_phase_path")
NOTE_FIELDS = ("pitch", "onset", "offset", "is_drum")
METRICS = ("onset_f1", "onset_offset_f1")
RATES = ("onset_precision", "onset_recall", "offset_precision", "offset_recall")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fingerprint(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def _json(raw: bytes):
    def invalid(_value):
        raise ValueError("nonfinite JSON scalar")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=invalid, object_pairs_hook=unique)


def _read(path: Path, max_bytes=16_000_000) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("private file missing, linked or oversized")
    return path.read_bytes()


class Checks:
    def __init__(self):
        self.counts = Counter()
        self.maximum_numeric_difference = 0.0

    def equal(self, actual, expected, label):
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                raise ValueError(label + ": expected object")
            for key, value in expected.items():
                if key not in actual:
                    raise ValueError(label + ": missing field " + str(key))
                self.equal(actual[key], value, label + "/" + str(key))
            return
        if isinstance(expected, (list, tuple)):
            if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
                raise ValueError(label + ": sequence length/type mismatch")
            for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
                self.equal(left, right, label + "/" + str(index))
            return
        self.counts[label.split("/")[0]] += 1
        if isinstance(expected, bool):
            if not isinstance(actual, bool) or actual is not expected:
                raise ValueError(label + ": boolean mismatch")
        elif isinstance(expected, int):
            if not isinstance(actual, int) or isinstance(actual, bool) or actual != expected:
                raise ValueError(label + ": integer mismatch")
        elif isinstance(expected, float):
            if (not isinstance(actual, (int, float)) or isinstance(actual, bool)
                    or not math.isfinite(actual) or not math.isfinite(expected)):
                raise ValueError(label + ": invalid numeric value")
            difference = abs(actual - expected)
            self.maximum_numeric_difference = max(self.maximum_numeric_difference, difference)
            if difference > 1e-10:
                raise ValueError(label + ": numeric mismatch")
        elif actual != expected:
            raise ValueError(label + ": value mismatch")


def parse_notes(raw: bytes, duration: float):
    """Validate the exact saved Note payload without repository model imports."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("invalid audio duration")
    values = _json(raw)
    if not isinstance(values, list):
        raise ValueError("notes must be an array")
    canonical, previous_end = [], 0.0
    for value in values:
        if not isinstance(value, dict) or set(value) != set(NOTE_FIELDS):
            raise ValueError("invalid note fields")
        pitch, onset, offset, drum = (value[key] for key in NOTE_FIELDS)
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not 0 <= pitch <= 127:
            raise ValueError("invalid note pitch")
        if drum is not False:
            raise ValueError("vocal note cannot be a drum")
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
               for v in (onset, offset)):
            raise ValueError("invalid note endpoint")
        if (onset < 0 or offset > duration + 1e-10 or offset - onset < .080 - 1e-10
                or onset < previous_end - 1e-10):
            raise ValueError("note duration, bounds or monophonic ordering violated")
        canonical.append({key: value[key] for key in NOTE_FIELDS})
        previous_end = offset
    if raw != (json.dumps(canonical, indent=2, allow_nan=False) + "\n").encode():
        raise ValueError("note file is not the frozen canonical pretty encoding")
    intervals = np.asarray([(v["onset"], v["offset"]) for v in canonical], dtype=float).reshape(-1, 2)
    hz = np.asarray([440.0 * 2 ** ((v["pitch"] - 69) / 12) for v in canonical], dtype=float)
    return canonical, intervals, hz


def parse_reference(raw: bytes):
    """Keep original Hz and stable onset order; do not quantize annotations."""
    rows = []
    for row in csv.reader(io.StringIO(raw.decode("utf-8"))):
        if len(row) != 3:
            raise ValueError("reference row does not have start, Hz, duration")
        start, hz, duration = map(float, row)
        if (not all(math.isfinite(v) for v in (start, hz, duration))
                or start < 0 or hz <= 0 or duration <= 0):
            raise ValueError("invalid reference note")
        rows.append((start, start + duration, hz))
    if not rows:
        raise ValueError("empty human reference")
    rows.sort(key=lambda row: row[0])
    return np.asarray([(r[0], r[1]) for r in rows]), np.asarray([r[2] for r in rows])


def array_identity(array):
    value = np.asarray(array)
    return {"dtype": value.dtype.str, "shape": list(value.shape),
            "sha256": sha256(np.ascontiguousarray(value).tobytes())}


def check_observations(raw: bytes, recorded, checks: Checks):
    if not isinstance(recorded, dict) or set(recorded) != set(OBSERVATIONS):
        raise ValueError("observation inventory differs")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        if len(archive.files) != len(OBSERVATIONS) or set(archive.files) != set(OBSERVATIONS):
            raise ValueError("private observation inventory differs")
        arrays = {key: archive[key] for key in OBSERVATIONS}
    for name, value in arrays.items():
        if (value.ndim != 1 or value.dtype.kind not in "fiu"
                or not np.isfinite(value).all()):
            raise ValueError("invalid observation array " + name)
        checks.equal(recorded[name], array_identity(value), "observation_array_identity/" + name)
    frames = len(arrays["hz"])
    if frames == 0 or any(len(arrays[key]) != frames for key in OBSERVATIONS if key != "attacks"):
        raise ValueError("observation clock/shape mismatch")
    if (np.any(arrays["hz"] < 0) or np.any(arrays["rms"] < 0)
            or np.any(arrays["probability"] < 0) or np.any(arrays["probability"] > 1)
            or np.any(arrays["attacks"] < 0) or np.any(np.diff(arrays["attacks"]) <= 0)):
        raise ValueError("observation domain mismatch")
    if any(arrays[key].dtype.kind not in "iu" for key in ("phase_path", "rms_phase_path")):
        raise ValueError("state paths must use integer encodings")
    return {"frames": frames, "attacks": len(arrays["attacks"]), "arrays": len(arrays)}


def _metrics_for_pairs(pairs, reference_count, prediction_count):
    if len({pair[0] for pair in pairs}) != len(pairs) or len({pair[1] for pair in pairs}) != len(pairs):
        raise ValueError("matching is not one-to-one")
    if any(not 0 <= i < reference_count or not 0 <= j < prediction_count for i, j in pairs):
        raise ValueError("matching index outside population")
    matched = len(pairs)
    return {
        "matched": matched,
        "precision": matched / prediction_count if prediction_count else 0.,
        "recall": matched / reference_count,
        "f1": round(2 * matched / (reference_count + prediction_count), 8),
    }


def direct_score(reference, prediction):
    import mir_eval.transcription as transcription

    reference_intervals, reference_hz = reference
    intervals, hz = prediction
    values = {"reference_note_count": len(reference_hz)}
    reference_ids = {}
    for name, ratio in (("onset", None), ("onset_offset", .2)):
        pairs = transcription.match_notes(
            reference_intervals, reference_hz, intervals, hz,
            onset_tolerance=.05, pitch_tolerance=50., offset_ratio=ratio,
            offset_min_tolerance=.05,
        ) if len(hz) else []
        computed = _metrics_for_pairs(pairs, len(reference_hz), len(hz))
        values[name + "_f1"] = computed["f1"]
        values[name + "_matched"] = computed["matched"]
        values[name + "_unmatched_reference"] = len(reference_hz) - computed["matched"]
        values[name + "_unmatched_prediction"] = len(hz) - computed["matched"]
        rate_name = "offset" if name == "onset_offset" else "onset"
        values[rate_name + "_precision"] = computed["precision"]
        values[rate_name + "_recall"] = computed["recall"]
        reference_ids[name] = {int(pair[0]) for pair in pairs}
    return values, reference_ids


def aggregate_rows(rows):
    if (len(rows) != len(CASES) or [row.get("id") for row in rows] != list(CASES)
            or any(set(row.get("arms", {})) != set(ARMS) for row in rows)
            or any(set(row["arms"][arm].get("annotators", {})) != set(ANNOTATORS)
                   for row in rows for arm in ARMS)):
        raise ValueError("aggregate requires exact forty-case, five-arm, two-annotator population")
    result = {}
    for arm in ARMS:
        summary = {"predicted_notes": sum(row["arms"][arm]["count"] for row in rows)}
        for metric in METRICS:
            by_annotator = {
                ann: [row["arms"][arm]["annotators"][ann][metric] for row in rows]
                for ann in ANNOTATORS
            }
            means = [(by_annotator["A1"][i] + by_annotator["A2"][i]) / 2
                     for i in range(len(rows))]
            base = [math.fsum(row["arms"][ARMS[0]]["annotators"][ann][metric]
                             for ann in ANNOTATORS) / 2 for row in rows]
            if not all(math.isfinite(value) and 0 <= value <= 1
                       for values in by_annotator.values() for value in values):
                raise ValueError("invalid score in aggregate")
            changes = [value - old for value, old in zip(means, base, strict=True)]
            better = sum(value > 1e-8 for value in changes)
            worse = sum(value < -1e-8 for value in changes)
            summary[metric] = {
                "macro": math.fsum(means) / len(rows),
                "A1_macro": math.fsum(by_annotator["A1"]) / len(rows),
                "A2_macro": math.fsum(by_annotator["A2"]) / len(rows),
                "delta_vs_runs": math.fsum(changes) / len(rows),
                "recordings_improved": better, "recordings_worse": worse,
                "recordings_tied": len(rows) - better - worse,
            }
        for rate in RATES:
            summary[rate] = math.fsum(row["arms"][arm]["annotators"][ann][rate]
                                     for row in rows for ann in ANNOTATORS) / (len(rows) * 2)
        for prefix in ("onset", "onset_offset"):
            for kind in ("gained", "lost"):
                summary[prefix + "_" + kind + "_reference_count"] = sum(
                    len(row["arms"][arm]["annotators"][ann][prefix + "_" + kind + "_reference_ids"])
                    for row in rows for ann in ANNOTATORS)
        result[arm] = summary
    return result


def audit_private(work: Path, report_path: Path):
    import soundfile

    started = time.monotonic()
    if work.is_symlink() or not work.is_dir():
        raise ValueError("private workspace unavailable or linked")
    raw_report = _read(report_path, 32_000_000)
    report = _json(raw_report)
    checks = Checks()
    checks.equal(report.get("status"), "complete", "report_complete")
    checks.equal(report.get("all_cases_complete"), True, "report_complete")
    checks.equal(report.get("all_predictions_frozen_before_references"), True, "recorded_order_contract")
    checks.equal(report.get("reference_access_started_after_predicted_cases"), 40, "recorded_order_contract")
    checks.equal(report.get("planned_case_ids"), list(CASES), "exact_case_plan")
    checks.equal(report.get("planned_arms"), list(ARMS), "exact_arm_plan")
    parity = report.get("historical_baseline_parity")
    if not isinstance(parity, dict):
        raise ValueError("historical baseline parity gate is required")
    checks.equal(parity.get("all_equal"), True, "recorded_baseline_parity_gate")
    source_hashes = report.get("source_sha256")
    if not isinstance(source_hashes, dict) or "scripts/audit_note_state_experiment.py" not in source_hashes:
        raise ValueError("frozen source inventory missing auditor")
    repo = Path(__file__).resolve().parents[1]
    for relative, expected in source_hashes.items():
        path = repo / relative
        if not path.resolve().is_relative_to(repo):
            raise ValueError("frozen source path outside repository")
        checks.equal(sha256(_read(path)), expected, "frozen_source_identity")
    public_rows = report.get("cases", [])
    checks.equal([row.get("id") for row in public_rows], list(CASES), "exact_case_population")
    rescored_rows, summaries, manifest = [], [], {}
    for row in public_rows:
        case = row["id"]
        checks.equal(row.get("status"), "scored", "case_complete")
        directory = work / case
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("private case directory unavailable or linked")
        if set(row.get("arms", {})) != set(ARMS):
            raise ValueError("public arm inventory differs")
        wav = _read(directory / "source.wav", 60_000_000)
        checks.equal(sha256(wav), row["audio_sha256"], "original_source_identity")
        audio_info = soundfile.info(io.BytesIO(wav))
        duration = row["duration_seconds"]
        if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
                or not math.isfinite(duration) or duration <= 0
                or abs(duration - audio_info.frames / audio_info.samplerate) > 1 / 16000 + 1e-10):
            raise ValueError("recorded duration differs from original audio")
        checks.equal(audio_info.frames > 0, True, "source_header_nonempty")
        observations = _read(directory / "observations.npz")
        if "observation_sha256" in row:
            checks.equal(sha256(observations), row["observation_sha256"], "observation_file_identity")
        observation_summary = check_observations(observations, row["observations"], checks)
        predictions, note_payloads = {}, {}
        manifest[case] = {}
        for arm in ARMS:
            note_raw = _read(directory / (arm + ".json"))
            notes, intervals, hz = parse_notes(note_raw, duration)
            checks.equal(sha256(note_raw), row["arms"][arm]["event_sha256"], "complete_prediction_identity")
            checks.equal(len(notes), row["arms"][arm]["count"], "prediction_count")
            manifest[case][arm] = sha256(note_raw)
            note_payloads[arm] = notes
            predictions[arm] = intervals, hz
        references = {}
        for annotator in ANNOTATORS:
            raw = _read(directory / (annotator + ".csv"))
            checks.equal(sha256(raw), row["reference_sha256"][annotator], "original_reference_identity")
            references[annotator] = parse_reference(raw)
        f0_reference = _read(directory / "f0.csv")
        checks.equal(sha256(f0_reference), row["f0_reference_sha256"], "original_f0_reference_identity")
        computed_row = {"id": case, "arms": {}}
        base_ids = {}
        for arm in ARMS:
            computed_arm = {"count": len(note_payloads[arm]), "annotators": {}}
            public_arm = row["arms"][arm]
            if set(public_arm.get("annotators", {})) != set(ANNOTATORS):
                raise ValueError("public annotator inventory differs")
            for annotator in ANNOTATORS:
                values, ids = direct_score(references[annotator], predictions[arm])
                if arm == ARMS[0]:
                    base_ids[annotator] = ids
                for criterion in ("onset", "onset_offset"):
                    values[criterion + "_gained_reference_ids"] = sorted(ids[criterion] - base_ids[annotator][criterion])
                    values[criterion + "_lost_reference_ids"] = sorted(base_ids[annotator][criterion] - ids[criterion])
                checks.equal(public_arm["annotators"][annotator], values, "independent_note_matching")
                computed_arm["annotators"][annotator] = values
            computed_row["arms"][arm] = computed_arm
        rescored_rows.append(computed_row)
        summaries.append({"id": case, "status": "pass", **observation_summary,
                          "prediction_files": len(predictions), "human_references": len(references)})
    checks.equal(report.get("predictions_manifest_sha256"), fingerprint(manifest), "prediction_manifest_identity")
    checks.equal(report.get("post_evaluation_predictions_manifest_sha256"), fingerprint(manifest), "post_evaluation_manifest_identity")
    aggregate = aggregate_rows(rescored_rows)
    public_aggregate = report.get("aggregate")
    if not isinstance(public_aggregate, dict) or set(public_aggregate) != set(ARMS):
        raise ValueError("aggregate arm inventory differs")
    for arm in ARMS:
        checks.equal(public_aggregate[arm], aggregate[arm], "independent_aggregate")
    return {
        "schema_version": 1, "status": "pass", "audit_completed": True,
        "scope": "saved private byte identities and independent original-Hz note matching/aggregation",
        "report_sha256": sha256(raw_report), "script_sha256": sha256(Path(__file__).read_bytes()),
        "archive_sha256": report.get("archive_sha256"),
        "historical_baseline_parity_reported": report.get("historical_baseline_parity"),
        "historical_baseline_parity_independently_recomputed": False,
        "predictions_manifest_sha256": fingerprint(manifest),
        "checks_passed": sum(checks.counts.values()), "checks_by_kind": dict(sorted(checks.counts.items())),
        "maximum_numeric_difference": checks.maximum_numeric_difference,
        "cases": summaries, "aggregate": aggregate,
        "source_files_verified": len(CASES), "observation_arrays_verified": len(CASES) * len(OBSERVATIONS),
        "complete_prediction_files_verified": len(CASES) * len(ARMS),
        "human_reference_files_verified": len(CASES) * len(ANNOTATORS),
        "f0_reference_files_hash_verified": len(CASES),
        "neural_model_calls": 0, "pyin_calls": 0, "segmentation_model_calls": 0,
        "source_network_downloads": 0, "raw_musical_arrays_published": False,
        "elapsed_seconds": time.monotonic() - started,
        "limitations": [
            "Independently parses original-Hz references and scores saved notes with the declared mir_eval matcher; no independent human truth is created.",
            "Verifies observation hashes but does not rerun pYIN or independently reproduce the HMM/RMS decoder.",
            "The before-evaluation ordering is a recorded frozen-runner contract; post-hoc files cannot independently prove historical access order.",
            "Reference gain/loss uses deterministic maximum matching; ambiguous admissible matchings prevent a causal normal-note-damage interpretation.",
            "The forty repeatedly used development recordings are not held-out evidence or product, notation, rest or human-edit validation.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    if (args.audit.exists() or args.audit.is_symlink()
            or args.audit.resolve() in (args.report.resolve(), args.work.resolve())):
        parser.error("a new distinct audit output is required")
    try:
        result = audit_private(args.work, args.report)
    except Exception as exc:
        result = {
            "schema_version": 1, "status": "failed", "audit_completed": False,
            "error_type": type(exc).__name__, "error": str(exc),
            "planned_case_ids": list(CASES), "aggregate": None,
            "raw_musical_arrays_published": False,
        }
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.audit.with_suffix(args.audit.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(args.audit)
    print(json.dumps({"status": result["status"], "checks_passed": result.get("checks_passed", 0)}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
