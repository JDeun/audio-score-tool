from pathlib import Path

from audio_score_tool.lyrics import attach_lyrics_to_musicxml, expand_korean_syllables
from audio_score_tool.models import WordTiming

XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <direction><sound tempo="120"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""


def test_korean_word_expands_to_syllables():
    words = [WordTiming("사랑", 0.0, 1.0)]
    out = expand_korean_syllables(words)
    assert [x.text for x in out] == ["사", "랑"]
    assert out[0].start == 0.0
    assert out[-1].end == 1.0


def test_attach_lyrics(tmp_path: Path):
    source = tmp_path / "in.musicxml"
    target = tmp_path / "out.musicxml"
    source.write_text(XML, encoding="utf-8")

    words = [
        WordTiming("하", 0.0, 0.3),
        WordTiming("나", 0.5, 0.8),
        WordTiming("님", 1.0, 1.3),
    ]
    part_id, count = attach_lyrics_to_musicxml(source, target, words)

    assert part_id == "P1"
    assert count == 3
    text = target.read_text(encoding="utf-8")
    assert "<text>하</text>" in text
    assert "<text>나</text>" in text
    assert "<text>님</text>" in text
