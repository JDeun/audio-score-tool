from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from .metrics import evaluate_midi_files

_EDIT_KEYS = (
    "manual_note_edits",
    "manual_chord_edits",
    "manual_measure_edits",
    "manual_part_edits",
    "manual_lyric_edits",
    "manual_layout_edits",
)


@dataclass(frozen=True, slots=True)
class Tier2EngineIdentity:
    id: str
    model_revision: str
    runtime_revision: str
    artifact_sha256: str


@dataclass(frozen=True, slots=True)
class Tier2Case:
    id: str
    title: str
    category: str
    genre: str
    tags: tuple[str, ...]
    reference_midi: str | None


@dataclass(frozen=True, slots=True)
class Tier2CaseResult:
    case_id: str
    engine: Tier2EngineIdentity
    music_metrics: dict[str, Any]
    product_metrics: dict[str, Any]
    prediction_midi: str | None
    reference_midi: str | None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = "1"
        return payload


@dataclass(frozen=True, slots=True)
class Tier2Report:
    corpus_version: str
    engine: Tier2EngineIdentity
    cases: tuple[Tier2CaseResult, ...]
    summary: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "corpus_version": self.corpus_version,
            "engine": asdict(self.engine),
            "cases": [case.as_dict() for case in self.cases],
            "summary": self.summary,
        }


def _require_string(payload: dict[str, Any], key: str, *, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def load_manifest(path: Path) -> tuple[str, tuple[Tier2Case, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Tier 2 manifest root must be an object")
    corpus_version = _require_string(payload, "corpus_version", context="manifest")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("manifest.cases must be a non-empty array")

    cases: list[Tier2Case] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"manifest.cases[{index}] must be an object")
        case_id = _require_string(raw, "id", context=f"manifest.cases[{index}]")
        if case_id in seen:
            raise ValueError(f"duplicate Tier 2 case id: {case_id}")
        seen.add(case_id)
        reference = raw.get("reference") or {}
        if not isinstance(reference, dict):
            raise ValueError(f"manifest.cases[{index}].reference must be an object")
        tags = raw.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
            raise ValueError(f"manifest.cases[{index}].tags must be an array of strings")
        cases.append(
            Tier2Case(
                id=case_id,
                title=_require_string(raw, "title", context=f"manifest.cases[{index}]"),
                category=_require_string(raw, "category", context=f"manifest.cases[{index}]"),
                genre=_require_string(raw, "genre", context=f"manifest.cases[{index}]"),
                tags=tuple(tags),
                reference_midi=reference.get("midi") if isinstance(reference.get("midi"), str) else None,
            )
        )
    return corpus_version, tuple(cases)


def resolve_locator(locator: str, *, corpus_root: Path) -> Path:
    if locator.startswith("private://"):
        relative = locator.removeprefix("private://")
        candidate = corpus_root / relative
    elif locator.startswith("file://"):
        candidate = Path(locator.removeprefix("file://"))
    else:
        raw = Path(locator)
        candidate = raw if raw.is_absolute() else corpus_root / raw
    return candidate.resolve()


def load_product_metrics(path: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {key: 0 for key in _EDIT_KEYS}
    defaults.update(
        {
            "total_edit_actions": 0,
            "time_to_publish_seconds": None,
            "successful_export": False,
        }
    )
    if not path.exists():
        return defaults
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"product metrics must be an object: {path}")
    result = {**defaults, **payload}
    for key in _EDIT_KEYS:
        value = result[key]
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{key} must be a non-negative integer")
    calculated = sum(int(result[key]) for key in _EDIT_KEYS)
    declared = result.get("total_edit_actions")
    if declared in (None, 0):
        result["total_edit_actions"] = calculated
    elif declared != calculated:
        raise ValueError(
            f"total_edit_actions mismatch in {path}: declared={declared}, calculated={calculated}"
        )
    duration = result.get("time_to_publish_seconds")
    if duration is not None and (not isinstance(duration, (int, float)) or duration < 0):
        raise ValueError("time_to_publish_seconds must be null or a non-negative number")
    if not isinstance(result.get("successful_export"), bool):
        raise ValueError("successful_export must be boolean")
    return result


def _load_optional_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"optional metrics must be an object: {path}")
    return payload


def evaluate_tier2_case(
    case: Tier2Case,
    *,
    engine: Tier2EngineIdentity,
    corpus_root: Path,
    predictions_root: Path,
) -> Tier2CaseResult:
    prediction_midi = predictions_root / f"{case.id}.mid"
    reference_midi = (
        resolve_locator(case.reference_midi, corpus_root=corpus_root)
        if case.reference_midi is not None
        else None
    )
    music_metrics = _load_optional_metrics(predictions_root / f"{case.id}.music.json")
    if prediction_midi.exists() and reference_midi is not None and reference_midi.exists():
        music_metrics = {**music_metrics, **evaluate_midi_files(prediction_midi, reference_midi).as_dict()}
    product_metrics = load_product_metrics(predictions_root / f"{case.id}.product.json")
    return Tier2CaseResult(
        case_id=case.id,
        engine=engine,
        music_metrics=music_metrics,
        product_metrics=product_metrics,
        prediction_midi=str(prediction_midi) if prediction_midi.exists() else None,
        reference_midi=str(reference_midi) if reference_midi is not None else None,
    )


def _average(values: list[float]) -> float | None:
    return round(mean(values), 6) if values else None


def summarize_tier2_results(results: list[Tier2CaseResult]) -> dict[str, Any]:
    note_f1 = [float(r.music_metrics["note_f1"]) for r in results if r.music_metrics.get("note_f1") is not None]
    instrument_f1 = [
        float(r.music_metrics["instrument_f1"])
        for r in results
        if r.music_metrics.get("instrument_f1") is not None
    ]
    edit_actions = [int(r.product_metrics["total_edit_actions"]) for r in results]
    publish_times = [
        float(r.product_metrics["time_to_publish_seconds"])
        for r in results
        if r.product_metrics.get("time_to_publish_seconds") is not None
    ]
    exports = [bool(r.product_metrics.get("successful_export")) for r in results]
    return {
        "case_count": len(results),
        "evaluated_note_cases": len(note_f1),
        "mean_note_f1": _average(note_f1),
        "mean_instrument_f1": _average(instrument_f1),
        "mean_total_edit_actions": _average([float(value) for value in edit_actions]),
        "mean_time_to_publish_seconds": _average(publish_times),
        "successful_export_rate": _average([1.0 if value else 0.0 for value in exports]),
        "all_exports_successful": bool(exports) and all(exports),
    }


def run_tier2_benchmark(
    manifest_path: Path,
    *,
    corpus_root: Path,
    predictions_root: Path,
    engine: Tier2EngineIdentity,
) -> Tier2Report:
    corpus_version, cases = load_manifest(manifest_path)
    results = [
        evaluate_tier2_case(
            case,
            engine=engine,
            corpus_root=corpus_root,
            predictions_root=predictions_root,
        )
        for case in cases
    ]
    return Tier2Report(
        corpus_version=corpus_version,
        engine=engine,
        cases=tuple(results),
        summary=summarize_tier2_results(results),
    )


def write_tier2_report(path: Path, report: Tier2Report) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
