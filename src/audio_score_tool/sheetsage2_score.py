"""Import the official model's notated Vocal voice, retaining its raw predictions."""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

MODEL_REVISION = "b83c3d79a6d98bcffaf8f9ed112c90aa887887bc"
CHECKPOINT_SHA256 = "b235f68091a5f5b644000f2b5acb57d1e70432aca2b34ab1b9cf27236e1f4274"
BASE_REVISION = "d8ba1c745e733b3908ce6ad16ebeb17ac7600a42"


def _parse_vocal_abc(text):
    from music21 import abcFormat
    from music21.abcFormat import translate

    class NativeABCHandler(abcFormat.ABCHandler):
        def tokensToBarIndices(self):
            # Upstream treats mid-song metadata as a bar boundary and drops it.
            return [i for i, token in enumerate(self.tokens) if isinstance(token, abcFormat.ABCBar)]

    handler = NativeABCHandler()
    handler.process(text)
    return translate.abcToStreamScore(handler)


def vocal_abc(text: str) -> str:
    """music21 splits repeated V: declarations into new parts; collect one voice."""
    header, body = [], []
    in_body, active = False, None
    for line in text.splitlines():
        if line.startswith("V:"):
            active = line[2:].strip().split()[0]
            continue
        if not in_body:
            header.append(line)
            if line.startswith("K:"):
                in_body, active = True, None
        elif active == "Vocal":
            body.append(line)
    if not in_body or not body:
        raise ValueError("Official score has no explicit Vocal voice")
    # music21 ignores ABC multi-measure rests; expand with the declared meter/unit.
    meter, unit = None, None
    expanded = []
    for line in header + body:
        if line.startswith("M:"):
            meter = Fraction(line[2:].strip())
        elif line.startswith("L:"):
            unit = Fraction(line[2:].strip())

        def expand_rest(match):
            if match.group(1) is None:
                return match.group(0)  # Quoted chord/annotation.
            count = int(match.group(1) or 1)
            if meter is None or unit is None or not 1 <= count <= 4096:
                raise ValueError("Invalid ABC multi-measure rest")
            duration = meter / unit
            return "|".join(f"z{duration}" for _ in range(count))

        metadata = line.startswith("%") or bool(re.match(r"^[A-Za-z]:", line))
        expanded.append(line if metadata else re.sub(r'"[^"\n]*"|Z(\d*)', expand_rest, line))
    return "\n".join(expanded) + "\n"


