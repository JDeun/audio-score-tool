from __future__ import annotations

import copy
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal

from .musicxml_editor import MusicXMLEditError, parse_note_id

_NOTE_QUARTERS = {
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
}
_ARTICULATIONS = {"staccato", "tenuto", "accent", "strong-accent"}
_BEAMS = {"begin", "continue", "end", "forward hook", "backward hook"}
_ATTRIBUTE_ORDER = [
    "divisions",
    "key",
    "time",
    "staves",
    "part-symbol",
    "instruments",
    "clef",
    "staff-details",
    "transpose",
    "directive",
    "measure-style",
]


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _write(tree: ET.ElementTree, path: Path) -> None:
    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    temp = path.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)


def _find_note_context(
    root: ET.Element,
    note_id: str,
) -> tuple[ET.Element, ET.Element, ET.Element, int, int, int, str]:
    part_index, measure_index, note_index = parse_note_id(note_id)
    ns = _namespace(root)
    parts = root.findall(f"{ns}part")
    if part_index >= len(parts):
        raise MusicXMLEditError(f"Part not found for note id: {note_id}")
    part = parts[part_index]
    measures = part.findall(f"{ns}measure")
    if measure_index >= len(measures):
        raise MusicXMLEditError(f"Measure not found for note id: {note_id}")
    measure = measures[measure_index]
    notes = measure.findall(f"{ns}note")
    if note_index >= len(notes):
        raise MusicXMLEditError(f"Note not found for note id: {note_id}")
    return part, measure, notes[note_index], part_index, measure_index, note_index, ns


def _text_int(node: ET.Element | None, default: int) -> int:
    if node is None or not node.text:
        return default
    try:
        return int(node.text)
    except ValueError:
        return default


def _effective_attributes(part: ET.Element, measure_index: int, ns: str) -> dict[str, Any]:
    divisions = 1
    beats = 4
    beat_type = 4
    fifths = 0
    mode = "major"
    latest_attributes: ET.Element | None = None
    measures = part.findall(f"{ns}measure")
    for measure in measures[: measure_index + 1]:
        attrs = measure.find(f"{ns}attributes")
        if attrs is None:
            continue
        latest_attributes = attrs
        divisions = _text_int(attrs.find(f"{ns}divisions"), divisions)
        key = attrs.find(f"{ns}key")
        if key is not None:
            fifths = _text_int(key.find(f"{ns}fifths"), fifths)
            mode_node = key.find(f"{ns}mode")
            if mode_node is not None and mode_node.text:
                mode = mode_node.text
        time = attrs.find(f"{ns}time")
        if time is not None:
            beats = _text_int(time.find(f"{ns}beats"), beats)
            beat_type = _text_int(time.find(f"{ns}beat-type"), beat_type)
    return {
        "divisions": max(1, divisions),
        "beats": max(1, beats),
        "beat_type": max(1, beat_type),
        "fifths": fifths,
        "mode": mode,
        "attributes": latest_attributes,
    }


def _duration_for_type(divisions: int, note_type: str, dots: int) -> int:
    if note_type not in _NOTE_QUARTERS:
        raise MusicXMLEditError(f"지원하지 않는 음표 길이입니다: {note_type}")
    if dots < 0 or dots > 2:
        raise MusicXMLEditError("점음표는 0-2개만 지원합니다.")
    multiplier = 1.0 if dots == 0 else 2.0 - 0.5**dots
    value = divisions * _NOTE_QUARTERS[note_type] * multiplier
    rounded = int(round(value))
    if rounded < 1 or not math.isclose(value, rounded, rel_tol=0, abs_tol=0.05):
        raise MusicXMLEditError(
            "현재 MusicXML divisions로 이 음표 길이를 정확히 표현할 수 없습니다."
        )
    return rounded


def _insert_before(parent: ET.Element, child: ET.Element, before_tags: set[str]) -> None:
    for index, existing in enumerate(list(parent)):
        if existing.tag in before_tags:
            parent.insert(index, child)
            return
    parent.append(child)


