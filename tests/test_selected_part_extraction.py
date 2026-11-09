from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from audio_score_tool.musicxml_parts import extract_part_musicxml, extract_parts_musicxml


def _note(duration: int, *, extra: str = "", voice: int = 1) -> str:
    return (
        f"<note>{extra}<pitch><step>C</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice><type>quarter</type>"
        "<notations><tied type='start'/></notations></note>"
    )


def _tempo(value: int, *, mark: bool = True, extra: str = "") -> str:
    direction_type = (
        f"<direction-type><metronome><beat-unit>quarter</beat-unit>"
        f"<per-minute>{value}</per-minute></metronome></direction-type>"
        if mark else "<direction-type><words>Tempo</words></direction-type>"
    )
    return f"<direction placement='above'>{direction_type}{extra}<sound tempo='{value}'/></direction>"


def _score(
    tmp_path: Path, *, first: str | None = None, second: str | None = None,
    part_list: str | None = None, namespace: str = "", other_parts: str = "",
) -> Path:
    if first is None:
        first = (
            "<measure number='1'><attributes><divisions>12</divisions>"
            "<key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type>"
            "</time><clef><sign>G</sign><line>2</line></clef></attributes>"
            + _tempo(120) + _note(48) + "</measure>"
        )
    if second is None:
        second = (
            "<measure number='1'><attributes><divisions>8</divisions>"
            "<key><fifths>2</fifths></key><time><beats>4</beats><beat-type>4</beat-type>"
            "</time><clef><sign>F</sign><line>4</line></clef>"
            "<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose>"
            "</attributes>" + _note(8, extra="<tie type='start'/>")
            + _note(8, extra="<chord/>")
            + "<backup><duration>8</duration></backup><forward><duration>4</duration></forward>"
            + _note(28, voice=2) + "</measure>"
        )
    if part_list is None:
        part_list = """
        <score-part id='P1'><part-name>Piano</part-name>
          <score-instrument id='I1'><instrument-name>Piano</instrument-name></score-instrument>
          <midi-instrument id='I1'><midi-channel>1</midi-channel><midi-program>1</midi-program></midi-instrument>
        </score-part>
        <score-part id='P2'><part-name>Clarinet</part-name>
          <score-instrument id='I2'><instrument-name>Clarinet</instrument-name></score-instrument>
          <midi-instrument id='I2'><midi-channel>2</midi-channel><midi-program>72</midi-program></midi-instrument>
        </score-part>
        <score-part id='P3'><part-name>Guitar</part-name>
          <midi-instrument id='I3'><midi-channel>3</midi-channel><midi-program>25</midi-program></midi-instrument>
        </score-part>
        """
    path = tmp_path / "source.musicxml"
    path.write_text(
        f"<score-partwise version='4.0'{namespace}><work><work-title>Original title</work-title>"
        "</work><identification><creator type='composer'>Original composer</creator>"
        "</identification><credit page='1'><credit-words>Original credit</credit-words></credit>"
        f"<part-list>{part_list}</part-list><part id='P1'>{first}</part>"
        f"<part id='P2'>{second}</part><part id='P3'>{second}</part>{other_parts}</score-partwise>",
        encoding="utf-8",
    )
    return path


def _canonical(element: ET.Element) -> str:
    return ET.canonicalize(ET.tostring(element, encoding="unicode"), strip_text=True)


@pytest.mark.parametrize("namespace", ["", " xmlns='http://www.musicxml.org/ns/musicxml'"])
def test_subset_preserves_score_order_metadata_gm_and_exact_notation(tmp_path: Path, namespace: str):
    source = _score(tmp_path, namespace=namespace)
    before = source.read_bytes()
    original = ET.parse(source).getroot()
    ns = "{http://www.musicxml.org/ns/musicxml}" if namespace else ""
    target = tmp_path / "selected.musicxml"
    extract_parts_musicxml(source, ["P3", "P2"], target)
    result = ET.parse(target).getroot()
    assert source.read_bytes() == before
    assert [p.get("id") for p in result.findall(f"{ns}part")] == ["P2", "P3"]
    assert [p.get("id") for p in result.findall(f"{ns}part-list/{ns}score-part")] == ["P2", "P3"]
    for tag in ["work", "identification", "credit"]:
        assert _canonical(result.find(ns + tag)) == _canonical(original.find(ns + tag))
    for part_id in ["P2", "P3"]:
        original_part = original.find(f"{ns}part[@id='{part_id}']")
        result_part = result.find(f"{ns}part[@id='{part_id}']")
        for tag in ["note", "backup", "forward", "attributes"]:
            assert [_canonical(x) for x in result_part.iter(ns + tag)] == [
                _canonical(x) for x in original_part.iter(ns + tag)
            ]
        assert _canonical(result.find(f"{ns}part-list/{ns}score-part[@id='{part_id}']")) == _canonical(
            original.find(f"{ns}part-list/{ns}score-part[@id='{part_id}']"),
        )
    assert result.find(f"{ns}part[@id='P2']/{ns}measure/{ns}direction/{ns}sound").get("tempo") == "120"


