"""Audit and combine exact official author-sample MR-MT3 reference scores.

Uses metadata only from four private runs. All original WAV/MIDI, predicted
MIDI/MusicXML and model bytes remain private. This program cannot assess
training/test generalization, legal redistribution, or human editing quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

from scripts.fetch_pinned_mrmt3_checkpoint import CHECKPOINT_SHA256, MODEL_REVISION
from scripts.fetch_pinned_yourmt3_checkpoint import (
    CHECKPOINT_SHA256 as YOURMT3_CHECKPOINT_SHA256,
)
from scripts.fetch_pinned_yourmt3_checkpoint import (
    MODEL_REVISION as YOURMT3_MODEL_REVISION,
)
from scripts.prepare_cocochorales_official_sample import (
    SAMPLE_BLOBS,
    SAMPLE_ROOT,
    SOURCE_COMMIT,
    SOURCE_RELEASE,
)
from scripts.score_cocochorales_tiny import _source_receipt

TRACKS = (
    "string_track001010",
    "brass_track049013",
    "woodwind_track097010",
    "random_track145011",
)
_EXPECTED_RUNTIME = "mt3-infer-0.2.0-transformers-4.57.6-ast-program-preserving-v1"
_EXPECTED_MODEL_PROFILES = {
    "mr_mt3": (MODEL_REVISION, CHECKPOINT_SHA256, _EXPECTED_RUNTIME),
    "yourmt3": (
        YOURMT3_MODEL_REVISION,
        YOURMT3_CHECKPOINT_SHA256,
        "mt3-infer-0.2.0-transformers-4.44.2-yptf-moe-nops",
    ),
}
_METRICS = (
    "note_onset_f1", "note_onset_offset_f1",
    "instrument_onset_offset_f1",
)
_MAX_JSON_BYTES = 4 * 1024 * 1024


class AuthorSampleAggregateError(ValueError):
    """Source, model, scoring, or privacy attestation is not trustworthy."""


def _require(ok: bool, description: str) -> None:
    if not ok:
        raise AuthorSampleAggregateError(description)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_json(data: dict) -> str:
    # Must match the existing single-sample scorer's canonical JSON digest.
    return _sha256_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())


def _read_json(root: Path, path: Path) -> dict:
    _require(
        path.is_relative_to(root) and not path.is_symlink() and path.is_file()
        and 0 < path.stat().st_size <= _MAX_JSON_BYTES,
        "A bounded, private, regular JSON evidence file is required",
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError) as exc:
        raise AuthorSampleAggregateError("Invalid official sample JSON evidence") from exc
    _require(isinstance(payload, dict), "All official sample receipts must be objects")
    return payload


def aggregate_official_samples(
    evidence_root: Path, *, model_key: str = "mr_mt3",
) -> dict[str, Any]:
    """Fail closed on incomplete/forged batches without conflating candidate identities."""
    _require(model_key in _EXPECTED_MODEL_PROFILES, "Unsupported paired AMT model")
    source_revision, checkpoint_sha, runtime_revision = _EXPECTED_MODEL_PROFILES[model_key]
    root = evidence_root.expanduser().absolute()
    _require(root.is_dir() and not root.is_symlink(), "Private evidence folder missing")
    model = _read_json(root, root / "model-source.pending.json")
    _require(
        model.get("model") == model_key
        and model.get("upstream_revision") == source_revision
        and model.get("checkpoint_sha256") == checkpoint_sha
        and model.get("immutable_revision_requested") is True
        and model.get("checkpoint_sha256_verified") is True
        and model.get("redistribution_status") == "pending"
        and model.get("model_redistribution_approved") is False,
        "Unverified or unapproved MR-MT3 checkpoint identity",
    )

    observed = []
    for track_id in TRACKS:
        folder = root / track_id
        _require(folder.is_dir() and not folder.is_symlink(), "Per-ensemble evidence folder missing")
        pairs = _read_json(root, folder / "pairs.json")
        source = _read_json(root, folder / "source-proof.pending.json")
        score = _read_json(root, folder / "mt3-real-score.pending.json")
        items = pairs.get("cases")
        _require(isinstance(items, list) and len(items) == 1, "Single author track required")
        pair = items[0]
        _require(
            isinstance(pair, dict)
            and pair.get("id") == f"coco-{track_id}"
            and pair.get("recording_id") == track_id
            and pair.get("dataset_id") == "cocochorales"
            and pair.get("split") == "train"
            and pair.get("rights_reviewed") is True,
            "Case identity or licensing review does not match original author track",
        )
        try:
            _source_receipt(source, split="train", paired=pairs)
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthorSampleAggregateError("Original sample source identity is inconsistent") from exc
        expected_blob, expected_size = SAMPLE_BLOBS[track_id]
        _require(
            source.get("source_revision") == SOURCE_COMMIT
            and source.get("official_release") == SOURCE_RELEASE
            and source.get("official_archive_path") == f"{SAMPLE_ROOT}/{track_id}.zip"
            and source.get("archive_git_blob_sha1") == expected_blob
            and source.get("archive_bytes") == expected_size,
            "Original sample ZIP not pinned to author's Git revision",
        )
        _require(
            source.get("paired_fingerprint") == score.get("paired_fingerprint")
            and score.get("official_archive_sha256") == source.get("archive_sha256")
            and score.get("source_evidence_sha256") == _sha256_json(source)
            and score.get("schema_version") == 1
            and score.get("purpose") == "cocochorales-tiny-mt3-note-evaluation"
            and score.get("case_count") == 1
            and score.get("split") == "train"
            and score.get("scored_case_count") in (0, 1)
            and score.get("model_redistribution_approved") is False
            and score.get("source_media_published") is False
            and score.get("release_quality_approved") is False,
            "Scored note references are not cryptographically bound to source ZIP",
        )
        engine = score.get("engine")
        _require(
            isinstance(engine, dict)
            and engine.get("id") == "mt3_infer"
            and engine.get("model_revision") == f"sha256:{checkpoint_sha}"
            and engine.get("artifact_sha256") == checkpoint_sha
            and engine.get("runtime_revision") == runtime_revision,
            "A different or unpinned model produced the score",
        )
        cases = score.get("cases")
        _require(isinstance(cases, list) and len(cases) == 1, "Exactly one scored case required")
        case = cases[0]
        _require(isinstance(case, dict) and case.get("case_id") == pair["id"],
                 "Score case differs from original paired MIDI identity")
        status = case.get("status")
        _require(status in {"scored", "failed"}, "Unknown model scoring status")
        if status == "scored":
            diagnostics = case.get("instrument_part_diagnostics")
            _require(isinstance(diagnostics, dict), "Actual GM program diagnostics missing")
            prediction = diagnostics.get("prediction_gm_program_note_counts")
            reference = diagnostics.get("reference_gm_program_note_counts")
            _require(isinstance(prediction, list) and isinstance(reference, list),
                     "GM program note histograms missing")
            _require(
                sum(int(row["note_count"]) for row in prediction) == case.get("prediction_note_count")
                and sum(int(row["note_count"]) for row in reference) == case.get("reference_note_count")
                and diagnostics.get("prediction_musicxml_part_count")
                == case.get("musicxml", {}).get("parts"),
                "GM note histogram or MusicXML part count disagrees with scored case",
            )
            for metric in _METRICS:
                value = case.get(metric)
                _require(
                    type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1,
                    f"Missing or non-finite observed {metric}",
                )
        else:
            _require(
                case.get("failure_reason") in {
                    "prediction-artifact-missing-or-linked",
                    "invalid-prediction-midi-or-musicxml",
                    "zero-predicted-notes",
                },
                "Real inference failure reason is unreviewed",
            )
        observed.append({
            "ensemble": track_id.split("_track", 1)[0],
            "track_id": track_id,
            "split": "train",
            "status": status,
            "failure_reason": case.get("failure_reason"),
            "source_proof_sha256": _sha256_json(source),
            "score_report_sha256": _sha256_json(score),
            "audio_sha256": pair["audio"]["sha256"],
            "reference_midi_sha256": pair["reference_midi"]["sha256"],
            "reference_note_count": case.get("reference_note_count"),
            "prediction_note_count": case.get("prediction_note_count"),
            "note_onset_f1": case.get("note_onset_f1"),
            "note_onset_offset_f1": case.get("note_onset_offset_f1"),
            "instrument_onset_offset_f1": case.get("instrument_onset_offset_f1"),
            "inference_seconds": case.get("model_inference_seconds"),
            "musicxml": case.get("musicxml"),
            "score_musicxml_reference_fidelity": case.get("score_musicxml_reference_fidelity"),
            "score_part_count_absolute_error": case.get("score_part_count_absolute_error"),
            "instrument_part_diagnostics": case.get("instrument_part_diagnostics"),
        })
    success = [entry for entry in observed if entry["status"] == "scored"]
    score_available = bool(success) and all(
        case.get("score_musicxml_reference_fidelity") is not None for case in success
    )
    # A partially measured group must never present selective MusicXML results
    # as an average over the full four-source sample set.
    _require(
        not any(case.get("score_musicxml_reference_fidelity") is not None for case in success)
        or score_available,
        "Partial MusicXML ground-truth coverage cannot produce a model average",
    )
    score_metrics = ("onset_f1", "onset_offset_f1", "instrument_onset_offset_f1")
    for case in (success if score_available else []):
        fidelity = case["score_musicxml_reference_fidelity"]
        _require(
            isinstance(fidelity, dict)
            and fidelity.get("method") == "music21_musicxml_to_midi_temp_roundtrip"
            and fidelity.get("reference_note_count") == case["reference_note_count"]
            and fidelity.get("predicted_midi_note_count") == case["prediction_note_count"]
            and type(fidelity.get("score_playable_note_count")) is int
            and fidelity["score_playable_note_count"] > 0
            and type(case.get("score_part_count_absolute_error")) is int
            and case["score_part_count_absolute_error"] >= 0
            and fidelity.get("reference_part_count") == 4,
            "MusicXML ground-truth receipt is incomplete or mismatched",
        )
        for against in ("against_reference", "against_prediction_midi"):
            values = fidelity.get(against)
            _require(
                isinstance(values, dict)
                and all(
                    type(values.get(metric)) in (int, float)
                    and math.isfinite(values[metric])
                    and 0 <= values[metric] <= 1
                    for metric in score_metrics
                ),
                "MusicXML accuracy metrics are invalid",
            )

    score_macro = None
    if score_available:
        score_macro = {
            against: {
                metric: round(mean(
                    case["score_musicxml_reference_fidelity"][against][metric]
                    for case in success
                ), 8)
                for metric in score_metrics
            }
            for against in ("against_reference", "against_prediction_midi")
        }
        score_macro["part_count_absolute_error"] = round(
            mean(case["score_part_count_absolute_error"] for case in success), 8
        )
    return {
        "schema_version": 1,
        "purpose": "four-ensemble-author-sample-real-mt3-review",
        "model": model_key,
        "model_revision": source_revision,
        "runtime_revision": runtime_revision,
        "checkpoint_sha256": checkpoint_sha,
        "model_source_evidence_sha256": _sha256_json(model),
        "sample_count": len(observed),
        "scored_count": len(success),
        "failed_count": len(observed) - len(success),
        "cases": observed,
        "macro_metrics_successful_only": {
            metric: round(mean(case[metric] for case in success), 8) if success else None
            for metric in _METRICS
        },
        # Separate score (MusicXML) metrics from raw model MIDI metrics.
        # None means the historical report did not measure the final score;
        # it does NOT imply perfect fidelity or zero accuracy.
        "score_musicxml_macro_successful_only": score_macro,
        "dataset_is_author_generated_not_recorded_commercial_music": True,
        "all_samples_in_train_split": True,
        "heldout_generalization_measured": False,
        "human_editing_time_measured": False,
        "model_redistribution_approved": False,
        "commercial_release_quality_approved": False,
        "source_media_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate four private author-sample QA receipts")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--model", choices=sorted(_EXPECTED_MODEL_PROFILES), default="mr_mt3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("A new metadata-only report output is required")
    try:
        result = aggregate_official_samples(args.evidence_root, model_key=args.model)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Four-ensemble author sample evidence rejected: {exc}\n")
    print(json.dumps({
        "samples": result["sample_count"], "scored": result["scored_count"],
        "macro": result["macro_metrics_successful_only"],
        "generalization_approved": False,
    }, sort_keys=True))
    if result["failed_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
