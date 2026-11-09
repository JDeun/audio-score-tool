from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import mido
import pytest
from music21 import chord, meter, note, stream

from audio_score_tool import choir_postprocess
from audio_score_tool.choir_postprocess import reconstruct_satb
from audio_score_tool.metrics import midi_notes
from audio_score_tool.notation_backend import midi_to_musicxml, musicxml_to_midi


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

    result = reconstruct_satb(source, output, mode="choir")

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

    result = reconstruct_satb(source, output, mode="choir")

    assert result.applied is True
    assert result.confidence >= 0.72
    from music21 import converter

    parsed = converter.parse(str(output))
    assert len(parsed.parts) == 4
    assert all(len(list(part.recurse().notes)) > 0 for part in parsed.parts)


def _write_midi_score(
    xml: Path, tracks: list[tuple[int, list[tuple[int, int, tuple[int, ...]]]]],
    *, tempo_change: bool = False,
) -> Path:
    """Original MIDI fixtures, including timelines the notation writer cannot express."""
    midi = mido.MidiFile(ticks_per_beat=480)
    conductor = mido.MidiTrack()
    midi.tracks.append(conductor)
    conductor.append(mido.MetaMessage("set_tempo", tempo=666_667))
    if tempo_change:
        conductor.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=6 * 480))
    for channel, (program, events) in enumerate(tracks):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.Message("program_change", channel=channel, program=program))
        messages = []
        for start, end, pitches in events:
            for pitch in pitches:
                messages.extend(((start, 1, pitch), (end, 0, pitch)))
        previous = 0
        for tick, on, pitch in sorted(messages):
            track.append(mido.Message(
                "note_on" if on else "note_off", channel=channel, note=pitch,
                velocity=80 if on else 0, time=tick - previous,
            ))
            previous = tick
    source = xml.with_suffix(".mid")
    midi.save(source)
    midi_to_musicxml(source, xml)
    return source


def _assert_same_notes(source: Path, result: Path) -> None:
    def order(event):
        return event.pitch, event.program, event.is_drum, event.onset, event.offset

    expected = sorted(midi_notes(source), key=order)
    actual = sorted(midi_notes(result), key=order)
    assert len(actual) == len(expected)
    for before, after in zip(expected, actual, strict=True):
        assert (before.pitch, before.program, before.is_drum) == (
            after.pitch, after.program, after.is_drum,
        )
        assert after.onset == pytest.approx(before.onset, abs=1e-4)
        assert after.offset == pytest.approx(before.offset, abs=1e-4)


@pytest.mark.parametrize("writer", [_write_four_part_score, _write_chordal_score])
def test_auto_does_not_infer_a_choir_from_part_count_or_chords(tmp_path, writer):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    writer(source)
    original = source.read_bytes()

    result = reconstruct_satb(source, output, mode="auto")

    assert not result.applied
    assert result.reason == "automatic-satb-not-established"
    assert not output.exists()
    assert source.read_bytes() == original


def test_auto_keeps_existing_satb_labels_without_pitch_based_reassignment(tmp_path):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    _write_four_part_score(source)
    tree = ET.parse(source)
    # Existing labels can intentionally cross in pitch; auto must respect them.
    names = ["Bass", "Tenor", "Alto", "Soprano"]
    for definition, name in zip(tree.findall("part-list/score-part"), names, strict=True):
        definition.find("part-name").text = name
    tree.write(source)
    original = source.read_bytes()

    result = reconstruct_satb(source, output, mode="auto")

    assert not result.applied
    assert result.reason == "already-labelled-satb"
    assert source.read_bytes() == original


@pytest.mark.parametrize("overlap", [False, True])
def test_explicit_choir_keeps_all_sixty_notes_when_four_voices_cannot_represent_them(
    tmp_path, overlap,
):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    step = 240 if overlap else 480
    events = [
        (index * step, index * step + 480,
         tuple(pitch + index % 2 for pitch in (48, 55, 60, 64, 67)))
        for index in range(12)
    ]
    raw = _write_midi_score(source, [(0, events)])
    original = source.read_bytes()

    result = reconstruct_satb(source, output, mode="choir")

    assert not result.applied
    assert "require-manual-arrangement" in result.reason
    assert not output.exists()
    assert source.read_bytes() == original
    playback = musicxml_to_midi(source, tmp_path / "preserved.mid")
    assert len(midi_notes(playback)) == 60
    _assert_same_notes(raw, playback)


