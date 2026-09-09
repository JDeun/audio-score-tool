from pathlib import Path

from audio_score_tool.notation_backend import (
    backend_status,
    render_pdf,
)

SIMPLE_SCORE = """<?xml version='1.0' encoding='UTF-8'?>
<score-partwise version='4.0'>
  <part-list>
    <score-part id='P1'><part-name>Piano</part-name></score-part>
  </part-list>
  <part id='P1'>
    <measure number='1'>
      <attributes>
        <divisions>1</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def test_backend_status_has_only_embedded_notation_dependencies(monkeypatch):
    monkeypatch.setattr("audio_score_tool.notation_backend.music21_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.verovio_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.fpdf2_available", lambda: True)

    status = backend_status()

    assert status == {"music21": True, "verovio": True, "fpdf2": True}
    assert "musescore" not in status
    assert "lilypond" not in status
    assert "musicxml2ly" not in status


def test_render_pdf_is_self_contained(tmp_path: Path):
    source = tmp_path / "score.musicxml"
    source.write_text(SIMPLE_SCORE, encoding="utf-8")
    target = tmp_path / "score.pdf"

    result, renderer = render_pdf(source, target)

    assert result == target
    assert renderer == "verovio-fpdf2"
    assert target.read_bytes().startswith(b"%PDF-")
    assert target.stat().st_size > 500
    assert not list(tmp_path.glob("*.ly"))
