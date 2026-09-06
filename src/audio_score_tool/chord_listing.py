from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .chord_editor import harmony_symbol


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def list_chords(path: Path) -> list[dict]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    result: list[dict] = []

    part_names: dict[str, str] = {}
    for score_part in root.findall(f".//{ns}score-part"):
        part_id = score_part.get("id") or ""
        part_names[part_id] = score_part.findtext(f"{ns}part-name") or part_id

    for part_index, part in enumerate(root.findall(f"{ns}part")):
        part_id = part.get("id") or f"P{part_index + 1}"
        part_name = part_names.get(part_id, part_id)
        for measure_index, measure in enumerate(part.findall(f"{ns}measure")):
            measure_number = measure.get("number") or str(measure_index + 1)
            note_index = -1
            pending_harmony: ET.Element | None = None
            for child in list(measure):
                local = _local_name(child.tag)
                if local == "harmony":
                    pending_harmony = child
                    continue
                if local != "note":
                    if local in {"backup", "forward"}:
                        pending_harmony = None
                    continue

                note_index += 1
                if pending_harmony is not None:
                    symbol = harmony_symbol(pending_harmony, ns)
                    if symbol:
                        result.append(
                            {
                                "note_id": f"p{part_index}-m{measure_index}-n{note_index}",
                                "part_id": part_id,
                                "part_name": part_name,
                                "measure": measure_number,
                                "symbol": symbol,
                            }
                        )
                    pending_harmony = None
    return result
