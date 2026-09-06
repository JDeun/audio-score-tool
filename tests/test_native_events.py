from pathlib import Path

import mido

from audio_score_tool.native_events import BOS, EOS, decode_tokens, midi_to_tokens, tokens_to_midi


def _write_midi(path: Path) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    track.append(mido.Message("program_change", program=0, channel=0, time=0))
    track.append(mido.Message("note_on", note=60, velocity=100, channel=0, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, channel=0, time=480))
    track.append(mido.Message("note_on", note=64, velocity=90, channel=0, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, channel=0, time=480))
    midi.save(path)


def test_native_event_codec_round_trip(tmp_path: Path):
    source = tmp_path / "source.mid"
    _write_midi(source)

    tokens = midi_to_tokens(source)
    assert tokens[0] == BOS
    assert tokens[-1] == EOS

    bpm, notes = decode_tokens(tokens)
    assert 119 <= bpm <= 121
    assert [note.pitch for note in notes] == [60, 64]
    assert all(note.end_ms > note.start_ms for note in notes)

    output = tmp_path / "decoded.mid"
    tokens_to_midi(tokens, output)
    assert output.exists()
    decoded = mido.MidiFile(output)
    assert len(decoded.tracks) >= 2
