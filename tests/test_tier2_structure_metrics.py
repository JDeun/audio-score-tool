from __future__ import annotations

from pathlib import Path

from music21 import harmony, meter, note, stream

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
