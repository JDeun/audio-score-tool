"""Independent-reference chord and beat comparison without source recordings."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mir_eval")

from scripts import compare_chord_playalong
from scripts.import_manual_chord_chart import import_manual_chord_chart


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(header)
        w.writerows(rows)
    return path


def _inputs(tmp_path: Path) -> tuple[dict, dict, dict]:
    sha = "a" * 64
    chords = _write_csv(
        tmp_path / "manual.csv", ("time_seconds", "chord"),
        [("0", "C"), ("2", "Am")],
    )
    beats = _write_csv(
        tmp_path / "beats.csv", ("time_seconds", "kind"),
        [("0", "downbeat"), ("0.5", "beat"), ("1", "beat"),
         ("1.5", "beat"), ("2", "downbeat"), ("2.5", "beat"),
         ("3", "beat"), ("3.5", "beat")],
    )
    manual = import_manual_chord_chart(
        chords, duration_seconds=4.0, recording_sha256=sha, beats_csv=beats,
    )
    sheetsage = json.loads(json.dumps(manual))
    sheetsage["source"] = {"type": "sheetsage2", "model_revision": "test-only"}
    reference = {
        "schema_version": 1, "recording_sha256": sha, "duration_seconds": 4.0,
        "annotators": [
            {"index": 0, "intervals": [
                {"start": 0.0, "end": 2.0, "label": "C:maj"},
                {"start": 2.0, "end": 4.0, "label": "A:min"},
            ]},
            {"index": 1, "intervals": [
                {"start": 0.0, "end": 2.0, "label": "C:maj"},
                {"start": 2.0, "end": 4.0, "label": "A:min"},
            ]},
        ],
        "beats": manual["beats"],
        "downbeats": manual["downbeats"],
    }
    return reference, manual, sheetsage


def test_perfect_independent_chord_beat_metrics(tmp_path: Path):
    reference, manual, sheetsage = _inputs(tmp_path)
    report = compare_chord_playalong.compare_chord_predictions(reference, manual, sheetsage)
    assert report["independent_annotators"] == 2
    assert report["by_model"]["manual"]["chords"]["mean_by_metric"]["root"] == pytest.approx(1)
    assert report["by_model"]["manual"]["chords"]["mean_by_metric"]["majmin"] == pytest.approx(1)
    assert report["by_model"]["sheetsage2"]["chords"]["mean_by_metric"]["sevenths"] == pytest.approx(1)
    assert report["by_model"]["manual"]["beat_f1"] == pytest.approx(1)
    assert report["by_model"]["manual"]["downbeat_f1"] == pytest.approx(1)
    assert report["inter_model_agreement_not_accuracy"]["root"] == pytest.approx(1)
    assert report["commercial_model_approved"] is False
    assert report["copyright_and_alignment_verification"].startswith("operator-provided")


def test_model_agreement_does_not_substitute_independent_accuracy(tmp_path: Path):
    reference, manual, sheetsage = _inputs(tmp_path)
    # Both systems agree on a wrong D major chord: agreement=1; accuracy<1.
    reference["annotators"] = [{
        "index": 0, "intervals": [{"start": 0, "end": 4, "label": "C:maj"}],
    }]
    for events in (manual, sheetsage):
        events["chords"] = [{"time_seconds": 0.0, "label": "D:maj"}]
    report = compare_chord_playalong.compare_chord_predictions(reference, manual, sheetsage)
    assert report["inter_model_agreement_not_accuracy"]["root"] == pytest.approx(1)
    assert report["by_model"]["manual"]["chords"]["mean_by_metric"]["root"] == pytest.approx(0)
    assert report["by_model"]["sheetsage2"]["chords"]["mean_by_metric"]["root"] == pytest.approx(0)


def test_no_chord_recall_is_measured_separately(tmp_path: Path):
    reference, manual, sheetsage = _inputs(tmp_path)
    reference["annotators"] = [
        {"index": 0, "intervals": [
            {"start": 0, "end": 2, "label": "C:maj"},
            {"start": 2, "end": 4, "label": "N"},
        ]},
    ]
    manual["chords"] = [
        {"time_seconds": 0.0, "label": "C:maj"},
        {"time_seconds": 2.0, "label": "N"},
    ]
    report = compare_chord_playalong.compare_chord_predictions(reference, manual, sheetsage)
    assert report["by_model"]["manual"]["no_chord_recall_mean"] == pytest.approx(1)
    assert report["by_model"]["sheetsage2"]["no_chord_recall_mean"] == pytest.approx(0)


def test_mismatched_audio_fingerprint_refuses_comparison(tmp_path: Path):
    reference, manual, sheetsage = _inputs(tmp_path)
    sheetsage["recording_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="matching recording SHA-256"):
        compare_chord_playalong.compare_chord_predictions(reference, manual, sheetsage)


def test_invalid_reference_timing_is_rejected(tmp_path: Path):
    reference, manual, sheetsage = _inputs(tmp_path)
    reference["annotators"][0]["intervals"][1]["start"] = -1.0
    with pytest.raises(ValueError, match="nonoverlapping"):
        compare_chord_playalong.compare_chord_predictions(reference, manual, sheetsage)


def test_cli_exports_json_and_csv_without_media(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reference, manual, sheetsage = _inputs(tmp_path)
    paths = [tmp_path / name for name in ("reference.json", "manual.json", "sheetsage.json")]
    for path, value in zip(paths, (reference, manual, sheetsage), strict=True):
        path.write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "result.json"
    csv_out = tmp_path / "result.csv"
    monkeypatch.setattr(sys, "argv", [
        "compare_chord_playalong.py", *(str(path) for path in paths),
        str(output), "--output-csv", str(csv_out),
    ])
    assert compare_chord_playalong.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["reference_annotation_sha256"] == report["input_sha256"]["reference"]
    assert "manual" in csv_out.read_text(encoding="utf-8")
    assert "sheetsage2" in csv_out.read_text(encoding="utf-8")
