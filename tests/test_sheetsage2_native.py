"""Pinned official protocol and notated vocal import; synthetic inputs only."""
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace

import pytest
from music21 import converter, harmony, key, meter, note, tempo

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
    assert len(xml.findall(".//metronome[@print-object='no']")) == 1
    assert len(xml.findall(".//sound[@tempo]")) == 2
    from audio_score_tool.notation_backend import _verovio_toolkit

    toolkit = _verovio_toolkit()
    assert toolkit.loadFile(str(target))
    svg = ET.fromstring(toolkit.renderToSVG(1))
    assert len([g for g in svg.iter()
                if "tempo" in g.get("class", "").split() and "".join(g.itertext()).strip()]) == 1


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


def test_pickup_padding_uses_audio_span_without_stretching_rest(tmp_path):
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
