from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from audio_score_tool.auto_chords import apply_inferred_chords, infer_chords
from audio_score_tool.chord_listing import list_chords
from audio_score_tool.musicxml_parts import extract_part_musicxml, list_score_parts


def _score(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Piano</part-name></score-part>
    <score-part id="P2"><part-name>Electric Bass</part-name></score-part>
    <score-part id="P3"><part-name>Drums</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
      <note><chord/><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
      <note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
      <note><chord/><pitch><step>A</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
      <note><chord/><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>2</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>F</step><octave>2</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
    </measure>
  </part>
  <part id="P3">
    <measure number="1"><note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>1</duration></note></measure>
    <measure number="2"><note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched><duration>1</duration></note></measure>
  </part>
</score-partwise>
""",
        encoding="utf-8",
    )
    return path


def test_infers_and_writes_chords_from_multi_instrument_score(tmp_path: Path):
    score = _score(tmp_path / "score.musicxml")
    inferred = infer_chords(score)

    assert [item.symbol for item in inferred] == ["C", "F"]
    assert inferred[0].confidence >= 0.48

    applied = apply_inferred_chords(score, report_path=tmp_path / "chords.json")
    assert [item.symbol for item in applied] == ["C", "F"]
    assert [item["symbol"] for item in list_chords(score)] == ["C", "F"]
    assert (tmp_path / "chords.json").exists()


def test_drum_part_is_not_used_as_harmonic_source(tmp_path: Path):
    score = _score(tmp_path / "score.musicxml")
    inferred = infer_chords(score)
    assert inferred
    assert all(item.target_note_id and item.target_note_id.startswith("p0-") for item in inferred)


def test_extracts_editable_musicxml_per_detected_instrument(tmp_path: Path):
    score = _score(tmp_path / "score.musicxml")
    parts = list_score_parts(score)
    assert [part["name"] for part in parts] == ["Piano", "Electric Bass", "Drums"]

    target = tmp_path / "bass.musicxml"
    extract_part_musicxml(score, "P2", target)
    root = ET.parse(target).getroot()
    assert len(root.findall("part")) == 1
    assert root.find("part").get("id") == "P2"
    score_parts = root.findall("./part-list/score-part")
    assert len(score_parts) == 1
    assert score_parts[0].get("id") == "P2"
