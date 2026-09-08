from pathlib import Path

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
