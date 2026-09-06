from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class MusicXMLEditError(RuntimeError):
    pass


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _text(node: ET.Element | None, default: str | None = None) -> str | None:
    if node is None or node.text is None:
        return default
    return node.text


def _int_text(node: ET.Element | None) -> int | None:
    value = _text(node)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _note_id(part_index: int, measure_index: int, note_index: int) -> str:
    return f"p{part_index}-m{measure_index}-n{note_index}"


def parse_note_id(note_id: str) -> tuple[int, int, int]:
    try:
        p, m, n = note_id.split("-")
        return int(p[1:]), int(m[1:]), int(n[1:])
    except (ValueError, IndexError) as exc:
        raise MusicXMLEditError(f"Invalid note id: {note_id}") from exc


def score_summary(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)

    part_names: dict[str, str] = {}
    for score_part in root.findall(f".//{ns}score-part"):
        part_id = score_part.get("id") or ""
        name = _text(score_part.find(f"{ns}part-name"), part_id) or part_id
        part_names[part_id] = name

    notes: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    for part_index, part in enumerate(root.findall(f"{ns}part")):
        part_id = part.get("id") or f"P{part_index + 1}"
        part_name = part_names.get(part_id, part_id)
        measure_count = 0
        note_count = 0
        for measure_index, measure in enumerate(part.findall(f"{ns}measure")):
            measure_count += 1
            measure_number = measure.get("number") or str(measure_index + 1)
            for note_index, note in enumerate(measure.findall(f"{ns}note")):
                note_count += 1
                pitch = note.find(f"{ns}pitch")
                rest = note.find(f"{ns}rest") is not None
                lyric = note.find(f"{ns}lyric/{ns}text")
                ties = [tie.get("type") for tie in note.findall(f"{ns}tie") if tie.get("type")]
                notes.append(
                    {
                        "note_id": _note_id(part_index, measure_index, note_index),
                        "part_id": part_id,
                        "part_name": part_name,
                        "measure": measure_number,
                        "voice": _text(note.find(f"{ns}voice")),
                        "staff": _text(note.find(f"{ns}staff")),
                        "rest": rest,
                        "step": _text(pitch.find(f"{ns}step")) if pitch is not None else None,
                        "alter": _int_text(pitch.find(f"{ns}alter")) if pitch is not None else None,
                        "octave": _int_text(pitch.find(f"{ns}octave")) if pitch is not None else None,
                        "duration": _int_text(note.find(f"{ns}duration")),
                        "type": _text(note.find(f"{ns}type")),
                        "lyric": _text(lyric, "") or "",
                        "ties": ties,
                    }
                )
        parts.append(
            {
                "part_id": part_id,
                "name": part_name,
                "measures": measure_count,
                "notes": note_count,
            }
        )

    title = _text(root.find(f".//{ns}work-title")) or _text(root.find(f".//{ns}movement-title"))
    return {"title": title, "parts": parts, "notes": notes}


def _find_note(root: ET.Element, note_id: str) -> tuple[ET.Element, str]:
    part_index, measure_index, note_index = parse_note_id(note_id)
    ns = _namespace(root)
    parts = root.findall(f"{ns}part")
    if part_index >= len(parts):
        raise MusicXMLEditError(f"Part not found for note id: {note_id}")
    measures = parts[part_index].findall(f"{ns}measure")
    if measure_index >= len(measures):
        raise MusicXMLEditError(f"Measure not found for note id: {note_id}")
    notes = measures[measure_index].findall(f"{ns}note")
    if note_index >= len(notes):
        raise MusicXMLEditError(f"Note not found for note id: {note_id}")
    return notes[note_index], ns


def _set_child(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = value
    return child


def _set_pitch_alter(pitch: ET.Element, ns: str, value: int | None) -> None:
    tag = f"{ns}alter"
    existing = pitch.find(tag)
    if value in (None, 0):
        if existing is not None:
            pitch.remove(existing)
        return

    if existing is not None:
        existing.text = str(value)
        return

    alter = ET.Element(tag)
    alter.text = str(value)
    octave = pitch.find(f"{ns}octave")
    if octave is None:
        pitch.append(alter)
        return
    children = list(pitch)
    pitch.insert(children.index(octave), alter)


def update_note(path: Path, note_id: str, patch: dict[str, Any]) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    note, ns = _find_note(root, note_id)

    pitch_fields = {"step", "alter", "octave"}
    if any(key in patch for key in pitch_fields):
        if note.find(f"{ns}rest") is not None:
            raise MusicXMLEditError("쉼표에는 음정을 지정할 수 없습니다.")
        pitch = note.find(f"{ns}pitch")
        if pitch is None:
            raise MusicXMLEditError("이 노트에는 pitch 요소가 없습니다.")

        if "step" in patch and patch["step"] is not None:
            step = str(patch["step"]).upper().strip()
            if step not in {"A", "B", "C", "D", "E", "F", "G"}:
                raise MusicXMLEditError("step은 A-G 중 하나여야 합니다.")
            _set_child(pitch, f"{ns}step", step)

        if "alter" in patch:
            alter = patch["alter"]
            if alter in (None, 0, "", "0"):
                _set_pitch_alter(pitch, ns, None)
            else:
                try:
                    value = int(alter)
                except (TypeError, ValueError) as exc:
                    raise MusicXMLEditError("alter는 정수여야 합니다.") from exc
                if value < -2 or value > 2:
                    raise MusicXMLEditError("alter는 -2에서 2 사이만 지원합니다.")
                _set_pitch_alter(pitch, ns, value)

        if "octave" in patch and patch["octave"] is not None:
            try:
                octave = int(patch["octave"])
            except (TypeError, ValueError) as exc:
                raise MusicXMLEditError("octave는 정수여야 합니다.") from exc
            if octave < 0 or octave > 9:
                raise MusicXMLEditError("octave는 0에서 9 사이여야 합니다.")
            _set_child(pitch, f"{ns}octave", str(octave))

    if "lyric" in patch:
        lyric_value = "" if patch["lyric"] is None else str(patch["lyric"])
        lyric_nodes = note.findall(f"{ns}lyric")
        if lyric_value == "":
            for node in lyric_nodes:
                note.remove(node)
        else:
            lyric_node = lyric_nodes[0] if lyric_nodes else ET.SubElement(note, f"{ns}lyric")
            _set_child(lyric_node, f"{ns}text", lyric_value)

    temp = path.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)


def set_score_title(path: Path, title: str) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    work = root.find(f"{ns}work")
    if work is None:
        work = ET.Element(f"{ns}work")
        root.insert(0, work)
    _set_child(work, f"{ns}work-title", title)
    temp = path.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)


def snapshot(path: Path, revisions_dir: Path, revision: int) -> Path:
    revisions_dir.mkdir(parents=True, exist_ok=True)
    target = revisions_dir / f"rev-{revision:04d}.musicxml"
    shutil.copy2(path, target)
    return target


def undo_last(path: Path, revisions_dir: Path) -> Path | None:
    candidates = sorted(revisions_dir.glob("rev-*.musicxml"))
    if not candidates:
        return None
    latest = candidates[-1]
    shutil.copy2(latest, path)
    latest.unlink()
    return latest
