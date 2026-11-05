"""Synthetic, no-model verification for Tier 2 execution and retest receipts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.tier2_execution_ledger import build_receipt, save_receipt

SHA = "a" * 64
MANIFEST = Path("benchmarks/tier2/manifest.example.json")


def _matrix(path: Path) -> Path:
    path.write_text(json.dumps({"schema_version": 1, "stages": [
        {"id": "yourmt3", "kind": "amt", "enabled": True},
        {"id": "mr-mt3", "kind": "amt", "enabled": True},
    ]}), encoding="utf-8")
    return path


def _summary(first: str = "blocked") -> dict:
    return {"schema_version": 1, "results": [
        {"id": "yourmt3", "status": first,
         **({"reason": "/secret/private-model-token"} if first in {"blocked", "failed"} else {})},
        {"id": "mr-mt3", "status": "planned"},
    ], "completed": 0, "blocked": int(first == "blocked")}


def test_dry_run_receipt_redacts_raw_reason_and_does_not_invent_benchmarks(tmp_path: Path):
    result = build_receipt(summary=_summary(), matrix_path=_matrix(tmp_path / "matrix.json"),
                           output_root=tmp_path)
    assert result["blocked"] == 1 and result["completed"] == 0
    assert result["corpus"] is None
    assert result["commercial_approval"] is False
    assert result["source_audio_copied_to_receipt"] is False
    assert "/secret/" not in json.dumps(result)
    assert result["stages"][0]["failure_reason_sha256"] == hashlib.sha256(
        b"/secret/private-model-token"
    ).hexdigest()


def test_duplicate_stage_and_counters_are_rejected(tmp_path: Path):
    matrix = _matrix(tmp_path / "matrix.json")
    summary = _summary()
    summary["results"].append(dict(summary["results"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_receipt(summary=summary, matrix_path=matrix, output_root=tmp_path)
    summary = _summary()
    summary["completed"] = 1
    with pytest.raises(ValueError, match="counters"):
        build_receipt(summary=summary, matrix_path=matrix, output_root=tmp_path)


def test_execution_without_a_real_manifest_cannot_be_claimed(tmp_path: Path):
    matrix = _matrix(tmp_path / "matrix.json")
    with pytest.raises(ValueError, match="corpus manifest"):
        build_receipt(summary=_summary("failed"), matrix_path=matrix, output_root=tmp_path)


def test_failed_stage_requires_reason_and_supports_retest_chain(tmp_path: Path):
    matrix = _matrix(tmp_path / "matrix.json")
    summary = _summary("failed")
    with pytest.raises(ValueError, match="recorded reason"):
        missing = json.loads(json.dumps(summary))
        missing["results"][0].pop("reason")
        build_receipt(summary=missing, matrix_path=matrix, output_root=tmp_path,
                      manifest_path=MANIFEST)
    prior = build_receipt(summary=summary, matrix_path=matrix, output_root=tmp_path,
                          manifest_path=MANIFEST)
    file = tmp_path / "previous.json"
    save_receipt(file, prior)
    after = build_receipt(summary=summary, matrix_path=matrix, output_root=tmp_path,
                          manifest_path=MANIFEST, retest_of=file)
    assert after["retest_of"]["run_id"] == prior["run_id"]
    assert after["retest_of"]["receipt_sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
    assert after["run_id"] != prior["run_id"]


def test_comparison_failure_is_tracked_without_raw_logs(tmp_path: Path):
    matrix = _matrix(tmp_path / "matrix.json")
    summary = _summary()
    summary["results"].append({"id": "comparison", "status": "failed"})
    result = build_receipt(summary=summary, matrix_path=matrix, output_root=tmp_path)
    assert result["failed"] == 1
    assert result["stages"][-1]["kind"] == "comparison"


def _completed_fixture(tmp_path: Path) -> tuple[Path, dict, Path]:
    manifest = MANIFEST
    matrix = _matrix(tmp_path / "matrix.json")
    root = tmp_path / "predictions"
    model_root = root / "yourmt3"
    model_root.mkdir(parents=True)
    midi, xml = b"owned MIDI bytes", b"owned MusicXML bytes"
    (model_root / "pop-band-001.mid").write_bytes(midi)
    (model_root / "pop-band-001.musicxml").write_bytes(xml)
    record = {
        "schema_version": "1", "corpus_version": "1", "case_ids": ["pop-band-001"],
        "engine": {"id": "yourmt3", "model_revision": "pinned-model",
                   "runtime_revision": "pinned-runtime", "artifact_sha256": SHA},
        "inference_engine": {"id": "mt3_infer", "model_revision": "pinned-model",
                             "runtime_revision": "pinned-runtime", "artifact_sha256": SHA},
        "stage_id": "yourmt3",
        "experiment": {
            "run_id": "a" * 32, "recorded_at_utc": "2026-11-05T09:00:00+00:00",
            "corpus_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "candidate_kind": "amt", "commercial_eligible": None,
            "repository_commit": None,
            "artifacts": {"pop-band-001": {
                "mid_sha256": hashlib.sha256(midi).hexdigest(),
                "musicxml_sha256": hashlib.sha256(xml).hexdigest(),
            }},
        },
    }
    (model_root / "tier2-prediction-provenance.json").write_text(
        json.dumps(record), encoding="utf-8",
    )
    report = root / "yourmt3-report.json"
    report.write_text('{"schema_version": 1}', encoding="utf-8")
    summary = {
        "schema_version": 1,
        "results": [
            {"id": "yourmt3", "status": "completed", "report": str(report),
             "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest()},
            {"id": "mr-mt3", "status": "blocked", "reason": "not available"},
        ],
        "completed": 1, "blocked": 1,
    }
    return matrix, summary, root


def test_completed_artifacts_are_verified_against_manifest(tmp_path: Path):
    matrix, summary, root = _completed_fixture(tmp_path)
    result = build_receipt(summary=summary, matrix_path=matrix, output_root=root,
                           manifest_path=MANIFEST)
    assert result["stages"][0]["report_verified"] is True
    assert result["stages"][0]["validated_artifact_count"] == 2
    assert result["stages"][0]["prediction_run_id"] == "a" * 32
    assert result["corpus"]["cases"][0]["rights_independently_verified"] is False


def test_tampered_report_or_midi_must_fail_closed(tmp_path: Path):
    matrix, summary, root = _completed_fixture(tmp_path)
    (root / "yourmt3-report.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_receipt(summary=summary, matrix_path=matrix, output_root=root, manifest_path=MANIFEST)
    matrix, summary, root = _completed_fixture(tmp_path)
    (root / "yourmt3" / "pop-band-001.mid").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_receipt(summary=summary, matrix_path=matrix, output_root=root, manifest_path=MANIFEST)
