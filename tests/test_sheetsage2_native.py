"""Pinned official protocol and notated vocal import; synthetic inputs only."""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest
from music21 import clef, converter, harmony, key, meter, note, tempo

from audio_score_tool.config import Settings
from audio_score_tool.score_requests import needs_stem_separation, validate_engine_score_mode
from audio_score_tool.sheetsage2_score import import_native_lead_sheet, vocal_abc
from audio_score_tool.transcription_engine import SheetSage2Engine, TranscriptionEngineUnavailable
from scripts.fetch_pinned_sheetsage2 import verify_files
from scripts.sheetsage2_infer_adapter import normalize_native_result

ABC = '''X:1
T:Synthetic
M:3/4
L:1/8
Q:1/4=120
V:Vocal clef=treble
V:Ins clef=treble
K:G
V: Vocal
"G"G2 A2 B2 |
V: Ins
c6 |
V: Vocal
"D7"d2 c2 B2 |]
V: Ins
d6 |]
'''


def _native(tmp_path):
    (tmp_path / "score.abc").write_text(ABC)
    mapping = [dict(start=0, end=3, score_start=0, score_end=.75),
               dict(start=3, end=4.5, score_start=.75, score_end=1.5)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    return mapping


def test_vocal_import_keeps_chords_key_meter_and_audio_clock(tmp_path):
    _native(tmp_path)
    target = tmp_path / "canonical.musicxml"
    report = import_native_lead_sheet(tmp_path, target)
    score = converter.parse(target)
    assert report["vocal_notes"] == 6
    assert len(score.parts) == 1
    assert [n.nameWithOctave for n in score.recurse().getElementsByClass(note.Note)] == ["G4", "A4", "B4", "D5", "C5", "B4"]
    assert [h.figure for h in score.recurse().getElementsByClass(harmony.ChordSymbol)] == ["G", "D7"]
    assert [m.ratioString for m in score.recurse().getElementsByClass(meter.TimeSignature)] == ["3/4"]
    assert [k.sharps for k in score.recurse().getElementsByClass(key.KeySignature)] == [1]
    assert [m.number for m in score.recurse().getElementsByClass(tempo.MetronomeMark)] == [60, 120]
    xml = ET.parse(target)
    assert len(xml.findall(".//metronome[@print-object='no']")) == 2
    assert len(xml.findall(".//sound[@tempo]")) == 2
    assert "".join(w.text or "" for w in xml.findall(".//words")) == "♩ ≈ 120"
    from audio_score_tool.notation_backend import _verovio_toolkit

    toolkit = _verovio_toolkit()
    assert toolkit.loadFile(str(target))
    svg = ET.fromstring(toolkit.renderToSVG(1))
    assert len([g for g in svg.iter()
                if "tempo" in g.get("class", "").split() and "".join(g.itertext()).strip()]) == 0
    rendered = "".join(svg.itertext())
    assert "♩" in rendered and "≈ 120" in rendered


def test_voice_and_changed_bar_grid_fail_explicitly(tmp_path):
    with pytest.raises(ValueError, match="Vocal"):
        vocal_abc(ABC.replace("Vocal", "Ins"))
    mapping = _native(tmp_path)
    mapping[1]["score_end"] = 2
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    with pytest.raises(ValueError, match="grid"):
        import_native_lead_sheet(tmp_path, tmp_path / "bad.musicxml")
    assert not (tmp_path / "bad.musicxml").exists()


def test_abc_multi_measure_rests_keep_following_note_and_chord_positions(tmp_path):
    (tmp_path / "score.abc").write_text(ABC.replace('"G"G2 A2 B2 |', 'Z2|'))
    mapping = [dict(start=i * 3, end=(i + 1) * 3, score_start=i * .75, score_end=(i + 1) * .75)
               for i in range(3)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "rest.musicxml"
    assert import_native_lead_sheet(tmp_path, target)["measures"] == 3
    score = converter.parse(target)
    assert [n.nameWithOctave for n in score.recurse().getElementsByClass(note.Note)] == ["D5", "C5", "B4"]
    assert score.parts[0].measure(3).offset == 6


def test_pickup_padding_uses_audio_span_without_stretching_rest(tmp_path, caplog):
    mapping = _native(tmp_path)
    (tmp_path / "score.abc").write_text(ABC.replace('"G"G2 A2 B2 |', 'z4 "G"B2 |'))
    mapping[0].update(start=.5, end=1.5, leading_rest=.5)
    mapping[1].update(start=1.5, end=4.5)
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "pickup.musicxml"
    import_native_lead_sheet(tmp_path, target)
    score = converter.parse(target)
    events = [(m.offset, m.number) for m in score.parts[0].measure(1).getElementsByClass(tempo.MetronomeMark)]
    assert events == [(0, 240), (2, 60)]
    from audio_score_tool.notation_backend import render_pdf

    render_pdf(target, tmp_path / "pickup.pdf")
    assert not any("missing" in record.getMessage() and "glyph" in record.getMessage()
                   for record in caplog.records)


def test_meter_and_key_changes_survive_musicxml_reload_without_extra_beats(tmp_path):
    (tmp_path / "score.abc").write_text('''X:1
M:3/4
L:1/8
K:G
V: Vocal
G2 A2 B2 |
M:1/4
K:C
f2 |
M:3/4
c2 B2 A2 |]
''')
    mapping = [dict(start=0,end=1.5,score_start=0,score_end=.75),
               dict(start=1.5,end=2,score_start=.75,score_end=1),
               dict(start=2,end=3.5,score_start=1,score_end=1.75)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "changes.musicxml"
    import_native_lead_sheet(tmp_path, target)
    score = converter.parse(target)
    assert [m.ratioString for m in score.recurse().getElementsByClass(meter.TimeSignature)] == ["3/4", "1/4", "3/4"]
    assert [k.sharps for k in score.recurse().getElementsByClass(key.KeySignature)] == [1, 0]
    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import musicxml_to_midi

    events = midi_notes(musicxml_to_midi(target, tmp_path / "changes.mid"))
    assert [(n.pitch, n.onset) for n in events] == [(67, 0), (69, .5), (71, 1), (77, 1.5), (72, 2), (71, 2.5), (69, 3)]


def test_tied_key_change_preserves_sounding_pitch_and_readable_spelling(tmp_path, capfd):
    text = '''X:1
M:4/4
L:1/4
Q:1/4=120
K:Ab
V: Vocal
B4- |
K:A
^A4 |]
'''
    abc = tmp_path / "score.abc"
    abc.write_text(text)
    mapping = [dict(start=0,end=2,score_start=0,score_end=1),
               dict(start=2,end=4,score_start=1,score_end=2)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "key-tie.musicxml"
    report = import_native_lead_sheet(tmp_path, target)
    assert report["enharmonic_tie_respellings"] == 1
    assert abc.read_text() == text
    score = converter.parse(target)
    notes = list(score.recurse().getElementsByClass(note.Note))
    assert [n.nameWithOctave for n in notes] == ["B-4", "B-4"]
    assert [k.sharps for k in score.recurse().getElementsByClass(key.KeySignature)] == [-4, 3]
    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import _verovio_toolkit, musicxml_to_midi
    from audio_score_tool.vocal_evidence import part_notes

    played = midi_notes(musicxml_to_midi(target, tmp_path / "key-tie.mid"))
    assert [(n.pitch, n.onset, n.offset) for n in played] == [(70, 0, 4)]
    observed = part_notes(score, score.parts[0])
    assert len(observed) == 1 and observed[0]["measure"] == "1"
    assert observed[0]["end_seconds"] == 4
    toolkit = _verovio_toolkit()
    assert toolkit.loadFile(str(target))
    toolkit.renderToSVG(1)
    assert "ties left open" not in capfd.readouterr().err


@pytest.mark.parametrize("origin", [0, .037])
def test_native_beat_clock_preserves_within_measure_variation_and_changed_meter(tmp_path, origin):
    (tmp_path / "score.abc").write_text('''X:1
M:4/4
L:1/8
K:C
V: Vocal
cdefgabc |
M:2/4
c2d2 |]
''')
    mapping = [dict(start=origin,end=2+origin,score_start=0,score_end=1),
               dict(start=2+origin,end=3.4+origin,score_start=1,score_end=1.5)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    (tmp_path / "notation").mkdir()
    beats = [(0,1,4),(.4,2,4),(1,3,4),(1.3,4,4),(2,1,2),(2.5,2,2),(3.4,1,2)]
    (tmp_path / "notation/song_beats.txt").write_text("".join(
        f"{at+origin}\t{beat}\t{num}\t4\n" for at,beat,num in beats))
    target = tmp_path / "beats.musicxml"
    report = import_native_lead_sheet(tmp_path, target)
    assert report["timing"] == "model_notation_with_per_beat_audio_clock"
    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import musicxml_to_midi
    from audio_score_tool.vocal_evidence import part_notes

    score = converter.parse(target)
    expected = [at+origin for at in [0, .2, .4, .7, 1, 1.15, 1.3, 1.65, 2, 2.5]]
    observed = part_notes(score, score.parts[0])
    assert [n["start_seconds"] for n in observed] == pytest.approx(expected, abs=1e-5)
    played = midi_notes(musicxml_to_midi(target, tmp_path / "beats.mid"))
    assert [n.onset for n in played] == pytest.approx(expected, abs=5e-5)
    assert played[-1].offset == pytest.approx(3.4+origin, abs=5e-5)
    assert len(ET.parse(target).findall(".//metronome[@print-object='no']")) == 6


@pytest.mark.parametrize("rows", ["0 1 3 4\n", "0 1 3 4\n0 2 3 4\n",
                                  "nan 1 3 4\n3 2 3 4\n", "0 1 3 3\n3 2 3 3\n",
                                  "0 1 3 4\n2 2 3 4\n4 3 3 4\n6 1 3 4\n"])
def test_incomplete_or_inconsistent_native_beats_fail_before_export(tmp_path, rows):
    _native(tmp_path)
    (tmp_path / "notation").mkdir()
    (tmp_path / "notation/song_beats.txt").write_text(rows)
    target = tmp_path / "bad-beats.musicxml"
    with pytest.raises(ValueError, match="beat"):
        import_native_lead_sheet(tmp_path, target)
    assert not target.exists()


def test_native_beat_clock_preserves_pickup_and_clipped_last_beat(tmp_path):
    (tmp_path / "score.abc").write_text('''X:1
M:4/4
L:1/8
K:C
V: Vocal
z6c2 | d2e2z4 |]
''')
    mapping = [dict(start=.25,end=.75,score_start=0,score_end=1,leading_rest=.75),
               dict(start=.75,end=1.75,score_start=1,score_end=2,trailing_rest=.5)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    (tmp_path / "notation").mkdir()
    (tmp_path / "notation/song_beats.txt").write_text(
        ".25 4 4 4\n.75 1 4 4\n1.15 2 4 4\n1.85 3 4 4\n")
    target = tmp_path / "pickup-beats.musicxml"
    import_native_lead_sheet(tmp_path, target)
    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import musicxml_to_midi
    from audio_score_tool.vocal_evidence import part_notes

    score = converter.parse(target)
    observations = part_notes(score, score.parts[0])
    assert [n["start_seconds"] for n in observations] == pytest.approx([.25,.75,1.15], abs=1e-5)
    events = midi_notes(musicxml_to_midi(target, tmp_path / "pickup-beats.mid"))
    assert [n.onset for n in events] == pytest.approx([.25,.75,1.15], abs=1e-5)
    assert events[-1].offset == pytest.approx(1.75, abs=1e-5)


def test_native_accidentals_carry_across_octaves_and_reset_at_barline(tmp_path, capfd):
    text = '''X:1
M:4/4
L:1/4
K:Ab
V: Vocal
=E e E E- | =E E _E E | E4 |]
'''
    (tmp_path / "score.abc").write_text(text)
    mapping = [dict(start=2*i,end=2*(i+1),score_start=i,score_end=i+1)
               for i in range(3)]
    (tmp_path / "playback.json").write_text(json.dumps({"measures": mapping}))
    target = tmp_path / "accidentals.musicxml"
    import_native_lead_sheet(tmp_path, target)
    score = converter.parse(target)
    assert [n.pitch.midi for n in score.recurse().getElementsByClass(note.Note)] == [
        64, 76, 64, 64, 64, 64, 63, 63, 63]
    from audio_score_tool.metrics import midi_notes
    from audio_score_tool.notation_backend import _verovio_toolkit, musicxml_to_midi

    played = midi_notes(musicxml_to_midi(target, tmp_path / "accidentals.mid"))
    assert len(played) == 8
    assert [(n.pitch, n.onset, n.offset) for n in played][3] == (64, 1.5, 2.5)
    toolkit = _verovio_toolkit()
    assert toolkit.loadFile(str(target))
    toolkit.renderToSVG(1)
    assert "ties left open" not in capfd.readouterr().err
    assert (tmp_path / "score.abc").read_text() == text


@pytest.mark.parametrize("declared,expected", [("treble", "G"), ("bass", "F")])
def test_vocal_clef_declaration_survives_voice_extraction(tmp_path, declared, expected):
    _native(tmp_path)
    text = ABC.replace("clef=treble", f"clef={declared}").replace('"G"G2 A2 B2 |', 'G,,2 A,,2 B,,2 |')
    (tmp_path / "score.abc").write_text(text)
    target = tmp_path / "clef.musicxml"
    import_native_lead_sheet(tmp_path, target)
    score = converter.parse(target)
    assert next(iter(score.recurse().getElementsByClass(clef.Clef))).sign == expected
    assert [n.pitch.midi for n in score.recurse().getElementsByClass(note.Note)][:3] == [43, 45, 47]


def test_official_lab_preserves_inversion_and_meter_changes():
    payload = normalize_native_result({"labs": {
        "chord": "0\t1\tC:maj/3\n1\t2\tG:sus4(b7)",
        "key": "0\t2\tC:maj", "beat": "0\t1\t3\t4\n0.5\t2\t3\t4\n1\t1\t6\t8"}})
    assert payload["chords"][0]["label"] == "C:maj/3"
    assert payload["meter"] == "3/4"
    assert len(payload["meters"]) == len(payload["downbeats"]) == 2
    assert payload["base_model_revision"]


@pytest.mark.parametrize("lab", ["nan\t1\t4\t4", "-1\t1\t4\t4", "0\t1\t4\t3", "0\t5\t4\t4", "1\t1\t4\t4\n0\t2\t4\t4"])
def test_official_lab_rejects_invalid_time_and_meter(lab):
    with pytest.raises(ValueError):
        normalize_native_result({"labs": {"beat": lab}})


def test_pinned_sources_reject_tampering_and_symlinks(tmp_path):
    source = tmp_path / "model.py"
    source.write_bytes(b"reviewed")
    pin = {source.name: hashlib.sha256(source.read_bytes()).hexdigest()}
    verify_files(tmp_path, pin)
    source.write_bytes(b"unreviewed")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_files(tmp_path, pin)
    source.unlink()
    source.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="unsafe"):
        verify_files(tmp_path, pin)


def test_engine_scope_and_policy(tmp_path, monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    settings = Settings(usage_mode="personal", transcription_engine="sheetsage2",
                        sheetsage2_cmd=sys.executable, sheetsage2_snapshot=tmp_path)
    engine = SheetSage2Engine(settings)
    assert not engine.ready()

    for folder in ("model", "mert"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "model.safetensors").write_bytes(b"not-real-weights")
    assert engine.ready()  # Inference additionally verifies every pinned byte.
    assert engine.describe()["supported_score_modes"] == ["lead_sheet"]
    assert not needs_stem_separation("lead_sheet", engine="sheetsage2")
    assert needs_stem_separation("lead_sheet", engine="mt3_infer")
    for mode in ("full", "guitar_vocal"):
        with pytest.raises(ValueError):
            validate_engine_score_mode(mode, "sheetsage2")
    with pytest.raises(TranscriptionEngineUnavailable, match="noncommercial"):
        SheetSage2Engine(replace(settings, usage_mode="commercial")).transcribe(None, None, device="cpu")
    monkeypatch.setenv("AST_PACKAGED", "1")
    assert not engine.ready()


@pytest.mark.parametrize("wrong_revision", [False, True])
def test_engine_runs_pinned_native_import_and_refuses_other_model(tmp_path, monkeypatch, wrong_revision):
    from audio_score_tool import transcription_engine as engines
    from audio_score_tool.sheetsage2_score import BASE_REVISION, CHECKPOINT_SHA256, MODEL_REVISION

    settings = Settings(usage_mode="personal", transcription_engine="sheetsage2",
                        sheetsage2_cmd="reviewed-runtime", sheetsage2_snapshot=tmp_path / "snapshot")
    engine = SheetSage2Engine(settings)
    monkeypatch.setattr(engine, "ready", lambda: True)
    calls = []

    def run(command, args, **kwargs):
        calls.append((command, args, kwargs))
        output = args[1]
        output.write_text(json.dumps({"model_revision": "wrong" if wrong_revision else MODEL_REVISION,
                                      "checkpoint_sha256": CHECKPOINT_SHA256, "base_model_revision": BASE_REVISION}))
        native = output.parent / "native"
        native.mkdir()
        _native(native)

    monkeypatch.setattr(engines, "run_command", run)
    if wrong_revision:
        with pytest.raises(engines.TranscriptionEngineError, match="pinned model"):
            engine.transcribe(tmp_path / "source.wav", tmp_path / "out", device="mps")
        assert not (tmp_path / "out/score.musicxml").exists()
    else:
        artifacts = engine.transcribe(tmp_path / "source.wav", tmp_path / "out", device="mps")
        assert artifacts.musicxml_path.is_file() and artifacts.midi_path.is_file()
        assert calls[0][1][-2:] == ["--device", "cpu"]
        assert calls[0][2]["env"]["AST_USAGE_MODE"] == "personal"


def test_inline_key_change_preserves_tied_enharmonic_and_barline_accidentals(tmp_path):
    from music21 import note

    from audio_score_tool.sheetsage2_score import _parse_vocal_abc

    cases = [
        ('K:Bb', '_B6-[K:A]^A24-^A6z60|', [70, 70, 70], ['start', 'continue', 'stop']),
        ('K:Ab', '[K:A]=B48-B48-|B4B4z88|', [71, 71, 71, 71], ['start', 'continue', 'stop', None]),
    ]
    for header_key, body, pitches, ties in cases:
        source = f'X:1\nM:4/4\nL:1/96\n{header_key}\n{body}\n'
        score = _parse_vocal_abc(source)
        events = list(score.recurse().getElementsByClass(note.Note))
        assert [n.pitch.ps for n in events] == pitches
        assert [n.tie.type if n.tie else None for n in events] == ties
        assert source.endswith(body + '\n')
        from audio_score_tool.metrics import midi_notes
        from audio_score_tool.notation_backend import musicxml_to_midi

        xml = tmp_path / 'score.musicxml'
        score.write('musicxml', fp=str(xml))
        rendered = midi_notes(musicxml_to_midi(xml, tmp_path / 'score.mid'))
        assert rendered[0].pitch == pitches[0]
        assert rendered[0].onset == pytest.approx(0, abs=.002)
        assert rendered[0].offset == pytest.approx(.75 if len(events) == 3 else 25 / 12, abs=.002)


def test_inline_key_conversion_keeps_quoted_annotations_and_multiple_keys(monkeypatch):
    from music21 import abcFormat, note

    from audio_score_tool.sheetsage2_score import _parse_vocal_abc

    seen = []
    original = abcFormat.ABCHandler.process
    def capture(self, text):
        seen.append(text)
        return original(self, text)
    monkeypatch.setattr(abcFormat.ABCHandler, 'process', capture)
    score = _parse_vocal_abc('X:1\nM:4/4\nL:1/4\nK:Ab\n"[K:F]"[K:A]B4|[K:Ab]B4|\n')
    events = list(score.recurse().getElementsByClass(note.Note))
    assert [n.pitch.ps for n in events] == [71, 70]
    assert '"[K:F]"' in seen[0]


@pytest.mark.parametrize(('suffix', 'pitch_classes'), [
    ('', {0, 4, 7}), ('m', {0, 3, 7}), ('dim', {0, 3, 6}), ('aug', {0, 4, 8}),
    ('7', {0, 4, 7, 10}), ('maj7', {0, 4, 7, 11}), ('m7', {0, 3, 7, 10}),
    ('dim7', {0, 3, 6, 9}), ('m7b5', {0, 3, 6, 10}), ('sus4', {0, 5, 7}),
    ('sus2', {0, 2, 7}), ('6', {0, 4, 7, 9}), ('m6', {0, 3, 7, 9}),
    ('7sus4', {0, 5, 7, 10}), ('m(maj7)', {0, 3, 7, 11}),
])
def test_native_chord_qualities_survive_standard_xml(tmp_path, suffix, pitch_classes):
    text = f'X:1\nM:4/4\nL:1/4\nK:C\nV: Vocal\n"C{suffix}"C4|]\n'
    abc = tmp_path / 'score.abc'
    abc.write_text(text)
    (tmp_path / 'playback.json').write_text(json.dumps({'measures': [
        dict(start=0, end=2, score_start=0, score_end=1)]}))
    target = tmp_path / 'score.musicxml'
    import_native_lead_sheet(tmp_path, target)
    symbols = list(converter.parse(target).recurse().getElementsByClass(harmony.ChordSymbol))
    assert len(symbols) == 1
    assert {p.pitchClass for p in symbols[0].pitches} == pitch_classes
    assert not ET.parse(target).findall('.//kind[.="suspended-fourth-seventh"]')
    assert abc.read_text() == text


@pytest.mark.parametrize(("symbol", "root", "bass"), [("Cm(maj7)/Eb", 0, 3),
    ("C##m(maj7)/G##", 2, 9), ("Cbbm(maj7)/Gbb", 10, 5)])
def test_minor_major_alias_with_slash_bass_and_quoted_annotation(symbol, root, bass, monkeypatch):
    from music21 import abcFormat

    from audio_score_tool.sheetsage2_score import _parse_vocal_abc

    seen = []
    original = abcFormat.ABCHandler.process
    def capture(self, text):
        seen.append(text)
        return original(self, text)
    monkeypatch.setattr(abcFormat.ABCHandler, 'process', capture)
    text = f'X:1\nM:4/4\nL:1/4\nK:C\n"{symbol}"C2"not Cm(maj7)"D2|\n'
    score = _parse_vocal_abc(text)
    assert '"not Cm(maj7)"' in seen[0]
    symbol = list(score.recurse().getElementsByClass(harmony.ChordSymbol))[0]
    assert symbol.chordKind == 'minor-major-seventh'
    assert symbol.root().pitchClass == root and symbol.bass().pitchClass == bass
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        path = Path(folder) / "chord.musicxml"
        score.write("musicxml", fp=str(path))
        restored = list(converter.parse(path).recurse().getElementsByClass(harmony.ChordSymbol))[0]
        assert restored.root().pitchClass == root and restored.bass().pitchClass == bass


def test_suspended_seventh_is_visible_in_verovio_and_pdf(tmp_path):
    from audio_score_tool.notation_backend import _verovio_toolkit, render_pdf

    (tmp_path / 'score.abc').write_text('X:1\nM:4/4\nL:1/4\nK:C\nV: Vocal\n"E7sus4"C4|]\n')
    (tmp_path / 'playback.json').write_text(json.dumps({'measures': [
        dict(start=0, end=2, score_start=0, score_end=1)]}))
    target = tmp_path / 'score.musicxml'
    import_native_lead_sheet(tmp_path, target)
    toolkit = _verovio_toolkit()
    assert toolkit.loadFile(str(target))
    svg = ET.fromstring(toolkit.renderToSVG(1))
    harmony_text = ["".join("".join(element.itertext()).split()).replace("\uea64", "♭")
                    for element in svg.iter() if "harm" in element.get("class", "").split()]
    assert harmony_text == ["Esus4(♭7)"]
    output = tmp_path / 'score.pdf'
    render_pdf(target, output)
    assert output.read_bytes().startswith(b'%PDF')


@pytest.mark.parametrize('suffix', ['', 'm', 'dim', 'aug', '7', 'maj7', 'm7', 'dim7', 'm7b5',
                                    'sus4', 'sus2', '6', 'm6', '7sus4', 'm(maj7)'])
def test_native_chords_survive_listing_and_unchanged_edit(tmp_path, suffix):
    from audio_score_tool.chord_editor import set_chord_at_note
    from audio_score_tool.chord_listing import list_chords

    (tmp_path / 'score.abc').write_text(f'X:1\nM:4/4\nL:1/4\nK:C\nV: Vocal\n"C{suffix}"C4|]\n')
    (tmp_path / 'playback.json').write_text(json.dumps({'measures': [
        dict(start=0, end=2, score_start=0, score_end=1)]}))
    target = tmp_path / 'score.musicxml'
    import_native_lead_sheet(tmp_path, target)

    def signature():
        symbol = list(converter.parse(target).recurse().getElementsByClass(harmony.ChordSymbol))[0]
        return symbol.root().pitchClass, symbol.bass().pitchClass, {p.pitchClass for p in symbol.pitches}

    before = signature()
    chord = list_chords(target)[0]
    if suffix == 'm7b5':
        assert chord['symbol'] == 'Cm7b5'
    if suffix == 'm(maj7)':
        assert chord['symbol'] == 'Cm(maj7)'
    set_chord_at_note(target, chord['note_id'], chord['symbol'])
    assert signature() == before
