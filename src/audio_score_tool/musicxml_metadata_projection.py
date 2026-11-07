"""Project only chord/key/meter metadata onto canonical MusicXML without rewriting notes.

Music21 is used to *generate* correct MusicXML harmony spelling, but its
full-score re-export may change polyphonic chord and voice reconstruction.
Preserve every original <note>, <backup>, <forward>, lyrics and articulation.
Only trusted, bounded MusicXML with an approved standard PUBLIC DTD is parsed.
"""
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from .omr import OMRImportError, _strip_audiveris_musicxml_dtd


class AnnotationProjectionError(ValueError):
    """Safe metadata projection cannot preserve the source score structure."""


def _name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if _name(item) == name), None)


def _text(node: ET.Element, name: str, fallback: str = "") -> str:
    found = _child(node, name)
    return found.text if found is not None and found.text is not None else fallback


def _score(path: Path) -> ET.Element:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise AnnotationProjectionError("MusicXML is absent, oversized or symlinked")
    try:
        safe_xml = _strip_audiveris_musicxml_dtd(path.read_text(encoding="utf-8-sig"))
        root = ET.fromstring(safe_xml)
    except (OMRImportError, UnicodeError, ET.ParseError) as exc:
        raise AnnotationProjectionError("MusicXML contains an unsafe declaration or invalid XML") from exc
    if _name(root) != "score-partwise":
        raise AnnotationProjectionError("Only score-partwise MusicXML is supported")
    return root


def _metadata_from_measure(
    measure: ET.Element, divisions: int,
) -> tuple[list[tuple[Fraction, ET.Element]], list[ET.Element], int]:
    """Locate harmony tags in MusicXML's cursor/backup/forward score timeline."""
    cursor = Fraction(0)
    harmonies: list[tuple[Fraction, ET.Element]] = []
    attributes: list[ET.Element] = []
    for node in measure:
        kind = _name(node)
        if kind == "attributes":
            value = _text(node, "divisions")
            if value:
                divisions = int(value)
                if divisions <= 0:
                    raise AnnotationProjectionError("Invalid MusicXML divisions")
            for item in node:
                if _name(item) in {"key", "time"}:
                    if cursor != 0:
                        raise AnnotationProjectionError(
                            "Mid-measure key/time changes cannot be losslessly projected"
                        )
                    attributes.append(copy.deepcopy(item))
        elif kind == "harmony":
            onset = cursor + Fraction(_text(node, "offset", "0")) / divisions
            if onset < 0:
                raise AnnotationProjectionError("Negative harmony position")
            harmonies.append((onset, copy.deepcopy(node)))
        elif kind in {"backup", "forward"}:
            step = Fraction(_text(node, "duration", "0")) / divisions
            cursor += step if kind == "forward" else -step
        elif kind == "note" and _child(node, "chord") is None:
            cursor += Fraction(_text(node, "duration", "0")) / divisions
    return harmonies, attributes, divisions


_ATTR_ORDER = {"divisions": 0, "key": 1, "time": 2, "staves": 3, "clef": 4}


def project_musicxml_annotations(
    source: Path, augmented: Path, destination: Path,
    *, include_key: bool = True, include_meter: bool = True,
) -> None:
    """Project staged harmony/key/time, preserving source performance XML."""
    original = _score(source)
    added = _score(augmented)
    source_parts = [part for part in original if _name(part) == "part"]
    added_parts = [part for part in added if _name(part) == "part"]
    if not source_parts or len(source_parts) != len(added_parts):
        raise AnnotationProjectionError("Annotation changed part mapping")

    source_measures = [m for m in source_parts[0] if _name(m) == "measure"]
    augmented_measures = [m for m in added_parts[0] if _name(m) == "measure"]
    if not source_measures or len(source_measures) != len(augmented_measures):
        raise AnnotationProjectionError(
            "Annotation changed measure mapping: "
            f"source={[m.get('number') for m in source_measures]}, "
            f"stage={[m.get('number') for m in augmented_measures]}"
        )
    input_divisions = 1
    annotated_divisions = 1
    for measure, other in zip(source_measures, augmented_measures):
        if measure.get("number") != other.get("number"):
            raise AnnotationProjectionError("Annotation reordered source measures")
        for element in measure:
            if _name(element) == "attributes":
                value = _text(element, "divisions")
                if value:
                    input_divisions = int(value)
                    if input_divisions <= 0:
                        raise AnnotationProjectionError("Invalid input MusicXML divisions")

        harmonies, changed_attributes, annotated_divisions = _metadata_from_measure(
            other, annotated_divisions,
        )
        # Stage is annotation-only. Keep any pre-existing original harmonies
        # and append just the new annotations without touching note streams.
        changed_attributes = [
            item for item in changed_attributes
            if (_name(item) == "key" and include_key)
            or (_name(item) == "time" and include_meter)
        ]
        if changed_attributes:
            initial = next((node for node in measure if _name(node) == "attributes"), None)
            if initial is None:
                ns = measure.tag.split("}")[0] + "}" if "}" in measure.tag else ""
                initial = ET.Element(ns + "attributes")
                position = 0
                while position < len(measure) and _name(measure[position]) == "print":
                    position += 1
                measure.insert(position, initial)
            names = {_name(item) for item in changed_attributes}
            for item in list(initial):
                if _name(item) in names:
                    initial.remove(item)
            for item in changed_attributes:
                order = _ATTR_ORDER[_name(item)]
                index = next(
                    (i for i, old in enumerate(initial)
                     if _ATTR_ORDER.get(_name(old), 99) > order),
                    len(initial),
                )
                initial.insert(index, item)

        position = 0
        while position < len(measure) and _name(measure[position]) in {
            "print", "attributes", "direction",
        }:
            position += 1
        for i, (start, harmony) in enumerate(harmonies):
            # Inject metadata relative to the beginning of the measure.
            offset = _child(harmony, "offset")
            if offset is not None:
                harmony.remove(offset)
            ticks = start * input_divisions
            if ticks:
                ns = harmony.tag.split("}")[0] + "}" if "}" in harmony.tag else ""
                offset = ET.Element(ns + "offset")
                offset.text = (
                    str(ticks.numerator)
                    if ticks.denominator == 1 else format(float(ticks), ".12g")
                )
                before_staff = next(
                    (j for j, child in enumerate(harmony) if _name(child) == "staff"),
                    len(harmony),
                )
                harmony.insert(before_staff, offset)
            measure.insert(position + i, harmony)

    destination.write_bytes(ET.tostring(original, encoding="utf-8", xml_declaration=True))