def _insert_attribute_child(attrs: ET.Element, child: ET.Element) -> None:
    target_name = _local_name(child.tag)
    target_order = _ATTRIBUTE_ORDER.index(target_name)
    for index, existing in enumerate(list(attrs)):
        name = _local_name(existing.tag)
        if name in _ATTRIBUTE_ORDER and _ATTRIBUTE_ORDER.index(name) > target_order:
            attrs.insert(index, child)
            return
    attrs.append(child)


def _ensure_notations(note: ET.Element, ns: str) -> ET.Element:
    node = note.find(f"{ns}notations")
    if node is not None:
        return node
    node = ET.Element(f"{ns}notations")
    _insert_before(note, node, {f"{ns}lyric", f"{ns}play", f"{ns}listen"})
    return node


def _cleanup_empty_notations(note: ET.Element, ns: str) -> None:
    node = note.find(f"{ns}notations")
    if node is not None and len(node) == 0:
        note.remove(node)


def _set_pitch_or_rest(
    note: ET.Element,
    ns: str,
    *,
    rest: bool,
    step: str = "C",
    alter: int = 0,
    octave: int = 4,
) -> None:
    for tag in (f"{ns}pitch", f"{ns}rest", f"{ns}unpitched"):
        node = note.find(tag)
        if node is not None:
            note.remove(node)

    if rest:
        rest_node = ET.Element(f"{ns}rest")
        _insert_before(note, rest_node, {f"{ns}duration", f"{ns}tie", f"{ns}voice"})
        return

    step = step.upper().strip()
    if step not in {"A", "B", "C", "D", "E", "F", "G"}:
        raise MusicXMLEditError("step은 A-G 중 하나여야 합니다.")
    if alter < -2 or alter > 2:
        raise MusicXMLEditError("alter는 -2에서 2 사이만 지원합니다.")
    if octave < 0 or octave > 9:
        raise MusicXMLEditError("octave는 0에서 9 사이여야 합니다.")

    pitch = ET.Element(f"{ns}pitch")
    ET.SubElement(pitch, f"{ns}step").text = step
    if alter:
        ET.SubElement(pitch, f"{ns}alter").text = str(alter)
    ET.SubElement(pitch, f"{ns}octave").text = str(octave)
    _insert_before(note, pitch, {f"{ns}duration", f"{ns}tie", f"{ns}voice"})


def _set_note_type_and_dots(
    note: ET.Element,
    ns: str,
    *,
    divisions: int,
    note_type: str,
    dots: int,
) -> None:
    duration = _duration_for_type(divisions, note_type, dots)
    duration_node = note.find(f"{ns}duration")
    if duration_node is None:
        duration_node = ET.Element(f"{ns}duration")
        _insert_before(note, duration_node, {f"{ns}tie", f"{ns}voice"})
    duration_node.text = str(duration)

    type_node = note.find(f"{ns}type")
    if type_node is None:
        type_node = ET.Element(f"{ns}type")
        _insert_before(
            note,
            type_node,
            {
                f"{ns}dot",
                f"{ns}accidental",
                f"{ns}staff",
                f"{ns}beam",
                f"{ns}notations",
                f"{ns}lyric",
            },
        )
    type_node.text = note_type

    for dot in list(note.findall(f"{ns}dot")):
        note.remove(dot)
    type_index = list(note).index(type_node)
    for offset in range(dots):
        note.insert(type_index + 1 + offset, ET.Element(f"{ns}dot"))


def _set_articulations(note: ET.Element, ns: str, values: list[str]) -> None:
    invalid = [value for value in values if value not in _ARTICULATIONS]
    if invalid:
        raise MusicXMLEditError(f"지원하지 않는 아티큘레이션: {', '.join(invalid)}")
    notations = _ensure_notations(note, ns)
    articulations = notations.find(f"{ns}articulations")
    if articulations is not None:
        notations.remove(articulations)
    if values:
        articulations = ET.Element(f"{ns}articulations")
        for value in values:
            ET.SubElement(articulations, f"{ns}{value}")
        notations.append(articulations)
    _cleanup_empty_notations(note, ns)


