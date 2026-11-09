"""Import performed MIDI events without music21's implicit quantization.

MIDI timing is already expressed in integer ticks.  Retain that resolution in
MusicXML instead of snapping nearby attacks into chords.  Only exactly equal
onsets AND offsets share a chord; overlapping rhythms use stable voices, with
explicit ties at bar boundaries.  This is a transcription-preserving import,
not a rhythm-cleanup or instrument-inference pass.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import mido


@dataclass(frozen=True)
class _Note:
    track: int
    channel: int
    program: int
    pitch: int
    velocity: int
    start: int
    end: int


def _text(parent: ET.Element, name: str, value: object) -> ET.Element:
    node = ET.SubElement(parent, name)
    node.text = str(value)
    return node


def _note_type(node: ET.Element, ticks: int, divisions: int) -> None:
    """Specify ordinary notation only when it represents the exact duration.

    MusicXML permits duration without type.  Arbitrary performance timings must
    not be rounded merely to invent a conventional note value or tuplet.
    """
    length = Fraction(ticks, divisions)
    for name, base in (
        ("whole", Fraction(4)), ("half", Fraction(2)), ("quarter", Fraction(1)),
        ("eighth", Fraction(1, 2)), ("16th", Fraction(1, 4)),
        ("32nd", Fraction(1, 8)), ("64th", Fraction(1, 16)),
        ("128th", Fraction(1, 32)), ("256th", Fraction(1, 64)),
    ):
        for dots in range(3):
            if length == base * (2 - Fraction(1, 2**dots)):
                _text(node, "type", name)
                for _ in range(dots):
                    ET.SubElement(node, "dot")
                return


def _rest(measure: ET.Element, ticks: int, voice: int, divisions: int) -> None:
    if ticks <= 0:
        return
    node = ET.SubElement(measure, "note")
    ET.SubElement(node, "rest")
    _text(node, "duration", ticks)
    _text(node, "voice", voice)
    _note_type(node, ticks, divisions)


def _read_midi(source: Path):
    midi = mido.MidiFile(source)
    if midi.type == 2 or midi.ticks_per_beat <= 0:
        raise ValueError("Only synchronous, metrical MIDI type 0/1 is supported")
    events = []
    names = {}
    for track_index, track in enumerate(midi.tracks):
        tick = 0
        for index, message in enumerate(track):
            tick += message.time
            events.append((tick, track_index, index, message))
            if message.type == "track_name" and message.name.strip():
                names.setdefault(track_index, message.name.strip())
    events.sort(key=lambda row: row[:3])
    programs = defaultdict(int)
    active = defaultdict(deque)
    notes = []
    # Absence of a tempo event means MIDI's standard 120 BPM. Do not invent a
    # visible metronome marking in a score which never supplied one.
    tempos = {}
    meters = {0: (4, 4)}
    keys = {}
    lyrics = defaultdict(list)
    for tick, track, _index, message in events:
        if message.type == "set_tempo":
            if message.tempo <= 0:
                raise ValueError("MIDI tempo must be positive")
            tempos[tick] = message.tempo
        elif message.type == "time_signature":
            if message.numerator <= 0:
                raise ValueError("MIDI time signature must be positive")
            meters[tick] = (message.numerator, message.denominator)
        elif message.type == "key_signature":
            keys[tick] = message.key
        elif message.type == "lyrics":
            lyrics[(track, tick)].append(message.text)
        elif message.type == "program_change":
            programs[message.channel] = message.program
        elif message.type == "note_on" and message.velocity > 0:
            active[(message.channel, message.note)].append((
                tick, track, programs[message.channel], message.velocity,
            ))
        elif message.type in {"note_off", "note_on"}:
            pending = active[(message.channel, message.note)]
            if not pending:
                continue
            start, original_track, program, velocity = pending.popleft()
            if tick <= start:
                raise ValueError("MIDI contains a performed note with no positive duration")
            notes.append(_Note(
                original_track, message.channel, program, message.note,
                velocity, start, tick,
            ))
    if any(active.values()):
        raise ValueError("MIDI contains unterminated performed notes")
    if not notes:
        raise ValueError("MIDI contains no performed notes")
    return midi.ticks_per_beat, names, notes, tempos, meters, keys, lyrics


def _voices(notes: list[_Note]) -> list[list[list[_Note]]]:
    """Interval partitioning, joining only exactly coincident distinct pitches."""
    groups: dict[tuple[int, int], list[list[_Note]]] = defaultdict(list)
    for note in sorted(notes, key=lambda n: (n.start, n.end, n.pitch)):
        siblings = groups[(note.start, note.end)]
        chord = next((c for c in siblings if all(n.pitch != note.pitch for n in c)), None)
        if chord is None:
            chord = []
            siblings.append(chord)
        chord.append(note)
    voices: list[list[list[_Note]]] = []
    for span in sorted(groups):
        for chord in groups[span]:
            voice = next((v for v in voices if v[-1][0].end <= span[0]), None)
            if voice is None:
                voice = []
                voices.append(voice)
            voice.append(chord)
    return voices


def _bars(end: int, divisions: int, meters: dict[int, tuple[int, int]]):
    changes = sorted(meters)
    start = 0
    index = 0
    while start < end:
        while index + 1 < len(changes) and changes[index + 1] <= start:
            index += 1
        numerator, denominator = meters[changes[index]]
        finish = start + divisions * numerator * 4 // denominator
        if index + 1 < len(changes):
            finish = min(finish, changes[index + 1])
        yield start, finish, (numerator, denominator)
        start = finish


def midi_to_score_xml(source: Path, target: Path) -> Path:
    """Write one score part per source track/channel/program, at original ticks."""
    ppq, names, notes, tempos, meters, keys, lyrics = _read_midi(source)
    # Also represent fractional bar lengths for unusual PPQ/meter combinations.
    divisions = math.lcm(ppq, *(denominator for _, denominator in meters.values()))
    scale = divisions // ppq
    notes = [_Note(n.track, n.channel, n.program, n.pitch, n.velocity,
                   n.start * scale, n.end * scale) for n in notes]
    tempos = {tick * scale: value for tick, value in tempos.items()}
    meters = {tick * scale: value for tick, value in meters.items()}
    keys = {tick * scale: value for tick, value in keys.items()}
    lyrics = {(track, tick * scale): text for (track, tick), text in lyrics.items()}
    parts = defaultdict(list)
    for note in notes:
        parts[(note.track, note.channel, note.program)].append(note)
    bars = list(_bars(max(n.end for n in notes), divisions, meters))
    root = ET.Element("score-partwise", version="4.0")
    part_list = ET.SubElement(root, "part-list")
    from music21 import instrument, key

    for number, ((track, channel, program), part_notes) in enumerate(sorted(parts.items()), 1):
        part_id = f"P{number}"
        is_drum = channel == 9
        display = "Drums" if is_drum else instrument.instrumentFromMidiProgram(program).instrumentName
        score_part = ET.SubElement(part_list, "score-part", id=part_id)
        _text(score_part, "part-name", names.get(track) or display or f"GM {program}")
        pitches = sorted({n.pitch for n in part_notes}) if is_drum else [None]
        for pitch in pitches:
            instrument_id = f"{part_id}-I{pitch if pitch is not None else 1}"
            score_instrument = ET.SubElement(score_part, "score-instrument", id=instrument_id)
            _text(score_instrument, "instrument-name", display or f"GM {program}")
            midi_instrument = ET.SubElement(score_part, "midi-instrument", id=instrument_id)
            # Pitched MIDI channel assignment is playback-dependent. Retaining
            # recycled source channels across different program parts would let
            # a later part's program change overwrite the earlier part at t=0.
            if is_drum:
                _text(midi_instrument, "midi-channel", 10)
            _text(midi_instrument, "midi-program", program + 1)
            if pitch is not None:
                _text(midi_instrument, "midi-unpitched", pitch + 1)
        part = ET.SubElement(root, "part", id=part_id)
        voices = _voices(part_notes)
        for bar_index, (start, finish, signature) in enumerate(bars):
            measure = ET.SubElement(part, "measure", number=str(bar_index + 1))
            if bar_index == 0 or start in meters:
                attrs = ET.SubElement(measure, "attributes")
                if bar_index == 0:
                    _text(attrs, "divisions", divisions)
                time = ET.SubElement(attrs, "time")
                _text(time, "beats", signature[0])
                _text(time, "beat-type", signature[1])
                if bar_index == 0:
                    clef = ET.SubElement(attrs, "clef")
                    bass = not is_drum and sum(n.pitch for n in part_notes) / len(part_notes) < 60
                    _text(clef, "sign", "percussion" if is_drum else "F" if bass else "G")
                    if not is_drum:
                        _text(clef, "line", 4 if bass else 2)
            for tick, name in sorted(keys.items()):
                if not start <= tick < finish:
                    continue
                offset = tick - start
                if offset:
                    _text(ET.SubElement(measure, "forward"), "duration", offset)
                attrs = ET.SubElement(measure, "attributes")
                key_node = ET.SubElement(attrs, "key")
                minor = name.endswith("m")
                parsed_key = key.Key(
                    (name[:-1] if minor else name).replace("b", "-"),
                    "minor" if minor else "major",
                )
                _text(key_node, "fifths", parsed_key.sharps)
                _text(key_node, "mode", parsed_key.mode)
                if offset:
                    _text(ET.SubElement(measure, "backup"), "duration", offset)
            if number == 1:
                for tick, value in sorted(tempos.items()):
                    if start <= tick < finish:
                        direction = ET.SubElement(measure, "direction")
                        bpm = format(60_000_000 / value, ".12g")
                        # A plain-text marking stays printable in the embedded
                        # PDF renderer; SMuFL metronome text is not a text font.
                        _text(ET.SubElement(direction, "direction-type"), "words", f"{bpm} BPM")
                        _text(direction, "offset", tick - start).set("sound", "yes")
                        ET.SubElement(direction, "sound", tempo=bpm)
            for voice_number, voice in enumerate(voices, 1):
                if voice_number > 1:
                    _text(ET.SubElement(measure, "backup"), "duration", finish - start)
                cursor = start
                for chord in voice:
                    onset, offset = chord[0].start, chord[0].end
                    begin, end = max(start, onset), min(finish, offset)
                    if end <= begin:
                        continue
                    _rest(measure, begin - cursor, voice_number, divisions)
                    for chord_index, performed in enumerate(chord):
                        node = ET.SubElement(measure, "note", dynamics=format(performed.velocity * 100 / 90, ".6g"))
                        if chord_index:
                            ET.SubElement(node, "chord")
                        if is_drum:
                            unpitched = ET.SubElement(node, "unpitched")
                            _text(unpitched, "display-step", "C")
                            _text(unpitched, "display-octave", 5)
                        else:
                            pitch_node = ET.SubElement(node, "pitch")
                            step, alter = (("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
                                           ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0))[performed.pitch % 12]
                            _text(pitch_node, "step", step)
                            if alter:
                                _text(pitch_node, "alter", alter)
                            _text(pitch_node, "octave", performed.pitch // 12 - 1)
                        _text(node, "duration", end - begin)
                        ties = (["stop"] if begin > onset else []) + (["start"] if end < offset else [])
                        for kind in ties:
                            ET.SubElement(node, "tie", type=kind)
                        ET.SubElement(node, "instrument", id=f"{part_id}-I{performed.pitch if is_drum else 1}")
                        _text(node, "voice", voice_number)
                        _note_type(node, end - begin, divisions)
                        if ties:
                            notations = ET.SubElement(node, "notations")
                            for kind in ties:
                                ET.SubElement(notations, "tied", type=kind)
                        if not chord_index and begin == onset:
                            text = lyrics.pop((track, onset), None)
                            if text:
                                _text(ET.SubElement(node, "lyric"), "text", " ".join(text))
                    cursor = end
                _rest(measure, finish - cursor, voice_number, divisions)
    target.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target
