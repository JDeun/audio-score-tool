from __future__ import annotations

import json

import pytest
from music21 import converter, harmony, note, stream

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
    assert len(list(result.recurse().getElementsByClass(harmony.ChordSymbol))) == 2
    assert report["added"]["chords"] == 2


def test_adapter_rejects_unsorted_events(tmp_path):
    events = tmp_path / "bad.json"
    events.write_text(json.dumps({
        "schema_version": 1,
        "beats": [{"time_seconds": 2}, {"time_seconds": 1}],
    }), encoding="utf-8")
    with pytest.raises(SheetSageError, match="chronological"):
        load_sheetsage_events(events)


def test_variable_tempo_beat_alignment():
    from audio_score_tool.sheetsage_hybrid import _quarter_offset

    beats = [{"time_seconds": 0.0}, {"time_seconds": 0.4},
             {"time_seconds": 1.0}, {"time_seconds": 1.8}]
    assert _quarter_offset(0.7, bpm=120, beats=beats) == pytest.approx(1.5)
    assert _quarter_offset(1.4, bpm=120, beats=beats) == pytest.approx(2.5)


def test_nonfinite_beat_is_rejected(tmp_path):
    events = tmp_path / "bad.json"
    events.write_text('{"schema_version":1,"beats":[{"time_seconds":NaN}]}')
    with pytest.raises(SheetSageError, match="finite"):
        load_sheetsage_events(events)


@pytest.mark.parametrize(
    ("label", "expected_figure", "expected_kind"),
    [
        ("C:maj", "C", "major"),
        ("Bb:min", "B-m", "minor"),
        ("C:aug", "C+", "augmented"),
        ("F#:dim", "F#dim", "diminished"),
        ("D:min7", "Dm7", "minor-seventh"),
        ("G:7", "G7", "dominant-seventh"),
        ("C:hdim7", "Cm7b5", "minor-seventh"),
    ],
)
def test_sheetsage_harte_chord_symbol_uses_music21_spelling(
    label, expected_figure, expected_kind,
):
    from audio_score_tool.sheetsage_hybrid import _parse_chord_symbol

    parsed = _parse_chord_symbol(label)
    assert isinstance(parsed, harmony.ChordSymbol)
    assert parsed.figure == expected_figure
    assert parsed.chordKind == expected_kind
    if label == "C:hdim7":
        # Music21 represents m7b5 as minor-seventh + altered fifth, not a
        # separate chordKind. Verify the actual half-diminished pitch classes.
        assert sorted(p.pitchClass for p in parsed.pitches) == [0, 3, 6, 10]


def test_sheetsage_merge_accepts_augmented_chord_from_real_model(tmp_path):
    source = tmp_path / "amt.musicxml"
    score = stream.Score()
    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1))
    score.append(part)
    score.write("musicxml", fp=str(source))
    events = tmp_path / "events.json"
    events.write_text(
        json.dumps({"schema_version": 1, "chords": [{"time_seconds": 0, "label": "C:aug"}]}),
        encoding="utf-8",
    )
    target = tmp_path / "merged.musicxml"
    report = merge_sheetsage_musicxml(source, events, target)
    parsed = converter.parse(str(target))
    assert report["added"]["chords"] == 1
    symbols = list(parsed.recurse().getElementsByClass(harmony.ChordSymbol))
    assert any(item.chordKind == "augmented" for item in symbols), [
        (item.figure, item.chordKind) for item in symbols
    ]
    assert len(list(parsed.recurse().notes)) == 1


@pytest.mark.parametrize("label", ["C:unrecognized", "Q:maj", "C:aug/3"])
def test_sheetsage_rejects_unmappable_harte_chords(label):
    from audio_score_tool.sheetsage_hybrid import _parse_chord_symbol

    with pytest.raises(SheetSageError, match="unsupported chord label"):
        _parse_chord_symbol(label)


@pytest.mark.parametrize(
    ("label", "tonic", "mode"),
    [
        ("C:major", "C", "major"),
        ("A:minor", "A", "minor"),
        ("F#:maj", "F#", "major"),
        ("Bb:min", "B-", "minor"),
        ("D", "D", "major"),
    ],
)
def test_sheetsage_harte_key_label_normalization(label, tonic, mode):
    from audio_score_tool.sheetsage_hybrid import _parse_key_label

    parsed = _parse_key_label(label)
    assert parsed.tonic.name == tonic
    assert parsed.mode == mode


@pytest.mark.parametrize("label", ["C:unknown", "C:major/3", "X:major"])
def test_sheetsage_rejects_unsupported_key_labels(label):
    from audio_score_tool.sheetsage_hybrid import _parse_key_label

    with pytest.raises(SheetSageError, match="unsupported key label"):
        _parse_key_label(label)


def test_merge_accepts_harte_key_and_chord_from_sheet_sage(tmp_path):
    score = stream.Score()
    part = stream.Part()
    part.append(note.Note("C4", quarterLength=1))
    score.append(part)
    source = tmp_path / "score.musicxml"
    score.write("musicxml", fp=str(source))
    payload = tmp_path / "events.json"
    payload.write_text(
        json.dumps({
            "schema_version": 1,
            "chords": [{"time_seconds": 0.0, "label": "C:aug"}],
            "keys": [{"time_seconds": 0.0, "label": "C:major"}],
        }),
        encoding="utf-8",
    )
    target = tmp_path / "merged.musicxml"
    result = merge_sheetsage_musicxml(source, payload, target)
    assert result["added"]["chords"] == 1
    assert result["added"]["keys"] == 1
    assert target.is_file()
