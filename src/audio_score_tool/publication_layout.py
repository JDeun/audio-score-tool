from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

DEFAULT_PUBLICATION_SETTINGS: dict[str, Any] = {
    "page_size": "A4",
    "orientation": "portrait",
    "bars_per_system": 4,
    "systems_per_page": 5,
    "system_distance_mm": 10.0,
    "first_page_title_space_mm": 34.0,
    "top_margin_mm": 12.0,
    "bottom_margin_mm": 12.0,
    "left_margin_mm": 14.0,
    "right_margin_mm": 14.0,
    "title_font_size": 24.0,
    "subtitle_font_size": 12.0,
    "credit_font_size": 9.5,
    "subtitle": "",
    "composer": "",
    "lyricist": "",
    "arranger": "",
    "rights": "",
}

_PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
}

_AST_CREDIT_PREFIX = "ast-credit-"


def merged_publication_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_PUBLICATION_SETTINGS)
    if value:
        merged.update(value)
    return merged


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _set_text(parent: ET.Element, tag: str, value: str) -> ET.Element:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = value
    return child


def _insert_root_before_part_list(root: ET.Element, element: ET.Element) -> None:
    children = list(root)
    for index, child in enumerate(children):
        if _local_name(child.tag) in {"part-list", "part"}:
            root.insert(index, element)
            return
    root.append(element)


def _insert_root_identification(root: ET.Element, element: ET.Element) -> None:
    children = list(root)
    for index, child in enumerate(children):
        if _local_name(child.tag) in {"defaults", "credit", "part-list", "part"}:
            root.insert(index, element)
            return
    root.append(element)


def _ensure_defaults(root: ET.Element, ns: str) -> ET.Element:
    defaults = root.find(f"{ns}defaults")
    if defaults is None:
        defaults = ET.Element(f"{ns}defaults")
        _insert_root_before_part_list(root, defaults)
    return defaults


def _ensure_scaling(defaults: ET.Element, ns: str) -> tuple[float, float]:
    scaling = defaults.find(f"{ns}scaling")
    if scaling is None:
        scaling = ET.Element(f"{ns}scaling")
        defaults.insert(0, scaling)
    millimeters = _set_text(scaling, f"{ns}millimeters", "7")
    tenths = _set_text(scaling, f"{ns}tenths", "40")
    try:
        return float(millimeters.text or 7), float(tenths.text or 40)
    except ValueError:
        millimeters.text = "7"
        tenths.text = "40"
        return 7.0, 40.0


def _mm_to_tenths(mm: float, millimeters: float, tenths: float) -> float:
    return mm * tenths / millimeters


