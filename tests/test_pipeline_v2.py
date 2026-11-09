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


def test_sheetsage2_lead_sheet_preserves_native_analysis_without_demucs(tmp_path, monkeypatch):
    class LeadEngine(FakeEngine):
        key = "sheetsage2"

        def transcribe(self, audio, output_dir, **kwargs):
            artifacts = super().transcribe(audio, output_dir, **kwargs)
            (output_dir / "analysis.json").write_text(json.dumps({
                "chords": [{"time_seconds": 0, "label": "C:maj"}],
                "downbeats": [{"time_seconds": 0}],
                "meter": "3/4",
                "beats": [{"time_seconds": at, "beat": beat, "numerator": 3, "denominator": 4}
                          for at, beat in ((0, 1), (.5, 2), (1, 3), (1.5, 1))],
            }))
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
