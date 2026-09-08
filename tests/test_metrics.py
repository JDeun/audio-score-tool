from pathlib import Path

import mido

from audio_score_tool.metrics import evaluate_midi_files


def _write_midi(
    path: Path,
    notes: list[tuple[int, int]],
    *,
    program: int = 0,
    channel: int = 0,
    duration_ticks: int = 120,
) -> None:
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    track.append(mido.Message("program_change", program=program, channel=channel, time=0))
    previous_tick = 0
    for pitch, absolute_tick in notes:
        track.append(
            mido.Message(
                "note_on",
                note=pitch,
                velocity=90,
                channel=channel,
                time=absolute_tick - previous_tick,
            )
        )
        track.append(
            mido.Message(
                "note_off",
                note=pitch,
                velocity=0,
                channel=channel,
                time=duration_ticks,
            )
        )
        previous_tick = absolute_tick + duration_ticks
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
    assert metrics.offset_mae_ms == 0.0
    assert metrics.instrument_f1 == 1.0


def test_wrong_pitch_reduces_f1(tmp_path: Path):
    pred = tmp_path / "pred.mid"
    ref = tmp_path / "ref.mid"
    _write_midi(pred, [(60, 0), (65, 480)])
    _write_midi(ref, [(60, 0), (62, 480)])

    metrics = evaluate_midi_files(pred, ref)
    assert metrics.matched == 1
    assert metrics.f1 == 0.5


def test_wrong_instrument_is_visible_without_hiding_note_accuracy(tmp_path: Path):
    pred = tmp_path / "pred.mid"
    ref = tmp_path / "ref.mid"
    notes = [(60, 0), (64, 480)]
    _write_midi(pred, notes, program=24)  # guitar
    _write_midi(ref, notes, program=0)   # piano

    metrics = evaluate_midi_files(pred, ref)
    assert metrics.f1 == 1.0
    assert metrics.instrument_matched == 0
    assert metrics.instrument_f1 == 0.0


def test_wrong_note_duration_is_reported_as_offset_error(tmp_path: Path):
    pred = tmp_path / "pred.mid"
    ref = tmp_path / "ref.mid"
    _write_midi(pred, [(60, 0)], duration_ticks=240)
    _write_midi(ref, [(60, 0)], duration_ticks=120)

    metrics = evaluate_midi_files(pred, ref)
    assert metrics.f1 == 1.0
    assert metrics.onset_mae_ms == 0.0
    assert metrics.offset_mae_ms == 125.0
