from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from audio_score_tool.musicxml_editor import MusicXMLEditError
from audio_score_tool.score_structure import rhythm_edit

XML = '''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part>
<score-part id="P2"><part-name>Other</part-name></score-part></part-list><part id="P1"><measure number="1">
<attributes><divisions>4</divisions></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
<note><rest/><duration>4</duration><voice>1</voice><type>quarter</type></note>
<note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
</measure></part><part id="P2"><measure number="1"><attributes><divisions>4</divisions></attributes>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
</measure></part></score-partwise>'''


@pytest.fixture
def score(tmp_path: Path) -> Path:
    path = tmp_path / "score.musicxml"
    path.write_text(XML)
    return path


def notes(path: Path):
    return ET.parse(path).getroot().findall("./part/measure/note")


def test_split_maps_original_to_two_attacks_and_shifts_only_later_locators(score):
    result = rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    assert result["mapping"] == {"p0-m0-n0": ["p0-m0-n0", "p0-m0-n1"],
        "p0-m0-n1": ["p0-m0-n2"], "p0-m0-n2": ["p0-m0-n3"],
        "p0-m0-n3": ["p0-m0-n4"], "p1-m0-n0": ["p1-m0-n0"]}
    assert result["result_note_ids"] == ["p0-m0-n0", "p0-m0-n1"]
    written = notes(score)
    assert [int(n.findtext("duration")) for n in written] == [2, 2, 4, 4, 4, 4]
    assert [n.findtext("pitch/step") for n in written[:2]] == ["C", "C"]
    assert all(n.find("tie") is None for n in written[:2])


def test_merge_and_boundary_preserve_total_duration(score):
    result = rhythm_edit(score, "merge", ["p0-m0-n0", "p0-m0-n1"])
    assert result["mapping"]["p0-m0-n0"] == result["mapping"]["p0-m0-n1"] == ["p0-m0-n0"]
    assert result["mapping"]["p0-m0-n2"] == ["p0-m0-n1"]
    assert [int(n.findtext("duration")) for n in notes(score)] == [8, 4, 4, 4]
    result = rhythm_edit(score, "boundary", ["p0-m0-n0", "p0-m0-n1"],
                         left_note_type="quarter", left_dots=1)
    assert result["mapping"]["p0-m0-n0"] == ["p0-m0-n0"]
    assert result["mapping"]["p0-m0-n1"] == ["p0-m0-n1"]
    assert [int(n.findtext("duration")) for n in notes(score)] == [6, 6, 4, 4]
    assert notes(score)[1].find("rest") is not None


def test_delete_replaces_attack_with_equal_rest_without_inheriting_identity(score):
    result = rhythm_edit(score, "delete", ["p0-m0-n1"])
    assert result["mapping"]["p0-m0-n1"] == []
    assert result["mapping"]["p0-m0-n2"] == ["p0-m0-n2"]
    assert result["result_note_ids"] == ["p0-m0-n1"]
    assert notes(score)[1].find("rest") is not None
    assert notes(score)[1].findtext("duration") == "4"


def test_unaffected_lyric_and_tie_metadata_are_preserved(score):
    score.write_text(XML.replace('<step>D</step><octave>4</octave></pitch><duration>4</duration>',
                                 '<step>D</step><octave>4</octave></pitch><duration>4</duration><tie type="start"/>', 1)
                     .replace('<step>E</step><octave>4</octave></pitch>',
                              '<step>E</step><octave>4</octave></pitch><lyric><text>kept</text></lyric>', 1))
    result = rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    assert result["mapping"]["p0-m0-n3"] == ["p0-m0-n4"]
    assert result["mapping"]["p1-m0-n0"] == ["p1-m0-n0"]
    assert notes(score)[4].find("tie").get("type") == "start"
    assert notes(score)[5].findtext("lyric/text") == "kept"


@pytest.mark.parametrize("attribute", ['attack="1"', 'release="-1"'])
@pytest.mark.parametrize("action,ids,kwargs", [
    ("split", ["p0-m0-n0"], {"left_note_type": "eighth"}),
    ("merge", ["p0-m0-n0", "p0-m0-n1"], {}),
    ("boundary", ["p0-m0-n0", "p0-m0-n1"], {"left_note_type": "quarter"}),
    ("delete", ["p0-m0-n0"], {}),
])
def test_rhythm_edit_rejects_target_playback_offsets(score, attribute, action, ids, kwargs):
    score.write_text(XML.replace("<note>", f"<note {attribute}>", 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, action, ids, **kwargs)
    assert score.read_bytes() == before


@pytest.mark.parametrize("action,kwargs", [
    ("merge", {}),
    ("boundary", {"left_note_type": "quarter", "left_dots": 1}),
])
@pytest.mark.parametrize("target", [0, 1])
def test_rhythm_edit_rejects_styled_dot_without_writing(score, action, kwargs, target):
    original = '<duration>4</duration><voice>1</voice><type>quarter</type>'
    styled = '<duration>6</duration><voice>1</voice><type>quarter</type><dot placement="above"/>'
    xml = XML
    if target:
        first, remainder = xml.split(original, 1)
        xml = first + original + remainder.replace(original, styled, 1)
    else:
        xml = xml.replace(original, styled, 1)
    score.write_text(xml)
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, action, ["p0-m0-n0", "p0-m0-n1"], **kwargs)
    assert score.read_bytes() == before


