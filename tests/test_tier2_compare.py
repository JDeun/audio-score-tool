from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_score_tool.tier2_compare import Tier2ComparisonError, compare_tier2_reports


def _write_report(
    path: Path,
    *,
    engine_id: str,
    publish_time: float | None,
    edits: float | None,
    note_f1: float | None,
    export_rate: float,
    all_exports: bool,
    corpus_version: str = "1",
    manifest_sha256: str = "b" * 64,
    case_fingerprint: str = "c" * 64,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "corpus_version": corpus_version,
                "manifest_sha256": manifest_sha256,
                "case_fingerprint": case_fingerprint,
                "engine": {
                    "id": engine_id,
                    "model_revision": f"{engine_id}-model",
                    "runtime_revision": f"{engine_id}-runtime",
                    "artifact_sha256": "a" * 64,
                },
                "summary": {
                    "evaluated_note_cases": 10 if note_f1 is not None else 0,
                    "mean_note_f1": note_f1,
                    "mean_total_edit_actions": edits,
                    "mean_time_to_publish_seconds": publish_time,
                    "successful_export_rate": export_rate,
                    "all_exports_successful": all_exports,
                },
            }
        ),
        encoding="utf-8",
    )


def test_comparison_prioritizes_publish_time_before_note_f1(tmp_path: Path):
    fast = tmp_path / "fast.json"
    accurate = tmp_path / "accurate.json"
    _write_report(
        fast,
        engine_id="fast",
        publish_time=200,
        edits=40,
        note_f1=0.88,
        export_rate=1.0,
        all_exports=True,
    )
    _write_report(
        accurate,
        engine_id="accurate",
        publish_time=260,
        edits=20,
        note_f1=0.95,
        export_rate=1.0,
        all_exports=True,
    )

    result = compare_tier2_reports([fast, accurate])
    assert result["recommended_engine"] == "fast"
    assert result["release_approved"] is False
    assert result["manifest_sha256"] == "b" * 64
    assert result["case_fingerprint"] == "c" * 64
    assert result["ranking"][0]["mean_note_f1"] == 0.88


def test_failed_export_disqualifies_candidate_even_if_faster(tmp_path: Path):
    failed = tmp_path / "failed.json"
    stable = tmp_path / "stable.json"
    _write_report(
        failed,
        engine_id="failed",
        publish_time=100,
        edits=10,
        note_f1=0.99,
        export_rate=0.9,
        all_exports=False,
    )
    _write_report(
        stable,
        engine_id="stable",
        publish_time=300,
        edits=50,
        note_f1=0.85,
        export_rate=1.0,
        all_exports=True,
    )

    result = compare_tier2_reports([failed, stable])
    assert result["recommended_engine"] == "stable"
    assert result["ranking"][1]["qualified"] is False
    assert "not_all_exports_successful" in result["ranking"][1]["disqualifiers"]


def test_comparison_rejects_different_corpus_versions(tmp_path: Path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    _write_report(left, engine_id="left", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, corpus_version="1")
    _write_report(right, engine_id="right", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, corpus_version="2")
    with pytest.raises(Tier2ComparisonError, match="same corpus_version"):
        compare_tier2_reports([left, right])


def test_comparison_rejects_different_manifests(tmp_path: Path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    _write_report(left, engine_id="left", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, manifest_sha256="1" * 64)
    _write_report(right, engine_id="right", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, manifest_sha256="2" * 64)
    with pytest.raises(Tier2ComparisonError, match="exact same manifest"):
        compare_tier2_reports([left, right])


def test_comparison_rejects_different_case_fingerprints(tmp_path: Path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    _write_report(left, engine_id="left", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, case_fingerprint="1" * 64)
    _write_report(right, engine_id="right", publish_time=100, edits=10, note_f1=0.9, export_rate=1.0, all_exports=True, case_fingerprint="2" * 64)
    with pytest.raises(Tier2ComparisonError, match="exact same case set"):
        compare_tier2_reports([left, right])
