from __future__ import annotations

import json
import math
from bisect import bisect_left
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .models import WordTiming

_HANGUL_RE = re.compile(r"[가-힣]")


def load_whisperx_words(path: Path) -> list[WordTiming]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    words: list[WordTiming] = []
    for segment in payload.get("segments", []):
        for item in segment.get("words", []) or []:
            text = str(item.get("word", "")).strip()
            start = item.get("start")
            end = item.get("end")
            if not text or start is None or end is None:
                continue
            words.append(
                WordTiming(
                    text=text,
                    start=float(start),
                    end=float(end),
                    score=float(item["score"]) if item.get("score") is not None else None,
                )
            )
    return words


def expand_korean_syllables(words: list[WordTiming]) -> list[WordTiming]:
    """Split Korean words into timed Hangul syllables.

    This is intentionally conservative: non-Korean words stay intact. Each Hangul
    syllable receives an equal share of the word duration, which is only a v0.1
    heuristic and can later be replaced by phoneme/singing forced alignment.
    """
    expanded: list[WordTiming] = []
    for word in words:
        chars = [c for c in word.text if _HANGUL_RE.fullmatch(c)]
        if len(chars) <= 1 or len(chars) != len(word.text.replace(" ", "")):
            expanded.append(word)
            continue
        duration = max(0.001, word.end - word.start)
        step = duration / len(chars)
        for i, char in enumerate(chars):
            expanded.append(
                WordTiming(
                    text=char,
                    start=word.start + i * step,
                    end=word.start + (i + 1) * step,
                    score=word.score,
                )
            )
    return expanded


@dataclass(slots=True)
class NoteRef:
    note: ET.Element
    onset_seconds: float
    part_id: str
    part_name: str


def _tempo_bpm(root: ET.Element) -> float:
    for sound in root.findall(".//sound"):
        value = sound.attrib.get("tempo")
        if value:
            try:
                bpm = float(value)
                if bpm > 0:
                    return bpm
            except ValueError:
                pass
    # MuseScore commonly emits metronome markings instead of <sound tempo>.
    per_minute = root.find(".//per-minute")
    if per_minute is not None and per_minute.text:
        try:
            bpm = float(per_minute.text)
            if bpm > 0:
                return bpm
        except ValueError:
            pass
    return 120.0


def _part_names(root: ET.Element) -> dict[str, str]:
    names: dict[str, str] = {}
    for score_part in root.findall(".//score-part"):
        part_id = score_part.attrib.get("id", "")
        name_node = score_part.find("part-name")
        names[part_id] = (name_node.text or "") if name_node is not None else ""
    return names


def _part_notes(root: ET.Element) -> dict[str, list[NoteRef]]:
    bpm = _tempo_bpm(root)
    seconds_per_quarter = 60.0 / bpm
    names = _part_names(root)
    result: dict[str, list[NoteRef]] = {}

    for part in root.findall("part"):
        part_id = part.attrib.get("id", "")
        part_name = names.get(part_id, "")
        divisions = 1.0
        cursor_q = 0.0
        notes: list[NoteRef] = []

        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                div = attrs.find("divisions")
                if div is not None and div.text:
                    try:
                        divisions = max(1.0, float(div.text))
                    except ValueError:
                        pass

            measure_cursor_q = cursor_q
            local_q = 0.0
            last_onset_q = 0.0
            max_q = 0.0

            for child in list(measure):
                if child.tag == "backup":
                    duration = child.find("duration")
                    if duration is not None and duration.text:
                        local_q -= float(duration.text) / divisions
                    continue
                if child.tag == "forward":
                    duration = child.find("duration")
                    if duration is not None and duration.text:
                        local_q += float(duration.text) / divisions
                        max_q = max(max_q, local_q)
                    continue
                if child.tag != "note":
                    continue

                duration_node = child.find("duration")
                duration_q = (
                    float(duration_node.text) / divisions
                    if duration_node is not None and duration_node.text
                    else 0.0
                )
                is_chord = child.find("chord") is not None
                onset_q = last_onset_q if is_chord else local_q

                if child.find("rest") is None and child.find("grace") is None:
                    notes.append(
                        NoteRef(
                            note=child,
                            onset_seconds=(measure_cursor_q + onset_q) * seconds_per_quarter,
                            part_id=part_id,
                            part_name=part_name,
                        )
                    )

                if not is_chord:
                    last_onset_q = local_q
                    local_q += duration_q
                    max_q = max(max_q, local_q)

            cursor_q += max_q

        result[part_id] = notes
    return result


def _nearest_distance(onsets: list[float], target: float) -> float:
    if not onsets:
        return math.inf
    return min(abs(value - target) for value in onsets)


def choose_lyric_part(root: ET.Element, words: list[WordTiming]) -> tuple[str, list[NoteRef]]:
    parts = _part_notes(root)
    if not parts:
        raise ValueError("MusicXML contains no note-bearing parts.")

    names = _part_names(root)
    explicit = [
        part_id
        for part_id, name in names.items()
        if any(token in name.lower() for token in ("voice", "vocal", "singer", "vocals"))
        and parts.get(part_id)
    ]
    if explicit:
        part_id = explicit[0]
        return part_id, parts[part_id]

    # Fallback: select the part whose note attacks best match ASR word starts.
    sample = words[: min(200, len(words))]
    scored: list[tuple[float, str]] = []
    for part_id, refs in parts.items():
        if not refs:
            continue
        onsets = [ref.onset_seconds for ref in refs]
        distance = sum(_nearest_distance(onsets, word.start) for word in sample) / max(1, len(sample))
        scored.append((distance, part_id))
    if not scored:
        raise ValueError("No candidate part found for lyric alignment.")

    _, part_id = min(scored, key=lambda x: x[0])
    return part_id, parts[part_id]


def attach_lyrics_to_musicxml(
    source: Path,
    destination: Path,
    words: list[WordTiming],
) -> tuple[str, int]:
    tree = ET.parse(source)
    root = tree.getroot()
    if not words:
        raise ValueError("No timed words available for lyric alignment.")

    part_id, notes = choose_lyric_part(root, words)
    if not notes:
        raise ValueError("Selected lyric part has no notes.")

    # Collapse chord tones that share an onset. Lyrics belong to an attack, not
    # to every pitch in a chord. This also keeps the search space compact.
    candidates: list[NoteRef] = []
    for ref in notes:
        if not candidates or abs(ref.onset_seconds - candidates[-1].onset_seconds) > 1e-6:
            candidates.append(ref)

    # Monotonic nearest-onset alignment using binary search. The previous v0.1
    # implementation scanned only the next 12 notes, which could fail on long
    # melismas or sparse ASR timestamps. This version is O(W log N) and searches
    # the complete remaining vocal part while preserving lyric order.
    onsets = [ref.onset_seconds for ref in candidates]
    note_index = 0
    attached = 0
    for word in words:
        if note_index >= len(candidates):
            break

        pos = bisect_left(onsets, word.start, lo=note_index)
        possible = []
        if pos < len(candidates):
            possible.append(pos)
        if pos - 1 >= note_index:
            possible.append(pos - 1)
        best_i = min(possible, key=lambda i: abs(onsets[i] - word.start))

        note = candidates[best_i].note
        for existing in list(note.findall("lyric")):
            note.remove(existing)

        lyric = ET.SubElement(note, "lyric")
        syllabic = ET.SubElement(lyric, "syllabic")
        syllabic.text = "single"
        text = ET.SubElement(lyric, "text")
        text.text = word.text

        attached += 1
        note_index = best_i + 1

    try:
        ET.indent(tree, space="  ")
    except AttributeError:
        pass
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return part_id, attached
