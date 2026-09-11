from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from audio_score_tool.release_quality_approval import (
    ReleaseQualityApprovalError,
    load_quality_approval,
)
from audio_score_tool.tier2_compare import compare_tier2_reports


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(engine_id: str, *, seconds: float, artifact: str) -> dict:
    return {
        "schema_version": "1",
        "corpus_version": "tier2-v1",
        "engine": {
            "id": engine_id,
            "model_revision": "model-rev" if engine_id == "mt3_infer" else "other-model",
            "runtime_revision": "runtime-rev" if engine_id == "mt3_infer" else "other-runtime",
            "artifact_sha256": artifact,
        },
        "summary": {
            "successful_export_rate": 1.0,
            "all_exports_successful": True,
            "mean_time_to_publish_seconds": seconds,
            "mean_total_edit_actions": 8.0 if engine_id == "mt3_infer" else 12.0,
            "mean_note_f1": 0.93 if engine_id == "mt3_infer" else 0.88,
            "evaluated_note_cases": 8,
        },
    }


def _evidence(tmp_path: Path) -> tuple[str, list[dict[str, str]]]:
    first = tmp_path / "release/evidence/mt3.json"
    second = tmp_path / "release/evidence/other.json"
    first_sha = _write_json(first, _report("mt3_infer", seconds=90.0, artifact="a" * 64))
    second_sha = _write_json(second, _report("other_engine", seconds=120.0, artifact="b" * 64))
    comparison = tmp_path / "release/evidence/comparison.json"
    comparison_sha = _write_json(comparison, compare_tier2_reports([first, second]))
    sources = [
        {"path": "release/evidence/mt3.json", "sha256": first_sha},
        {"path": "release/evidence/other.json", "sha256": second_sha},
    ]
    return comparison_sha, sources


def _approval(comparison_sha: str, sources: list[dict[str, str]]) -> dict:
    return {
        "schema_version": "1",
        "status": "approved",
        "issue": 34,
        "corpus_version": "tier2-v1",
        "reviewer": "release-reviewer",
        "reviewed_at": "2026-09-11T12:00:00+09:00",
        "comparison_report": "release/evidence/comparison.json",
        "comparison_sha256": comparison_sha,
        "engine": {
            "id": "mt3_infer",
            "model_revision": "model-rev",
            "runtime_revision": "runtime-rev",
            "artifact_sha256": "a" * 64,
        },
        "source_reports": sources,
    }


def test_quality_approval_binds_selected_engine_to_recomputed_comparison(tmp_path: Path):
    comparison_sha, sources = _evidence(tmp_path)
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, _approval(comparison_sha, sources))

    result = load_quality_approval(receipt, repository_root=tmp_path)

    assert result["status"] == "approved"
    assert result["engine"]["id"] == "mt3_infer"
    assert result["comparison_sha256"] == comparison_sha
    assert result["source_report_count"] == 2


def test_quality_approval_rejects_tampered_comparison(tmp_path: Path):
    comparison_sha, sources = _evidence(tmp_path)
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, _approval(comparison_sha, sources))
    (tmp_path / "release/evidence/comparison.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ReleaseQualityApprovalError, match="SHA-256"):
        load_quality_approval(receipt, repository_root=tmp_path)


def test_quality_approval_requires_source_reports(tmp_path: Path):
    comparison_sha, _ = _evidence(tmp_path)
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, _approval(comparison_sha, []))

    with pytest.raises(ReleaseQualityApprovalError, match="at least two source_reports"):
        load_quality_approval(receipt, repository_root=tmp_path)


def test_quality_approval_rejects_noncommercial_default(tmp_path: Path):
    comparison_sha, sources = _evidence(tmp_path)
    approval = _approval(comparison_sha, sources)
    approval["engine"]["id"] = "muscriptor"
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, approval)

    with pytest.raises(ReleaseQualityApprovalError, match="commercial default"):
        load_quality_approval(receipt, repository_root=tmp_path)


def test_quality_approval_requires_timezone(tmp_path: Path):
    comparison_sha, sources = _evidence(tmp_path)
    approval = _approval(comparison_sha, sources)
    approval["reviewed_at"] = "2026-09-11T12:00:00"
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, approval)

    with pytest.raises(ReleaseQualityApprovalError, match="timezone"):
        load_quality_approval(receipt, repository_root=tmp_path)
