"""Product converter regressions, using owned synthetic note events only."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import mido
import pytest

from audio_score_tool.metrics import midi_notes
from audio_score_tool.mt3_program_midi import midi_from_program_notes
from audio_score_tool.notation_backend import (
    NotationBackendError,
    midi_to_musicxml,
    musicxml_to_midi,
    render_pdf,
)


def _note(pitch, start, end, program=40, drum=False):
    return SimpleNamespace(
        pitch=pitch, program=program, start_time=start, end_time=end,
        velocity=90, is_drum=drum,
    )


def _roundtrip(tmp_path: Path, notes, *, ppq=480):
    source = tmp_path / "performed.mid"
    score = tmp_path / "score.musicxml"
    output = tmp_path / "published.mid"
    midi_from_program_notes(notes, ticks_per_quarter=ppq).save(source)
    midi_to_musicxml(source, score)
    musicxml_to_midi(score, output)
    _assert_performance(source, output)
    return source, score, output


def _assert_performance(source: Path, output: Path):
    original = sorted(midi_notes(source), key=lambda n: (n.onset, n.pitch, n.instrument_key))
    final = sorted(midi_notes(output), key=lambda n: (n.onset, n.pitch, n.instrument_key))
    assert len(final) == len(original)
    for expected, actual in zip(original, final):
        assert (actual.pitch, actual.instrument_key) == (expected.pitch, expected.instrument_key)
        # music21's MIDI writer uses 10080 ticks/quarter; allow its final single
        # tick rounding, not the old 16th-note/chord-grouping quantization.
        assert actual.onset == pytest.approx(expected.onset, abs=0.0001)
        assert actual.offset == pytest.approx(expected.offset, abs=0.0001)


def test_cross_bar_polyphonic_ties_do_not_split_or_move_performed_notes(tmp_path):
    _, score, _ = _roundtrip(tmp_path, [
        _note(60, 0.0, 5.0), _note(64, 0.0, 3.0), _note(67, 1.0, 7.0),
    ])
    root = ET.parse(score).getroot()
    assert len(root.findall("part")) == 1
    assert len(root.findall("part/measure")) == 4
    assert root.findall("part/measure/note/tie")
    assert {n.text for n in root.findall("part/measure/note/voice")} == {"1", "2", "3"}


def test_nearby_attacks_and_unequal_offsets_do_not_become_a_single_chord(tmp_path):
    _, score, _ = _roundtrip(tmp_path, [
        _note(60, 0.0, 0.5), _note(64, 0.02, 0.54),
        _note(67, 0.045, 0.57), _note(72, 0.08, 0.59),
    ])
    assert not ET.parse(score).getroot().findall(".//chord")


def test_equal_intervals_form_real_chords_without_adding_attacks(tmp_path):
    _, score, _ = _roundtrip(tmp_path, [
        _note(60, 0.0, 4.5), _note(64, 0.0, 4.5), _note(67, 0.0, 4.5),
    ])
    root = ET.parse(score).getroot()
    assert root.findall(".//chord")
    assert {n.text for n in root.findall(".//voice")} == {"1"}


def test_overlapping_repeated_pitch_keeps_both_onsets_and_fifo_offsets(tmp_path):
    _roundtrip(tmp_path, [_note(60, 0.0, 1.0), _note(60, 0.5, 1.5)])


def test_sequential_channel_reuse_preserves_the_serializers_two_instrument_parts(tmp_path):
    source, score, _ = _roundtrip(tmp_path, [
        _note(60, 0.0, 0.25, program=40),
        _note(64, 0.5, 1.5, program=41),
        _note(67, 0.75, 1.0, program=40),
    ])
    note_channels = [
        {message.channel for message in track
         if message.type == "note_on" and message.velocity > 0}
        for track in mido.MidiFile(source).tracks
    ]
    assert {0, 1} in note_channels  # GM40 returns on a different idle channel.
    assert sum(bool(channels) for channels in note_channels) == 2
    assert len(ET.parse(score).getroot().findall("part")) == 2


@pytest.mark.parametrize("separate_tracks", [False, True], ids=[
    "concurrent_channels_in_type0", "sequential_channels_in_separate_tracks",
])
def test_independent_same_program_parts_remain_separate(tmp_path, separate_tracks):
    midi = mido.MidiFile(type=1 if separate_tracks else 0, ticks_per_beat=480)
    first = mido.MidiTrack([
        mido.Message("program_change", channel=0, program=40, time=0),
        mido.Message("note_on", channel=0, note=60, velocity=90, time=0),
        mido.Message("note_off", channel=0, note=60, time=480),
    ])
    second = mido.MidiTrack([
        mido.Message("program_change", channel=1, program=40, time=0),
        mido.Message("note_on", channel=1, note=67, velocity=90,
                     time=480 if separate_tracks else 240),
        mido.Message("note_off", channel=1, note=67, time=480),
    ])
    midi.tracks = [first, second] if separate_tracks else [mido.merge_tracks([first, second])]
    source = tmp_path / "independent.mid"
    score = tmp_path / "independent.musicxml"
    output = tmp_path / "independent-export.mid"
    midi.save(source)
    midi_to_musicxml(source, score)
    musicxml_to_midi(score, output)
    _assert_performance(source, output)
    assert len(ET.parse(score).getroot().findall("part")) == 2


def test_arbitrary_ticks_and_one_tick_notes_are_not_rounded_to_notated_values(tmp_path):
    source, score, _ = _roundtrip(tmp_path, [
        _note(60, 57 / 440, 58 / 440),
        _note(64, 59 / 440, 238 / 440),
        _note(67, 239 / 440, 1601 / 440),
    ], ppq=220)
    assert len(midi_notes(source)) == 3
    assert ET.parse(score).getroot().findtext("part/measure/attributes/divisions") == "220"


def test_note_below_export_resolution_fails_before_creating_a_sustained_midi(tmp_path):
    source = tmp_path / "tiny.mid"
    score = tmp_path / "tiny.musicxml"
    output = tmp_path / "tiny-export.mid"
    midi_from_program_notes([
        _note(60, 0, 1 / 65534),
    ], ticks_per_quarter=32767).save(source)
    midi_to_musicxml(source, score)
    assert score.is_file()
    with pytest.raises(NotationBackendError, match="shorter than the MIDI export resolution"):
        musicxml_to_midi(score, output)
    assert not output.exists()


def test_percussion_instrument_ids_preserve_each_drum_in_one_part(tmp_path):
    _, score, _ = _roundtrip(tmp_path, [
        _note(36, 0.0, 0.5, 0, True), _note(42, 0.0, 0.5, 0, True),
        _note(38, 0.5, 0.75, 0, True), _note(60, 0.0, 1.0),
    ])
    root = ET.parse(score).getroot()
    assert len(root.findall("part")) == 2
    assert {node.text for node in root.findall("part-list/score-part/midi-instrument/midi-unpitched")} == {
        "37", "39", "43",
    }


@pytest.mark.parametrize("program", [0, 1, 40, 127])
def test_percussion_never_captures_pitched_notes_with_the_same_program(tmp_path, program):
    _roundtrip(tmp_path, [
        _note(60, 0, 1, program), _note(64, 0.5, 1.5, program),
        _note(36, 0, 0.25, program, True), _note(42, 1, 1.25, program, True),
    ])


def test_unassigned_pitched_instrument_is_not_allocated_to_a_drum_channel(tmp_path):
    source = tmp_path / "no-program.musicxml"
    source.write_text('''<score-partwise version="4.0"><part-list>
      <score-part id="P1"><part-name>Unknown</part-name></score-part>
      <score-part id="P2"><part-name>Drums</part-name>
        <score-instrument id="I2"><instrument-name>Drums</instrument-name></score-instrument>
        <midi-instrument id="I2"><midi-channel>10</midi-channel><midi-program>1</midi-program>
          <midi-unpitched>37</midi-unpitched></midi-instrument></score-part></part-list>
      <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      </measure></part><part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
        <note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>
          <duration>1</duration><instrument id="I2"/><type>quarter</type></note>
      </measure></part></score-partwise>''')
    result = musicxml_to_midi(source, tmp_path / "no-program.mid")
    assert {(n.pitch, n.is_drum) for n in midi_notes(result)} == {(60, False), (36, True)}


@pytest.mark.parametrize("first", range(0, 128, 16))
def test_gm_program_variants_and_recycled_channels_survive_xml_playback(tmp_path, first):
    _roundtrip(tmp_path, [
        _note(60 + i % 12, i * 0.5, i * 0.5 + 0.25, first + i)
        for i in range(16)
    ])


def test_concurrent_fifteen_programs_do_not_share_the_fallback_channel(tmp_path):
    _roundtrip(tmp_path, [_note(48 + i, 0.0, 1.0, i) for i in range(15)])


def test_tempo_changes_pickup_silence_meter_changes_and_minor_key_survive(tmp_path):
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    conductor = mido.MidiTrack([
        mido.MetaMessage("set_tempo", tempo=666_667, time=0),
        mido.MetaMessage("time_signature", numerator=3, denominator=4, time=0),
        mido.MetaMessage("key_signature", key="Am", time=0),
        mido.MetaMessage("set_tempo", tempo=400_000, time=720),
        mido.MetaMessage("time_signature", numerator=5, denominator=8, time=720),
        mido.MetaMessage("set_tempo", tempo=750_000, time=240),
    ])
    performed = mido.MidiTrack([
        mido.Message("program_change", program=1, channel=0, time=0),
        mido.MetaMessage("lyrics", text="hello", time=240),
        mido.Message("note_on", note=60, velocity=90, time=0),
        mido.Message("note_on", note=64, velocity=90, time=240),
        mido.Message("note_off", note=64, time=720),
        mido.Message("note_off", note=60, time=480),
        mido.Message("note_on", note=67, velocity=90, time=0),
        mido.Message("note_off", note=67, time=480),
    ])
    midi.tracks = [conductor, performed]
    source = tmp_path / "source.mid"
    score = tmp_path / "score.musicxml"
    output = tmp_path / "out.mid"
    midi.save(source)
    midi_to_musicxml(source, score)
    musicxml_to_midi(score, output)
    _assert_performance(source, output)
    xml = ET.parse(score).getroot()
    assert xml.findtext(".//key/mode") == "minor"
    assert [lyric.text for lyric in xml.findall(".//lyric/text")] == ["hello"]
    assert [t.findtext("beats") for t in xml.findall(".//attributes/time")] == ["3", "5"]
    assert [m.tempo for m in mido.MidiFile(output) if m.type == "set_tempo"] == [666_667, 400_000, 750_000]
    assert all(node.get("sound") == "yes" for node in xml.findall(".//direction/offset"))


def test_real_generated_score_with_tempo_and_polyphony_renders_nonempty_pdf(tmp_path):
    _, score, _ = _roundtrip(tmp_path, [
        _note(60, 0.0, 3.0), _note(64, 0.0, 1.0), _note(67, 1.0, 2.0),
    ])
    output, _ = render_pdf(score, tmp_path / "score.pdf")
    assert output.read_bytes().startswith(b"%PDF-")
    assert output.stat().st_size > 1000


@pytest.mark.parametrize("invalid", ["empty", "unterminated", "zero_length", "type2"])
def test_invalid_performance_is_reported_without_fabricating_notes(tmp_path, invalid):
    midi = mido.MidiFile(type=2 if invalid == "type2" else 1)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    if invalid != "empty":
        track.append(mido.Message("note_on", note=60, velocity=90, time=0))
        if invalid != "unterminated":
            track.append(mido.Message("note_off", note=60, time=0 if invalid == "zero_length" else 480))
    source = tmp_path / "bad.mid"
    target = tmp_path / "bad.musicxml"
    midi.save(source)
    with pytest.raises(NotationBackendError):
        midi_to_musicxml(source, target)
    assert not target.exists()
