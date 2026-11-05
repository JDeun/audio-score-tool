"""Lawful synthetic JAMS and LAB chord annotations, no recording or scraping."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.import_chord_reference import import_chord_reference

FINGERPRINT = "a" * 64


def _jams(path: Path) -> Path:
    payload = {"annotations": [
        {"namespace": "chord", "data": [
            {"time": 0.0, "duration": 2.0, "value": "C:maj"},
            {"time": 2.0, "duration": 2.0, "value": "A:min"},
        ]},
        {"namespace": "chord", "data": [
            {"time": 0.0, "duration": 4.0, "value": "C:maj"},
        ]},
        {"namespace": "beat", "data": []},
    ]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _lab(path: Path) -> Path:
    path.write_text("0.0 2.0 C:maj\n2.0 4.0 N\n", encoding="utf-8")
    return path


def _import(source: Path, *, fmt: str = "jams", **kwargs) -> dict:
    return import_chord_reference(
        [source], format=fmt, dataset=kwargs.pop("dataset", "casd"),
        license=kwargs.pop("license", "CC-BY-NC-SA-4.0"),
        rights_reviewed=kwargs.pop("rights_reviewed", True),
        recording_sha256=FINGERPRINT, duration_seconds=4.0, **kwargs,
    )


def test_jams_retains_multiple_independent_annotators(tmp_path: Path):
    result = _import(_jams(tmp_path / "owned-test.jams"))
    assert result["dataset"] == "casd"
    assert len(result["annotators"]) == 2
    assert result["annotators"][0]["intervals"][1]["label"] == "A:min"
    assert result["annotators"][1]["intervals"][0]["end"] == 4.0
    assert result["recording_sha256"] == FINGERPRINT
    assert result["source_audio_included"] is False
    assert result["harte_label_semantics_independently_validated"] is False
    assert result["audio_recording_identity_independently_verified"] is False
    assert len(result["source_annotations"][0]["sha256"]) == 64


def test_lab_with_explicit_no_chord_and_two_experts(tmp_path: Path):
    a, b = _lab(tmp_path / "a.lab"), _lab(tmp_path / "b.lab")
    result = import_chord_reference(
        [a, b], format="lab", dataset="isophonics", license="CC-BY-4.0",
        rights_reviewed=True, recording_sha256=FINGERPRINT, duration_seconds=4.0,
    )
    assert len(result["annotators"]) == 2
    assert result["annotators"][0]["intervals"][1]["label"] == "N"
    assert result["source_annotations"][0]["name"] == "a.lab"


def test_optional_reference_beat_grid(tmp_path: Path):
    source = _jams(tmp_path / "chords.jams")
    beats = tmp_path / "beats.csv"
    with beats.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["time_seconds", "kind"])
        writer.writerows([
            [0, "downbeat"], [0.5, "beat"], [1.0, "beat"], [2.0, "downbeat"],
        ])
    result = _import(source, beats_csv=beats)
    assert len(result["beats"]) == 4
    assert result["downbeats"] == [{"time_seconds": 0.0}, {"time_seconds": 2.0}]
    assert len(result["beats_sha256"]) == 64


def test_gap_is_not_silently_invented_as_no_chord(tmp_path: Path):
    lab = tmp_path / "invalid.lab"
    lab.write_text("0.0 1.0 C:maj\n2.0 4.0 G:maj\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gap or overlap"):
        _import(lab, fmt="lab", dataset="manual", license="CC-BY-4.0")


def test_overlap_and_wrong_duration_rejected(tmp_path: Path):
    lab = tmp_path / "overlap.lab"
    lab.write_text("0.0 2.1 C:maj\n2.0 4.0 A:min\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gap or overlap"):
        _import(lab, fmt="lab", dataset="manual", license="CC-BY-4.0")
    lab.write_text("0.0 3.0 C:maj\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cover the full"):
        _import(lab, fmt="lab", dataset="manual", license="CC-BY-4.0")


def test_source_rights_must_be_operator_reviewed(tmp_path: Path):
    with pytest.raises(ValueError, match="operator must review"):
        _import(_jams(tmp_path / "source.jams"), rights_reviewed=False)


def test_casd_annotation_license_cannot_be_overridden(tmp_path: Path):
    with pytest.raises(ValueError, match="CASD annotation rights"):
        _import(_jams(tmp_path / "source.jams"), license="MIT")


def test_nc_casd_cannot_enter_commercial_reference_pipeline(tmp_path: Path):
    with pytest.raises(ValueError, match="non-permissive"):
        _import(_jams(tmp_path / "source.jams"), commercial=True)


def test_invalid_jams_without_chord_namespace_refused(tmp_path: Path):
    source = tmp_path / "invalid.jams"
    source.write_text(json.dumps({"annotations": [{"namespace": "beat", "data": []}]}),
                      encoding="utf-8")
    with pytest.raises(ValueError, match="no chord namespace"):
        _import(source)


def test_import_reference_compatible_with_existing_chord_scorer(tmp_path: Path):
    pytest.importorskip("mir_eval")
    from scripts.score_casd_chords import score

    reference = _import(_jams(tmp_path / "source.jams"))
    prediction = {"chords": [
        {"time_seconds": 0, "label": "C:maj"},
        {"time_seconds": 2, "label": "A:min"},
    ]}
    evaluated = score(reference, prediction)
    assert len(evaluated["annotators"]) == 2
    assert evaluated["annotators"][0]["metrics"]["majmin"] == pytest.approx(1)
    assert evaluated["annotators"][1]["metrics"]["majmin"] < 1


def test_unreviewed_or_missing_input_file_not_consumed(tmp_path: Path):
    with pytest.raises(ValueError, match="existing regular local file"):
        _import(tmp_path / "absent.jams")
