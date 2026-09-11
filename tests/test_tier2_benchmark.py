from __future__ import annotations

import json
from pathlib import Path

import mido
import pytest

from audio_score_tool.tier2_benchmark import (
    Tier2EngineIdentity,
    load_manifest,
    load_product_metrics,
    run_tier2_benchmark,
)


def _write_midi(path: Path, pitches: list[int]) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    for index, pitch in enumerate(pitches):
        track.append(mido.Message("note_on", note=pitch, velocity=90, time=0 if index == 0 else 360))
        track.append(mido.Message("note_off", note=pitch, velocity=0, time=120))
    midi.save(path)


def _manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "corpus_version": "1",
                "cases": [
                    {
                        "id": "case-001",
                        "title": "Example",
                        "category": "piano",
                        "genre": "ballad",
                        "tags": ["4_4"],
                        "reference": {"midi": "private://reference/case-001.mid"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_manifest_rejects_duplicate_case_ids(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "corpus_version": "1",
                "cases": [
                    {"id": "same", "title": "A", "category": "x", "genre": "x"},
                    {"id": "same", "title": "B", "category": "x", "genre": "x"},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate Tier 2 case id"):
        load_manifest(manifest)


def test_product_metrics_calculate_edit_total(tmp_path: Path):
    metrics = tmp_path / "case.product.json"
    metrics.write_text(
        json.dumps(
            {
                "manual_note_edits": 3,
                "manual_chord_edits": 2,
                "manual_measure_edits": 1,
                "manual_part_edits": 0,
                "manual_lyric_edits": 4,
                "manual_layout_edits": 5,
                "time_to_publish_seconds": 120.0,
                "successful_export": True,
            }
        ),
        encoding="utf-8",
    )
    result = load_product_metrics(metrics)
    assert result["total_edit_actions"] == 15


def test_product_metrics_reject_inconsistent_total(tmp_path: Path):
    metrics = tmp_path / "case.product.json"
    metrics.write_text(
        json.dumps({"manual_note_edits": 2, "total_edit_actions": 99}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="total_edit_actions mismatch"):
        load_product_metrics(metrics)


def test_tier2_runner_merges_midi_and_product_metrics(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest)
    corpus = tmp_path / "corpus"
    predictions = tmp_path / "predictions"
    (corpus / "reference").mkdir(parents=True)
    predictions.mkdir()
    _write_midi(corpus / "reference" / "case-001.mid", [60, 64, 67])
    _write_midi(predictions / "case-001.mid", [60, 64, 67])
    (predictions / "case-001.product.json").write_text(
        json.dumps(
            {
                "manual_note_edits": 2,
                "manual_layout_edits": 1,
                "time_to_publish_seconds": 90.0,
                "successful_export": True,
            }
        ),
        encoding="utf-8",
    )

    report = run_tier2_benchmark(
        manifest,
        corpus_root=corpus,
        predictions_root=predictions,
        engine=Tier2EngineIdentity(
            id="test-engine",
            model_revision="model-sha",
            runtime_revision="runtime-sha",
            artifact_sha256="abc123",
        ),
    )

    assert len(report.cases) == 1
    assert report.cases[0].music_metrics["note_f1"] == 1.0
    assert report.cases[0].product_metrics["total_edit_actions"] == 3
    assert report.summary["mean_note_f1"] == 1.0
    assert report.summary["mean_total_edit_actions"] == 3.0
    assert report.summary["mean_time_to_publish_seconds"] == 90.0
    assert report.summary["all_exports_successful"] is True