def _set_ties(note: ET.Element, ns: str, values: list[str]) -> None:
    normalized = list(dict.fromkeys(values))
    if any(value not in {"start", "stop"} for value in normalized):
        raise MusicXMLEditError("tie는 start/stop만 지원합니다.")
    for tie in list(note.findall(f"{ns}tie")):
        note.remove(tie)
    duration = note.find(f"{ns}duration")
    insert_index = list(note).index(duration) + 1 if duration is not None else 0
    for offset, value in enumerate(normalized):
        note.insert(insert_index + offset, ET.Element(f"{ns}tie", {"type": value}))

    notations = _ensure_notations(note, ns)
    for tied in list(notations.findall(f"{ns}tied")):
        notations.remove(tied)
    for value in normalized:
        ET.SubElement(notations, f"{ns}tied", {"type": value})
    _cleanup_empty_notations(note, ns)


def _set_slurs(note: ET.Element, ns: str, values: list[str]) -> None:
    normalized = list(dict.fromkeys(values))
    if any(value not in {"start", "stop"} for value in normalized):
        raise MusicXMLEditError("slur는 start/stop만 지원합니다.")
    notations = _ensure_notations(note, ns)
    for slur in list(notations.findall(f"{ns}slur")):
        notations.remove(slur)
    for value in normalized:
        ET.SubElement(notations, f"{ns}slur", {"type": value, "number": "1"})
    _cleanup_empty_notations(note, ns)


def _set_beam(note: ET.Element, ns: str, value: str | None) -> None:
    for beam in list(note.findall(f"{ns}beam")):
        note.remove(beam)
    if not value:
        return
    if value not in _BEAMS:
        raise MusicXMLEditError(f"지원하지 않는 beam 값입니다: {value}")
    beam = ET.Element(f"{ns}beam", {"number": "1"})
    beam.text = value
    _insert_before(note, beam, {f"{ns}notations", f"{ns}lyric", f"{ns}play", f"{ns}listen"})


def update_note_structure(path: Path, note_id: str, patch: dict[str, Any]) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    part, _measure, note, _pi, measure_index, _ni, ns = _find_note_context(root, note_id)
    attrs = _effective_attributes(part, measure_index, ns)

    note_type = str(patch.get("type") or (note.findtext(f"{ns}type") or "quarter"))
    dots = int(patch.get("dots", len(note.findall(f"{ns}dot"))))
    if "type" in patch or "dots" in patch:
        _set_note_type_and_dots(
            note,
            ns,
            divisions=int(attrs["divisions"]),
            note_type=note_type,
            dots=dots,
        )

    if "rest" in patch:
        current_pitch = note.find(f"{ns}pitch")
        step = current_pitch.findtext(f"{ns}step", "C") if current_pitch is not None else "C"
        alter = _text_int(current_pitch.find(f"{ns}alter") if current_pitch is not None else None, 0)
        octave = _text_int(current_pitch.find(f"{ns}octave") if current_pitch is not None else None, 4)
        _set_pitch_or_rest(
            note,
            ns,
            rest=bool(patch["rest"]),
            step=step,
            alter=alter,
            octave=octave,
        )

    if "articulations" in patch:
        _set_articulations(note, ns, [str(value) for value in patch["articulations"]])
    if "ties" in patch:
        _set_ties(note, ns, [str(value) for value in patch["ties"]])
    if "slurs" in patch:
        _set_slurs(note, ns, [str(value) for value in patch["slurs"]])
    if "beam" in patch:
        _set_beam(note, ns, str(patch["beam"]) if patch["beam"] else None)

    _write(tree, path)


