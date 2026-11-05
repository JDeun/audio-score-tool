"""Synthetic, lawful CSV fixtures for offline chord-grid normalization."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.import_manual_chord_chart import import_manual_chord_chart, normalize_chord


def _csv(path: Path, header: tuple[str, ...], rows: list[tuple[str, ...]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


@pytest.mark.parametrize(("input", "expected"), [
    ("C", "C:maj"),
    ("Am", "A:min"),
    ("Bb", "Bb:maj"),
    ("F#:min", "F#:min"),
    ("G7", "G:7"),
    ("Cmaj7", "C:maj7"),
    ("Cm7b5", "C:hdim7"),
    ("N.C.", "N"),
    ("no_chord", "N"),
])
def test_normalize_supported_chords(input: str, expected: str):
    assert normalize_chord(input) == expected


@pytest.mark.parametrize("label", ["A/C#", "Csus9", "unknown", "", "C:dim7", "C#:/m"])
def test_reject_ambiguous_or_unsupported_quality(label: str):
    with pytest.raises(ValueError, match="unsupported"):
        normalize_chord(label)


def test_import_timed_chords_with_beat_grid_and_manual_provenance(tmp_path: Path):
    chords = _csv(
        tmp_path / "chords.csv", ("time_seconds", "chord"),
        [("0", "C"), ("2.0", "Am"), ("3.5", "N.C.")],
    )
    beats = _csv(
        tmp_path / "beats.csv", ("time_seconds", "kind"),
        [("0", "downbeat"), ("0.5", "beat"), ("1.0", "beat"), ("2", "downbeat")],
    )
    result = import_manual_chord_chart(
        chords, duration_seconds=4.0, recording_sha256="A" * 64, beats_csv=beats,
    )
    assert result["recording_sha256"] == "a" * 64
    assert result["chords"] == [
        {"time_seconds": 0.0, "label": "C:maj"},
        {"time_seconds": 2.0, "label": "A:min"},
        {"time_seconds": 3.5, "label": "N"},
    ]
    assert result["downbeats"] == [{"time_seconds": 0.0}, {"time_seconds": 2.0}]
    assert len(result["beats"]) == 4
    assert result["source"]["recording_identity_verified"] is False
    assert result["source"]["third_party_rights_verified"] is False
    assert len(result["source"]["chords_csv_sha256"]) == 64


@pytest.mark.parametrize("rows", [
    [("-1", "C")],
    [("0", "C"), ("0", "G")],
    [("2", "Am"), ("1", "C")],
    [("nan", "C")],
    [("4", "C")],
])
def test_reject_bad_timestamps(tmp_path: Path, rows: list[tuple[str, str]]):
    chords = _csv(tmp_path / "chords.csv", ("time_seconds", "chord"), rows)
    with pytest.raises(ValueError, match="time"):
        import_manual_chord_chart(
            chords, duration_seconds=4.0, recording_sha256="a" * 64,
        )


def test_no_unreviewed_external_csv_or_bad_hashes(tmp_path: Path):
    input_file = _csv(
        tmp_path / "chords.csv", ("time_seconds", "chord"), [("0", "C")],
    )
    with pytest.raises(ValueError, match="64-hex"):
        import_manual_chord_chart(
            input_file, duration_seconds=4.0, recording_sha256="not-sha",
        )
    with pytest.raises(ValueError, match="finite"):
        import_manual_chord_chart(
            input_file, duration_seconds=float("inf"), recording_sha256="a" * 64,
        )
    invalid = _csv(tmp_path / "invalid.csv", ("beat", "chord"), [("0", "C")])
    with pytest.raises(ValueError, match="columns"):
        import_manual_chord_chart(
            invalid, duration_seconds=4.0, recording_sha256="a" * 64,
        )