def import_native_lead_sheet(root: Path, target: Path) -> dict:
    from music21 import converter, harmony, note, stream, tempo
    from music21.exceptions21 import Music21Exception

    abc = root / "score.abc"
    playback = root / "playback.json"
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 16 * 1024 * 1024
           for p in (abc, playback)):
        raise ValueError("Official notated score/playback is absent or unsafe")
    try:
        text = vocal_abc(abc.read_text())
        score = _parse_vocal_abc(text)
        if not list(score.recurse().getElementsByClass(stream.Measure)):
            score.makeMeasures(inPlace=True)
    except Music21Exception as exc:
        raise ValueError("Official Vocal ABC could not be imported") from exc
    if len(score.parts) != 1 or not list(score.recurse().getElementsByClass(note.Note)):
        raise ValueError("SheetSage2 did not produce a vocal melody")
    part = score.parts[0]
    part.partName = "Vocal"
    measures = list(part.getElementsByClass(stream.Measure))
    playback_data = json.loads(playback.read_text())
    mapping = playback_data.get("measures") if isinstance(playback_data, dict) else None
    if not isinstance(mapping, list) or len(mapping) != len(measures):
        raise ValueError("ABC import changed the model's measure count")
    original_marks = list(part.recurse().getElementsByClass(tempo.MetronomeMark))
    nominal_bpm = original_marks[0].getQuarterBPM() if original_marks else None
    for mark in original_marks:
        mark.activeSite.remove(mark)
    previous_end = None
    initial_offset = 0.0
    for index, (measure, row) in enumerate(zip(measures, mapping, strict=True)):
        measure.number = index + 1
        if not isinstance(row, dict) or any(
            type(row.get(name)) not in (int, float)
            for name in ("start", "end", "score_start", "score_end")
        ):
            raise ValueError("Invalid SheetSage2 measure clock")
        start, end = float(row["start"]), float(row["end"])
        begin, finish = 4 * float(row["score_start"]), 4 * float(row["score_end"])
        leading, trailing = 4 * float(row.get("leading_rest", 0)), 4 * float(row.get("trailing_rest", 0))
        if (not all(math.isfinite(x) for x in (start, end, begin, finish))
                or start < 0 or (previous_end is not None and abs(start - previous_end) > 1e-6)
                or end <= start or finish <= begin
                or not all(math.isfinite(x) and x >= 0 for x in (leading, trailing))
                or leading + trailing >= finish - begin
                or (leading and index != 0) or (trailing and index != len(mapping) - 1)
                or abs(float(measure.getOffsetBySite(part)) - begin) > 1e-6
                or abs(float(measure.duration.quarterLength) - (finish - begin)) > 1e-6):
            raise ValueError("ABC import changed the model's beat/measure grid")
        if leading:
            padding = tempo.MetronomeMark(number=60 * leading / max(start, leading * 1e-6))
            padding.style.hideObjectOnPrint = True
            measure.insert(0, padding)
        elif index == 0:
            initial_offset = start
        mark = tempo.MetronomeMark(number=60 * (finish - begin - leading - trailing) / (end - start))
        mark.style.hideObjectOnPrint = index > 0
        measure.insert(leading, mark)
        if trailing:
            padding = tempo.MetronomeMark(number=60_000_000)
            padding.style.hideObjectOnPrint = True
            measure.insert(finish - begin - trailing, padding)
        previous_end = end
    target.parent.mkdir(parents=True, exist_ok=True)
    score.write("musicxml", fp=str(target))
    # music21 omits this flag on tempo marks; serialize MusicXML's print-object.
    tree = ET.parse(target)
    xml_measures = tree.getroot().findall("./part/measure")
    for xml_measure in xml_measures:
        for direction in xml_measure.findall("direction"):
            sound = direction.find("sound[@tempo]")
            metronome = direction.find("./direction-type/metronome")
            if sound is None or metronome is None:
                continue
            metronome.set("print-object", "no")
    if nominal_bpm is not None:
        # Words cannot override the exact playback clock on MusicXML reload.
        visible = ET.Element("direction", placement="above")
        kind = ET.SubElement(visible, "direction-type")
        ET.SubElement(kind, "words").text = "♩ ≈ " + f"{nominal_bpm:.2f}".rstrip("0").rstrip(".")
        first = xml_measures[0]
        attributes = first.find("attributes")
        first.insert(list(first).index(attributes) + 1 if attributes is not None else 0, visible)
    tree.write(target, encoding="utf-8", xml_declaration=True)
    restored = converter.parse(str(target))
    restored_measures = list(restored.parts[0].getElementsByClass(stream.Measure))
    if len(restored_measures) != len(mapping) or any(
        abs(float(m.getOffsetBySite(restored.parts[0])) - float(row["score_start"]) * 4) > 1e-6
        or abs(float(m.duration.quarterLength) - (float(row["score_end"]) - float(row["score_start"])) * 4) > 1e-6
        for m, row in zip(restored_measures, mapping, strict=True)
    ):
        raise ValueError("MusicXML serialization changed the model's measure grid")
    return {"model_revision": MODEL_REVISION, "checkpoint_sha256": CHECKPOINT_SHA256,
            "measures": len(measures), "vocal_notes": len(list(part.recurse().getElementsByClass(note.Note))),
            "chord_symbols": len(list(part.recurse().getElementsByClass(harmony.ChordSymbol))),
            "timing": "model_notation_with_per_measure_audio_clock",
            "initial_audio_offset_seconds": initial_offset,
            "padding_clock_epsilon_seconds_per_quarter": 1e-6,
            "visible_tempo_decimal_places": 2,
            "nominal_tempo_bpm": nominal_bpm,
            "raw_predictions_preserved": True}