def insert_note(
    path: Path,
    anchor_note_id: str,
    *,
    position: Literal["before", "after"] = "after",
    rest: bool = False,
    step: str = "C",
    alter: int = 0,
    octave: int = 4,
    note_type: str = "quarter",
    dots: int = 0,
    lyric: str = "",
) -> str:
    tree = ET.parse(path)
    root = tree.getroot()
    part, measure, anchor, part_index, measure_index, note_index, ns = _find_note_context(
        root, anchor_note_id
    )
    attrs = _effective_attributes(part, measure_index, ns)

    new_note = ET.Element(f"{ns}note")
    _set_pitch_or_rest(
        new_note,
        ns,
        rest=rest,
        step=step,
        alter=int(alter),
        octave=int(octave),
    )
    voice = anchor.find(f"{ns}voice")
    if voice is not None and voice.text:
        ET.SubElement(new_note, f"{ns}voice").text = voice.text
    staff = anchor.find(f"{ns}staff")
    if staff is not None and staff.text:
        ET.SubElement(new_note, f"{ns}staff").text = staff.text
    _set_note_type_and_dots(
        new_note,
        ns,
        divisions=int(attrs["divisions"]),
        note_type=note_type,
        dots=dots,
    )
    if lyric:
        lyric_node = ET.SubElement(new_note, f"{ns}lyric")
        ET.SubElement(lyric_node, f"{ns}syllabic").text = "single"
        ET.SubElement(lyric_node, f"{ns}text").text = lyric

    children = list(measure)
    anchor_pos = children.index(anchor)
    insert_pos = anchor_pos if position == "before" else anchor_pos + 1
    measure.insert(insert_pos, new_note)
    _write(tree, path)

    new_index = note_index if position == "before" else note_index + 1
    return f"p{part_index}-m{measure_index}-n{new_index}"


