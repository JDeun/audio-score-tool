import xml.etree.ElementTree as ET
from pathlib import Path

from audio_score_tool.score_structure import (
    delete_measure,
    delete_note,
    insert_measure,
    insert_note,
    set_measure_signature,
    structure_summary,
    update_note_structure,
)

XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
    <score-part id="P2"><part-name>Piano</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths><mode>major</mode></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
  <part id="P2">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>0</fifths><mode>major</mode></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>A</step><octave>3</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>B</step><octave>3</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


def _score(tmp_path: Path) -> Path:
    path = tmp_path / "score.musicxml"
    path.write_text(XML, encoding="utf-8")
    return path


def _voice_measure_one_notes(root: ET.Element) -> list[ET.Element]:
    measure = root.find("./part[@id='P1']/measure[@number='1']")
    assert measure is not None
    return measure.findall("note")


def test_update_note_rhythm_and_expression(tmp_path: Path):
    path = _score(tmp_path)
    update_note_structure(
        path,
        "p0-m0-n0",
        {
            "type": "eighth",
            "dots": 1,
            "articulations": ["staccato", "accent"],
            "ties": ["start"],
            "slurs": ["start"],
            "beam": "begin",
        },
    )
    root = ET.parse(path).getroot()
    note = _voice_measure_one_notes(root)[0]
    assert note.findtext("duration") == "3"
    assert note.findtext("type") == "eighth"
    assert len(note.findall("dot")) == 1
    assert note.find("notations/articulations/staccato") is not None
    assert note.find("notations/articulations/accent") is not None
    assert note.find("notations/tied[@type='start']") is not None
    assert note.find("notations/slur[@type='start']") is not None
    assert note.findtext("beam") == "begin"


def test_convert_note_to_rest_and_back(tmp_path: Path):
    path = _score(tmp_path)
    update_note_structure(path, "p0-m0-n0", {"rest": True})
    root = ET.parse(path).getroot()
    note = _voice_measure_one_notes(root)[0]
    assert note.find("rest") is not None
    assert note.find("pitch") is None

    update_note_structure(path, "p0-m0-n0", {"rest": False})
    root = ET.parse(path).getroot()
    note = _voice_measure_one_notes(root)[0]
    assert note.find("rest") is None
    assert note.findtext("pitch/step") == "C"


def test_insert_and_delete_note(tmp_path: Path):
    path = _score(tmp_path)
    new_id = insert_note(
        path,
        "p0-m0-n0",
        position="after",
        step="F",
        alter=1,
        octave=5,
        note_type="eighth",
        dots=0,
        lyric="새",
    )
    assert new_id == "p0-m0-n1"
    root = ET.parse(path).getroot()
    notes = _voice_measure_one_notes(root)
    assert len(notes) == 3
    assert notes[1].findtext("pitch/step") == "F"
    assert notes[1].findtext("pitch/alter") == "1"
    assert notes[1].findtext("lyric/text") == "새"

    delete_note(path, new_id)
    root = ET.parse(path).getroot()
    assert len(_voice_measure_one_notes(root)) == 2


def test_insert_delete_measure_across_all_parts(tmp_path: Path):
    path = _score(tmp_path)
    new_index = insert_measure(path, 0)
    assert new_index == 1
    root = ET.parse(path).getroot()
    for part in root.findall("part"):
        measures = part.findall("measure")
        assert len(measures) == 3
        assert [measure.get("number") for measure in measures] == ["1", "2", "3"]
        assert measures[1].find("note/rest") is not None
        assert measures[1].findtext("note/duration") == "16"

    delete_measure(path, 1)
    root = ET.parse(path).getroot()
    assert all(len(part.findall("measure")) == 2 for part in root.findall("part"))


def test_signature_change_applies_to_every_part(tmp_path: Path):
    path = _score(tmp_path)
    set_measure_signature(
        path,
        1,
        fifths=-3,
        mode="minor",
        beats=6,
        beat_type=8,
    )
    root = ET.parse(path).getroot()
    for part in root.findall("part"):
        measure = part.findall("measure")[1]
        assert measure.findtext("attributes/key/fifths") == "-3"
        assert measure.findtext("attributes/key/mode") == "minor"
        assert measure.findtext("attributes/time/beats") == "6"
        assert measure.findtext("attributes/time/beat-type") == "8"

    summary = structure_summary(path)
    assert summary["measures"][1]["key_fifths"] == -3
    assert summary["measures"][1]["beats"] == 6
    assert summary["measures"][1]["beat_type"] == 8