@pytest.mark.parametrize("part_ids", [[], ["P2", "P2"], ["missing"], [""], [None], "P2"])
def test_invalid_selection_does_not_write_or_create_output_directory(tmp_path: Path, part_ids):
    source = _score(tmp_path)
    target = tmp_path / "new" / "selected.musicxml"
    with pytest.raises(ValueError):
        extract_parts_musicxml(source, part_ids, target)
    assert not target.parent.exists()


def test_preserves_only_complete_groups_with_at_least_two_retained_members(tmp_path: Path):
    source = _score(tmp_path, part_list="""
      <part-group number='1' type='start'><group-symbol>bracket</group-symbol></part-group>
      <score-part id='P1'><part-name>Piano</part-name></score-part>
      <part-group number='2' type='start'><group-symbol>brace</group-symbol></part-group>
      <part-group number='3' type='start'/>
      <score-part id='P2'><part-name>Clarinet</part-name></score-part>
      <part-group number='3' type='stop'/>
      <part-group number='4' type='start'/><part-group number='4' type='start'/>
      <score-part id='P3'><part-name>Guitar</part-name></score-part>
      <part-group number='4' type='stop'/>
      <part-group number='2' type='stop'/><part-group number='1' type='stop'/>
      <part-group number='5' type='start'/><part-group number='6' type='stop'/>
    """)
    target = tmp_path / "grouped.musicxml"
    extract_parts_musicxml(source, ["P3", "P2"], target)
    root = ET.parse(target).getroot()
    assert [(g.get("number"), g.get("type")) for g in root.findall("part-list/part-group")] == [
        ("1", "start"), ("2", "start"), ("2", "stop"), ("1", "stop"),
    ]
    extract_part_musicxml(source, "P2", target)
    assert not ET.parse(target).getroot().findall("part-list/part-group")


def test_first_part_retained_does_not_rewrite_existing_tempo(tmp_path: Path):
    source = _score(tmp_path)
    target = tmp_path / "subset.musicxml"
    extract_parts_musicxml(source, ["P3", "P1"], target)
    assert _canonical(ET.parse(target).getroot().find("part[@id='P1']")) == _canonical(
        ET.parse(source).getroot().find("part[@id='P1']"),
    )


def test_copies_tempos_at_exact_offsets_with_backups_and_different_divisions(tmp_path: Path):
    first = (
        "<measure number='1'><attributes><divisions>12</divisions></attributes>"
        + _tempo(120) + _note(12) + _note(12, extra="<chord/>")
        + _tempo(90, extra="<offset>6</offset><voice>7</voice><staff>2</staff>")
        + "<forward><duration>12</duration></forward><backup><duration>12</duration></backup>"
        + "<direction><direction-type><words>Rit.</words></direction-type>"
        "<sound tempo='60' dynamics='20'><offset>3</offset></sound></direction>"
        + _note(36) + "</measure>"
    )
    source = _score(tmp_path, first=first)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    root = ET.parse(target).getroot()
    directions = {d.find("sound").get("tempo"): d for d in root.findall("part/measure/direction")}
    assert len(directions) == 3
    shifted = directions["90"]
    # Visual offset is 1.5 quarters; playback defaults to the source cursor at 1 quarter.
    assert shifted.findtext("offset") == "12"
    assert shifted.findtext("sound/offset") == "8"
    assert shifted.find("voice") is None and shifted.find("staff") is None
    assert directions["60"].findtext("offset") == "8"
    assert directions["60"].findtext("sound/offset") == "10"
    assert directions["60"].find("sound").get("dynamics") is None


def test_sound_yes_offset_and_standalone_sound_retain_playback_position(tmp_path: Path):
    first = (
        "<measure number='1'><attributes><divisions>12</divisions></attributes>"
        + _note(12) + _tempo(80, extra="<offset sound='yes'>6</offset>")
        + "<sound tempo='100'><offset>3</offset></sound>" + _note(36) + "</measure>"
    )
    source = _score(tmp_path, first=first)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    measure = ET.parse(target).getroot().find("part/measure")
    assert measure.findtext("direction/offset") == "12"
    assert measure.findtext("direction/sound/offset") == "12"
    assert measure.findtext("sound/offset") == "10"


