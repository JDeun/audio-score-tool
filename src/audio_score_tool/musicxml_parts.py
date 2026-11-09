from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from math import gcd, lcm
from pathlib import Path


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value.strip()).strip("_")
    return cleaned or "part"


def list_score_parts(path: Path) -> list[dict[str, str | int]]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    names: dict[str, str] = {}
    for score_part in root.findall(f".//{ns}score-part"):
        part_id = score_part.get("id") or ""
        names[part_id] = score_part.findtext(f"{ns}part-name") or part_id

    parts: list[dict[str, str | int]] = []
    for index, part in enumerate(root.findall(f"{ns}part"), start=1):
        part_id = part.get("id") or f"P{index}"
        name = names.get(part_id, part_id)
        parts.append(
            {
                "index": index,
                "part_id": part_id,
                "name": name,
                "slug": f"{index:02d}_{_safe_name(name).lower()}",
            }
        )
    return parts


@dataclass
class _Tempo:
    element: ET.Element
    visible_at: Fraction
    sounds_at: Fraction | None


@dataclass
class _MeasureTiming:
    insertion_index: int
    insertion_divisions: Fraction | None
    extent: Fraction
    tempos: list[_Tempo]


def _number(text: str | None, name: str) -> Fraction:
    try:
        return Fraction(text or "0")
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid MusicXML {name}") from exc


def _quarters(text: str | None, divisions: Fraction | None) -> Fraction:
    value = _number(text, "duration or offset")
    if value == 0:
        return value
    if divisions is None:
        raise ValueError("Cannot align tempo without explicit MusicXML divisions")
    return value / divisions


def _part_timing(part: ET.Element, ns: str) -> list[_MeasureTiming]:
    """Read exact positions without normalizing or rewriting performed notes."""
    divisions: Fraction | None = None
    result = []
    for measure in part.findall(f"{ns}measure"):
        cursor = extent = Fraction(0)
        insertion_index = 0
        insertion_divisions = divisions
        rhythmic_content = False
        tempos = []
        for index, child in enumerate(measure):
            tag = child.tag.removeprefix(ns)
            if tag == "attributes":
                value = child.findtext(f"{ns}divisions")
                if value is not None:
                    divisions = _number(value, "divisions")
                    if divisions <= 0:
                        raise ValueError("MusicXML divisions must be positive")
                if not rhythmic_content:
                    insertion_index = index + 1
                    insertion_divisions = divisions
            elif tag in {"note", "forward", "backup"}:
                rhythmic_content = True
                if tag == "note" and (
                    child.find(f"{ns}chord") is not None
                    or child.find(f"{ns}grace") is not None
                ):
                    continue
                duration = _quarters(child.findtext(f"{ns}duration"), divisions)
                if duration < 0:
                    raise ValueError("MusicXML duration must not be negative")
                cursor += -duration if tag == "backup" else duration
                if cursor < 0:
                    raise ValueError("Cannot align tempo across a negative measure cursor")
                extent = max(extent, cursor)
            elif tag in {"direction", "sound"}:
                sound = child if tag == "sound" else child.find(f"{ns}sound")
                has_sound = sound is not None and sound.get("tempo") is not None
                has_mark = child.find(f"{ns}direction-type/{ns}metronome") is not None
                if not has_sound and not has_mark:
                    continue
                offset = child.find(f"{ns}offset")
                visible_at = cursor + _quarters(
                    offset.text if offset is not None else None, divisions,
                )
                sounds_at = None
                if has_sound:
                    sound_offset = sound.find(f"{ns}offset")
                    if sound_offset is not None:
                        sounds_at = cursor + _quarters(sound_offset.text, divisions)
                    elif offset is not None and offset.get("sound") == "yes":
                        sounds_at = visible_at
                    else:
                        # MusicXML direction/offset defaults to sound="no".
                        sounds_at = cursor
                tempos.append(_Tempo(child, visible_at, sounds_at))
        result.append(_MeasureTiming(
            insertion_index, insertion_divisions, extent, tempos,
        ))
    return result


def _metronome_identity(mark: ET.Element, ns: str) -> tuple:
    units = {
        "long": Fraction(16), "breve": Fraction(8), "whole": Fraction(4),
        "half": Fraction(2), "quarter": Fraction(1), "eighth": Fraction(1, 2),
        "16th": Fraction(1, 4), "32nd": Fraction(1, 8), "64th": Fraction(1, 16),
        "128th": Fraction(1, 32), "256th": Fraction(1, 64),
        "512th": Fraction(1, 128), "1024th": Fraction(1, 256),
    }
    unit = units.get(mark.findtext(f"{ns}beat-unit") or "")
    per_minute = mark.findtext(f"{ns}per-minute")
    if unit is not None and per_minute is not None:
        try:
            rate = Fraction(per_minute.strip())
        except (ValueError, ZeroDivisionError):
            pass  # Ranges and metric modulations retain their exact notation.
        else:
            dots = len(mark.findall(f"{ns}beat-unit-dot"))
            return ("rate", rate * unit * (2 - Fraction(1, 2 ** dots)))

    def shape(node: ET.Element) -> tuple:
        return (node.tag, (node.text or "").strip(), tuple(shape(c) for c in node))

    return ("notation", shape(mark))


