from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
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


def extract_part_musicxml(source: Path, part_id: str, target: Path) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    ns = _namespace(root)

    selected_part = None
    for part in root.findall(f"{ns}part"):
        if part.get("id") == part_id:
            selected_part = part
            break
    if selected_part is None:
        raise ValueError(f"Part not found: {part_id}")

    part_list = root.find(f"{ns}part-list")
    if part_list is not None:
        for child in list(part_list):
            if child.tag == f"{ns}score-part" and child.get("id") != part_id:
                part_list.remove(child)
            elif child.tag == f"{ns}part-group":
                part_list.remove(child)

    for part in list(root.findall(f"{ns}part")):
        if part is not selected_part:
            root.remove(part)

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(target)


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