def delete_note(path: Path, note_id: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    _part, measure, note, _pi, _mi, _ni, ns = _find_note_context(root, note_id)
    if len(measure.findall(f"{ns}note")) <= 1:
        raise MusicXMLEditError(
            "마디의 마지막 음표는 바로 삭제할 수 없습니다. 마디를 삭제하거나 쉼표로 바꾸세요."
        )
    measure.remove(note)
    _write(tree, path)


def _renumber_measures(root: ET.Element, ns: str) -> None:
    for part in root.findall(f"{ns}part"):
        for index, measure in enumerate(part.findall(f"{ns}measure"), start=1):
            measure.set("number", str(index))


def insert_measure(path: Path, after_measure_index: int) -> int:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    parts = root.findall(f"{ns}part")
    if not parts:
        raise MusicXMLEditError("악보에 파트가 없습니다.")

    target_index = max(0, after_measure_index + 1)
    for part in parts:
        measures = part.findall(f"{ns}measure")
        if after_measure_index < 0 or after_measure_index >= len(measures):
            raise MusicXMLEditError("마디 위치가 범위를 벗어났습니다.")
        attrs = _effective_attributes(part, after_measure_index, ns)
        new_measure = ET.Element(f"{ns}measure", {"number": str(target_index + 1)})
        latest_attrs = attrs.get("attributes")
        if latest_attrs is not None:
            new_measure.append(copy.deepcopy(latest_attrs))
        rest_note = ET.SubElement(new_measure, f"{ns}note")
        ET.SubElement(rest_note, f"{ns}rest", {"measure": "yes"})
        measure_quarters = int(attrs["beats"]) * 4.0 / int(attrs["beat_type"])
        ET.SubElement(rest_note, f"{ns}duration").text = str(
            max(1, int(round(int(attrs["divisions"]) * measure_quarters)))
        )
        ET.SubElement(rest_note, f"{ns}voice").text = "1"
        part.insert(target_index, new_measure)

    _renumber_measures(root, ns)
    _write(tree, path)
    return target_index


def delete_measure(path: Path, measure_index: int) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    parts = root.findall(f"{ns}part")
    if not parts:
        raise MusicXMLEditError("악보에 파트가 없습니다.")
    for part in parts:
        measures = part.findall(f"{ns}measure")
        if len(measures) <= 1:
            raise MusicXMLEditError("악보의 마지막 마디는 삭제할 수 없습니다.")
        if measure_index < 0 or measure_index >= len(measures):
            raise MusicXMLEditError("마디 위치가 범위를 벗어났습니다.")
        part.remove(measures[measure_index])
    _renumber_measures(root, ns)
    _write(tree, path)


def _ensure_attributes(measure: ET.Element, ns: str) -> ET.Element:
    attrs = measure.find(f"{ns}attributes")
    if attrs is not None:
        return attrs
    attrs = ET.Element(f"{ns}attributes")
    measure.insert(0, attrs)
    return attrs


def _ensure_attribute_node(attrs: ET.Element, ns: str, name: str) -> ET.Element:
    node = attrs.find(f"{ns}{name}")
    if node is not None:
        return node
    node = ET.Element(f"{ns}{name}")
    _insert_attribute_child(attrs, node)
    return node


def set_measure_signature(
    path: Path,
    measure_index: int,
    *,
    fifths: int | None = None,
    mode: str | None = None,
    beats: int | None = None,
    beat_type: int | None = None,
) -> None:
    if fifths is not None and not -7 <= fifths <= 7:
        raise MusicXMLEditError("조표 fifths는 -7에서 7 사이여야 합니다.")
    if mode is not None and mode not in {"major", "minor"}:
        raise MusicXMLEditError("조성 mode는 major/minor만 지원합니다.")
    if beats is not None and not 1 <= beats <= 32:
        raise MusicXMLEditError("박자 분자는 1-32 범위여야 합니다.")
    if beat_type is not None and beat_type not in {1, 2, 4, 8, 16, 32}:
        raise MusicXMLEditError("박자 분모는 1, 2, 4, 8, 16, 32 중 하나여야 합니다.")

    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    for part in root.findall(f"{ns}part"):
        measures = part.findall(f"{ns}measure")
        if measure_index < 0 or measure_index >= len(measures):
            raise MusicXMLEditError("마디 위치가 범위를 벗어났습니다.")
        attrs = _ensure_attributes(measures[measure_index], ns)

        if fifths is not None or mode is not None:
            key = _ensure_attribute_node(attrs, ns, "key")
            if fifths is not None:
                fifths_node = key.find(f"{ns}fifths")
                if fifths_node is None:
                    fifths_node = ET.Element(f"{ns}fifths")
                    key.insert(0, fifths_node)
                fifths_node.text = str(fifths)
            if mode is not None:
                mode_node = key.find(f"{ns}mode")
                if mode_node is None:
                    mode_node = ET.SubElement(key, f"{ns}mode")
                mode_node.text = mode

        if beats is not None or beat_type is not None:
            time = _ensure_attribute_node(attrs, ns, "time")
            if beats is not None:
                beats_node = time.find(f"{ns}beats")
                if beats_node is None:
                    beats_node = ET.SubElement(time, f"{ns}beats")
                beats_node.text = str(beats)
            if beat_type is not None:
                beat_node = time.find(f"{ns}beat-type")
                if beat_node is None:
                    beat_node = ET.SubElement(time, f"{ns}beat-type")
                beat_node.text = str(beat_type)

    _write(tree, path)


def structure_summary(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    parts = root.findall(f"{ns}part")
    if not parts:
        return {"measures": []}
    part = parts[0]
    measures: list[dict[str, Any]] = []
    for index, measure in enumerate(part.findall(f"{ns}measure")):
        attrs = _effective_attributes(part, index, ns)
        measures.append(
            {
                "measure_index": index,
                "number": measure.get("number") or str(index + 1),
                "divisions": attrs["divisions"],
                "key_fifths": attrs["fifths"],
                "key_mode": attrs["mode"],
                "beats": attrs["beats"],
                "beat_type": attrs["beat_type"],
            }
        )
    return {"measures": measures}