def test_rhythm_edit_preserves_unaffected_playback_offsets_and_styled_dot(score):
    score.write_text(XML.replace('<note><pitch><step>D', '<note attack="1" release="-1"><pitch><step>D', 1)
                     .replace('<step>D</step><octave>4</octave></pitch><duration>4</duration>',
                              '<step>D</step><octave>4</octave></pitch><duration>6</duration>', 1)
                     .replace('<step>D</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>',
                              '<step>D</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type><dot color="#ff0000"/>', 1))
    rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    unaffected = notes(score)[4]
    assert unaffected.get("attack") == "1" and unaffected.get("release") == "-1"
    assert unaffected.find("dot").get("color") == "#ff0000"


def test_merge_rejects_first_note_repeat_playback_condition_without_writing(score):
    score.write_text(XML.replace("<note>", '<note time-only="2">', 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, "merge", ["p0-m0-n0", "p0-m0-n1"])
    assert score.read_bytes() == before


@pytest.mark.parametrize("change,action,ids,kwargs", [
    (('<voice>1</voice>', '<tie type="start"/><voice>1</voice>'), 'split', ['p0-m0-n0'], {'left_note_type': 'eighth'}),
    (('<voice>1</voice>', '<lyric><text>word</text></lyric><voice>1</voice>'), 'split', ['p0-m0-n0'], {'left_note_type': 'eighth'}),
    (('<voice>1</voice>', '<time-modification><actual-notes>3</actual-notes></time-modification><voice>1</voice>'), 'split', ['p0-m0-n0'], {'left_note_type': 'eighth'}),
    (('</note>\n<note>', '</note>\n<harmony><root><root-step>C</root-step></root><kind>major</kind></harmony><note>'), 'merge', ['p0-m0-n0', 'p0-m0-n1'], {}),
    (('</note>\n<note>', '</note><backup><duration>4</duration></backup>\n<note>'), 'merge', ['p0-m0-n0', 'p0-m0-n1'], {}),
    (('<step>C</step>', '<step>D</step>'), 'merge', ['p0-m0-n0', 'p0-m0-n1'], {}),
    (('<duration>4</duration>', '<duration>3</duration>'), 'split', ['p0-m0-n0'], {'left_note_type': 'eighth'}),
])
def test_unsafe_edits_fail_without_writing(score, change, action, ids, kwargs):
    score.write_text(XML.replace(*change, 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, action, ids, **kwargs)
    assert score.read_bytes() == before


def test_unrepresentable_remainder_refused(score):
    score.write_text(XML.replace('<duration>4</duration><voice>1</voice><type>quarter</type>',
                                 '<duration>16</duration><voice>1</voice><type>whole</type>', 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, 'split', ['p0-m0-n0'], left_note_type='quarter', left_dots=1)
    assert score.read_bytes() == before


@pytest.mark.parametrize("attribute", ['id="existing"', 'xml:id="existing"'])
def test_split_refuses_descendant_attributes_without_writing(score, attribute):
    score.write_text(XML.replace('<duration>4</duration>', f'<duration {attribute}>4</duration>', 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    assert score.read_bytes() == before


def test_split_preserves_note_style_without_duplicating_ids_or_coordinates(score):
    score.write_text(XML.replace('<note><pitch><step>C',
        '<note id="one" xml:id="unique" print-object="no" color="#ff0000" dynamics="50" '
        'default-x="10" relative-y="2"><pitch><step>C', 1))
    rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    first, second = notes(score)[:2]
    assert first.get("id") == "one" and first.get("{http://www.w3.org/XML/1998/namespace}id") == "unique"
    assert second.get("id") is None and second.get("{http://www.w3.org/XML/1998/namespace}id") is None
    assert second.get("default-x") is None and second.get("relative-y") is None
    assert {key: second.get(key) for key in ("print-object", "color", "dynamics")} == {
        "print-object": "no", "color": "#ff0000", "dynamics": "50"}


def test_split_and_merge_preserve_declared_instrument_reference(score):
    score.write_text(XML.replace(
        "<part-name>Voice</part-name>", '<part-name>Voice</part-name><score-instrument id="I1">'
        '<instrument-name>Piano</instrument-name></score-instrument>', 1
    ).replace("<duration>4</duration><voice>1</voice>", '<duration>4</duration><instrument id="I1"/><voice>1</voice>', 1))
    rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    assert [n.find("instrument").get("id") for n in notes(score)[:2]] == ["I1", "I1"]
    rhythm_edit(score, "merge", ["p0-m0-n0", "p0-m0-n1"])
    assert notes(score)[0].find("instrument").get("id") == "I1"


def test_split_refuses_undeclared_instrument_reference(score):
    score.write_text(XML.replace("<duration>4</duration><voice>1</voice>",
                                 '<duration>4</duration><instrument id="unknown"/><voice>1</voice>', 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, "split", ["p0-m0-n0"], left_note_type="eighth")
    assert score.read_bytes() == before


@pytest.mark.parametrize("attribute", ['id="existing"', 'xml:id="existing"'])
def test_delete_refuses_note_ids_without_writing(score, attribute):
    score.write_text(XML.replace('<note><pitch><step>C', f'<note {attribute}><pitch><step>C', 1))
    before = score.read_bytes()
    with pytest.raises(MusicXMLEditError):
        rhythm_edit(score, "delete", ["p0-m0-n0"])
    assert score.read_bytes() == before