@pytest.mark.parametrize("same_median", [False, True])
def test_explicit_four_part_labels_preserve_arbitrary_ticks_and_equal_pitch_parts(
    tmp_path, same_median,
):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    pitches = (60, 60, 60, 60) if same_median else (76, 67, 55, 40)
    raw = _write_midi_score(source, [
        (program, [(53, 2443, (pitch,))])
        for program, pitch in zip((73, 56, 40, 32), pitches, strict=True)
    ])
    original = source.read_bytes()

    result = reconstruct_satb(source, output, mode="choir")

    assert result.applied, result.reason
    assert source.read_bytes() == original
    before, after = ET.parse(source), ET.parse(output)
    assert [ET.tostring(part) for part in after.findall("part")] == [
        ET.tostring(part) for part in before.findall("part")
    ]
    assert [part.findtext("part-name") for part in after.findall("part-list/score-part")] == [
        "Soprano", "Alto", "Tenor", "Bass",
    ]
    for definition in after.findall("part-list/score-part"):
        tags = [node.tag for node in definition]
        assert tags.index("part-abbreviation") < tags.index("midi-instrument")
    _assert_same_notes(raw, musicxml_to_midi(output, tmp_path / "playback.mid"))


def test_explicit_chord_assignment_preserves_gm_variant_and_changing_tempo(tmp_path):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    raw = _write_midi_score(source, [(1, [
        (index * 480, (index + 1) * 480, (48, 55, 64, 72))
        for index in range(12)
    ])], tempo_change=True)

    result = reconstruct_satb(source, output, mode="choir")

    assert result.applied, result.reason
    assert len(ET.parse(output).findall("part")) == 4
    playback = musicxml_to_midi(output, tmp_path / "playback.mid")
    _assert_same_notes(raw, playback)
    assert {event.program for event in midi_notes(playback)} == {1}
    assert {event.tempo for event in mido.MidiFile(playback) if event.type == "set_tempo"} == {
        666_667, 1_000_000,
    }
    assert {event.velocity for event in mido.MidiFile(playback)
            if event.type == "note_on" and event.velocity > 0} == {80}


@pytest.mark.parametrize("damage", ["empty", "pitch", "gm", "tempo", "duration"])
def test_candidate_guard_rejects_performance_changes_before_publishing(tmp_path, monkeypatch, damage):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    _write_midi_score(source, [(0, [
        (index * 480, (index + 1) * 480, (48, 55, 64, 72))
        for index in range(12)
    ])])
    original = source.read_bytes()

    def unsafe_candidate(_score, _part, candidate):
        tree = ET.parse(source)
        if damage == "empty":
            for measure in tree.findall("part/measure"):
                for element in list(measure.findall("note")):
                    measure.remove(element)
        elif damage == "pitch":
            tree.find("part/measure/note/pitch/octave").text = "7"
        elif damage == "gm":
            tree.find("part-list/score-part/midi-instrument/midi-program").text = "54"
        elif damage == "tempo":
            for sound in tree.findall(".//sound"):
                sound.set("tempo", "120")
            for rate in tree.findall(".//per-minute"):
                rate.text = "120"
        elif damage == "duration":
            tree.find("part/measure/note/duration").text = "240"
        tree.write(candidate)
        return choir_postprocess.ChoirResult(True, candidate, 1.0, "test-candidate", 1)

    monkeypatch.setattr(choir_postprocess, "_split_chordal_part", unsafe_candidate)
    result = reconstruct_satb(source, output, mode="choir")

    assert not result.applied
    assert result.reason == "performance-preservation-check-failed"
    assert not output.exists()
    assert source.read_bytes() == original


def test_optional_arrangement_exception_preserves_source_and_leaves_no_candidate(tmp_path, monkeypatch):
    source, output = tmp_path / "source.musicxml", tmp_path / "satb.musicxml"
    _write_chordal_score(source)
    original = source.read_bytes()

    def broken_writer(*_args):
        raise RuntimeError("unsupported notation")

    monkeypatch.setattr(choir_postprocess, "_split_chordal_part", broken_writer)
    result = reconstruct_satb(source, output, mode="choir")

    assert not result.applied
    assert "RuntimeError:unsupported notation" in result.reason
    assert source.read_bytes() == original
    assert not output.exists()
    assert not list(tmp_path.glob(".choir-*"))
