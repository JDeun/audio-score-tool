from __future__ import annotations

import json

import pytest
from music21 import chord, converter, note, stream

from audio_score_tool.sheetsage_hybrid import (
    SheetSageError,
    load_sheetsage_events,
    merge_sheetsage_musicxml,
)


def test_merger_preserves_notes_and_adds_chords(tmp_path):
    source = tmp_path / "amt.musicxml"
    score = stream.Score()
    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1))
    part.append(note.Note("E4", quarterLength=1))
    score.append(part)
    score.write("musicxml", fp=str(source))
    events = tmp_path / "events.json"
    events.write_text(json.dumps({
        "schema_version": 1,
        "chords": [{"time_seconds": 0.0, "label": "C"},
                   {"time_seconds": 0.5, "label": "G7"}],
        "keys": [{"time_seconds": 0.0, "label": "C"}],
        "meter": "4/4",
    }), encoding="utf-8")
    output = tmp_path / "hybrid.musicxml"
    report = merge_sheetsage_musicxml(source, events, output, bpm=120)
    result = converter.parse(str(output))
    assert [n.pitch.nameWithOctave for n in result.recurse().notes
            if isinstance(n, note.Note)] == ["C4", "E4"]
    assert len(list(result.recurse().getElementsByClass(chord.ChordSymbol))) == 2
    assert report["added"]["chords"] == 2


def test_adapter_rejects_unsorted_events(tmp_path):
    events = tmp_path / "bad.json"
    events.write_text(json.dumps({
        "schema_version": 1,
        "beats": [{"time_seconds": 2}, {"time_seconds": 1}],
    }), encoding="utf-8")
    with pytest.raises(SheetSageError, match="chronological"):
        load_sheetsage_events(events)
