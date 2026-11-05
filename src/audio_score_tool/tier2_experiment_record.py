"""Validate recorded Tier 2 experiment identities and local artifact hashes.

The validator reads only local files. It deliberately does not download private
audio, infer its license, or consider a model-quality/production approval valid.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .tier2_benchmark import Tier2EngineIdentity, load_manifest
from .tier2_prediction import load_tier2_prediction_provenance

_CANDIDATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,79}$")
_CASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[0-9a-f]{32}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class ExperimentRecordError(ValueError):
    """The experiment record is missing, inconsistent, or tampered with."""


def _required_text(payload: dict, key: str) -> str:
    text = payload.get(key)
    if not isinstance(text, str) or not text.strip():
        raise ExperimentRecordError(f"experiment {key} is required")
    return text.strip()


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ExperimentRecordError(f"experiment artifact cannot be read: {path.name}") from exc
    return digest.hexdigest()


def _check_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ExperimentRecordError(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _check_artifact(path: Path, expected: object, *, label: str) -> None:
    digest = _check_sha(expected, label=label)
    if not path.is_file() or path.is_symlink():
        raise ExperimentRecordError(f"{label} file is missing or unsafe")
    if _digest(path) != digest:
        raise ExperimentRecordError(f"{label} SHA-256 mismatch")


def validate_tier2_experiment_record(
    predictions_root: Path,
    *,
    manifest_path: Path | None = None,
    events_root: Path | None = None,
) -> dict[str, Any]:
    """Fail closed on a missing/stale/corrupt experiment provenance receipt."""
    root = predictions_root.expanduser().resolve()
    if not root.is_dir():
        raise ExperimentRecordError("experiment predictions_root does not exist")
    try:
        corpus, identity, case_ids, payload = load_tier2_prediction_provenance(root)
    except (OSError, ValueError) as exc:
        raise ExperimentRecordError("experiment prediction provenance is invalid") from exc

    stage = _required_text(payload, "stage_id")
    if not _CANDIDATE.fullmatch(stage) or ".." in stage or identity.id != stage:
        raise ExperimentRecordError("experiment stage_id must match the candidate identity")
    if len(set(case_ids)) != len(case_ids) or not all(
        _CASE.fullmatch(case) and ".." not in case for case in case_ids
    ):
        raise ExperimentRecordError("experiment case_ids contain duplicates or unsafe names")

    if manifest_path is not None:
        version, cases = load_manifest(manifest_path)
        if corpus != version or case_ids != tuple(item.id for item in cases):
            raise ExperimentRecordError("experiment corpus manifest identity does not match")

    execution = payload.get("inference_engine")
    if not isinstance(execution, dict):
        raise ExperimentRecordError("experiment inference_engine is required")
    try:
        Tier2EngineIdentity(
            id=_required_text(execution, "id"),
            model_revision=_required_text(execution, "model_revision"),
            runtime_revision=_required_text(execution, "runtime_revision"),
            artifact_sha256=_required_text(execution, "artifact_sha256"),
        )
    except ValueError as exc:
        raise ExperimentRecordError("experiment inference_engine identity is invalid") from exc

    info = payload.get("experiment")
    if not isinstance(info, dict):
        raise ExperimentRecordError("experiment metadata is missing")
    run_id = _required_text(info, "run_id")
    if not _RUN_ID.fullmatch(run_id):
        raise ExperimentRecordError("experiment run_id must be a 32-hex UUID")
    recorded = _required_text(info, "recorded_at_utc")
    try:
        timestamp = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentRecordError("experiment recorded_at_utc is invalid") from exc
    if timestamp.utcoffset() != timedelta(0):
        raise ExperimentRecordError("experiment recorded_at_utc must have UTC timezone")
    commit = info.get("repository_commit")
    if commit is not None and (
        not isinstance(commit, str) or not _COMMIT.fullmatch(commit)
    ):
        raise ExperimentRecordError("experiment repository_commit must be a 40-hex SHA")

    kind = info.get("candidate_kind")
    if kind not in {"amt", "hybrid"}:
        raise ExperimentRecordError("experiment candidate_kind must be amt or hybrid")
    analysis = payload.get("analysis")
    if kind == "hybrid":
        if info.get("commercial_eligible") is not False:
            raise ExperimentRecordError("hybrid analysis must be marked noncommercial")
        if not isinstance(analysis, dict) or analysis.get("provider") != "sheetsage2":
            raise ExperimentRecordError("hybrid SheetSage2 analysis identity is required")
        if analysis.get("commercial_eligible") is not False:
            raise ExperimentRecordError("hybrid SheetSage2 cannot be commercial-eligible")
        if analysis.get("license") != "CC BY-NC 4.0":
            raise ExperimentRecordError("hybrid analysis license must be explicit")
        for name in ("model_revision", "runtime_revision"):
            _required_text(analysis, name)
        _check_sha(analysis.get("artifact_sha256"), label="analysis artifact_sha256")
        if not isinstance(payload.get("source_stage_id"), str):
            raise ExperimentRecordError("hybrid source_stage_id is required")
        if events_root is None:
            raise ExperimentRecordError("hybrid events_root must be provided for verification")
    elif analysis is not None:
        raise ExperimentRecordError("nonhybrid candidate cannot contain analysis identity")

    artifacts = info.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(case_ids):
        raise ExperimentRecordError("experiment artifact manifest case set is inconsistent")

    for case in case_ids:
        fields = artifacts[case]
        if not isinstance(fields, dict):
            raise ExperimentRecordError(f"experiment artifact manifest missing: {case}")
        expected = {"mid_sha256", "musicxml_sha256"}
        if kind == "hybrid":
            expected.add("sheetsage_events_sha256")
        if set(fields) != expected:
            raise ExperimentRecordError(f"experiment artifact manifest fields invalid: {case}")
        for extension in ("mid", "musicxml"):
            _check_artifact(
                root / f"{case}.{extension}",
                fields[f"{extension}_sha256"],
                label=f"{case}.{extension}",
            )
        if kind == "hybrid":
            _check_artifact(
                events_root.expanduser().resolve() / f"{case}.json",
                fields["sheetsage_events_sha256"],
                label=f"{case}.sheetsage-events",
            )

    return {
        "validated": True,
        "stage_id": stage,
        "candidate_kind": kind,
        "run_id": run_id,
        "case_count": len(case_ids),
        "verified_artifacts": len(case_ids) * (3 if kind == "hybrid" else 2),
    }
