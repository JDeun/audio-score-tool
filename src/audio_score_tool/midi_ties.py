"""Prepare MusicXML ties for MIDI without merging unrelated score voices."""
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from fractions import Fraction
from pathlib import Path


def restore_instrument_bindings(score, source: Path) -> None:
    """Honor explicit MusicXML MIDI programs and percussion note identities.

    A drum kit is one score part with multiple midi-unpitched instruments.
    Parsing only its first instrument makes every hit the same drum. Match
    source notes by measure, voice and offset, preserving chord-member order.
    """
    from music21 import chord, instrument, note, stream

    if not isinstance(score, stream.Stream):
        return
    root = ET.parse(source).getroot()
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    bindings = {}
    programs = {}
    channels = {}
    for score_part in root.findall(f"{ns}part-list/{ns}score-part"):
        mapping = {}
        for midi_instrument in score_part.findall(f"{ns}midi-instrument"):
            channel = midi_instrument.findtext(f"{ns}midi-channel")
            channels.setdefault(score_part.get("id"), int(channel) - 1 if channel else None)
            program = midi_instrument.findtext(f"{ns}midi-program")
            if program is not None:
                value = int(program) - 1
                if not 0 <= value <= 127:
                    raise ValueError("MusicXML instrument program is outside MIDI range")
                programs.setdefault(score_part.get("id"), value)
            pitch = midi_instrument.findtext(f"{ns}midi-unpitched")
            if pitch is not None:
                value = int(pitch) - 1
                if not 0 <= value <= 127:
                    raise ValueError("MusicXML percussion pitch is outside MIDI range")
                mapping[midi_instrument.get("id")] = value
        if mapping:
            bindings[score_part.get("id")] = mapping
    # music21 can replace an explicit GM program with its instrument-name
    # class default (e.g. Bright Piano/GM 1 becomes Piano/GM 0).
    for part in score.parts:
        original_instrument = part.getInstrument(returnDefault=False)
        part_id = getattr(original_instrument, "partId", None)
        if ((bindings or 9 in channels.values()) and part_id not in bindings
                and channels.get(part_id) != 9):
            # None is now the drum allocator key; an unspecified pitched
            # instrument keeps MIDI's normal program-0 playback default.
            if original_instrument is None:
                original_instrument = instrument.Instrument()
                part.insert(0, original_instrument)
            if original_instrument.midiProgram is None:
                original_instrument.midiProgram = programs.get(part_id, 0)
        if original_instrument is not None and part_id in programs:
            # music21 keys channel allocation by program alone; drums must not
            # capture a pitched instrument with the same numeric GM program.
            original_instrument.midiProgram = (
                None if part_id in bindings or channels.get(part_id) == 9 else programs[part_id]
            )
            # GM 113/115/etc. can be pitched MIDI instruments. Their music21
            # class default of percussion channel 10 must not override XML.
            original_instrument.midiChannel = channels.get(part_id)
            if (part_id not in bindings and channels.get(part_id) != 9
                    and isinstance(original_instrument, instrument.UnpitchedPercussion)):
                # music21's packet writer forces channel 10 for this class even
                # when midiChannel is explicitly None/a pitched channel.
                pitched = instrument.Instrument()
                for attr in ("midiProgram", "midiChannel", "instrumentName",
                             "instrumentAbbreviation", "partName", "partAbbreviation",
                             "partId", "transposition"):
                    setattr(pitched, attr, copy.deepcopy(getattr(original_instrument, attr)))
                original_instrument.activeSite.replace(original_instrument, pitched)
    if not bindings:
        return
    sources = {}
    for xml_part in root.findall(f"{ns}part"):
        part_id = xml_part.get("id")
        mapping = bindings.get(part_id)
        if not mapping:
            continue
        divisions = 1
        lookup = defaultdict(deque)
        for index, measure in enumerate(xml_part.findall(f"{ns}measure")):
            cursor = Fraction(0)
            last_onset = cursor
            for child in measure:
                if child.tag == f"{ns}attributes":
                    divisions = int(child.findtext(f"{ns}divisions", str(divisions)))
                elif child.tag in {f"{ns}backup", f"{ns}forward"}:
                    value = Fraction(child.findtext(f"{ns}duration", "0")) / divisions
                    cursor += value if child.tag == f"{ns}forward" else -value
                elif child.tag == f"{ns}note":
                    is_chord = child.find(f"{ns}chord") is not None
                    onset = last_onset if is_chord else cursor
                    if child.find(f"{ns}unpitched") is not None:
                        ref = child.find(f"{ns}instrument")
                        instrument_id = ref.get("id") if ref is not None else next(iter(mapping))
                        if instrument_id in mapping:
                            voice = child.findtext(f"{ns}voice", "1")
                            lookup[(index, voice, onset)].append(mapping[instrument_id])
                    if not is_chord:
                        last_onset = onset
                        cursor += Fraction(child.findtext(f"{ns}duration", "0")) / divisions
        sources[part_id] = lookup
    for part in score.parts:
        original_instrument = part.getInstrument(returnDefault=False)
        part_id = getattr(original_instrument, "partId", None)
        lookup = sources.get(part_id)
        if lookup is None:
            continue
        for index, measure in enumerate(part.getElementsByClass(stream.Measure)):
            for event in measure.recurse().notes:
                voice = event.getContextByClass(stream.Voice)
                voice_id = str(voice.id) if voice is not None else "1"
                onset = Fraction(event.getOffsetInHierarchy(measure)).limit_denominator(10_000_000)
                members = event.notes if isinstance(event, chord.ChordBase) else [event]
                for member in members:
                    if not isinstance(member, note.Unpitched):
                        continue
                    pending = lookup[(index, voice_id, onset)]
                    if not pending:
                        raise ValueError("Cannot resolve MusicXML percussion instrument binding")
                    selected = instrument.UnpitchedPercussion()
                    selected.percMapPitch = pending.popleft()
                    member.storedInstrument = selected


