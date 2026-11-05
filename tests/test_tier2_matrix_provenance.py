"""Regression contracts for real Tier 2 candidate/hybrid experiment provenance."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from audio_score_tool.tier2_prediction import load_tier2_prediction_provenance
from scripts.run_tier2_matrix import (
    _pinned_analysis_identity,
    _write_experiment_provenance,
    plan,
)

ENGINE_SHA = "a" * 64
SHEETSAGE_SHA = "b" * 64
CASE_ID = "piano-1"


def _fixture(directory: Path, *, candidate: str = "mt3_infer") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tier2-prediction-provenance.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "corpus_version": "owned-corpus-2026",
                "case_ids": [CASE_ID],
                "device": "cpu",
                "engine": {
                    "id": candidate,
                    "model_revision": "exact-model-commit",
                    "runtime_revision": "pinned-runtime",
                    "artifact_sha256": ENGINE_SHA,
                },
            }
        ),
        encoding="utf-8",
    )
    (directory / f"{CASE_ID}.mid").write_bytes(b"midi-prediction")
    (directory / f"{CASE_ID}.musicxml").write_bytes(b"musicxml-prediction")
    return directory


def _write(root: Path, stage_id: str, *, source: Path | None = None,
           events: Path | None = None, analysis: dict | None = None) -> dict:
    return _write_experiment_provenance(
        source_root=source or root,
        prediction_root=root,
        stage_id=stage_id,
        corpus_version="owned-corpus-2026",
        case_ids=(CASE_ID,),
        analysis=analysis,
        event_root=events,
    )


def test_amt_stage_preserves_real_runner_identity_but_names_unique_candidate(tmp_path: Path):
    source = _fixture(tmp_path / "yourmt3")
    record = _write(source, "yourmt3")

    assert record["engine"]["id"] == "yourmt3"
    assert record["inference_engine"]["id"] == "mt3_infer"
    assert record["engine"]["artifact_sha256"] == ENGINE_SHA
    assert record["experiment"]["candidate_kind"] == "amt"
    assert len(record["experiment"]["run_id"]) == 32
    assert record["experiment"]["artifacts"][CASE_ID]["mid_sha256"] == hashlib.sha256(
        b"midi-prediction"
    ).hexdigest()
    version, engine, ids, loaded = load_tier2_prediction_provenance(source)
    assert version == "owned-corpus-2026"
    assert engine.id == "yourmt3"
    assert ids == (CASE_ID,)
    assert loaded["inference_engine"]["id"] == "mt3_infer"

    second = _fixture(tmp_path / "mr-mt3")
    other = _write(second, "mr-mt3")
    assert other["engine"]["id"] != record["engine"]["id"]
    assert other["inference_engine"]["id"] == record["inference_engine"]["id"]


def test_hybrid_pins_sheetsage2_noncommercial_checkpoint_and_event_hashes(tmp_path: Path):
    base = _fixture(tmp_path / "yourmt3")
    _write(base, "yourmt3")
    hybrid = tmp_path / "yourmt3+sheetsage2"
    hybrid.mkdir()
    (hybrid / f"{CASE_ID}.mid").write_bytes(b"midi-prediction")
    (hybrid / f"{CASE_ID}.musicxml").write_bytes(b"augmented-score")
    events = tmp_path / "sheetsage2"
    events.mkdir()
    (events / f"{CASE_ID}.json").write_text(
        json.dumps({"schema_version": 1, "chords": [{"time_seconds": 0, "label": "C:maj"}]}),
        encoding="utf-8",
    )
    analysis = {
        "provider": "sheetsage2",
        "model_revision": "pinned-hf-revision",
        "runtime_revision": "pinned-requirements",
        "artifact_sha256": SHEETSAGE_SHA,
        "license": "CC BY-NC 4.0",
        "commercial_eligible": False,
    }
    record = _write_experiment_provenance(
        source_root=base,
        prediction_root=hybrid,
        stage_id="yourmt3+sheetsage2",
        corpus_version="owned-corpus-2026",
        case_ids=(CASE_ID,),
        analysis=analysis,
        event_root=events,
    )

    assert record["engine"]["id"] == "yourmt3+sheetsage2"
    assert record["source_stage_id"] == "yourmt3"
    assert record["inference_engine"]["id"] == "mt3_infer"
    assert record["analysis"] == analysis
    assert record["experiment"]["candidate_kind"] == "hybrid"
    assert record["experiment"]["commercial_eligible"] is False
    assert record["experiment"]["artifacts"][CASE_ID]["musicxml_sha256"] == hashlib.sha256(
        b"augmented-score"
    ).hexdigest()
    assert record["experiment"]["artifacts"][CASE_ID]["sheetsage_events_sha256"] == hashlib.sha256(
        (events / f"{CASE_ID}.json").read_bytes()
    ).hexdigest()
    assert load_tier2_prediction_provenance(hybrid)[1].id == "yourmt3+sheetsage2"


def test_unverified_hybrid_fails_closed_and_preserves_source(tmp_path: Path):
    base = _fixture(tmp_path / "base")
    hybrid = tmp_path / "hybrid"
    _fixture(hybrid)
    with pytest.raises(ValueError, match="analysis checkpoint"):
        _write_experiment_provenance(
            source_root=base, prediction_root=hybrid, stage_id="hybrid",
            corpus_version="owned-corpus-2026", case_ids=(CASE_ID,),
        )
    before = (hybrid / "tier2-prediction-provenance.json").read_bytes()
    with pytest.raises(ValueError, match="corpus manifest"):
        _write_experiment_provenance(
            source_root=base, prediction_root=hybrid, stage_id="hybrid",
            corpus_version="different-corpus", case_ids=(CASE_ID,),
            analysis={"provider": "sheetsage2"},
        )
    assert (hybrid / "tier2-prediction-provenance.json").read_bytes() == before


def test_missing_hybrid_events_refuses_a_successful_candidate(tmp_path: Path):
    source = _fixture(tmp_path / "source")
    target = _fixture(tmp_path / "target")
    with pytest.raises(FileNotFoundError, match="analysis events"):
        _write_experiment_provenance(
            source_root=source,
            prediction_root=target,
            stage_id="base+sheetsage2",
            corpus_version="owned-corpus-2026",
            case_ids=(CASE_ID,),
            analysis={"provider": "sheetsage2", "model_revision": "pinned"},
            event_root=tmp_path / "missing-events",
        )


def test_sheet_sage_identity_requires_all_three_pins(monkeypatch: pytest.MonkeyPatch):
    keys = ("MODEL_REVISION", "RUNTIME_REVISION", "ARTIFACT_SHA256")
    for key in keys:
        monkeypatch.delenv("TIER2_SHEETSAGE2_" + key, raising=False)
    assert _pinned_analysis_identity() is None
    monkeypatch.setenv("TIER2_SHEETSAGE2_MODEL_REVISION", "checkpoint-sha")
    monkeypatch.setenv("TIER2_SHEETSAGE2_RUNTIME_REVISION", "runtime-sha")
    monkeypatch.setenv("TIER2_SHEETSAGE2_ARTIFACT_SHA256", "not-a-sha")
    assert _pinned_analysis_identity() is None
    monkeypatch.setenv("TIER2_SHEETSAGE2_ARTIFACT_SHA256", SHEETSAGE_SHA)
    identity = _pinned_analysis_identity()
    assert identity is not None
    assert identity["commercial_eligible"] is False
    assert identity["artifact_sha256"] == SHEETSAGE_SHA


@pytest.mark.parametrize("stage_id", ["../escape", "abc\\evil", " space", "/path", "a..b"])
def test_stage_identifier_rejects_unsafe_directory_names(stage_id: str):
    with pytest.raises(ValueError, match="unsafe"):
        plan({"schema_version": 1, "stages": [
            {"id": stage_id, "kind": "amt", "enabled": False},
        ]})
