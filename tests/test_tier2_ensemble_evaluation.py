"""Real-reference contract tests for AMT consensus candidate comparisons."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import mido
import pytest

from scripts.evaluate_tier2_ensemble import evaluate_ensemble_candidates
from scripts.run_tier2_matrix import _write_experiment_provenance


def _midi(path: Path, notes: list[tuple[int, float, float]]) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    events = []
    for pitch, start, end in notes:
        events.extend([
            (round(start * 960), 1, pitch,
             mido.Message("note_on", channel=0, note=pitch, velocity=90)),
            (round(end * 960), 0, pitch,
             mido.Message("note_off", channel=0, note=pitch, velocity=0)),
        ])
    previous = 0
    for tick, _order, _pitch, msg in sorted(events, key=lambda item: item[:3]):
        msg.time = tick - previous
        track.append(msg)
        previous = tick
    midi.tracks.append(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.save(str(path))


def _corpus(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    corpus = tmp_path / "private"
    references = corpus / "reference"
    references.mkdir(parents=True)
    _midi(references / "a.mid", [(60, 0.1, 0.5), (64, 0.7, 1.0)])
    _midi(references / "b.mid", [(72, 0.1, 0.5)])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "corpus_version": "owned-fixtures-v1",
        "cases": [
            {
                "id": cid, "title": f"private {cid}", "category": "solo_piano",
                "genre": "classical", "tags": ["owned"],
                "reference": {"midi": f"private://reference/{cid}.mid"},
            } for cid in ("a", "b")
        ],
    }), encoding="utf-8")
    first = tmp_path / "yourmt3"
    second = tmp_path / "mr-mt3"
    for root, name in [(first, "yourmt3"), (second, "mr-mt3")]:
        root.mkdir()
        (root / "tier2-prediction-provenance.json").write_text(json.dumps({
            "schema_version": "1", "corpus_version": "owned-fixtures-v1",
            "case_ids": ["a", "b"], "engine": {
                "id": name, "model_revision": "pinned-model",
                "runtime_revision": "pinned-runtime", "artifact_sha256": "a" * 64,
            },
        }), encoding="utf-8")
    _midi(first / "a.mid", [(60, 0.1, 0.5), (67, 0.7, 1.0)])
    _midi(second / "a.mid", [(60, 0.12, 0.52), (64, 0.7, 1.0)])
    _midi(first / "b.mid", [])
    _midi(second / "b.mid", [(72, 0.1, 0.5)])
    for root, candidate in ((first, "yourmt3"), (second, "mr-mt3")):
        _write_experiment_provenance(
            source_root=root, prediction_root=root,
            stage_id=candidate, corpus_version="owned-fixtures-v1",
            case_ids=("a", "b"), manifest_path=manifest,
        )
    return manifest, corpus, first, second


def _evaluate(tmp_path: Path) -> dict:
    manifest, corpus, first, second = _corpus(tmp_path)
    return evaluate_ensemble_candidates(
        manifest, corpus_root=corpus, first_root=first, second_root=second,
        output_root=tmp_path / "outputs",
    )


def test_ensemble_evaluation_measures_independent_reference_not_prediction_agreement(tmp_path: Path):
    result = _evaluate(tmp_path)
    assert result["case_count"] == 2
    assert result["source_candidates"]["first"]["id"] == "yourmt3"
    assert result["source_candidates"]["second"]["id"] == "mr-mt3"
    a, b = result["cases"]
    assert a["case_id"] == "a"
    assert a["notes"] == {"first": 2, "second": 2, "consensus": 1}
    assert a["metrics"]["first"]["note_f1"] == pytest.approx(0.5)
    assert a["metrics"]["second"]["note_f1"] == pytest.approx(1.0)
    assert a["metrics"]["consensus"]["note_precision"] == pytest.approx(1.0)
    assert a["metrics"]["consensus"]["note_recall"] == pytest.approx(0.5)
    assert a["metrics"]["consensus"]["note_f1"] == pytest.approx(2 / 3)
    assert a["metrics"]["consensus"]["instrument_f1"] == pytest.approx(2 / 3)
    assert b["notes"] == {"first": 0, "second": 1, "consensus": 0}
    assert result["summary"]["first"]["empty_output_rate"] == pytest.approx(0.5)
    assert result["summary"]["second"]["empty_output_rate"] == 0
    assert result["summary"]["consensus"]["empty_output_rate"] == pytest.approx(0.5)
    assert result["model_inference_runtime_seconds"] is None
    assert result["human_publish_metrics"] is None
    assert result["commercial_baseline_approved"] is False
    assert result["cases"][0]["prediction_sha256"]["consensus"] == hashlib.sha256(
        (tmp_path / "outputs/consensus/a.mid").read_bytes()
    ).hexdigest()
    saved = json.loads((tmp_path / "outputs/ensemble-evaluation.json").read_text())
    assert saved["summary"] == result["summary"]


def test_ensemble_provenance_case_order_mismatch_fails_before_any_output(tmp_path: Path):
    manifest, corpus, first, second = _corpus(tmp_path)
    src = second / "tier2-prediction-provenance.json"
    d = json.loads(src.read_text(encoding="utf-8"))
    d["case_ids"] = ["b", "a"]
    src.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="corpus manifest identity"):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=tmp_path / "results",
        )
    assert not (tmp_path / "results").exists()


def test_ensemble_missing_independent_reference_fails_closed(tmp_path: Path):
    manifest, corpus, first, second = _corpus(tmp_path)
    (corpus / "reference/b.mid").unlink()
    with pytest.raises(FileNotFoundError, match="reference"):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=tmp_path / "results",
        )
    assert not (tmp_path / "results").exists()


def test_ensemble_duplicate_engine_ids_are_not_distinct_candidates(tmp_path: Path):
    manifest, corpus, first, second = _corpus(tmp_path)
    p = second / "tier2-prediction-provenance.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["engine"]["id"] = "yourmt3"
    d["stage_id"] = "yourmt3"
    p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct engine IDs"):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=tmp_path / "results",
        )


@pytest.mark.parametrize("parameter,value", [
    ("onset_tolerance", float("nan")),
    ("min_overlap", 1.5),
    ("metric_onset_tolerance", 0.0),
])
def test_ensemble_rejects_invalid_thresholds(
    tmp_path: Path, parameter: str, value: float,
):
    manifest, corpus, first, second = _corpus(tmp_path)
    with pytest.raises(ValueError, match=parameter):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=tmp_path / "results", **{parameter: value},
        )


def test_ensemble_output_must_not_overwrite_inputs(tmp_path: Path):
    manifest, corpus, first, second = _corpus(tmp_path)
    with pytest.raises(ValueError, match="source and output"):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=first,
        )


def test_ensemble_consensus_is_not_a_commercial_release_decision(tmp_path: Path):
    result = _evaluate(tmp_path)
    assert not result["commercial_baseline_approved"]
    assert result["notes"].startswith("Metrics use independent MIDI references")
    assert result["consensus"]["total_consensus_runtime_seconds"] >= 0


def test_ensemble_rejects_tampered_candidate_before_scoring(tmp_path: Path):
    manifest, corpus, first, second = _corpus(tmp_path)
    (first / "a.mid").write_bytes(b"modified-prediction")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        evaluate_ensemble_candidates(
            manifest, corpus_root=corpus, first_root=first, second_root=second,
            output_root=tmp_path / "results",
        )
    assert not (tmp_path / "results").exists()


def test_ensemble_cli_returns_report_from_frozen_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
):
    import sys

    from scripts import evaluate_tier2_ensemble

    manifest, corpus, first, second = _corpus(tmp_path)
    output = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", [
        "evaluate_tier2_ensemble.py", str(manifest),
        "--corpus-root", str(corpus), "--first-root", str(first),
        "--second-root", str(second), "--output-root", str(output),
    ])
    assert evaluate_tier2_ensemble.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["case_count"] == 2
    assert report["candidate_ids"] == ["yourmt3", "mr-mt3"]
    assert (output / "ensemble-evaluation.json").is_file()