def test_triplet_tempo_uses_exact_temporary_divisions_without_changing_notes(tmp_path: Path):
    first = (
        "<measure number='1'><attributes><divisions>3</divisions></attributes>"
        + _note(1) + _tempo(100) + _note(11) + "</measure>"
    )
    second = "<measure number='1'><attributes><divisions>1</divisions></attributes>" + _note(4) + "</measure>"
    source = _score(tmp_path, first=first, second=second)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    measure = ET.parse(target).getroot().find("part/measure")
    assert [a.findtext("divisions") for a in measure.findall("attributes")] == ["1", "3", "1"]
    assert measure.findtext("direction/offset") == "1"
    assert measure.findtext("direction/sound/offset") == "1"
    assert measure.findtext("note/duration") == "4"
    assert [node.tag for node in measure] == ["attributes", "attributes", "direction", "attributes", "note"]


def test_later_measure_tempo_uses_inherited_divisions_and_local_position(tmp_path: Path):
    source = _score(tmp_path)
    tree = ET.parse(source)
    root = tree.getroot()
    for part in root.findall("part"):
        amount = 12 if part.get("id") == "P1" else 8
        measure = ET.SubElement(part, "measure", number="2")
        measure.append(ET.fromstring(_note(amount)))
        if part.get("id") == "P1":
            measure.append(ET.fromstring(_tempo(100)))
        measure.append(ET.fromstring(_note(amount * 3)))
    tree.write(source)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    second = ET.parse(target).getroot().find("part/measure[@number='2']")
    assert second.findtext("direction/offset") == "8"
    assert second.findtext("direction/sound/offset") == "8"


def test_existing_equivalent_tempo_and_metronome_are_not_duplicated(tmp_path: Path):
    source = _score(tmp_path)
    tree = ET.parse(source)
    measure = tree.getroot().find("part[@id='P2']/measure")
    tempo = ET.fromstring(_tempo(120))
    tempo.find("direction-type/metronome/beat-unit").text = "half"
    tempo.find("direction-type/metronome/per-minute").text = "60"
    measure.insert(1, tempo)
    tree.write(source)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    root = ET.parse(target).getroot()
    assert len(root.findall(".//sound[@tempo='120']")) == 1
    assert len(root.findall(".//metronome")) == 1
    assert root.findtext(".//metronome/beat-unit") == "half"


def test_sound_already_present_still_receives_missing_visible_metronome(tmp_path: Path):
    source = _score(tmp_path)
    tree = ET.parse(source)
    tree.getroot().find("part[@id='P2']/measure").insert(1, ET.fromstring("<sound tempo='120'/>"))
    tree.write(source)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    root = ET.parse(target).getroot()
    assert len(root.findall(".//sound[@tempo='120']")) == 1
    assert len(root.findall(".//metronome")) == 1


@pytest.mark.parametrize("problem", ["number", "missing_measure", "too_short", "no_divisions", "conflict"])
def test_unalignable_or_conflicting_tempo_does_not_replace_target(tmp_path: Path, problem: str):
    source = _score(tmp_path)
    tree = ET.parse(source)
    root = tree.getroot()
    selected = root.find("part[@id='P2']")
    measure = selected.find("measure")
    if problem == "number":
        measure.set("number", "2")
    elif problem == "missing_measure":
        selected.remove(measure)
    elif problem == "too_short":
        first_measure = root.find("part[@id='P1']/measure")
        first_measure.append(ET.fromstring(_tempo(100)))
        for node in list(measure):
            if node.tag != "attributes":
                measure.remove(node)
        measure.append(ET.fromstring(_note(8)))
    elif problem == "no_divisions":
        attributes = measure.find("attributes")
        attributes.remove(attributes.find("divisions"))
    else:
        measure.insert(1, ET.fromstring(_tempo(90)))
    tree.write(source)
    target = tmp_path / "subset.musicxml"
    target.write_text("previous successful export", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_part_musicxml(source, "P2", target)
    assert target.read_text() == "previous successful export"
    assert not target.with_suffix(".musicxml.tmp").exists()


def test_legacy_single_part_without_tempo_needs_no_new_timing_assumptions(tmp_path: Path):
    first = "<measure number='1'>" + _note(4) + "</measure>"
    second = "<measure number='1'>" + _note(1) + "</measure>"
    source = _score(tmp_path, first=first, second=second)
    target = tmp_path / "subset.musicxml"
    extract_part_musicxml(source, "P2", target)
    assert _canonical(ET.parse(target).getroot().find("part")) == _canonical(
        ET.parse(source).getroot().find("part[@id='P2']"),
    )
