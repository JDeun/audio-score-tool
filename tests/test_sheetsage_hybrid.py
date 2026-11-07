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


def test_hybrid_rejects_rest_only_amt_even_with_valid_harmony(tmp_path):
    source = tmp_path / "rest-only.musicxml"
    score = stream.Score()
    part = stream.Part()
    part.append(note.Rest(quarterLength=1))
    part.append(harmony.ChordSymbol("C"))
    score.append(part)
    score.write("musicxml", fp=str(source))
    events = tmp_path / "sheetsage.json"
    events.write_text(
        json.dumps({"schema_version": 1, "chords": [
            {"time_seconds": 0.0, "label": "C:maj"},
        ]}),
        encoding="utf-8",
    )
    output = tmp_path / "hybrid.musicxml"
    with pytest.raises(SheetSageError, match="no performed note events"):
        merge_sheetsage_musicxml(source, events, output)
    assert not output.exists()


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
    # music21 also exposes harmony.ChordSymbol via .notes; filter pitched
    # note.Note instances when checking AMT note preservation.
    assert len([item for item in parsed.recurse().notes if isinstance(item, note.Note)]) == 1


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



def test_dense_polyphonic_voices_preserved_by_hybrid_enrichment(tmp_path):
    """SheetSage metadata must not multiply notes in a multivoice model score."""
    import xml.etree.ElementTree as ET

    from music21 import chord, instrument, meter

    score = stream.Score()
    part = stream.Part()
    part.insert(0, instrument.Piano())
    part.insert(0, meter.TimeSignature("4/4"))
    for number in range(1, 5):
        measure = stream.Measure(number=number)
        lead = stream.Voice()
        for pitch in ("C4", "E4", "G4", "C5"):
            lead.append(note.Note(pitch, quarterLength=1))
        bass = stream.Voice()
        bass.append(chord.Chord(["C3", "G3"], quarterLength=4))
        measure.insert(0, lead)
        measure.insert(0, bass)
        part.append(measure)
    score.append(part)
    original = tmp_path / "complex.musicxml"
    score.write("musicxml", fp=str(original))

    analysis = tmp_path / "sheetsage.json"
    analysis.write_text(json.dumps({
        "schema_version": 1,
        "chords": [{"time_seconds": i * 2.0, "label": "C:maj"} for i in range(4)],
        "keys": [{"time_seconds": 0.0, "label": "C:major"}],
        "meter": "4/4",
        "beats": [{"time_seconds": i * 0.5} for i in range(17)],
    }), encoding="utf-8")
    target = tmp_path / "complex-hybrid.musicxml"
    merge_sheetsage_musicxml(original, analysis, target)

    orig_xml = ET.parse(original).getroot()
    output_xml = ET.parse(target).getroot()
    assert [ET.tostring(n) for n in orig_xml.findall(".//note")] == [
        ET.tostring(n) for n in output_xml.findall(".//note")
    ]
    assert len(output_xml.findall(".//harmony")) == 4
    assert len(list(converter.parse(str(target)).recurse().getElementsByClass(harmony.ChordSymbol))) == 4


def test_hybrid_metadata_overlay_preserves_all_multi_instrument_parts(tmp_path):
    from scripts.run_tier2_hybrid_smoke import performed_note_signature

    score = stream.Score()
    piano = stream.Part()
    piano.append(note.Note("C4", quarterLength=1))
    bass = stream.Part()
    bass.append(note.Note("C2", quarterLength=2))
    score.insert(0, piano)
    score.insert(0, bass)
    source = tmp_path / "multi.musicxml"
    score.write("musicxml", fp=str(source))
    baseline = performed_note_signature(source)
    assert len(baseline) == 2

    events = tmp_path / "sheetsage.json"
    events.write_text(json.dumps({
        "schema_version": 1,
        "model": "sheetsage2",
        "chords": [{"time_seconds": 0.0, "label": "C:maj"}],
        "keys": [{"time_seconds": 0.0, "label": "C:major"}],
        "meter": "4/4",
    }), encoding="utf-8")
    target = tmp_path / "augmented.musicxml"
    merged = merge_sheetsage_musicxml(source, events, target)
    result = converter.parse(str(target))
    assert len(result.parts) == 2
    assert performed_note_signature(target) == baseline
    assert merged["added"] == {"chords": 1, "keys": 1, "meter": 1}
