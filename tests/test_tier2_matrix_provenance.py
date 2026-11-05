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
           events: Path | None = None, analysis: dict | None = None,
           manifest: Path | None = None) -> dict:
    return _write_experiment_provenance(
        source_root=source or root,
        prediction_root=root,
        stage_id=stage_id,
        corpus_version="owned-corpus-2026",
        case_ids=(CASE_ID,),
        manifest_path=manifest,
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


def test_non_dry_matrix_reaches_hybrid_evaluation_with_distinct_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Exercise full matrix branching, not just individual helper functions."""
    import sys

    from music21 import note, stream

    from scripts import run_tier2_matrix

    corpus = tmp_path / "licensed-corpus"
    (corpus / "audio").mkdir(parents=True)
    (corpus / "audio" / "piano.wav").write_bytes(b"owned-test-placeholder")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "corpus_version": "owned-corpus-2026",
            "cases": [{
                "id": CASE_ID, "title": "piano mock",
                "category": "solo_piano", "genre": "classical",
                "tags": ["piano"],
                "audio": {"locator": "private://audio/piano.wav"},
            }],
        }),
        encoding="utf-8",
    )
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps({
            "schema_version": 1, "stages": [
                {"id": "yourmt3", "kind": "amt", "enabled": True,
                 "engine": "mt3_infer", "model": "yourmt3"},
                {"id": "yourmt3+sheetsage2", "kind": "hybrid",
                 "enabled": True, "base_stage": "yourmt3"},
            ],
        }),
        encoding="utf-8",
    )
    output_root = tmp_path / "output"
    events = output_root / "sheetsage2"
    events.mkdir(parents=True)
    (events / f"{CASE_ID}.json").write_text(
        json.dumps({
            "schema_version": 1,
            "chords": [{"time_seconds": 0, "label": "C:maj"}],
            "keys": [{"time_seconds": 0, "label": "C:major"}],
        }),
        encoding="utf-8",
    )
    for prefix, suffix in (
        ("TIER2_YOURMT3_", "MODEL_REVISION"),
        ("TIER2_YOURMT3_", "RUNTIME_REVISION"),
        ("TIER2_SHEETSAGE2_", "MODEL_REVISION"),
        ("TIER2_SHEETSAGE2_", "RUNTIME_REVISION"),
    ):
        monkeypatch.setenv(prefix + suffix, "pinned-test-revision")
    monkeypatch.setenv("TIER2_YOURMT3_ARTIFACT_SHA256", ENGINE_SHA)
    monkeypatch.setenv("TIER2_SHEETSAGE2_ARTIFACT_SHA256", SHEETSAGE_SHA)

    evaluated = []

    def run(command, *, check):
        assert check is True
        operation = Path(command[1]).name
        if operation == "generate_tier2_predictions.py":
            root = Path(command[command.index("--predictions-root") + 1])
            _fixture(root)
            score = stream.Score()
            part = stream.Part()
            part.append(note.Note("C4", quarterLength=1))
            score.append(part)
            score.write("musicxml", fp=str(root / f"{CASE_ID}.musicxml"))
        elif operation == "run_tier2_benchmark.py":
            root = Path(command[command.index("--predictions-root") + 1])
            version, identity, cases, payload = load_tier2_prediction_provenance(root)
            assert version == "owned-corpus-2026"
            assert cases == (CASE_ID,)
            assert payload["experiment"]["artifacts"][CASE_ID]["musicxml_sha256"]
            evaluated.append(identity.id)
            report = Path(command[command.index("--output") + 1])
            report.write_text(json.dumps({"engine_id": identity.id}), encoding="utf-8")
        elif operation == "compare_tier2_reports.py":
            assert evaluated == ["yourmt3", "yourmt3+sheetsage2"]
            Path(command[command.index("--output") + 1]).write_text(
                "{}", encoding="utf-8"
            )
        else:
            raise AssertionError(f"unexpected subprocess: {command}")

    monkeypatch.setattr(run_tier2_matrix.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", [
        "run_tier2_matrix.py", "--matrix", str(matrix), "--manifest", str(manifest),
        "--corpus-root", str(corpus), "--output-root", str(output_root),
    ])
    assert run_tier2_matrix.main() == 0
    assert evaluated == ["yourmt3", "yourmt3+sheetsage2"]
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    assert summary["completed"] == 2
    assert summary["blocked"] == 0
    assert all(entry["status"] == "completed" for entry in summary["results"])


def test_receipt_validator_detects_modified_output_files(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    root = _fixture(tmp_path / "amt")
    _write(root, "yourmt3")
    receipt = validate_tier2_experiment_record(root)
    assert receipt["validated"] is True
    assert receipt["verified_artifacts"] == 2
    (root / f"{CASE_ID}.musicxml").write_bytes(b"tampered-after-prediction")
    with pytest.raises(ExperimentRecordError, match="SHA-256 mismatch"):
        validate_tier2_experiment_record(root)


def test_receipt_validator_rejects_bad_record_metadata(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    root = _fixture(tmp_path / "amt")
    _write(root, "yourmt3")
    path = root / "tier2-prediction-provenance.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    original["experiment"]["run_id"] = "untracked"
    path.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ExperimentRecordError, match="run_id"):
        validate_tier2_experiment_record(root)


def test_receipt_validator_rejects_mismatched_corpus_manifest(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    root = _fixture(tmp_path / "amt")
    _write(root, "yourmt3")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "corpus_version": "wrong-version",
            "cases": [{
                "id": CASE_ID, "title": "fixture", "category": "solo",
                "genre": "test", "tags": [],
            }],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ExperimentRecordError, match="corpus manifest identity"):
        validate_tier2_experiment_record(root, manifest_path=manifest)


def test_hybrid_receipt_requires_events_and_noncommercial_license(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    base = _fixture(tmp_path / "base")
    _write(base, "yourmt3")
    hybrid = _fixture(tmp_path / "hybrid")
    events = tmp_path / "sheetsage2"
    events.mkdir()
    (events / f"{CASE_ID}.json").write_text(
        json.dumps({"schema_version": 1, "chords": []}), encoding="utf-8",
    )
    _write_experiment_provenance(
        source_root=base,
        prediction_root=hybrid,
        stage_id="yourmt3+sheetsage2",
        corpus_version="owned-corpus-2026",
        case_ids=(CASE_ID,),
        analysis={
            "provider": "sheetsage2",
            "model_revision": "checked-checkpoint",
            "runtime_revision": "checked-runtime",
            "artifact_sha256": SHEETSAGE_SHA,
            "license": "CC BY-NC 4.0",
            "commercial_eligible": False,
        },
        event_root=events,
    )
    assert validate_tier2_experiment_record(
        hybrid, events_root=events,
    )["verified_artifacts"] == 3
    with pytest.raises(ExperimentRecordError, match="events_root"):
        validate_tier2_experiment_record(hybrid)

    provenance = hybrid / "tier2-prediction-provenance.json"
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    payload["analysis"]["commercial_eligible"] = True
    provenance.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExperimentRecordError, match="cannot be commercial"):
        validate_tier2_experiment_record(hybrid, events_root=events)


@pytest.mark.parametrize("case_id", ["../escape", "folder/note", "C:\\Windows", " bad"])
def test_corpus_loader_rejects_unsafe_case_ids(tmp_path: Path, case_id: str):
    from audio_score_tool.tier2_benchmark import load_manifest

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({
            "corpus_version": "1", "cases": [{
                "id": case_id, "title": "unsafe", "category": "solo",
                "genre": "test", "tags": [],
            }],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsafe Tier 2 case id"):
        load_manifest(path)


def test_validate_experiment_cli_reports_verified_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
):
    import sys

    from scripts import validate_tier2_experiment

    root = _fixture(tmp_path / "amt")
    _write(root, "yourmt3")
    monkeypatch.setattr(sys, "argv", [
        "validate_tier2_experiment.py", "--predictions-root", str(root),
    ])
    assert validate_tier2_experiment.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["validated"] is True
    assert output["stage_id"] == "yourmt3"
    assert output["verified_artifacts"] == 2


def test_receipt_binds_exact_manifest_bytes_not_just_case_ids(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    root = _fixture(tmp_path / "amt")
    manifest = tmp_path / "manifest.json"
    source = {
        "corpus_version": "owned-corpus-2026",
        "cases": [{
            "id": CASE_ID, "title": "reviewed input",
            "category": "solo", "genre": "classical", "tags": [],
        }],
    }
    manifest.write_text(json.dumps(source), encoding="utf-8")
    record = _write(root, "yourmt3", manifest=manifest)
    assert record["experiment"]["corpus_manifest_sha256"] == hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert validate_tier2_experiment_record(
        root, manifest_path=manifest,
    )["validated"] is True

    source["cases"][0]["title"] = "silently modified input"
    manifest.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ExperimentRecordError, match="manifest SHA-256 mismatch"):
        validate_tier2_experiment_record(root, manifest_path=manifest)


def test_receipt_refuses_mutated_model_revision(tmp_path: Path):
    from audio_score_tool.tier2_experiment_record import (
        ExperimentRecordError,
        validate_tier2_experiment_record,
    )

    root = _fixture(tmp_path / "amt")
    _write(root, "yourmt3")
    provenance = root / "tier2-prediction-provenance.json"
    record = json.loads(provenance.read_text(encoding="utf-8"))
    record["engine"]["model_revision"] = "silently-changed-checkpoint"
    provenance.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ExperimentRecordError, match="candidate identity differs"):
        validate_tier2_experiment_record(root)
