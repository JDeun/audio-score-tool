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


def rhythm_edit(
    path: Path,
    action: str,
    note_ids: list[str],
    *,
    left_note_type: str | None = None,
    left_dots: int = 0,
) -> dict[str, Any]:
    """Edit one rhythmic region without moving later events or inventing identity."""
    from fractions import Fraction

    if action not in {"split", "merge", "boundary", "delete"}:
        raise MusicXMLEditError("지원하지 않는 리듬 편집입니다.")
    if type(left_dots) is not int:
        raise MusicXMLEditError("점음표 수가 올바르지 않습니다.")
    expected_count = 2 if action in {"merge", "boundary"} else 1
    if len(note_ids) != expected_count or len(set(note_ids)) != expected_count:
        raise MusicXMLEditError("리듬 편집의 음표 수가 올바르지 않습니다.")
    if action in {"split", "boundary"}:
        if left_note_type is None:
            raise MusicXMLEditError("왼쪽 음표 길이가 필요합니다.")
    elif left_note_type is not None or left_dots != 0:
        raise MusicXMLEditError("이 편집에는 왼쪽 음표 길이를 지정할 수 없습니다.")

    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    if root.tag != f"{ns}score-partwise":
        raise MusicXMLEditError("지원하지 않는 악보 형식입니다.")

    def locators() -> dict[str, ET.Element]:
        return {f"p{p}-m{m}-n{n}": note
                for p, part in enumerate(root.findall(f"{ns}part"))
                for m, measure in enumerate(part.findall(f"{ns}measure"))
                for n, note in enumerate(measure.findall(f"{ns}note"))}

    old = locators()
    if any(note_id not in old for note_id in note_ids):
        raise MusicXMLEditError("음표 위치가 올바르지 않습니다.")
    contexts = [_find_note_context(root, note_id) for note_id in note_ids]
    part, measure, first, _p, mi, _ni, _ns = contexts[0]
    targets = [context[2] for context in contexts]
    if any(context[0] is not part or context[1] is not measure for context in contexts):
        raise MusicXMLEditError("같은 파트와 마디의 음표만 편집할 수 있습니다.")
    if len(targets) == 2:
        children = list(measure)
        if children.index(targets[1]) != children.index(first) + 1:
            raise MusicXMLEditError("인접한 음표만 편집할 수 있습니다.")
    # shortcut: a single linear voice only; support simultaneous voices with explicit timing proof.
    notes = measure.findall(f"{ns}note")
    voices = {(note.findtext(f"{ns}voice") or "1", note.findtext(f"{ns}staff") or "1") for note in notes}
    if (len(voices) != 1 or measure.find(f"{ns}backup") is not None
            or measure.find(f"{ns}forward") is not None
            or any(note.find(f"{ns}chord") is not None or note.find(f"{ns}grace") is not None
                   or note.find(f"{ns}time-modification") is not None
                   or note.find(f"{ns}notations/{ns}tuplet") is not None for note in notes)):
        raise MusicXMLEditError("다성부·겹음·꾸밈음·잇단음표는 지원하지 않습니다.")
    instrument_tag = f"{ns}instrument"
    declared_instruments = {
        instrument.get("id") for score_part in root.findall(f"{ns}part-list/{ns}score-part")
        if score_part.get("id") == part.get("id")
        for instrument in score_part.findall(f"{ns}score-instrument") if instrument.get("id")
    }
    allowed = {f"{ns}{tag}" for tag in ("pitch", "rest", "duration", "voice", "type", "dot", "staff", "instrument")}
    instrument_refs = {}
    for note in targets:
        if any(child.tag not in allowed for child in note):
            raise MusicXMLEditError("가사·이음줄·기호 등 손실될 수 있는 정보가 있습니다.")
        if (len(note.findall(f"{ns}duration")) != 1 or len(note.findall(f"{ns}type")) != 1
                or len(note.findall(f"{ns}voice")) > 1 or len(note.findall(f"{ns}staff")) > 1
                or len(note.findall(f"{ns}pitch")) > 1 or len(note.findall(f"{ns}rest")) > 1):
            raise MusicXMLEditError("음표 구조가 올바르지 않습니다.")
        if (note.find(f"{ns}pitch") is None) == (note.find(f"{ns}rest") is None):
            raise MusicXMLEditError("음표 또는 쉼표가 올바르지 않습니다.")
        instruments = note.findall(instrument_tag)
        if (len(instruments) > 1 or any(set(ref.attrib) != {"id"} or ref.get("id") not in declared_instruments
                                        or len(ref) or (ref.text or "").strip() for ref in instruments)):
            raise MusicXMLEditError("선언된 악기 참조를 확인할 수 없습니다.")
        instrument_refs[note] = instruments[0] if instruments else None
        rest = note.find(f"{ns}rest")
        if rest is not None and rest.attrib:
            raise MusicXMLEditError("특수 쉼표는 편집할 수 없습니다.")
        pitch = note.find(f"{ns}pitch")
        if pitch is not None and (pitch.attrib or any(child.tag not in {
                f"{ns}step", f"{ns}alter", f"{ns}octave"} for child in pitch)):
            raise MusicXMLEditError("지원하지 않는 음높이 표현입니다.")
        if pitch is not None:
            try:
                step = pitch.findtext(f"{ns}step")
                alter = int(pitch.findtext(f"{ns}alter", "0"))
                octave = int(pitch.findtext(f"{ns}octave", ""))
                if (step not in {"A", "B", "C", "D", "E", "F", "G"}
                        or not -2 <= alter <= 2 or not 0 <= octave <= 9
                        or len(pitch.findall(f"{ns}step")) != 1
                        or len(pitch.findall(f"{ns}alter")) > 1
                        or len(pitch.findall(f"{ns}octave")) != 1):
                    raise ValueError
            except ValueError as exc:
                raise MusicXMLEditError("음높이 정보가 올바르지 않습니다.") from exc
    if action == "split" and first.find(f"{ns}pitch") is None:
        raise MusicXMLEditError("쉼표는 음표로 나눌 수 없습니다.")
    if action == "split" and any(element.attrib for element in first.iter()
                                 if element is not first and element is not instrument_refs[first]):
        raise MusicXMLEditError("음표의 하위 속성은 안전하게 복제할 수 없습니다.")
    if action == "delete" and first.find(f"{ns}pitch") is None:
        raise MusicXMLEditError("쉼표를 다시 삭제할 수 없습니다.")
    if action == "delete" and any(key in first.attrib for key in ("id", "{http://www.w3.org/XML/1998/namespace}id")):
        raise MusicXMLEditError("음표 ID를 보존하며 삭제할 수 없습니다.")
    if action == "merge":
        second = targets[1]
        if any(element.attrib for element in second.iter() if element is not instrument_refs[second]):
            raise MusicXMLEditError("두 번째 음표의 속성을 보존할 수 없습니다.")
        first_ref = instrument_refs[first]
        second_ref = instrument_refs[second]
        if (first_ref.attrib if first_ref is not None else {}) != (second_ref.attrib if second_ref is not None else {}):
            raise MusicXMLEditError("서로 다른 악기 참조는 합칠 수 없습니다.")
        def pitch_value(note: ET.Element) -> tuple[str, str, str] | None:
            pitch = note.find(f"{ns}pitch")
            if pitch is None:
                return None
            return (pitch.findtext(f"{ns}step", ""), pitch.findtext(f"{ns}alter", "0"),
                    pitch.findtext(f"{ns}octave", ""))
        if pitch_value(first) is None or pitch_value(first) != pitch_value(second):
            raise MusicXMLEditError("같은 음높이의 인접한 음표만 합칠 수 있습니다.")
        if any(first.findtext(f"{ns}{tag}") != second.findtext(f"{ns}{tag}") for tag in ("voice", "staff")):
            raise MusicXMLEditError("서로 다른 성부 또는 보표 정보는 합칠 수 없습니다.")

    attrs = _effective_attributes(part, mi, ns)
    divisions = int(attrs["divisions"])
    found_divisions = None
    for prior in part.findall(f"{ns}measure")[:mi + 1]:
        for element in prior.findall(f"{ns}attributes/{ns}divisions"):
            try:
                found_divisions = int(element.text or "")
            except ValueError as exc:
                raise MusicXMLEditError("divisions 값이 올바르지 않습니다.") from exc
            if found_divisions <= 0:
                raise MusicXMLEditError("divisions 값이 올바르지 않습니다.")
    if found_divisions != divisions:
        raise MusicXMLEditError("현재 divisions를 확인할 수 없습니다.")
    # Division changes within a measure would make integer durations incomparable.
    attributes = measure.findall(f"{ns}attributes")
    if len(attributes) > 1 or (attributes and list(measure).index(attributes[0]) > list(measure).index(notes[0])):
        raise MusicXMLEditError("마디 중간의 속성 변경은 지원하지 않습니다.")
    for note in notes:
        try:
            if int(note.findtext(f"{ns}duration", "")) <= 0:
                raise ValueError
        except ValueError as exc:
            raise MusicXMLEditError("마디의 음표 길이가 올바르지 않습니다.") from exc

    def duration_for(note_type: str, dots: int) -> int:
        value = _duration_for_type(divisions, note_type, dots)
        exact = Fraction(str(_NOTE_QUARTERS[note_type])) * divisions * (2 - Fraction(1, 2**dots))
        if exact.denominator != 1 or exact.numerator != value:
            raise MusicXMLEditError("현재 divisions로 음표 길이를 정확히 표현할 수 없습니다.")
        return value

    def represent(duration: int) -> tuple[str, int]:
        for note_type in _NOTE_QUARTERS:
            for dots in range(3):
                try:
                    if duration_for(note_type, dots) == duration:
                        return note_type, dots
                except MusicXMLEditError:
                    continue
        raise MusicXMLEditError("남은 음표 길이를 정확히 표기할 수 없습니다.")

    durations = []
    for note in targets:
        try:
            duration = int(note.findtext(f"{ns}duration", ""))
        except ValueError as exc:
            raise MusicXMLEditError("음표 길이가 올바르지 않습니다.") from exc
        note_type = note.findtext(f"{ns}type") or ""
        dots = len(note.findall(f"{ns}dot"))
        if duration <= 0 or duration_for(note_type, dots) != duration:
            raise MusicXMLEditError("음표 길이와 표기가 일치하지 않습니다.")
        durations.append(duration)

    def set_duration(note: ET.Element, spec: tuple[str, int]) -> None:
        _set_note_type_and_dots(note, ns, divisions=divisions, note_type=spec[0], dots=spec[1])

    replacements: dict[ET.Element, list[ET.Element]] = {}
    if action == "split":
        left = duration_for(left_note_type or "", left_dots)
        right_spec = represent(durations[0] - left)
        new = copy.deepcopy(first)
        for key in ("id", "{http://www.w3.org/XML/1998/namespace}id",
                    "default-x", "default-y", "relative-x", "relative-y"):
            new.attrib.pop(key, None)
        set_duration(first, (left_note_type or "", left_dots))
        set_duration(new, right_spec)
        measure.insert(list(measure).index(first) + 1, new)
        replacements[first] = [first, new]
        outputs = [first, new]
    elif action == "merge":
        spec = represent(sum(durations))
        set_duration(first, spec)
        measure.remove(targets[1])
        replacements[targets[1]] = [first]
        outputs = [first]
    elif action == "boundary":
        left = duration_for(left_note_type or "", left_dots)
        right_spec = represent(sum(durations) - left)
        set_duration(first, (left_note_type or "", left_dots))
        set_duration(targets[1], right_spec)
        outputs = targets
    else:
        new = copy.deepcopy(first)
        new.attrib.pop("id", None)
        _set_pitch_or_rest(new, ns, rest=True)
        index = list(measure).index(first)
        measure.remove(first)
        measure.insert(index, new)
        replacements[first] = []
        outputs = [new]

    new_ids = {node: locator for locator, node in locators().items()}
    mapping = {locator: [new_ids[node] for node in replacements.get(old_node, [old_node])]
               for locator, old_node in old.items()}
    result = {"mapping": mapping, "result_note_ids": [new_ids[node] for node in outputs]}
    _write(tree, path)
    return result
