from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path


class ChordEditError(RuntimeError):
    pass


_CHORD_RE = re.compile(
    r"^\s*([A-Ga-g])([#b♯♭]?)([^/]*?)(?:/([A-Ga-g])([#b♯♭]?))?\s*$"
)

_KIND_BY_SUFFIX = {
    "": "major",
    "m": "minor",
    "min": "minor",
    "7": "dominant",
    "maj7": "major-seventh",
    "M7": "major-seventh",
    "Δ7": "major-seventh",
    "m7": "minor-seventh",
    "min7": "minor-seventh",
    "6": "major-sixth",
    "m6": "minor-sixth",
    "9": "dominant-ninth",
    "maj9": "major-ninth",
    "M9": "major-ninth",
    "m9": "minor-ninth",
    "11": "dominant-11th",
    "13": "dominant-13th",
    "dim": "diminished",
    "°": "diminished",
    "dim7": "diminished-seventh",
    "°7": "diminished-seventh",
    "aug": "augmented",
    "+": "augmented",
    "sus": "suspended-fourth",
    "sus4": "suspended-fourth",
    "sus2": "suspended-second",
    "m7b5": "half-diminished",
    "ø": "half-diminished",
    "ø7": "half-diminished",
    "5": "power",
}

_SUFFIX_BY_KIND = {
    "major": "",
    "minor": "m",
    "dominant": "7",
    "major-seventh": "maj7",
    "minor-seventh": "m7",
    "major-sixth": "6",
    "minor-sixth": "m6",
    "dominant-ninth": "9",
    "major-ninth": "maj9",
    "minor-ninth": "m9",
    "dominant-11th": "11",
    "dominant-13th": "13",
    "diminished": "dim",
    "diminished-seventh": "dim7",
    "augmented": "aug",
    "suspended-fourth": "sus4",
    "suspended-second": "sus2",
    "half-diminished": "m7b5",
    "power": "5",
    "other": "",
}


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_note_id(note_id: str) -> tuple[int, int, int]:
    try:
        p, m, n = note_id.split("-")
        return int(p[1:]), int(m[1:]), int(n[1:])
    except (ValueError, IndexError) as exc:
        raise ChordEditError(f"Invalid note id: {note_id}") from exc


def _accidental_to_alter(value: str) -> int:
    normalized = value.replace("♯", "#").replace("♭", "b")
    if normalized == "#":
        return 1
    if normalized == "b":
        return -1
    return 0


def _alter_to_accidental(value: str | None) -> str:
    if value is None:
        return ""
    try:
        number = int(float(value))
    except ValueError:
        return ""
    return {2: "𝄪", 1: "♯", -1: "♭", -2: "𝄫"}.get(number, "")


def parse_chord_symbol(symbol: str) -> dict[str, str | int | None]:
    match = _CHORD_RE.match(symbol)
    if not match:
        raise ChordEditError(
            "코드는 C, Am7, F#maj7, Bb7, G/B 같은 형식으로 입력하세요."
        )

    root_step, root_accidental, suffix, bass_step, bass_accidental = match.groups()
    suffix = (suffix or "").strip()
    normalized_suffix = suffix.replace("♭", "b").replace("♯", "#")
    kind = _KIND_BY_SUFFIX.get(normalized_suffix, "other")
    return {
        "root_step": root_step.upper(),
        "root_alter": _accidental_to_alter(root_accidental),
        "suffix": suffix,
        "kind": kind,
        "bass_step": bass_step.upper() if bass_step else None,
        "bass_alter": _accidental_to_alter(bass_accidental or "") if bass_step else None,
    }


def harmony_symbol(harmony: ET.Element, ns: str) -> str:
    root = harmony.find(f"{ns}root")
    if root is None:
        return ""
    root_step = root.findtext(f"{ns}root-step") or ""
    root_alter = _alter_to_accidental(root.findtext(f"{ns}root-alter"))
    kind = harmony.find(f"{ns}kind")
    if kind is None:
        suffix = ""
    else:
        suffix = kind.get("text")
        if suffix is None:
            suffix = _SUFFIX_BY_KIND.get(kind.text or "", "")

    bass = harmony.find(f"{ns}bass")
    bass_text = ""
    if bass is not None:
        bass_step = bass.findtext(f"{ns}bass-step") or ""
        bass_alter = _alter_to_accidental(bass.findtext(f"{ns}bass-alter"))
        if bass_step:
            bass_text = f"/{bass_step}{bass_alter}"
    return f"{root_step}{root_alter}{suffix}{bass_text}"


def harmony_before_note(
    measure: ET.Element,
    note: ET.Element,
    ns: str,
) -> ET.Element | None:
    children = list(measure)
    try:
        note_position = children.index(note)
    except ValueError:
        return None

    candidate: ET.Element | None = None
    for child in reversed(children[:note_position]):
        local = _local_name(child.tag)
        if local == "harmony":
            candidate = child
            break
        if local in {"note", "backup", "forward"}:
            break
    return candidate


def chord_symbol_before_note(measure: ET.Element, note: ET.Element, ns: str) -> str:
    harmony = harmony_before_note(measure, note, ns)
    return harmony_symbol(harmony, ns) if harmony is not None else ""


def _build_harmony(ns: str, symbol: str) -> ET.Element:
    parsed = parse_chord_symbol(symbol)
    harmony = ET.Element(f"{ns}harmony", {"placement": "above"})

    root = ET.SubElement(harmony, f"{ns}root")
    ET.SubElement(root, f"{ns}root-step").text = str(parsed["root_step"])
    if parsed["root_alter"]:
        ET.SubElement(root, f"{ns}root-alter").text = str(parsed["root_alter"])

    kind_attributes: dict[str, str] = {}
    suffix = str(parsed["suffix"] or "")
    if suffix:
        kind_attributes["text"] = suffix
    kind = ET.SubElement(harmony, f"{ns}kind", kind_attributes)
    kind.text = str(parsed["kind"])

    if parsed["bass_step"]:
        bass = ET.SubElement(harmony, f"{ns}bass")
        ET.SubElement(bass, f"{ns}bass-step").text = str(parsed["bass_step"])
        if parsed["bass_alter"]:
            ET.SubElement(bass, f"{ns}bass-alter").text = str(parsed["bass_alter"])
    return harmony


def set_chord_at_note(path: Path, note_id: str, symbol: str | None) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    part_index, measure_index, note_index = _parse_note_id(note_id)

    parts = root.findall(f"{ns}part")
    if part_index >= len(parts):
        raise ChordEditError("코드를 넣을 파트를 찾지 못했습니다.")
    measures = parts[part_index].findall(f"{ns}measure")
    if measure_index >= len(measures):
        raise ChordEditError("코드를 넣을 마디를 찾지 못했습니다.")
    notes = measures[measure_index].findall(f"{ns}note")
    if note_index >= len(notes):
        raise ChordEditError("코드를 넣을 음표 위치를 찾지 못했습니다.")

    measure = measures[measure_index]
    note = notes[note_index]
    existing = harmony_before_note(measure, note, ns)
    cleaned = (symbol or "").strip()

    if not cleaned:
        if existing is not None:
            measure.remove(existing)
    else:
        replacement = _build_harmony(ns, cleaned)
        children = list(measure)
        if existing is not None:
            position = children.index(existing)
            measure.remove(existing)
            measure.insert(position, replacement)
        else:
            position = children.index(note)
            measure.insert(position, replacement)

    temp = path.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)
