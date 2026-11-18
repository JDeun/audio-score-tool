import json
from pathlib import Path

import pytest

from audio_score_tool import pipeline_v2
from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import TranscriptionArtifacts

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


class FakeEngine:
    key = "fake"
    display_name = "Fake"

    def transcribe(self, _audio, output_dir, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        midi = output_dir / "score.mid"
        xml = output_dir / "score.musicxml"
        pdf = output_dir / "full_score.pdf"
        midi.write_bytes(b"MThd")
        xml.write_text(MUSICXML, encoding="utf-8")
        pdf.write_bytes(b"%PDF")
        return TranscriptionArtifacts(midi, xml, pdf)


def test_transcription_defers_pdf_and_part_exports(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        pipeline_v2,
        "resolve_transcription_engine",
        lambda _settings: FakeEngine(),
    )

    result = pipeline_v2.transcribe(
        audio,
        tmp_path / "out",
        skip_lyrics=True,
        settings=Settings(),
    )

    assert result.musicxml_path.is_file()
    assert result.midi_path.is_file()
    assert result.pdf_path is None
    assert result.part_pdfs == []
    assert list(result.score_dir.rglob("*.pdf")) == []


@pytest.mark.parametrize("engine_key", ["sheetsage2", "vocal_lead_v1"])
def test_native_lead_preserves_audio_structure_without_outer_separation(tmp_path, monkeypatch, engine_key):
    class LeadEngine(FakeEngine):
        key = engine_key

        def transcribe(self, audio, output_dir, **kwargs):
            artifacts = super().transcribe(audio, output_dir, **kwargs)
            analysis = {
                "chords": [{"time_seconds": 0, "label": "C:maj"}],
                "downbeats": [{"time_seconds": 0}],
                "meter": "3/4",
                "beats": [{"time_seconds": at, "beat": beat, "numerator": 3, "denominator": 4}
                          for at, beat in ((0, 1), (.5, 2), (1, 3), (1.5, 1))],
            }
            if engine_key == "vocal_lead_v1":
                analysis.update(clock_provider="beat-this", nominal_tempo_bpm=120)
                (output_dir / "stems").mkdir()
                (output_dir / "stems/vocals.wav").write_bytes(b"vocal waveform")
                (output_dir / "interpretation.json").write_text(json.dumps({
                    "unrepresented_note_indices": [0,2]}))
            (output_dir / "analysis.json").write_text(json.dumps(analysis))
            return artifacts

    audio = tmp_path / "song.wav"
    audio.write_bytes(b"synthetic")
    monkeypatch.setattr(pipeline_v2, "resolve_transcription_engine", lambda _: LeadEngine())
    monkeypatch.setattr(pipeline_v2, "transcribe_selected_stems", lambda *a, **k: pytest.fail("must not separate"))
    monkeypatch.setattr(pipeline_v2, "apply_inferred_chords", lambda *a, **k: pytest.fail("must not replace native chords"))
    monkeypatch.setattr(pipeline_v2, "analyze_midi_meter_and_pickup", lambda *a: pytest.fail("must not infer tempo from padding MIDI"))
    result = pipeline_v2.transcribe(audio, tmp_path / "out", score_mode="lead_sheet",
                                    skip_lyrics=True, preserve_source_audio=False)
    assert json.loads(result.chord_report_path.read_text())["source"] == "sheetsage2"
    structure = json.loads(result.structure_report_path.read_text())
    assert structure["meter_source"] == "sheetsage2_audio_model"
    assert structure["tempo_bpm"] == 120
    assert structure["meter_numerator"] == 3
    expected_tempo_source = "beat_this_audio_grid" if engine_key == "vocal_lead_v1" else "sheetsage2_audio_grid"
    assert structure["tempo_source"] == expected_tempo_source
    if engine_key == "vocal_lead_v1":
        assert any("짧은 음표 2개" in warning for warning in result.warnings)
