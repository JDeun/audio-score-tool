from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from audio_score_tool.release_quality_approval import (
    ReleaseQualityApprovalError,
    load_quality_approval,
)


def _write_json(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _comparison() -> dict:
    return {
        "schema_version": "1",
        "corpus_version": "tier2-v1",
        "recommended_engine": "mt3_infer",
        "release_approved": False,
        "ranking": [
            {
                "rank": 1,
                "engine_id": "mt3_infer",
                "model_revision": "model-rev",
                "runtime_revision": "runtime-rev",
                "artifact_sha256": "a" * 64,
                "qualified": True,
            }
        ],
    }


def _approval(comparison_sha: str) -> dict:
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
        "source_reports": [],
    }


def test_quality_approval_binds_selected_engine_to_comparison(tmp_path: Path):
    comparison = tmp_path / "release/evidence/comparison.json"
    comparison_sha = _write_json(comparison, _comparison())
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, _approval(comparison_sha))

    result = load_quality_approval(receipt, repository_root=tmp_path)

    assert result["status"] == "approved"
    assert result["engine"]["id"] == "mt3_infer"
    assert result["comparison_sha256"] == comparison_sha


def test_quality_approval_rejects_tampered_comparison(tmp_path: Path):
    comparison = tmp_path / "release/evidence/comparison.json"
    comparison_sha = _write_json(comparison, _comparison())
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, _approval(comparison_sha))
    comparison.write_text("{}", encoding="utf-8")

    with pytest.raises(ReleaseQualityApprovalError, match="SHA-256"):
        load_quality_approval(receipt, repository_root=tmp_path)


def test_quality_approval_rejects_noncommercial_default(tmp_path: Path):
    comparison_payload = _comparison()
    comparison_payload["recommended_engine"] = "muscriptor"
    comparison_payload["ranking"][0]["engine_id"] = "muscriptor"
    comparison = tmp_path / "release/evidence/comparison.json"
    comparison_sha = _write_json(comparison, comparison_payload)
    approval = _approval(comparison_sha)
    approval["engine"]["id"] = "muscriptor"
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, approval)

    with pytest.raises(ReleaseQualityApprovalError, match="commercial default"):
        load_quality_approval(receipt, repository_root=tmp_path)


def test_quality_approval_requires_timezone(tmp_path: Path):
    comparison = tmp_path / "release/evidence/comparison.json"
    comparison_sha = _write_json(comparison, _comparison())
    approval = _approval(comparison_sha)
    approval["reviewed_at"] = "2026-09-11T12:00:00"
    receipt = tmp_path / "release/v1-quality-approval.json"
    _write_json(receipt, approval)

    with pytest.raises(ReleaseQualityApprovalError, match="timezone"):
        load_quality_approval(receipt, repository_root=tmp_path)
