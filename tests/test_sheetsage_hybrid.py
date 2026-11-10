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


def test_analysis_annotations_follow_unchanged_score_clock_despite_other_beat_grid(tmp_path):
    import xml.etree.ElementTree as ET

    from music21 import meter, tempo

    score = stream.Score()
    part = stream.Part()
    for number, bpm in ((1, 60), (2, 120)):
        measure = stream.Measure(number=number)
        if number == 1:
            measure.insert(0, meter.TimeSignature("3/4"))
        measure.insert(0, tempo.MetronomeMark(number=bpm))
        for pitch in (60, 62, 64):
            measure.append(note.Note(pitch, quarterLength=1))
        part.append(measure)
    score.insert(0, part)
    source = tmp_path / "source.musicxml"
    score.write("musicxml", fp=str(source))
    events = tmp_path / "events.json"
    events.write_text(json.dumps({
        "schema_version": 1,
        "beats": [{"time_seconds": at} for at in (0, 0.25, 0.5, 0.75)],
        "chords": [{"time_seconds": 4, "label": "G:7"}],
    }))
    target = tmp_path / "merged.musicxml"
    report = merge_sheetsage_musicxml(source, events, target)
    parsed = converter.parse(str(target))
    symbol = list(parsed.recurse().getElementsByClass(harmony.ChordSymbol))[0]
    assert symbol.getOffsetInHierarchy(parsed) == 5
    for tag in ("note", "time", "direction"):
        assert [ET.tostring(n) for n in ET.parse(source).iter(tag)] == [
            ET.tostring(n) for n in ET.parse(target).iter(tag)
        ]
    assert report["alignment"] == "source_score_tempo_map"
    assert report["beat_grid_applied"] is False


def test_lead_sheet_normalization_preserves_minor_mode_and_tempo_changes(tmp_path):
    from music21 import key, tempo

    from audio_score_tool.sheetsage_hybrid import normalize_lead_sheet_musicxml

    score = stream.Score()
    part = stream.Part()
    part.insert(0, key.Key("a"))
    part.insert(0, tempo.MetronomeMark(number=60))
    part.insert(2, tempo.MetronomeMark(number=120))
    part.insert(0, note.Note(60, quarterLength=4))
    part.insert(3, harmony.ChordSymbol("Am"))
    score.insert(0, part)
    source = tmp_path / "minor.musicxml"
    score.write("musicxml", fp=str(source))
    report = normalize_lead_sheet_musicxml(source, tmp_path / "events.json")
    assert report["keys"] == [{"time_seconds": 0, "label": "A:minor"}]
    assert report["chords"][0]["time_seconds"] == 2.5


def test_score_clock_uses_fallback_only_until_first_explicit_tempo():
    from music21 import tempo

    from audio_score_tool.score_timing import score_time_clocks

    score = stream.Score()
    part = stream.Part()
    part.insert(2, tempo.MetronomeMark(number=120))
    part.insert(0, note.Note(60, quarterLength=4))
    score.insert(0, part)
    seconds, quarters = score_time_clocks(score, fallback_bpm=60)
    assert seconds(3) == 2.5
    assert quarters(2.5) == 3
    part.insert(2, tempo.MetronomeMark(number=90))
    with pytest.raises(ValueError, match="conflicting"):
        score_time_clocks(score)


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


@pytest.mark.parametrize("label,root,bass,classes", [
    ("C:maj/3", 0, 4, {0, 4, 7}),
    ("Bb:min/b3", 10, 1, {10, 1, 5}),
    ("G:7/b7", 7, 5, {7, 11, 2, 5}),
    ("F#:maj7/7", 6, 5, {6, 10, 1, 5}),
    ("C:sus4(b7)", 0, 0, {0, 5, 7, 10}),
])
def test_native_sheetsage2_full_chord_vocabulary_preserves_inversions(label, root, bass, classes):
    from audio_score_tool.sheetsage_hybrid import _parse_chord_symbol

    symbol = _parse_chord_symbol(label)
    assert symbol.root().pitchClass == root
    assert symbol.bass().pitchClass == bass
    assert {p.pitchClass for p in symbol.pitches} == classes


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


def test_suspended_seventh_harmony_is_standard_and_roundtrips(tmp_path):
    import xml.etree.ElementTree as ET

    source = tmp_path / 'source.musicxml'
    score = stream.Score()
    part = stream.Part()
    part.append(note.Note('C4', quarterLength=4))
    score.append(part)
    score.write('musicxml', fp=str(source))
    events = tmp_path / 'events.json'
    events.write_text(json.dumps({'schema_version': 1, 'chords': [
        {'time_seconds': 0, 'label': 'F#7sus4/C#'}]}))
    target = tmp_path / 'hybrid.musicxml'
    merge_sheetsage_musicxml(source, events, target, bpm=120)
    tree = ET.parse(target)
    h = tree.find('.//harmony')
    assert h.findtext('kind') == 'suspended-fourth' and h.find('kind').get('text') == 'sus4'
    assert h.findtext('root/root-alter') == '1'
    assert [(d.findtext('degree-value'), d.findtext('degree-alter'), d.findtext('degree-type'))
            for d in h.findall('degree')] == [('7', '-1', 'add')]
    parsed = converter.parse(target)
    chord = list(parsed.recurse().getElementsByClass(harmony.ChordSymbol))[0]
    assert {p.pitchClass for p in chord.pitches} == {1, 4, 6, 11}
    again = tmp_path / 'again.musicxml'
    parsed.write('musicxml', fp=str(again))
    assert ET.parse(again).findtext('.//harmony/kind') == 'suspended-fourth'
    assert ET.parse(again).findtext('.//harmony/degree/degree-alter') == '-1'


