"""Offline synthetic fixtures for source-bound four-ensemble MR-MT3 score receipts."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from scripts import aggregate_cocochorales_author_samples as batch
from scripts.fetch_pinned_mrmt3_checkpoint import CHECKPOINT_SHA256, MODEL_REVISION
from scripts.prepare_cocochorales_official_sample import (
    SAMPLE_BLOBS,
    SAMPLE_ROOT,
    SOURCE_COMMIT,
    SOURCE_RELEASE,
)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "private-sample-metadata"
    root.mkdir()
    model = {
        "model": "mr_mt3",
        "upstream_revision": MODEL_REVISION,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_sha256_verified": True,
        "model_redistribution_approved": False,
        "redistribution_status": "pending",
    }
    (root / "model-source.pending.json").write_text(json.dumps(model), encoding="utf-8")
    for track in batch.TRACKS:
        folder = root / track
        folder.mkdir()
        case = {
            "id": f"coco-{track}", "recording_id": track,
            "dataset_id": "cocochorales", "split": "train",
            "rights_reviewed": True,
            "audio": {"locator": f"private://{track}/mix.wav", "sha256": "a" * 64},
            "reference_midi": {"locator": f"private://{track}/mix.mid", "sha256": "b" * 64},
        }
        pairs = {"schema_version": 1, "cases": [case]}
        source = {
            "schema_version": 1, "dataset": "cocochorales",
            "source_kind": "official-sample-zip",
            "official_source": "https://magenta.tensorflow.org/datasets/cocochorales",
            "official_sample_page": "https://lukewys.github.io/cocochorales/",
            "source_repository": "lukewys/lukewys.github.io",
            "source_revision": SOURCE_COMMIT,
            "official_release": SOURCE_RELEASE,
            "official_format_source_commit": "4647edbce6719fe907e17fcc072651def168eaa5",
            "official_archive_path": f"{SAMPLE_ROOT}/{track}.zip",
            "archive_git_blob_sha1": SAMPLE_BLOBS[track][0],
            "archive_bytes": SAMPLE_BLOBS[track][1],
            "archive_sha256": "c" * 64, "track_count": 1,
            "paired_fingerprint": "d" * 64,
            "operator_rights_reviewed": True,
            "upstream_rights_independently_verified": False,
            "source_media_published": False,
            "tracks": [{
                "track_id": track, "split": "train",
                "mix_wav_sha256": "a" * 64, "mix_midi_sha256": "b" * 64,
                "instruments": [
                    {"voice": i, "instrument": "violin", "midi_program": 40}
                    for i in range(4)
                ],
            }],
        }
        diagnostic = {
            "reference_gm_program_note_counts": [
                {"is_drum": False, "program": 40, "note_count": 2},
            ],
            "prediction_gm_program_note_counts": [
                {"is_drum": False, "program": 56, "note_count": 3},
            ],
            "reference_midi": {"note_bearing_tracks": 4, "total_tracks": 4},
            "prediction_midi": {"note_bearing_tracks": 1, "total_tracks": 1},
            "prediction_musicxml_part_count": 1,
            "source_declared_gm_programs": [40],
        }
        score = {
            "schema_version": 1, "purpose": "cocochorales-tiny-mt3-note-evaluation",
            "case_count": 1, "split": "train",
            "paired_fingerprint": source["paired_fingerprint"],
            "official_archive_sha256": source["archive_sha256"],
            "source_evidence_sha256": batch._sha256_json(source),
            "scored_case_count": 1,
            "engine": {
                "id": "mt3_infer",
                "model_revision": f"sha256:{CHECKPOINT_SHA256}",
                "runtime_revision": "mt3-infer-0.2.0-transformers-4.57.6",
                "artifact_sha256": CHECKPOINT_SHA256,
            },
            "cases": [{
                "case_id": f"coco-{track}", "status": "scored",
                "failure_reason": None,
                "reference_note_count": 2, "prediction_note_count": 3,
                "note_onset_f1": 0.5,
                "note_onset_offset_f1": 0.25,
                "instrument_onset_offset_f1": 0.0,
                "model_inference_seconds": 1.4,
                "musicxml": {"parts": 1, "notes": 3},
                "instrument_part_diagnostics": diagnostic,
            }],
            "source_media_published": False,
            "model_redistribution_approved": False,
            "release_quality_approved": False,
        }
        for name, obj in (
            ("pairs.json", pairs),
            ("source-proof.pending.json", source),
            ("mt3-real-score.pending.json", score),
        ):
            (folder / name).write_text(json.dumps(obj), encoding="utf-8")
    return root


def _modify(root: Path, track: str, file: str, mutation) -> None:
    path = root / track / file
    payload = json.loads(path.read_text())
    mutation(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_four_real_ensemble_evidence_aggregates_without_approval(tmp_path):
    root = _fixture(tmp_path)
    result = batch.aggregate_official_samples(root)
    assert result["sample_count"] == 4
    assert result["scored_count"] == 4
    assert result["failed_count"] == 0
    assert [case["ensemble"] for case in result["cases"]] == [
        "string", "brass", "woodwind", "random",
    ]
    assert result["macro_metrics_successful_only"] == {
        "note_onset_f1": 0.5, "note_onset_offset_f1": 0.25,
        "instrument_onset_offset_f1": 0.0,
    }
    assert result["model_redistribution_approved"] is False
    assert result["commercial_release_quality_approved"] is False
    assert result["heldout_generalization_measured"] is False
    assert result["source_media_published"] is False
    assert str(root) not in json.dumps(result)
    assert "mix.wav" not in json.dumps(result)


@pytest.mark.parametrize("file,mutation,expected", [
    (
        "source-proof.pending.json",
        lambda data: data.update(archive_git_blob_sha1="f" * 40),
        "Original sample source",
    ),
    (
        "source-proof.pending.json",
        lambda data: data.update(source_revision="mutable-main"),
        "Original sample source",
    ),
    (
        "source-proof.pending.json",
        lambda data: data.update(source_media_published=True),
        "Original sample source",
    ),
    (
        "mt3-real-score.pending.json",
        lambda data: data["engine"].update(artifact_sha256="e" * 64),
        "different or unpinned model",
    ),
    (
        "mt3-real-score.pending.json",
        lambda data: data.update(release_quality_approved=True),
        "cryptographically bound",
    ),
    (
        "mt3-real-score.pending.json",
        lambda data: data["cases"][0]["instrument_part_diagnostics"][
            "prediction_gm_program_note_counts"
        ][0].update(note_count=999),
        "GM note histogram",
    ),
])
def test_changed_source_model_score_or_histogram_is_rejected(tmp_path, file, mutation, expected):
    root = _fixture(tmp_path)
    _modify(root, "brass_track049013", file, mutation)
    with pytest.raises(batch.AuthorSampleAggregateError, match=expected):
        batch.aggregate_official_samples(root)


def test_partial_failed_inference_is_counted_not_dropped(tmp_path):
    root = _fixture(tmp_path)
    track = "woodwind_track097010"

    def fail(data):
        data["scored_case_count"] = 0
        case = data["cases"][0]
        case["status"] = "failed"
        case["failure_reason"] = "zero-predicted-notes"
        case.pop("instrument_part_diagnostics")
        for key in batch._METRICS:
            case[key] = None

    _modify(root, track, "mt3-real-score.pending.json", fail)
    result = batch.aggregate_official_samples(root)
    assert result["scored_count"] == 3
    assert result["failed_count"] == 1
    assert result["cases"][2]["status"] == "failed"
    assert result["macro_metrics_successful_only"]["note_onset_f1"] == 0.5


def test_missing_fourth_model_reference_or_script_output_is_blocked(tmp_path):
    root = _fixture(tmp_path)
    (root / "random_track145011/mt3-real-score.pending.json").unlink()
    with pytest.raises(batch.AuthorSampleAggregateError, match="evidence"):
        batch.aggregate_official_samples(root)
    (root / "model-source.pending.json").unlink()
    with pytest.raises(batch.AuthorSampleAggregateError, match="evidence"):
        batch.aggregate_official_samples(root)


def test_metadata_only_cli_produces_audit_and_never_clobbers(tmp_path, monkeypatch, capsys):
    root = _fixture(tmp_path)
    dest = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", [
        "aggregate_cocochorales_author_samples.py",
        "--evidence-root", str(root), "--output", str(dest),
    ])
    assert batch.main() == 0
    assert json.loads(dest.read_text())["sample_count"] == 4
    assert "generalization_approved" in capsys.readouterr().out
    with pytest.raises(SystemExit) as err:
        batch.main()
    assert err.value.code == 2


def test_workflow_uses_four_real_fixed_examples_and_keeps_media_off_artifacts():
    path = Path(__file__).resolve().parents[1] / (
        ".github/workflows/cocochorales-real-mt3-benchmark.yml"
    )
    workflow = path.read_text(encoding="utf-8")
    assert "scripts.aggregate_cocochorales_author_samples" in workflow
    for track in batch.TRACKS:
        assert track in workflow
    assert "four-ensemble-score.pending.json" in workflow
    assert "MT3_CHECKPOINT_DIR" in workflow
    upload = workflow.split("name: Upload metadata only", 1)[1]
    for suffix in (".wav", ".mid", ".musicxml", ".pth", ".zip"):
        assert suffix not in upload
