from __future__ import annotations

from pathlib import Path

import pytest
from music21 import harmony, meter, note, stream, tempo

from audio_score_tool.tier2_structure_metrics import evaluate_musicxml_structure


def _write_satb_score(path: Path) -> None:
    score = stream.Score()
    for index, name in enumerate(("Soprano", "Alto", "Tenor", "Bass")):
        part = stream.Part()
        part.partName = name
        measure = stream.Measure(number=0)
        measure.append(meter.TimeSignature("4/4"))
        item = note.Note(60 - index * 5, quarterLength=1.0)
        if index == 0:
            item.lyric = "Amen"
            measure.insert(0, harmony.ChordSymbol("C"))
        measure.append(item)
        part.append(measure)
        score.append(part)
    score.write("musicxml", fp=str(path))


def _write_full_measure_score(path: Path) -> None:
    score = stream.Score()
    part = stream.Part()
    measure = stream.Measure(number=1)
    measure.append(meter.TimeSignature("4/4"))
    for pitch in (60, 62, 64, 65):
        measure.append(note.Note(pitch, quarterLength=1.0))
    part.append(measure)
    score.append(part)
    score.write("musicxml", fp=str(path))


def test_musicxml_structure_metrics_cover_release_dimensions(tmp_path: Path):
    prediction = tmp_path / "prediction.musicxml"
    reference = tmp_path / "reference.musicxml"
    _write_satb_score(prediction)
    _write_satb_score(reference)

    metrics = evaluate_musicxml_structure(
        prediction,
        reference_path=reference,
        expected_structure={
            "meter": "4/4",
            "pickup_quarter_length": 3.0,
            "part_count": 4,
            "has_lyrics": True,
            "has_chords": True,
        },
        tags=("satb",),
        category="choir",
    )

    assert metrics["meter_correct"] is True
    assert metrics["pickup_mae_quarter_length"] == 0.0
    assert metrics["part_count_correct"] is True
    assert metrics["lyrics_alignment_coverage"] == 1.0
    assert metrics["chord_accuracy"] == 1.0
    assert metrics["satb_part_count_correct"] is True
    assert metrics["satb_voice_order_correct"] is True


def test_musicxml_structure_metrics_do_not_invent_pickup_for_full_measure(tmp_path: Path):
    prediction = tmp_path / "full.musicxml"
    _write_full_measure_score(prediction)

    metrics = evaluate_musicxml_structure(
        prediction,
        reference_path=None,
        expected_structure={"meter": "4/4", "pickup_quarter_length": 0.0, "part_count": 1},
        tags=(),
        category="piano",
    )

    assert metrics["meter_correct"] is True
    assert metrics["pickup_mae_quarter_length"] == 0.0
    assert metrics["part_count_correct"] is True


def test_chord_and_lyric_presence_without_reference_is_not_quality_evidence(tmp_path):
    prediction = tmp_path / "prediction.musicxml"
    _write_satb_score(prediction)
    metrics = evaluate_musicxml_structure(
        prediction, reference_path=None,
        expected_structure={"has_chords": True, "has_lyrics": True},
        tags=(), category="vocal_lead_sheet",
    )
    assert metrics["has_chord_symbols"] is True
    assert metrics["has_lyrics"] is True
    assert "chord_accuracy" not in metrics
    assert "lyrics_alignment_coverage" not in metrics


def _write_timed_annotations(path, *, chord_change=2, lyric="hello", lyric_at=0, bpm=60,
                             duration=4, inversion="G", repeat_chord=False):
    score = stream.Score()
    part = stream.Part()
    part.insert(0, meter.TimeSignature("4/4"))
    part.insert(0, tempo.MetronomeMark(number=bpm))
    if lyric_at:
        part.insert(0, note.Rest(quarterLength=lyric_at))
    part.insert(0, harmony.ChordSymbol("C"))
    part.insert(chord_change, harmony.ChordSymbol(inversion))
    if repeat_chord:
        part.insert(1, harmony.ChordSymbol("C"))
    sung = note.Note(60, quarterLength=duration - lyric_at)
    sung.lyric = lyric
    part.insert(lyric_at, sung)
    score.insert(0, part)
    score.write("musicxml", fp=str(path))


@pytest.mark.parametrize("changes,chord_score,lyric_score", [
    ({"chord_change": 3}, 0.75, 1.0),
    ({"lyric": "wrong"}, 1.0, 0.0),
    ({"lyric_at": 1}, 1.0, 0.0),
    ({"bpm": 120}, 0.25, 1.0),
    ({"inversion": "G/B"}, 0.5, 1.0),
    ({"repeat_chord": True}, 1.0, 1.0),
])
def test_annotation_accuracy_uses_elapsed_time_text_and_inversion(
    tmp_path, changes, chord_score, lyric_score,
):
    prediction = tmp_path / "prediction.musicxml"
    reference = tmp_path / "reference.musicxml"
    _write_timed_annotations(reference)
    _write_timed_annotations(prediction, **changes)
    metrics = evaluate_musicxml_structure(
        prediction, reference_path=reference,
        expected_structure={"has_chords": True, "has_lyrics": True},
        tags=(), category="vocal_lead_sheet",
    )
    assert metrics["chord_accuracy"] == chord_score
    assert metrics["lyrics_alignment_coverage"] == lyric_score


def test_annotation_accuracy_integrates_tempo_changes_and_matches_lyric_once(tmp_path):
    from audio_score_tool.tier2_structure_metrics import (
        _annotation_timeline,
        _timed_lyric_coverage,
    )

    score = stream.Score()
    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=60))
    part.insert(2, tempo.MetronomeMark(number=120))
    part.insert(0, note.Note(60, quarterLength=4))
    part.insert(3, harmony.ChordSymbol("C"))
    score.insert(0, part)
    chords, _, end = _annotation_timeline(score)
    assert chords[0][0] == 2.5
    assert end == 3.0
    assert _timed_lyric_coverage(
        [(0.025, "1", "la")], [(0.0, "1", "la"), (0.05, "1", "la")],
    ) == 0.5
    assert _timed_lyric_coverage(
        [(0.965, "1", "la"), (1.015, "1", "la")],
        [(1.0, "1", "la"), (1.06, "1", "la")],
    ) == 1.0