def _tenths_string(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _page_dimensions(settings: dict[str, Any]) -> tuple[float, float]:
    width, height = _PAGE_SIZES_MM.get(str(settings["page_size"]).upper(), _PAGE_SIZES_MM["A4"])
    if settings.get("orientation") == "landscape":
        return height, width
    return width, height


def _apply_page_defaults(
    defaults: ET.Element,
    ns: str,
    settings: dict[str, Any],
    millimeters: float,
    tenths: float,
) -> tuple[float, float]:
    page_width_mm, page_height_mm = _page_dimensions(settings)
    page_width = _mm_to_tenths(page_width_mm, millimeters, tenths)
    page_height = _mm_to_tenths(page_height_mm, millimeters, tenths)

    page_layout = defaults.find(f"{ns}page-layout")
    if page_layout is None:
        page_layout = ET.Element(f"{ns}page-layout")
        scaling = defaults.find(f"{ns}scaling")
        insert_at = list(defaults).index(scaling) + 1 if scaling is not None else 0
        defaults.insert(insert_at, page_layout)
    _set_text(page_layout, f"{ns}page-height", _tenths_string(page_height))
    _set_text(page_layout, f"{ns}page-width", _tenths_string(page_width))

    margins = page_layout.find(f"{ns}page-margins")
    if margins is None:
        margins = ET.SubElement(page_layout, f"{ns}page-margins", {"type": "both"})
    else:
        margins.set("type", "both")

    for name, key in (
        ("left-margin", "left_margin_mm"),
        ("right-margin", "right_margin_mm"),
        ("top-margin", "top_margin_mm"),
        ("bottom-margin", "bottom_margin_mm"),
    ):
        _set_text(
            margins,
            f"{ns}{name}",
            _tenths_string(_mm_to_tenths(float(settings[key]), millimeters, tenths)),
        )

    system_layout = defaults.find(f"{ns}system-layout")
    if system_layout is None:
        system_layout = ET.SubElement(defaults, f"{ns}system-layout")

    system_margins = system_layout.find(f"{ns}system-margins")
    if system_margins is None:
        system_margins = ET.Element(f"{ns}system-margins")
        system_layout.insert(0, system_margins)
    _set_text(system_margins, f"{ns}left-margin", "0")
    _set_text(system_margins, f"{ns}right-margin", "0")
    _set_text(
        system_layout,
        f"{ns}system-distance",
        _tenths_string(
            _mm_to_tenths(float(settings["system_distance_mm"]), millimeters, tenths)
        ),
    )
    _set_text(
        system_layout,
        f"{ns}top-system-distance",
        _tenths_string(_mm_to_tenths(8.0, millimeters, tenths)),
    )
    return page_width, page_height


def _measure_print(measure: ET.Element, ns: str) -> ET.Element:
    print_element = measure.find(f"{ns}print")
    if print_element is None:
        print_element = ET.Element(f"{ns}print")
        measure.insert(0, print_element)
    return print_element


def _clear_forced_breaks(root: ET.Element, ns: str) -> None:
    for print_element in root.findall(f".//{ns}print"):
        print_element.attrib.pop("new-system", None)
        print_element.attrib.pop("new-page", None)
        if print_element.get("id") == "ast-first-page-layout":
            parent_measure = next(
                (
                    measure
                    for measure in root.findall(f".//{ns}measure")
                    if print_element in list(measure)
                ),
                None,
            )
            if parent_measure is not None:
                parent_measure.remove(print_element)


def _apply_forced_breaks(root: ET.Element, ns: str, settings: dict[str, Any]) -> None:
    bars_per_system = max(1, int(settings["bars_per_system"]))
    systems_per_page = max(1, int(settings["systems_per_page"]))

    for part in root.findall(f"{ns}part"):
        measures = part.findall(f"{ns}measure")
        for measure_index, measure in enumerate(measures):
            if measure_index == 0:
                continue
            if measure_index % bars_per_system != 0:
                continue
            system_index = measure_index // bars_per_system
            print_element = _measure_print(measure, ns)
            if system_index % systems_per_page == 0:
                print_element.set("new-page", "yes")
                print_element.attrib.pop("new-system", None)
            else:
                print_element.set("new-system", "yes")
                print_element.attrib.pop("new-page", None)


def _apply_first_page_title_space(
    root: ET.Element,
    ns: str,
    settings: dict[str, Any],
    millimeters: float,
    tenths: float,
) -> None:
    first_part = root.find(f"{ns}part")
    if first_part is None:
        return
    first_measure = first_part.find(f"{ns}measure")
    if first_measure is None:
        return
    print_element = _measure_print(first_measure, ns)
    print_element.set("id", "ast-first-page-layout")
    system_layout = print_element.find(f"{ns}system-layout")
    if system_layout is None:
        system_layout = ET.SubElement(print_element, f"{ns}system-layout")
    _set_text(
        system_layout,
        f"{ns}top-system-distance",
        _tenths_string(
            _mm_to_tenths(float(settings["first_page_title_space_mm"]), millimeters, tenths)
        ),
    )


def _remove_ast_credits(root: ET.Element, ns: str) -> None:
    for credit in list(root.findall(f"{ns}credit")):
        if (credit.get("id") or "").startswith(_AST_CREDIT_PREFIX):
            root.remove(credit)


def _credit(
    root: ET.Element,
    ns: str,
    *,
    credit_id: str,
    credit_type: str,
    text: str,
    x: float,
    y: float,
    font_size: float,
    justify: str,
    font_weight: str | None = None,
) -> None:
    if not text.strip():
        return
    credit = ET.Element(f"{ns}credit", {"page": "1", "id": f"{_AST_CREDIT_PREFIX}{credit_id}"})
    _set_text(credit, f"{ns}credit-type", credit_type)
    attributes = {
        "default-x": _tenths_string(x),
        "default-y": _tenths_string(y),
        "font-size": _tenths_string(font_size),
        "justify": justify,
        "valign": "top",
    }
    if font_weight:
        attributes["font-weight"] = font_weight
    words = ET.SubElement(credit, f"{ns}credit-words", attributes)
    words.text = text.strip()
    _insert_root_before_part_list(root, credit)


def _apply_credits(
    root: ET.Element,
    ns: str,
    title: str,
    settings: dict[str, Any],
    page_width: float,
    page_height: float,
    millimeters: float,
    tenths: float,
) -> None:
    _remove_ast_credits(root, ns)
    left = _mm_to_tenths(float(settings["left_margin_mm"]), millimeters, tenths)
    right = _mm_to_tenths(float(settings["right_margin_mm"]), millimeters, tenths)
    top = _mm_to_tenths(float(settings["top_margin_mm"]), millimeters, tenths)
    bottom = _mm_to_tenths(float(settings["bottom_margin_mm"]), millimeters, tenths)
    center_x = left + (page_width - left - right) / 2
    top_y = page_height - top
    step = _mm_to_tenths(6.5, millimeters, tenths)

    _credit(
        root,
        ns,
        credit_id="title",
        credit_type="title",
        text=title,
        x=center_x,
        y=top_y,
        font_size=float(settings["title_font_size"]),
        justify="center",
        font_weight="bold",
    )
    _credit(
        root,
        ns,
        credit_id="subtitle",
        credit_type="subtitle",
        text=str(settings.get("subtitle") or ""),
        x=center_x,
        y=top_y - step,
        font_size=float(settings["subtitle_font_size"]),
        justify="center",
    )

    right_x = page_width - right
    credit_y = top_y - step * 2.1
    credit_size = float(settings["credit_font_size"])
    rows = (
        ("composer", "composer", "작곡", settings.get("composer")),
        ("lyricist", "lyricist", "작사", settings.get("lyricist")),
        ("arranger", "arranger", "편곡", settings.get("arranger")),
    )
    for offset, (credit_id, credit_type, label, value) in enumerate(rows):
        value_text = str(value or "").strip()
        if not value_text:
            continue
        _credit(
            root,
            ns,
            credit_id=credit_id,
            credit_type=credit_type,
            text=f"{label}  {value_text}",
            x=right_x,
            y=credit_y - step * 0.72 * offset,
            font_size=credit_size,
            justify="right",
        )

    rights = str(settings.get("rights") or "").strip()
    if rights:
        _credit(
            root,
            ns,
            credit_id="rights",
            credit_type="rights",
            text=rights,
            x=center_x,
            y=max(bottom * 0.45, 10.0),
            font_size=max(7.0, credit_size - 1.0),
            justify="center",
        )


def _update_creator(identification: ET.Element, ns: str, role: str, value: str) -> None:
    existing = None
    for creator in identification.findall(f"{ns}creator"):
        if creator.get("type") == role:
            existing = creator
            break
    value = value.strip()
    if not value:
        if existing is not None:
            identification.remove(existing)
        return
    if existing is None:
        existing = ET.SubElement(identification, f"{ns}creator", {"type": role})
    existing.text = value


def _apply_identification(root: ET.Element, ns: str, settings: dict[str, Any]) -> None:
    identification = root.find(f"{ns}identification")
    if identification is None:
        identification = ET.Element(f"{ns}identification")
        _insert_root_identification(root, identification)
    _update_creator(identification, ns, "composer", str(settings.get("composer") or ""))
    _update_creator(identification, ns, "lyricist", str(settings.get("lyricist") or ""))
    _update_creator(identification, ns, "arranger", str(settings.get("arranger") or ""))

    rights_value = str(settings.get("rights") or "").strip()
    rights = identification.find(f"{ns}rights")
    if rights_value:
        if rights is None:
            rights = ET.SubElement(identification, f"{ns}rights")
        rights.text = rights_value
    elif rights is not None:
        identification.remove(rights)


def apply_publication_layout(
    path: Path,
    *,
    title: str,
    settings: dict[str, Any],
) -> None:
    settings = merged_publication_settings(settings)
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)

    defaults = _ensure_defaults(root, ns)
    millimeters, tenths = _ensure_scaling(defaults, ns)
    page_width, page_height = _apply_page_defaults(
        defaults,
        ns,
        settings,
        millimeters,
        tenths,
    )
    _clear_forced_breaks(root, ns)
    _apply_forced_breaks(root, ns, settings)
    _apply_first_page_title_space(root, ns, settings, millimeters, tenths)
    _apply_credits(
        root,
        ns,
        title,
        settings,
        page_width,
        page_height,
        millimeters,
        tenths,
    )
    _apply_identification(root, ns, settings)

    temp = path.with_suffix(".musicxml.tmp")
    tree.write(temp, encoding="utf-8", xml_declaration=True)
    temp.replace(path)
