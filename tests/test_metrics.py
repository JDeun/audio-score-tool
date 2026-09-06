from pathlib import Path

import mido

from audio_score_tool.metrics import evaluate_midi_files


def _write_midi(path: Path, notes: list[tuple[int, int]]) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    previous_tick = 0
    for pitch, absolute_tick in notes:
        track.append(mido.Message("note_on", note=pitch, velocity=90, time=absolute_tick - previous_tick))
        track.append(mido.Message("note_off", note=pitch, velocity=0, time=120))
        previous_tick = absolute_tick + 120
    midi.save(path)


def test_identical_midi_scores_perfectly(tmp_path: Path):
    pred = tmp_path / "pred.mid"
    ref = tmp_path / "ref.mid"
    notes = [(60, 0), (62, 480), (64, 960)]
    _write_midi(pred, notes)
    _write_midi(ref, notes)

    metrics = evaluate_midi_files(pred, ref)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.onset_mae_ms == 0.0


def test_wrong_pitch_reduces_f1(tmp_path: Path):
    pred = tmp_path / "pred.mid"
    ref = tmp_path / "ref.mid"
    _write_midi(pred, [(60, 0), (65, 480)])
    _write_midi(ref, [(60, 0), (62, 480)])

    metrics = evaluate_midi_files(pred, ref)
    assert metrics.matched == 1
    assert metrics.f1 == 0.5
