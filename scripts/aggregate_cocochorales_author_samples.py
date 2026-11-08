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


def aggregate_official_samples(evidence_root: Path) -> dict[str, Any]:
    """Fail closed on incomplete/forged batch, keep every per-ensemble failure."""
    root = evidence_root.expanduser().absolute()
    _require(root.is_dir() and not root.is_symlink(), "Private evidence folder missing")
    model = _read_json(root, root / "model-source.pending.json")
    _require(
        model.get("model") == "mr_mt3"
        and model.get("upstream_revision") == MODEL_REVISION
        and model.get("checkpoint_sha256") == CHECKPOINT_SHA256
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
            and engine.get("model_revision") == f"sha256:{CHECKPOINT_SHA256}"
            and engine.get("artifact_sha256") == CHECKPOINT_SHA256
            and engine.get("runtime_revision") == _EXPECTED_RUNTIME,
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
            "instrument_part_diagnostics": case.get("instrument_part_diagnostics"),
        })
    success = [entry for entry in observed if entry["status"] == "scored"]
    return {
        "schema_version": 1,
        "purpose": "four-ensemble-author-sample-real-mrmt3-review",
        "model": "mr_mt3",
        "model_revision": MODEL_REVISION,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "model_source_evidence_sha256": _sha256_json(model),
        "sample_count": len(observed),
        "scored_count": len(success),
        "failed_count": len(observed) - len(success),
        "cases": observed,
        "macro_metrics_successful_only": {
            metric: round(mean(case[metric] for case in success), 8) if success else None
            for metric in _METRICS
        },
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("A new metadata-only report output is required")
    try:
        result = aggregate_official_samples(args.evidence_root)
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
