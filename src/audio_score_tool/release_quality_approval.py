from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .engine_release_policy import EnginePromotionError, assert_default_promotion
from .tier2_compare import Tier2ComparisonError, compare_tier2_reports, load_tier2_report

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReleaseQualityApprovalError(ValueError):
    pass


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ReleaseQualityApprovalError(f"quality approval {key} is required")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseQualityApprovalError(f"release evidence file cannot be read: {path}") from exc
    return digest.hexdigest()


def _validate_reviewed_at(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReleaseQualityApprovalError("reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseQualityApprovalError("reviewed_at must include a timezone")
    return value


def _repository_path(repository_root: Path, relative: str, *, label: str) -> Path:
    path = (repository_root / relative).resolve()
    try:
        path.relative_to(repository_root)
    except ValueError as exc:
        raise ReleaseQualityApprovalError(f"{label} must stay inside the repository") from exc
    return path


def load_quality_approval(path: Path, *, repository_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseQualityApprovalError(f"quality approval receipt is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseQualityApprovalError(f"quality approval receipt cannot be read: {path}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise ReleaseQualityApprovalError("quality approval schema_version must be '1'")
    if payload.get("status") != "approved":
        raise ReleaseQualityApprovalError("quality approval status must be 'approved'")
    if payload.get("issue") != 34:
        raise ReleaseQualityApprovalError("quality approval must reference issue #34")

    corpus_version = _required_text(payload, "corpus_version")
    reviewer = _required_text(payload, "reviewer")
    reviewed_at = _validate_reviewed_at(_required_text(payload, "reviewed_at"))
    comparison_path_text = _required_text(payload, "comparison_report")
    comparison_sha256 = _required_text(payload, "comparison_sha256").lower()
    if not _SHA256.fullmatch(comparison_sha256):
        raise ReleaseQualityApprovalError("comparison_sha256 must be a 64-hex SHA-256")

    engine = payload.get("engine")
    if not isinstance(engine, dict):
        raise ReleaseQualityApprovalError("quality approval engine object is required")
    engine_id = _required_text(engine, "id")
    model_revision = _required_text(engine, "model_revision")
    runtime_revision = _required_text(engine, "runtime_revision")
    artifact_sha256 = _required_text(engine, "artifact_sha256").lower()
    if not _SHA256.fullmatch(artifact_sha256):
        raise ReleaseQualityApprovalError("engine artifact_sha256 must be a 64-hex SHA-256")

    try:
        policy = assert_default_promotion(engine_id, usage_mode="commercial", tier2_approved=True)
    except EnginePromotionError as exc:
        raise ReleaseQualityApprovalError(str(exc)) from exc

    repository_root = repository_root.resolve()
    source_reports = payload.get("source_reports")
    if not isinstance(source_reports, list) or len(source_reports) < 2:
        raise ReleaseQualityApprovalError("at least two source_reports are required")

    source_paths: list[Path] = []
    for source in source_reports:
        if not isinstance(source, dict):
            raise ReleaseQualityApprovalError("source_reports entries must be objects")
        rel = _required_text(source, "path")
        expected_sha = _required_text(source, "sha256").lower()
        if not _SHA256.fullmatch(expected_sha):
            raise ReleaseQualityApprovalError("source report sha256 must be a 64-hex SHA-256")
        source_path = _repository_path(repository_root, rel, label="source report")
        if _sha256_file(source_path) != expected_sha:
            raise ReleaseQualityApprovalError(f"source report SHA-256 mismatch: {rel}")
        try:
            source_payload = load_tier2_report(source_path)
        except (OSError, json.JSONDecodeError, Tier2ComparisonError) as exc:
            raise ReleaseQualityApprovalError(f"invalid Tier 2 source report: {rel}") from exc
        if str(source_payload.get("corpus_version") or "") != corpus_version:
            raise ReleaseQualityApprovalError(f"source report corpus_version mismatch: {rel}")
        source_paths.append(source_path)

    comparison_path = _repository_path(repository_root, comparison_path_text, label="comparison_report")
    if not comparison_path.is_file():
        raise ReleaseQualityApprovalError(f"comparison report is missing: {comparison_path_text}")
    if _sha256_file(comparison_path) != comparison_sha256:
        raise ReleaseQualityApprovalError("comparison report SHA-256 does not match approval receipt")
    try:
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        recomputed = compare_tier2_reports(source_paths)
    except (OSError, json.JSONDecodeError, Tier2ComparisonError) as exc:
        raise ReleaseQualityApprovalError("Tier 2 comparison evidence is invalid") from exc
    if comparison != recomputed:
        raise ReleaseQualityApprovalError("comparison report does not match recomputed source reports")
    if comparison.get("recommended_engine") != policy.engine_key:
        raise ReleaseQualityApprovalError("approved engine is not the benchmark recommended_engine")

    ranking = comparison.get("ranking")
    selected = next(
        (item for item in ranking if isinstance(item, dict) and item.get("engine_id") == policy.engine_key),
        None,
    ) if isinstance(ranking, list) else None
    if selected is None or selected.get("qualified") is not True:
        raise ReleaseQualityApprovalError("approved engine is not a qualified Tier 2 candidate")
    expected = {
        "model_revision": model_revision,
        "runtime_revision": runtime_revision,
        "artifact_sha256": artifact_sha256,
    }
    for key, value in expected.items():
        if str(selected.get(key) or "") != value:
            raise ReleaseQualityApprovalError(f"approved engine {key} does not match comparison report")

    return {
        "schema_version": "1",
        "status": "approved",
        "issue": 34,
        "corpus_version": corpus_version,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "engine": {
            "id": policy.engine_key,
            "model_revision": model_revision,
            "runtime_revision": runtime_revision,
            "artifact_sha256": artifact_sha256,
        },
        "comparison_report": comparison_path_text,
        "comparison_sha256": comparison_sha256,
        "source_report_count": len(source_reports),
    }
