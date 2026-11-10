"""Import the official model's notated Vocal voice, retaining its raw predictions."""
from __future__ import annotations

import bisect
import copy
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

    # The official writer carries accidentals by letter across octaves to the barline.
    handler = NativeABCHandler(abcVersion=(2, 1, 0))
    text = re.sub(r'"[^"\n]*"|\[K:([^]\n]+)\]',
                  lambda match: f"\nK:{match.group(1)}\n" if match.group(1) else match.group(0), text)
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
    from music21 import clef, converter, harmony, metadata, meter, note, stream, tempo
    from music21.exceptions21 import Music21Exception

    abc = root / "score.abc"
    playback = root / "playback.json"
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size > 16 * 1024 * 1024
           for p in (abc, playback)):
        raise ValueError("Official notated score/playback is absent or unsafe")
    try:
        raw_abc = abc.read_text()
        text = vocal_abc(raw_abc)
        score = _parse_vocal_abc(text)
        if not list(score.recurse().getElementsByClass(stream.Measure)):
            score.makeMeasures(inPlace=True)
    except Music21Exception as exc:
        raise ValueError("Official Vocal ABC could not be imported") from exc
    if len(score.parts) != 1 or not list(score.recurse().getElementsByClass(note.Note)):
        raise ValueError("SheetSage2 did not produce a vocal melody")
    part = score.parts[0]
    part.partName = "Vocal"
    declared = re.findall(r"(?m)^V:\s*Vocal\b[^\n]*\bclef=(\S+)", raw_abc)
    if declared:
        choices = {"treble": clef.TrebleClef, "bass": clef.BassClef,
                   "alto": clef.AltoClef, "tenor": clef.TenorClef}
        if len(set(declared)) != 1 or declared[0] not in choices:
            raise ValueError("Unsupported or changing native Vocal clef")
        for original in list(part.recurse().getElementsByClass(clef.Clef)):
            original.activeSite.remove(original)
        # Applying the display clef after ABC parsing avoids its bass octave shift.
        part.getElementsByClass(stream.Measure).first().insert(0, choices[declared[0]]())
    performed = list(part.recurse().getElementsByClass(note.Note))
    respellings = 0
    for previous, current in zip(performed, performed[1:]):
        if (previous.tie and previous.tie.type in {"start", "continue"}
                and current.tie and current.tie.type in {"continue", "stop"}
                and previous.pitch.ps == current.pitch.ps
                and previous.pitch.nameWithOctave != current.pitch.nameWithOctave
                and abs(float(previous.getOffsetInHierarchy(part) + previous.quarterLength
                              - current.getOffsetInHierarchy(part))) < 1e-8):
            # Keep one written pitch through a tied key change; raw ABC is unchanged.
            current.pitch = copy.deepcopy(previous.pitch)
            if current.pitch.accidental is not None:
                current.pitch.accidental.displayStatus = True
            respellings += 1
    measures = list(part.getElementsByClass(stream.Measure))
    playback_data = json.loads(playback.read_text())
    mapping = playback_data.get("measures") if isinstance(playback_data, dict) else None
    if not isinstance(mapping, list) or len(mapping) != len(measures):
        raise ValueError("ABC import changed the model's measure count")
    beat_file = root / "notation" / "song_beats.txt"
    beat_times = None
    if beat_file.exists() or beat_file.is_symlink():
        if (beat_file.parent.is_symlink() or beat_file.is_symlink()
                or not beat_file.is_file() or beat_file.stat().st_size > 16 * 1024 * 1024):
            raise ValueError("Unsafe native beat clock")
        beat_times = []
        for line in beat_file.read_text().splitlines():
            row = line.split()
            if len(row) != 4:
                raise ValueError("Invalid native beat clock columns")
            at, beat, numerator, denominator = float(row[0]), *map(int, row[1:])
            if (not math.isfinite(at) or at < 0 or beat < 1 or numerator < 1
                    or denominator < 1 or denominator & (denominator - 1)
                    or (beat_times and at <= beat_times[-1])):
                raise ValueError("Invalid native beat clock event")
            beat_times.append(at)
        if len(beat_times) < 2:
            raise ValueError("Incomplete native beat clock")
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
        if beat_times is None:
            segments = [(leading, finish - begin - leading - trailing, end - start)]
        else:
            signature = measure.timeSignature or measure.getContextByClass(meter.TimeSignature)
            if signature is None:
                raise ValueError("Native beat clock requires an explicit meter")
            step = 4 / signature.denominator
            count = (finish - begin - leading - trailing) / step
            first = bisect.bisect_left(beat_times, start - 1e-6)
            if (abs(count - round(count)) > 1e-6 or count < 1
                    or first + round(count) >= len(beat_times)
                    or abs(beat_times[first] - start) > 1e-6):
                raise ValueError("Native beats do not cover the notated measure")
            times = beat_times[first:first + round(count) + 1]
            if abs(times[-1] - end) > 1e-6:
                if index != len(mapping) - 1 or not times[-2] < end < times[-1]:
                    raise ValueError("Native beats disagree with the measure audio clock")
                times[-1] = end  # The source recording can end inside the final beat.
            segments = [(leading + k * step, step, b - a)
                        for k, (a, b) in enumerate(zip(times, times[1:]))]
        for position, length, seconds in segments:
            mark = tempo.MetronomeMark(number=60 * length / seconds)
            mark.style.hideObjectOnPrint = True
            measure.insert(position, mark)
        if trailing:
            padding = tempo.MetronomeMark(number=60_000_000)
            padding.style.hideObjectOnPrint = True
            measure.insert(finish - begin - trailing, padding)
        previous_end = end
    if initial_offset:
        from .score_timing import AUDIO_ORIGIN_FIELD

        if score.metadata is None:
            score.metadata = metadata.Metadata()
        score.metadata.addCustom(AUDIO_ORIGIN_FIELD, str(initial_offset))
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
            "enharmonic_tie_respellings": respellings,
            "chord_symbols": len(list(part.recurse().getElementsByClass(harmony.ChordSymbol))),
            "timing": ("model_notation_with_per_beat_audio_clock" if beat_times is not None
                       else "model_notation_with_per_measure_audio_clock"),
            "initial_audio_offset_seconds": initial_offset,
            "padding_clock_epsilon_seconds_per_quarter": 1e-6,
            "visible_tempo_decimal_places": 2,
            "nominal_tempo_bpm": nominal_bpm,
            "raw_predictions_preserved": True}
