from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChordInference:
    measure_index: int
    measure: str
    offset_quarters: float
    symbol: str
    confidence: float
    target_note_id: str | None = None


_QUALITIES: tuple[tuple[str, str, tuple[int, ...], float], ...] = (
    ("", "major", (0, 4, 7), 0.00),
    ("m", "minor", (0, 3, 7), 0.00),
    ("7", "dominant", (0, 4, 7, 10), 0.12),
    ("maj7", "major-seventh", (0, 4, 7, 11), 0.14),
    ("m7", "minor-seventh", (0, 3, 7, 10), 0.12),
    ("dim", "diminished", (0, 3, 6), 0.08),
    ("m7b5", "half-diminished", (0, 3, 6, 10), 0.16),
    ("aug", "augmented", (0, 4, 8), 0.10),
    ("sus2", "suspended-second", (0, 2, 7), 0.10),
    ("sus4", "suspended-fourth", (0, 5, 7), 0.10),
)

_NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_NOTE_NAMES_FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_FLAT_KEYS = {-7, -6, -5, -4, -3, -2, -1}


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0] + "}"
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _pitch_class(pitch: ET.Element, ns: str) -> tuple[int, int] | None:
    step = pitch.findtext(f"{ns}step")
    octave_text = pitch.findtext(f"{ns}octave")
    if not step or octave_text is None:
        return None
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}.get(step.upper())
    if base is None:
        return None
    try:
        octave = int(octave_text)
        alter = int(float(pitch.findtext(f"{ns}alter") or "0"))
    except ValueError:
        return None
    midi = (octave + 1) * 12 + base + alter
    return midi % 12, midi


def _part_weight(name: str) -> float:
    lowered = name.lower()
    if any(token in lowered for token in ("drum", "percussion", "kit")):
        return 0.0
    if "bass" in lowered:
        return 1.45
    if any(token in lowered for token in ("piano", "keyboard", "organ", "guitar", "harp")):
        return 1.30
    if any(token in lowered for token in ("vocal", "voice", "singer", "choir", "alto", "soprano", "tenor")):
        return 0.72
    return 1.0