def test_suspended_seventh_preserves_existing_degrees():
    import xml.etree.ElementTree as ET

    from audio_score_tool.musicxml_metadata_projection import normalize_suspended_seventh

    root = ET.fromstring('''<score-partwise><part><measure><harmony>
        <root><root-step>F</root-step><root-alter>1</root-alter></root>
        <kind>suspended-fourth-seventh</kind><bass><bass-step>C</bass-step><bass-alter>1</bass-alter></bass>
        <degree><degree-value>9</degree-value><degree-alter>-1</degree-alter><degree-type>add</degree-type></degree>
        </harmony></measure></part></score-partwise>''')
    normalize_suspended_seventh(root)
    harmony_xml = root.find('.//harmony')
    assert harmony_xml.findtext('bass/bass-alter') == '1'
    assert [(x.findtext('degree-value'), x.findtext('degree-alter'))
            for x in harmony_xml.findall('degree')] == [('7', '-1'), ('9', '-1')]


def test_suspended_seventh_preserves_custom_text_and_namespace():
    import xml.etree.ElementTree as ET

    from audio_score_tool.musicxml_metadata_projection import normalize_suspended_seventh

    root = ET.fromstring('''<score-partwise xmlns="urn:musicxml"><harmony>
        <root><root-step>E</root-step></root><kind text="custom">suspended-fourth-seventh</kind>
        </harmony></score-partwise>''')
    normalize_suspended_seventh(root)
    before = ET.tostring(root)
    normalize_suspended_seventh(root)
    assert ET.tostring(root) == before
    assert root.find('.//{urn:musicxml}kind').get('text') == 'custom'
    assert root.findtext('.//{urn:musicxml}degree/{urn:musicxml}degree-alter') == '-1'


def test_suspended_seventh_chord_listing_and_edit_preserve_degree():
    from audio_score_tool.chord_editor import _build_harmony, harmony_symbol

    for spelling in ('F#7sus4/C#', 'F#sus4(b7)/C#'):
        harmony_xml = _build_harmony('', spelling)
        assert harmony_symbol(harmony_xml, '') == 'F♯7sus4/C♯'
        assert harmony_xml.findtext('kind') == 'suspended-fourth'
        assert harmony_xml.findtext('degree/degree-alter') == '-1'


@pytest.mark.parametrize('symbol', ['B♭m(maj7)/D♭', 'B♭mM7/D♭', 'B♭m7b5/D♭'])
def test_minor_seventh_aliases_preserve_harmony_on_edit(tmp_path, symbol):
    from audio_score_tool.chord_editor import set_chord_at_note
    from audio_score_tool.chord_listing import list_chords

    score = stream.Score()
    part = stream.Part()
    part.append(note.Note('C4', quarterLength=4))
    score.append(part)
    target = tmp_path / 'score.musicxml'
    score.write('musicxml', fp=str(target))
    set_chord_at_note(target, 'p0-m0-n0', symbol)
    chord = list(converter.parse(target).recurse().getElementsByClass(harmony.ChordSymbol))[0]
    assert (chord.root().pitchClass, chord.bass().pitchClass) == (10, 1)
    assert {p.pitchClass for p in chord.pitches} == ({10, 1, 5, 9} if 'maj7' in symbol or 'mM7' in symbol else {10, 1, 4, 8})
    listed = list_chords(target)[0]
    set_chord_at_note(target, listed['note_id'], listed['symbol'])
    assert list_chords(target)[0]['symbol'] == listed['symbol']


def test_unchanged_chord_edit_preserves_custom_text_and_extra_degree(tmp_path):
    import xml.etree.ElementTree as ET

    from audio_score_tool.chord_editor import set_chord_at_note
    from audio_score_tool.chord_listing import list_chords

    score = stream.Score()
    part = stream.Part()
    part.insert(0, harmony.ChordSymbol('Cm7b5add9'))
    part.insert(0, note.Note('C4', quarterLength=4))
    score.append(part)
    target = tmp_path / 'score.musicxml'
    score.write('musicxml', fp=str(target))
    tree = ET.parse(target)
    tree.find('.//harmony/kind').set('text', 'custom')
    tree.write(target, encoding='utf-8', xml_declaration=True)
    original = target.read_bytes()
    chord = list_chords(target)[0]
    set_chord_at_note(target, chord['note_id'], chord['symbol'])
    assert target.read_bytes() == original
    assert len(ET.parse(target).findall('.//harmony/degree')) == 2


def test_unchanged_half_diminished_keeps_additional_degree(tmp_path):
    import xml.etree.ElementTree as ET

    from audio_score_tool.chord_editor import set_chord_at_note
    from audio_score_tool.chord_listing import list_chords

    score = stream.Score()
    part = stream.Part()
    part.insert(0, harmony.ChordSymbol('Cm7b5add9'))
    part.insert(0, note.Note('C4', quarterLength=4))
    score.append(part)
    target = tmp_path / 'score.musicxml'
    score.write('musicxml', fp=str(target))
    before = target.read_bytes()
    listed = list_chords(target)[0]
    assert listed['symbol'] == 'Cm7b5'
    set_chord_at_note(target, listed['note_id'], listed['symbol'])
    assert target.read_bytes() == before
    assert len(ET.parse(target).findall('.//harmony/degree')) == 2
