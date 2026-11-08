"""Compare actual MR-MT3 / YourMT3 paired author-sample note scores.

Inputs are independently audited JSON-only proof from two model jobs in the
same GitHub workflow. Refuse differing audio/reference/split/model identity
rather than accidentally ranking incomparable datasets or trials.

All four original author examples are TRAIN split; this is an engineering
regression comparison, never a held-out or commercial release approval.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.aggregate_cocochorales_author_samples import TRACKS
from scripts.fetch_pinned_mrmt3_checkpoint import CHECKPOINT_SHA256 as MR_SHA
from scripts.fetch_pinned_mrmt3_checkpoint import MODEL_REVISION as MR_REVISION
from scripts.fetch_pinned_yourmt3_checkpoint import CHECKPOINT_SHA256 as YOUR_SHA
from scripts.fetch_pinned_yourmt3_checkpoint import MODEL_REVISION as YOUR_REVISION

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MODEL_ID = {
    "mr_mt3": (MR_REVISION, MR_SHA, "mt3-infer-0.2.0-transformers-4.57.6-ast-program-preserving-v1"),
    "yourmt3": (YOUR_REVISION, YOUR_SHA, "mt3-infer-0.2.0-transformers-4.44.2-yptf-moe-nops"),
}
_METRICS = ("note_onset_f1", "note_onset_offset_f1", "instrument_onset_offset_f1")


class ModelComparisonError(ValueError):
    """Incompatible, unreviewed, incomplete or manipulated candidate evidence."""


def _expect(value: bool, explanation: str) -> None:
    if not value:
        raise ModelComparisonError(explanation)


def _verified_report(document: dict[str, Any], model_key: str) -> dict[str, Any]:
    expected_revision, checkpoint_sha, runtime = _MODEL_ID[model_key]
    _expect(
        isinstance(document, dict)
        and document.get("schema_version") == 1
        and document.get("purpose") == "four-ensemble-author-sample-real-mt3-review"
        and document.get("model") == model_key
        and document.get("model_revision") == expected_revision
        and document.get("runtime_revision") == runtime
        and document.get("checkpoint_sha256") == checkpoint_sha
        and document.get("all_samples_in_train_split") is True
        and document.get("heldout_generalization_measured") is False
        and document.get("human_editing_time_measured") is False
        and document.get("commercial_release_quality_approved") is False
        and document.get("model_redistribution_approved") is False
        and document.get("source_media_published") is False
        and document.get("sample_count") == len(TRACKS),
        f"{model_key} report is not a pinned unapproved actual reference experiment",
    )
    cases = document.get("cases")
    _expect(isinstance(cases, list) and len(cases) == len(TRACKS),
            f"{model_key} has incomplete ensemble coverage")
    _expect(
        document.get("scored_count") == sum(c.get("status") == "scored" for c in cases)
        and document.get("failed_count") == sum(c.get("status") == "failed" for c in cases),
        f"{model_key} score count or missing failure was concealed",
    )
    by_track = {}
    for index, case in enumerate(cases):
        _expect(
            isinstance(case, dict)
            and case.get("track_id") == TRACKS[index]
            and case.get("split") == "train"
            and case.get("status") in ("scored", "failed")
            and case.get("ensemble") == TRACKS[index].split("_track", 1)[0]
            and all(
                isinstance(case.get(field), str) and _SHA.fullmatch(case[field])
                for field in ("source_proof_sha256", "score_report_sha256",
                              "audio_sha256", "reference_midi_sha256")
            )
            and type(case.get("reference_note_count")) is int
            and case["reference_note_count"] > 0,
            f"{model_key} contains an invalid track, data fingerprint, or reference",
        )
        if case["status"] == "scored":
            _expect(
                type(case.get("prediction_note_count")) is int
                and case["prediction_note_count"] > 0
                and all(
                    type(case.get(metric)) in {int, float}
                    and math.isfinite(case[metric])
                    and 0 <= case[metric] <= 1 for metric in _METRICS
                )
                and type(case.get("inference_seconds")) in {int, float}
                and math.isfinite(case["inference_seconds"])
                and case["inference_seconds"] >= 0,
                f"{model_key} scored case lacks real inference/metrics",
            )
        by_track[case["track_id"]] = case
    expected_macro = {
        metric: round(mean(c[metric] for c in cases if c["status"] == "scored"), 8)
        if document["scored_count"] else None
        for metric in _METRICS
    }
    _expect(
        document.get("macro_metrics_successful_only") == expected_macro,
        f"{model_key} claimed macro metrics differ from observed cases",
    )
    return by_track


def compare_same_source_models(mr: dict, your: dict) -> dict:
    mr_rows = _verified_report(mr, "mr_mt3")
    your_rows = _verified_report(your, "yourmt3")
    rows = []
    for track in TRACKS:
        left, right = mr_rows[track], your_rows[track]
        for field in (
            "source_proof_sha256", "audio_sha256", "reference_midi_sha256",
            "reference_note_count", "split",
        ):
            _expect(
                left[field] == right[field],
                f"{track}: different original audio, independent MIDI or split ({field})",
            )
        pair_scored = left["status"] == right["status"] == "scored"
        rows.append({
            "track_id": track,
            "ensemble": left["ensemble"],
            "source_proof_sha256": left["source_proof_sha256"],
            "audio_sha256": left["audio_sha256"],
            "reference_midi_sha256": left["reference_midi_sha256"],
            "reference_note_count": left["reference_note_count"],
            "mr_mt3": {
                "status": left["status"], "prediction_notes": left.get("prediction_note_count"),
                "inference_seconds": left.get("inference_seconds"),
                "musicxml": left.get("musicxml"),
                "metrics": {key: left.get(key) for key in _METRICS},
            },
            "yourmt3": {
                "status": right["status"], "prediction_notes": right.get("prediction_note_count"),
                "inference_seconds": right.get("inference_seconds"),
                "musicxml": right.get("musicxml"),
                "metrics": {key: right.get(key) for key in _METRICS},
            },
            "both_scored": pair_scored,
            "yourmt3_minus_mrmt3": {
                key: round(right[key] - left[key], 8) for key in _METRICS
            } if pair_scored else None,
        })

    complete = all(x["both_scored"] for x in rows)
    rank = None
    if complete:
        ordered = sorted(
            [mr, your],
            key=lambda report: (
                -report["macro_metrics_successful_only"]["instrument_onset_offset_f1"],
                -report["macro_metrics_successful_only"]["note_onset_offset_f1"],
                -report["macro_metrics_successful_only"]["note_onset_f1"],
                report["model"],
            ),
        )
        rank = [item["model"] for item in ordered]
    return {
        "schema_version": 1,
        "purpose": "head-to-head-author-train-cocochorales-not-release-gate",
        "exactly_same_audio_and_independent_reference_proven": True,
        "model_checkpoints": {
            name: {"checkpoint_sha256": _MODEL_ID[name][1], "source_revision": _MODEL_ID[name][0],
                   "runtime_revision": _MODEL_ID[name][2]}
            for name in ("mr_mt3", "yourmt3")
        },
        "tracks": rows,
        "case_count": len(rows),
        "complete_paired_case_count": sum(row["both_scored"] for row in rows),
        "all_candidates_completed": complete,
        "observed_macro_by_candidate": {
            name: source["macro_metrics_successful_only"] for name, source in (
                ("mr_mt3", mr), ("yourmt3", your),
            )
        },
        "research_only_order_if_complete": rank,
        "selection_basis": "4 upstream TRAIN-split author-generated ensemble examples",
        "heldout_generalization_measured": False,
        "human_editing_time_measured": False,
        "release_quality_approved": False,
        "model_redistribution_approved": False,
        "commercial_default_selected": False,
        "discarded_models": [],
        "source_media_published": False,
    }


def _read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
        raise ModelComparisonError("Comparisons require bounded regular proof files")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelComparisonError("Invalid source-bound model JSON") from exc
    _expect(isinstance(payload, dict), "Candidate JSON must be an object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two genuine source-bound AMT reports")
    parser.add_argument("--mrmt3", type=Path, required=True)
    parser.add_argument("--yourmt3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Model comparison evidence cannot overwrite an existing report")
    try:
        report = compare_same_source_models(_read_json(args.mrmt3), _read_json(args.yourmt3))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, sort_keys=True, indent=2)
            file.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"MT3 head-to-head refused: {exc}\n")
    print(json.dumps({
        "same_reference": True,
        "scored_pairs": report["complete_paired_case_count"],
        "research_order": report["research_only_order_if_complete"],
        "heldout": False,
        "commercial_default_selected": False,
    }, sort_keys=True))
    return 0 if report["all_candidates_completed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
