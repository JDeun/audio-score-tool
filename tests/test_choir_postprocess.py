from __future__ import annotations

from pathlib import Path

from music21 import chord, meter, note, stream

from audio_score_tool.choir_postprocess import reconstruct_satb


def _write_four_part_score(path: Path) -> None:
    score = stream.Score()
    for name, midi in (("P1", 72), ("P2", 64), ("P3", 55), ("P4", 43)):
        part = stream.Part(id=name)
        measure = stream.Measure(number=1)
        measure.append(meter.TimeSignature("4/4"))
        for _ in range(4):
            n = note.Note(midi)
            n.quarterLength = 1
            measure.append(n)
        part.append(measure)
        score.append(part)
    score.write("musicxml", fp=str(path))


def _write_chordal_score(path: Path) -> None:
    score = stream.Score()
    part = stream.Part(id="mix")
    for measure_number in range(1, 5):
        measure = stream.Measure(number=measure_number)
        if measure_number == 1:
            measure.append(meter.TimeSignature("4/4"))
        for pitches in ((60, 64, 67, 72), (62, 65, 69, 74), (59, 63, 67, 71), (60, 65, 69, 72)):
            c = chord.Chord(pitches)
            c.quarterLength = 1
            measure.append(c)
        part.append(measure)
    score.append(part)
    score.write("musicxml", fp=str(path))


def test_four_parts_are_named_satb(tmp_path: Path) -> None:
    source = tmp_path / "source.musicxml"
    output = tmp_path / "satb.musicxml"
    _write_four_part_score(source)

    result = reconstruct_satb(source, output, mode="auto")

    assert result.applied is True
    assert output.is_file()
    parsed = stream.Score()
    from music21 import converter

    parsed = converter.parse(str(output))
    assert [part.partName for part in parsed.parts] == ["Soprano", "Alto", "Tenor", "Bass"]


def test_chordal_single_part_is_split_into_satb(tmp_path: Path) -> None:
    source = tmp_path / "source.musicxml"
    output = tmp_path / "satb.musicxml"
    _write_chordal_score(source)

    result = reconstruct_satb(source, output, mode="auto")

    assert result.applied is True
    assert result.confidence >= 0.72
    from music21 import converter

    parsed = converter.parse(str(output))
    assert len(parsed.parts) == 4
    assert all(len(list(part.recurse().notes)) > 0 for part in parsed.parts)