def _tempo_keys(tempo: _Tempo, ns: str) -> tuple[tuple | None, list[tuple]]:
    node = tempo.element
    sound = node if node.tag == f"{ns}sound" else node.find(f"{ns}sound")
    sound_key = None
    if sound is not None and sound.get("tempo") is not None:
        sound_key = (
            tempo.sounds_at, _number(sound.get("tempo"), "tempo"),
            sound.get("time-only", ""),
        )
    marks = [
        (tempo.visible_at, _metronome_identity(mark, ns))
        for mark in node.findall(f"{ns}direction-type/{ns}metronome")
    ]
    return sound_key, marks


def _decimal(value: Fraction) -> str:
    """Serialize a terminating MusicXML decimal with no floating-point rounding."""
    denominator = value.denominator
    scale = 0
    while denominator > 1:
        common = gcd(denominator, 10)
        if common == 1:
            raise ValueError("Tempo position cannot be expressed in current divisions")
        denominator //= common
        scale += 1
    numerator = value.numerator * (10 ** scale // value.denominator)
    if not scale:
        return str(numerator)
    sign = "-" if numerator < 0 else ""
    digits = str(abs(numerator)).rjust(scale + 1, "0")
    return (sign + digits[:-scale] + "." + digits[-scale:]).rstrip("0").rstrip(".")


def _set_offset(node: ET.Element, value: Fraction, ns: str) -> None:
    existing = node.find(f"{ns}offset")
    if existing is not None:
        existing.text = _decimal(value)
        return
    if value == 0:
        return
    offset = ET.Element(f"{ns}offset")
    offset.text = _decimal(value)
    # direction-type* precedes offset; sound/offset is its final child.
    index = len(node)
    if node.tag == f"{ns}direction":
        index = next((i for i, c in enumerate(node) if c.tag != f"{ns}direction-type"), index)
    node.insert(index, offset)


def _copy_tempo(
    tempo: _Tempo, *, copy_sound: bool, marks: set[tuple], divisions: Fraction, ns: str,
) -> ET.Element:
    node = deepcopy(tempo.element)
    if node.tag == f"{ns}direction":
        for child in list(node):
            if child.tag in {f"{ns}staff", f"{ns}voice"}:
                node.remove(child)
            elif child.tag == f"{ns}direction-type":
                for detail in list(child):
                    if detail.tag == f"{ns}metronome":
                        if (tempo.visible_at, _metronome_identity(detail, ns)) not in marks:
                            child.remove(detail)
                    elif detail.tag != f"{ns}words" or (not marks and not copy_sound):
                        child.remove(detail)
                if not len(child):
                    node.remove(child)
        _set_offset(node, tempo.visible_at * divisions, ns)
    sound = node if node.tag == f"{ns}sound" else node.find(f"{ns}sound")
    if sound is not None:
        if not copy_sound:
            node.remove(sound)
        else:
            # Source instrument routing, pedals and dynamics do not belong to the
            # selected instrument. Only the shared tempo and repeat scope move.
            sound.attrib = {k: v for k, v in sound.attrib.items() if k in {"tempo", "time-only"}}
            for child in list(sound):
                if child.tag != f"{ns}offset":
                    sound.remove(child)
            _set_offset(sound, (tempo.sounds_at or Fraction(0)) * divisions, ns)
    return node


def _carry_tempos(source: ET.Element, selected: ET.Element, ns: str) -> None:
    if not any(
        node.find(f"{ns}direction-type/{ns}metronome") is not None
        or (node.find(f"{ns}sound") is not None and node.find(f"{ns}sound").get("tempo") is not None)
        or (node.tag == f"{ns}sound" and node.get("tempo") is not None)
        for measure in source.findall(f"{ns}measure") for node in measure
    ):
        return
    source_measures = source.findall(f"{ns}measure")
    selected_measures = selected.findall(f"{ns}measure")
    if len(source_measures) != len(selected_measures) or any(
        left.get("number") != right.get("number")
        for left, right in zip(source_measures, selected_measures, strict=True)
    ):
        raise ValueError("Cannot align source tempo with selected part measures")
    source_timing = _part_timing(source, ns)
    selected_timing = _part_timing(selected, ns)
    for measure, original, destination in zip(
        selected_measures, source_timing, selected_timing, strict=True,
    ):
        sound_keys: set[tuple] = set()
        mark_keys: set[tuple] = set()
        for event in destination.tempos:
            sound, marks = _tempo_keys(event, ns)
            if sound is not None:
                sound_keys.add(sound)
            mark_keys.update(marks)
        copies = []
        for event in original.tempos:
            sound, marks = _tempo_keys(event, ns)
            copy_sound = sound is not None and sound not in sound_keys
            missing_marks = set(marks) - mark_keys
            if not copy_sound and not missing_marks:
                continue
            if copy_sound and any(k[0] == sound[0] and k[2] == sound[2] for k in sound_keys):
                raise ValueError("Conflicting tempo in the selected part")
            if any(k[0] == mark[0] for mark in missing_marks for k in mark_keys):
                raise ValueError("Conflicting metronome in the selected part")
            positions = [event.visible_at]
            if copy_sound:
                positions.append(event.sounds_at)
            if any(p is None or p < 0 or p > destination.extent for p in positions):
                raise ValueError("Source tempo is outside the selected part measure")
            copies.append((event, copy_sound, missing_marks))
            if copy_sound:
                sound_keys.add(sound)
            mark_keys.update(missing_marks)
        if not copies:
            continue
        divisions = destination.insertion_divisions
        if divisions is None:
            raise ValueError("Cannot align tempo without selected part divisions")
        changed_divisions = False
        try:
            for event, copy_sound, _marks in copies:
                _decimal(event.visible_at * divisions)
                if copy_sound:
                    _decimal(event.sounds_at * divisions)
        except ValueError:
            # A 1/3-quarter tempo can be absent from otherwise quarter-only
            # parts. Temporarily use exact divisions around directions at zero;
            # restore the original value before any note/backup/forward.
            divisions = Fraction(lcm(*[
                position.denominator for event, copy_sound, _marks in copies
                for position in [event.visible_at, *([event.sounds_at] if copy_sound else [])]
            ]))
            changed_divisions = True
        additions = []
        if changed_divisions:
            attributes = ET.Element(f"{ns}attributes")
            ET.SubElement(attributes, f"{ns}divisions").text = _decimal(divisions)
            additions.append(attributes)
        additions.extend(_copy_tempo(
            event, copy_sound=copy_sound, marks=marks, divisions=divisions, ns=ns,
        ) for event, copy_sound, marks in copies)
        if changed_divisions:
            attributes = ET.Element(f"{ns}attributes")
            ET.SubElement(attributes, f"{ns}divisions").text = _decimal(destination.insertion_divisions)
            additions.append(attributes)
        for offset, addition in enumerate(additions):
            measure.insert(destination.insertion_index + offset, addition)


def _retained_groups(part_list: ET.Element, selected: set[str], ns: str) -> set[ET.Element]:
    active: dict[str, tuple[ET.Element, int] | None] = {}
    retained: set[ET.Element] = set()
    members = 0
    for child in part_list:
        if child.tag == f"{ns}score-part" and child.get("id") in selected:
            members += 1
        elif child.tag == f"{ns}part-group":
            number = child.get("number", "1")
            if child.get("type") == "start":
                active[number] = None if number in active else (child, members)
            elif child.get("type") == "stop":
                start = active.pop(number, None)
                if start is not None and members - start[1] >= 2:
                    retained.update((start[0], child))
    return retained


def extract_parts_musicxml(source: Path, part_ids: list[str], target: Path) -> None:
    """Extract a score subset while retaining exact notation and shared tempo."""
    if not isinstance(part_ids, list) or not part_ids or any(
        not isinstance(part_id, str) or not part_id for part_id in part_ids
    ):
        raise ValueError("Select at least one valid part ID")
    selected = set(part_ids)
    if len(selected) != len(part_ids):
        raise ValueError("Duplicate selected part IDs")
    tree = ET.parse(source)
    root = tree.getroot()
    ns = _namespace(root)
    if root.tag != f"{ns}score-partwise":
        raise ValueError("Part extraction requires a partwise MusicXML score")
    parts = root.findall(f"{ns}part")
    actual_ids = [part.get("id") for part in parts]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("Duplicate part IDs in source score")
    if not selected.issubset(actual_ids):
        raise ValueError(f"Part not found: {', '.join(sorted(selected - set(actual_ids)))}")
    selected_parts = [part for part in parts if part.get("id") in selected]
    part_list = root.find(f"{ns}part-list")
    if part_list is None:
        raise ValueError("Source score has no part-list")
    listed_ids = [
        child.get("id") for child in part_list.findall(f"{ns}score-part")
        if child.get("id") in selected
    ]
    if listed_ids != [part.get("id") for part in selected_parts]:
        raise ValueError("Selected parts do not match the source part-list")
    if parts[0] is not selected_parts[0]:
        _carry_tempos(parts[0], selected_parts[0], ns)
    groups = _retained_groups(part_list, selected, ns)
    for child in list(part_list):
        if (
            child.tag == f"{ns}score-part" and child.get("id") not in selected
        ) or (child.tag == f"{ns}part-group" and child not in groups):
            part_list.remove(child)
    for part in parts:
        if part.get("id") not in selected:
            root.remove(part)

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(target)


def extract_part_musicxml(source: Path, part_id: str, target: Path) -> None:
    extract_parts_musicxml(source, [part_id], target)


def copy_initial_part_pdfs(score_dir: Path, target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in sorted(score_dir.glob("*.pdf")):
        if source.name == "full_score.pdf" or source.name.endswith("_tab.pdf"):
            continue
        target = target_dir / source.name
        shutil.copy2(source, target)
        copied.append(target)
    return copied