def _part_names(root: ET.Element, ns: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for score_part in root.findall(f".//{ns}score-part"):
        part_id = score_part.get("id") or ""
        names[part_id] = score_part.findtext(f"{ns}part-name") or part_id
    return names


def _measure_signature(measure: ET.Element, ns: str, state: dict[str, Any]) -> None:
    attributes = measure.find(f"{ns}attributes")
    if attributes is None:
        return
    divisions = attributes.findtext(f"{ns}divisions")
    if divisions:
        try:
            state["divisions"] = max(1.0, float(divisions))
        except ValueError:
            pass
    time = attributes.find(f"{ns}time")
    if time is not None:
        try:
            state["beats"] = max(1, int(time.findtext(f"{ns}beats") or state["beats"]))
            state["beat_type"] = max(
                1, int(time.findtext(f"{ns}beat-type") or state["beat_type"])
            )
        except ValueError:
            pass
    key = attributes.find(f"{ns}key")
    if key is not None:
        try:
            state["fifths"] = int(key.findtext(f"{ns}fifths") or state["fifths"])
        except ValueError:
            pass


def _measure_events(
    measure: ET.Element,
    ns: str,
    state: dict[str, Any],
    weight: float,
) -> tuple[list[dict[str, float | int]], list[tuple[int, float]]]:
    _measure_signature(measure, ns, state)
    divisions = float(state["divisions"])
    cursor = 0.0
    previous_onset = 0.0
    events: list[dict[str, float | int]] = []
    note_onsets: list[tuple[int, float]] = []
    note_index = -1

    for child in list(measure):
        local = _local_name(child.tag)
        if local == "backup":
            try:
                cursor -= float(child.findtext(f"{ns}duration") or "0") / divisions
            except ValueError:
                pass
            continue
        if local == "forward":
            try:
                cursor += float(child.findtext(f"{ns}duration") or "0") / divisions
            except ValueError:
                pass
            continue
        if local != "note":
            continue

        note_index += 1
        is_chord = child.find(f"{ns}chord") is not None
        onset = previous_onset if is_chord else cursor
        note_onsets.append((note_index, onset))
        try:
            duration = float(child.findtext(f"{ns}duration") or "0") / divisions
        except ValueError:
            duration = 0.0
        if child.find(f"{ns}grace") is not None:
            duration = 0.0

        pitch = child.find(f"{ns}pitch")
        if pitch is not None and weight > 0:
            parsed = _pitch_class(pitch, ns)
            if parsed is not None:
                pitch_class, midi = parsed
                events.append(
                    {
                        "pc": pitch_class,
                        "midi": midi,
                        "onset": onset,
                        "duration": max(duration, 0.12),
                        "weight": weight,
                    }
                )

        if not is_chord:
            previous_onset = onset
            cursor += duration

    return events, note_onsets


def _slot_size(beats: int, beat_type: int) -> float:
    beat_quarters = 4.0 / beat_type
    if beat_type == 8 and beats >= 6 and beats % 3 == 0:
        return beat_quarters * 3.0
    if beat_quarters < 0.75:
        return 1.0
    return beat_quarters


def _score_candidate(
    histogram: list[float],
    root: int,
    intervals: tuple[int, ...],
    complexity_penalty: float,
    bass_pc: int | None,
) -> tuple[float, float]:
    total = sum(histogram)
    if total <= 0:
        return -math.inf, 0.0
    template = {(root + interval) % 12 for interval in intervals}
    inside = sum(histogram[pc] for pc in template)
    outside = total - inside
    present = sum(1 for pc in template if histogram[pc] >= total * 0.035)
    coverage = present / len(template)
    root_strength = histogram[root] / total
    bass_bonus = 0.18 * total if bass_pc == root else 0.0
    score = (
        inside
        - outside * 0.58
        + root_strength * total * 0.42
        + coverage * total * 0.32
        + bass_bonus
        - complexity_penalty * total
    )
    confidence = max(0.0, min(1.0, inside / total * 0.72 + coverage * 0.28))
    return score, confidence


def _best_chord(
    events: list[dict[str, float | int]],
    start: float,
    end: float,
    *,
    use_flats: bool,
) -> tuple[str, float] | None:
    histogram = [0.0] * 12
    bass_event: tuple[int, float] | None = None
    for event in events:
        event_start = float(event["onset"])
        event_end = event_start + float(event["duration"])
        overlap = max(0.0, min(end, event_end) - max(start, event_start))
        if overlap <= 0:
            continue
        weight = float(event["weight"]) * max(overlap, 0.08)
        pc = int(event["pc"])
        histogram[pc] += weight
        midi = int(event["midi"])
        if bass_event is None or midi < bass_event[0]:
            bass_event = (midi, weight)

    total = sum(histogram)
    active_classes = sum(1 for value in histogram if value >= total * 0.04) if total else 0
    if total < 0.12 or active_classes < 2:
        return None

    bass_pc = bass_event[0] % 12 if bass_event else None
    names = _NOTE_NAMES_FLAT if use_flats else _NOTE_NAMES_SHARP
    best: tuple[float, str, float] | None = None
    second_score = -math.inf
    for root in range(12):
        for suffix, _kind, intervals, penalty in _QUALITIES:
            score, confidence = _score_candidate(histogram, root, intervals, penalty, bass_pc)
            symbol = f"{names[root]}{suffix}"
            if best is None or score > best[0]:
                if best is not None:
                    second_score = best[0]
                best = (score, symbol, confidence)
            elif score > second_score:
                second_score = score

    if best is None:
        return None
    margin = best[0] - second_score if math.isfinite(second_score) else best[0]
    separation = max(0.0, min(1.0, margin / max(total, 0.01) * 1.8))
    confidence = best[2] * 0.82 + separation * 0.18
    if confidence < 0.48:
        return None
    return best[1], round(confidence, 3)


def infer_chords(path: Path) -> list[ChordInference]:
    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    names = _part_names(root, ns)
    parts = root.findall(f"{ns}part")
    if not parts:
        return []

    per_measure: dict[int, list[dict[str, float | int]]] = {}
    signatures: dict[int, dict[str, Any]] = {}
    anchors_by_part: dict[int, dict[int, list[tuple[int, float]]]] = {}
    part_weights: dict[int, float] = {}

    for part_index, part in enumerate(parts):
        part_id = part.get("id") or f"P{part_index + 1}"
        weight = _part_weight(names.get(part_id, part_id))
        part_weights[part_index] = weight
        state: dict[str, Any] = {"divisions": 1.0, "beats": 4, "beat_type": 4, "fifths": 0}
        anchors_by_part[part_index] = {}
        for measure_index, measure in enumerate(part.findall(f"{ns}measure")):
            events, note_onsets = _measure_events(measure, ns, state, weight)
            per_measure.setdefault(measure_index, []).extend(events)
            anchors_by_part[part_index][measure_index] = note_onsets
            if measure_index not in signatures:
                signatures[measure_index] = dict(state)

    candidate_parts = [
        index
        for index, part in enumerate(parts)
        if part_weights[index] > 0
        and any(anchors_by_part[index].get(mi) for mi in anchors_by_part[index])
    ]
    if not candidate_parts:
        return []

    def target_rank(index: int) -> tuple[int, int]:
        part = parts[index]
        part_id = part.get("id") or f"P{index + 1}"
        name = names.get(part_id, part_id).lower()
        if any(token in name for token in ("vocal", "voice", "singer", "alto", "soprano", "tenor")):
            return (0, index)
        if any(token in name for token in ("piano", "keyboard", "guitar", "organ")):
            return (1, index)
        if "bass" in name:
            return (3, index)
        return (2, index)

    target_part = sorted(candidate_parts, key=target_rank)[0]
    inferences: list[ChordInference] = []
    previous_symbol: str | None = None

    target_measures = parts[target_part].findall(f"{ns}measure")
    for measure_index, measure in enumerate(target_measures):
        state = signatures.get(
            measure_index,
            {"beats": 4, "beat_type": 4, "fifths": 0, "divisions": 1.0},
        )
        beats = int(state["beats"])
        beat_type = int(state["beat_type"])
        measure_quarters = beats * 4.0 / beat_type
        slot = _slot_size(beats, beat_type)
        events = per_measure.get(measure_index, [])
        anchors = anchors_by_part[target_part].get(measure_index, [])
        if not anchors:
            continue
        measure_number = measure.get("number") or str(measure_index + 1)
        offset = 0.0
        while offset < measure_quarters - 1e-6:
            end = min(measure_quarters, offset + slot)
            best = _best_chord(
                events,
                offset,
                end,
                use_flats=int(state.get("fifths", 0)) in _FLAT_KEYS,
            )
            if best is not None:
                symbol, confidence = best
                if symbol != previous_symbol:
                    note_index, _note_onset = min(
                        anchors,
                        key=lambda item: abs(item[1] - offset),
                    )
                    inferences.append(
                        ChordInference(
                            measure_index=measure_index,
                            measure=measure_number,
                            offset_quarters=round(offset, 3),
                            symbol=symbol,
                            confidence=confidence,
                            target_note_id=f"p{target_part}-m{measure_index}-n{note_index}",
                        )
                    )
                    previous_symbol = symbol
            offset += slot
    return inferences


def apply_inferred_chords(path: Path, *, report_path: Path | None = None) -> list[ChordInference]:
    from .chord_editor import set_chord_at_note

    tree = ET.parse(path)
    root = tree.getroot()
    ns = _namespace(root)
    if root.findall(f".//{ns}harmony"):
        return []

    inferred = infer_chords(path)
    applied: list[ChordInference] = []
    used_notes: set[str] = set()
    for chord in inferred:
        if not chord.target_note_id or chord.target_note_id in used_notes:
            continue
        set_chord_at_note(path, chord.target_note_id, chord.symbol)
        used_notes.add(chord.target_note_id)
        applied.append(chord)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps([asdict(item) for item in applied], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return applied
