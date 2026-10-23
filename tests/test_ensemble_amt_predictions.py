"""Unit tests for pitch/program-aware consensus ensemble."""
from __future__ import annotations

from pathlib import Path

import pretty_midi

from scripts.ensemble_amt_predictions import ensemble


def _write(path: Path, notes: list[tuple[int, float, float]], program: int = 0) -> None:
    midi = pretty_midi.PrettyMIDI()
    instrument = pretty_midi.Instrument(program=program)
    for pitch, start, end in notes:
        instrument.notes.append(pretty_midi.Note(velocity=90, pitch=pitch, start=start, end=end))
    midi.instruments.append(instrument)
    midi.write(str(path))


def test_consensus_retains_matching_notes_only(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(60, 0.1, 0.8), (64, 1.0, 1.5)])
    _write(b, [(60, 0.13, 0.83), (67, 1.0, 1.5)])
    result = ensemble(a, b, out)
    assert result["matched_notes"] == 1
    notes = pretty_midi.PrettyMIDI(str(out)).instruments[0].notes
    assert len(notes) == 1
    assert notes[0].pitch == 60


def test_consensus_does_not_merge_different_instruments(tmp_path: Path) -> None:
    a, b, out = (tmp_path / x for x in ("a.mid", "b.mid", "out.mid"))
    _write(a, [(60, 0.1, 0.8)], program=0)
    _write(b, [(60, 0.1, 0.8)], program=24)
    assert ensemble(a, b, out)["matched_notes"] == 0
