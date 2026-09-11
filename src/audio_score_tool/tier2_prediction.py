from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from .runtime_settings import runtime_settings
from .tier2_benchmark import Tier2EngineIdentity, load_manifest, resolve_locator
from .transcription_engine import resolve_transcription_engine

_PROVENANCE_FILE = "tier2-prediction-provenance.json"


def load_tier2_prediction_provenance(
    predictions_root: Path,
) -> tuple[str, Tier2EngineIdentity, tuple[str, ...], dict[str, Any]]:
    path = predictions_root / _PROVENANCE_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Tier 2 prediction provenance is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Tier 2 prediction provenance cannot be read: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1":
        raise ValueError("Unsupported Tier 2 prediction provenance schema")
    corpus_version = str(payload.get("corpus_version") or "").strip()
    engine = payload.get("engine")
    case_ids = payload.get("case_ids")
    if not corpus_version or not isinstance(engine, dict):
        raise ValueError("Tier 2 prediction provenance is incomplete")
    if not isinstance(case_ids, list) or not case_ids or not all(isinstance(item, str) for item in case_ids):
        raise ValueError("Tier 2 prediction provenance case_ids are invalid")
    identity = Tier2EngineIdentity(
        id=str(engine.get("id") or ""),
        model_revision=str(engine.get("model_revision") or ""),
        runtime_revision=str(engine.get("runtime_revision") or ""),
        artifact_sha256=str(engine.get("artifact_sha256") or ""),
    )
    return corpus_version, identity, tuple(case_ids), payload


def generate_tier2_predictions(
    manifest_path: Path,
    *,
    corpus_root: Path,
    predictions_root: Path,
    engine_id: str,
    model_revision: str,
    runtime_revision: str,
    artifact_sha256: str,
    model: str | None = None,
    device: str = "cpu",
) -> list[dict[str, str]]:
    """Run one exactly identified AMT engine over every Tier 2 case."""

    corpus_version, cases = load_manifest(manifest_path)
    predictions_root.mkdir(parents=True, exist_ok=True)

    base = runtime_settings()
    normalized_engine = engine_id.strip().lower()
    if normalized_engine == "yourmt3":
        normalized_engine = "mt3_infer"
    identity = Tier2EngineIdentity(
        id=normalized_engine,
        model_revision=model_revision,
        runtime_revision=runtime_revision,
        artifact_sha256=artifact_sha256,
    )

    settings = replace(base, transcription_engine=normalized_engine)
    if normalized_engine == "mt3_infer" and model:
        settings = replace(settings, mt3_model=model.strip().lower())
    if normalized_engine == "muscriptor" and model:
        settings = replace(settings, muscriptor_model=model.strip().lower())

    engine = resolve_transcription_engine(settings)
    if not engine.ready():
        raise RuntimeError(f"Tier 2 engine is not ready: {engine.describe()}")

    generated: list[dict[str, str]] = []
    for case in cases:
        if case.audio_locator is None:
            raise ValueError(f"Tier 2 case has no audio locator: {case.id}")
        audio_path = resolve_locator(case.audio_locator, corpus_root=corpus_root)
        if not audio_path.is_file():
            raise FileNotFoundError(f"Tier 2 audio is missing: {audio_path}")

        with tempfile.TemporaryDirectory(
            prefix=f".{case.id}-",
            dir=predictions_root,
        ) as raw_work:
            artifacts = engine.transcribe(
                audio_path,
                Path(raw_work),
                device=device,
            )
            midi_target = predictions_root / f"{case.id}.mid"
            xml_target = predictions_root / f"{case.id}.musicxml"
            shutil.copy2(artifacts.midi_path, midi_target)
            shutil.copy2(artifacts.musicxml_path, xml_target)

        generated.append(
            {
                "case_id": case.id,
                "audio": str(audio_path),
                "midi": str(midi_target),
                "musicxml": str(xml_target),
            }
        )

    provenance = {
        "schema_version": "1",
        "corpus_version": corpus_version,
        "engine": asdict(identity),
        "device": device,
        "case_ids": [item["case_id"] for item in generated],
    }
    (predictions_root / _PROVENANCE_FILE).write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return generated