def prepare_score_for_midi(score):
    """Resolve explicit contiguous ties per part, voice and pitch.

    music21's MIDI writer strips ties after flattening each measured part. In
    polyphony this can interrupt a chain with an unrelated voice, duplicate
    attacks, or merge the wrong notes. Build flat playback parts only after
    resolving those chains. The canonical MusicXML is never changed.
    """
    from music21 import chord, defaults, harmony, note, stream

    if not isinstance(score, stream.Stream):
        return score
    expanded = score.expandRepeats() if score[stream.Measure] else score
    result = stream.Score()
    parts = list(expanded.parts) if isinstance(expanded, stream.Score) else [expanded]
    for original in parts:
        part = stream.Part(id=original.id)
        part.partName = getattr(original, "partName", None)
        part.partAbbreviation = getattr(original, "partAbbreviation", None)
        # Keep tempo, meter, instruments, dynamics and other playback context at
        # their absolute score offsets. Unlike voicesToParts(), this also keeps
        # tempo/instrument changes that are nested inside measures with voices.
        for element in original.flatten():
            if not isinstance(element, note.GeneralNote):
                part.insert(element.offset, copy.deepcopy(element))
        events = []
        for element in original.recurse().notes:
            if isinstance(element, harmony.Harmony) and not element.writeAsChord:
                continue
            voice = element.activeSite if isinstance(element.activeSite, stream.Voice) else None
            voice_id = str(voice.id) if voice is not None else "1"
            onset = element.getOffsetInHierarchy(original)
            if isinstance(element, chord.ChordBase):
                members = list(element.notes)
            else:
                members = [element]
            for member in members:
                cloned = copy.deepcopy(member)
                cloned.quarterLength = element.quarterLength
                if 0 < cloned.quarterLength and round(cloned.quarterLength * defaults.ticksPerQuarter) == 0:
                    raise ValueError(
                        "A note is shorter than the MIDI export resolution "
                        f"({defaults.ticksPerQuarter} ticks per quarter note). "
                        "Lengthen it in the editor or export MusicXML to preserve its exact timing."
                    )
                # A chord's dynamic is often on its container, not its members.
                if isinstance(element, chord.ChordBase) and cloned.volume.velocity is None:
                    cloned.volume = copy.deepcopy(element.volume)
                if isinstance(member, note.Note):
                    pitch_key = ("pitched", member.pitch.nameWithOctave)
                else:
                    stored = getattr(member, "storedInstrument", None)
                    pitch_key = ("unpitched", getattr(stored, "percMapPitch", None),
                                 getattr(member, "displayName", None))
                events.append((onset, voice_id, pitch_key, cloned))
        events.sort(key=lambda item: item[0])
        pending = defaultdict(list)
        for onset, voice_id, pitch_key, played in events:
            kind = played.tie.type if played.tie else None
            played.tie = None
            duration = played.quarterLength
            key = (voice_id, pitch_key)
            previous = next((event for event in pending[key]
                             if abs(float(event[0] + event[1].quarterLength - onset)) < 1e-8), None)
            if kind in {"continue", "stop"} and previous is not None:
                previous[1].quarterLength += duration
                if kind == "stop":
                    pending[key].remove(previous)
                continue
            part.insert(onset, played)
            if kind in {"start", "continue"}:
                pending[key].append((onset, played))
        result.insert(0, part)
    return result
