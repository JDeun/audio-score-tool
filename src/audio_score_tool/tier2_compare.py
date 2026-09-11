from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class Tier2ComparisonError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RankedEngine:
    rank: int
    engine_id: str
    model_revision: str
    runtime_revision: str
    artifact_sha256: str
    qualified: bool
    disqualifiers: tuple[str, ...]
    mean_time_to_publish_seconds: float | None
    mean_total_edit_actions: float | None
    mean_note_f1: float | None
    successful_export_rate: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "engine_id": self.engine_id,
            "model_revision": self.model_revision,
            "runtime_revision": self.runtime_revision,
            "artifact_sha256": self.artifact_sha256,
            "qualified": self.qualified,
            "disqualifiers": list(self.disqualifiers),
            "mean_time_to_publish_seconds": self.mean_time_to_publish_seconds,
            "mean_total_edit_actions": self.mean_total_edit_actions,
            "mean_note_f1": self.mean_note_f1,
            "successful_export_rate": self.successful_export_rate,
        }


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_tier2_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise Tier2ComparisonError(f"Tier 2 report must be an object: {path}")
    if payload.get("schema_version") != "1":
        raise Tier2ComparisonError(f"Unsupported Tier 2 report schema: {path}")
    if not isinstance(payload.get("engine"), dict) or not isinstance(payload.get("summary"), dict):
        raise Tier2ComparisonError(f"Incomplete Tier 2 report: {path}")
    return payload


def _candidate(payload: dict[str, Any]) -> dict[str, Any]:
    engine = payload["engine"]
    summary = payload["summary"]
    engine_id = str(engine.get("id") or "").strip()
    if not engine_id:
        raise Tier2ComparisonError("Tier 2 report engine.id is required")

    disqualifiers: list[str] = []
    export_rate = _number(summary.get("successful_export_rate"))
    publish_time = _number(summary.get("mean_time_to_publish_seconds"))
    edit_actions = _number(summary.get("mean_total_edit_actions"))
    note_f1 = _number(summary.get("mean_note_f1"))
    evaluated_note_cases = summary.get("evaluated_note_cases")

    if export_rate is None or export_rate < 1.0 or summary.get("all_exports_successful") is not True:
        disqualifiers.append("not_all_exports_successful")
    if publish_time is None:
        disqualifiers.append("missing_publish_time")
    if edit_actions is None:
        disqualifiers.append("missing_edit_actions")
    if not isinstance(evaluated_note_cases, int) or evaluated_note_cases <= 0 or note_f1 is None:
        disqualifiers.append("missing_note_evaluation")

    return {
        "engine_id": engine_id,
        "model_revision": str(engine.get("model_revision") or ""),
        "runtime_revision": str(engine.get("runtime_revision") or ""),
        "artifact_sha256": str(engine.get("artifact_sha256") or ""),
        "qualified": not disqualifiers,
        "disqualifiers": tuple(disqualifiers),
        "mean_time_to_publish_seconds": publish_time,
        "mean_total_edit_actions": edit_actions,
        "mean_note_f1": note_f1,
        "successful_export_rate": export_rate,
    }


def compare_tier2_reports(paths: list[Path]) -> dict[str, Any]:
    if len(paths) < 2:
        raise Tier2ComparisonError("At least two Tier 2 reports are required for comparison")
    reports = [load_tier2_report(path) for path in paths]
    corpus_versions = {str(report.get("corpus_version")) for report in reports}
    if len(corpus_versions) != 1:
        raise Tier2ComparisonError("Tier 2 reports must use the same corpus_version")

    candidates = [_candidate(report) for report in reports]
    engine_ids = [candidate["engine_id"] for candidate in candidates]
    if len(engine_ids) != len(set(engine_ids)):
        raise Tier2ComparisonError("Tier 2 comparison requires unique engine ids")

    candidates.sort(
        key=lambda item: (
            0 if item["qualified"] else 1,
            item["mean_time_to_publish_seconds"]
            if item["mean_time_to_publish_seconds"] is not None
            else float("inf"),
            item["mean_total_edit_actions"]
            if item["mean_total_edit_actions"] is not None
            else float("inf"),
            -(item["mean_note_f1"] if item["mean_note_f1"] is not None else -1.0),
            item["engine_id"],
        )
    )

    ranked = [RankedEngine(rank=index + 1, **candidate) for index, candidate in enumerate(candidates)]
    qualified = [item for item in ranked if item.qualified]
    recommended = qualified[0].engine_id if qualified else None
    return {
        "schema_version": "1",
        "corpus_version": next(iter(corpus_versions)),
        "selection_priority": [
            "all_exports_successful",
            "mean_time_to_publish_seconds",
            "mean_total_edit_actions",
            "mean_note_f1",
        ],
        "recommended_engine": recommended,
        "release_approved": False,
        "release_approval_note": (
            "Ranking is benchmark evidence only. Commercial provenance and #34 review are still required."
        ),
        "ranking": [item.as_dict() for item in ranked],
    }


def write_comparison(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
