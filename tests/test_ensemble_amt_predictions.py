"""Unit tests for pitch/program-aware consensus ensemble with declared mido."""
from __future__ import annotations

from pathlib import Path

import mido
import pytest

from scripts.ensemble_amt_predictions import _read_events, ensemble


def _write(
    path: Path,
    notes: list[tuple[int, float, float]],
    program: int = 0,
    *,
    channel: int = 0,
    tempo: int = 500_000,
) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=960)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    midi.tracks.append(conductor)
    track = mido.MidiTrack()
    track.append(mido.Message("program_change", channel=channel, program=program, time=0))
    messages = []
    ticks_per_second = (1_000_000 / tempo) * 960
    for pitch, start, end in notes:
        messages.append(
            (round(start * ticks_per_second), 1, pitch, mido.Message(
                "note_on", channel=channel, note=pitch, velocity=90,
            ))
        )
        messages.append(
            (round(end * ticks_per_second), 0, pitch, mido.Message(
                "note_off", channel=channel, note=pitch, velocity=0,
            ))
        )
    current = 0
    for tick, _kind, _pitch, message in sorted(messages):
        message.time = tick - current
        track.append(message)
        current = tick
    midi.tracks.append(track)
    midi.save(str(path))


def test_consensus_retains_matching_notes_only(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(60, 0.1, 0.8), (64, 1.0, 1.5)])
    _write(b, [(60, 0.13, 0.83), (67, 1.0, 1.5)])
    result = ensemble(a, b, out)
    assert result["matched_notes"] == 1
    notes = _read_events(out)[(0, False)]
    assert len(notes) == 1
    assert notes[0].pitch == 60
    assert notes[0].start == pytest.approx(0.115, abs=0.002)


def test_consensus_does_not_merge_different_instruments(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(60, 0.1, 0.8)], program=0)
    _write(b, [(60, 0.1, 0.8)], program=24)
    assert ensemble(a, b, out)["matched_notes"] == 0
    assert _read_events(out) == {}


def test_consensus_matches_programs_across_different_channels(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(60, 0.1, 0.8)], program=24, channel=1)
    _write(b, [(60, 0.1, 0.8)], program=24, channel=2)
    assert ensemble(a, b, out)["matched_notes"] == 1
    assert _read_events(out)[(24, False)][0].pitch == 60


def test_consensus_reads_non_default_tempo_correctly(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(72, 0.2, 1.2)], tempo=750_000)
    _write(b, [(72, 0.2, 1.2)], tempo=1_000_000)
    assert ensemble(a, b, out)["matched_notes"] == 1
    note = _read_events(out)[(0, False)][0]
    assert note.end == pytest.approx(1.2, abs=0.002)


def test_consensus_rejects_invalid_thresholds(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [])
    _write(b, [])
    with pytest.raises(ValueError, match="Invalid consensus"):
        ensemble(a, b, out, onset_tolerance=float("nan"))
    with pytest.raises(ValueError, match="Invalid consensus"):
        ensemble(a, b, out, min_overlap=1.5)
