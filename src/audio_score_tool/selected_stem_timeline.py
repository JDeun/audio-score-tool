"""Align independently transcribed stem parts on one time/tempo grid.

Two MusicXML <part> elements cannot simply be concatenated: independent AMT
models may emit different metronome maps. The first part establishes the score
tempo and meter; seconds-based notes from each selected part are rebased to
that common grid before a single MIDI→MusicXML conversion. No prediction is
added or dropped to improve measured accuracy.
"""
from __future__ import annotations

import bisect
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido

from .metrics import midi_notes
from .notation_backend import midi_to_musicxml, musicxml_to_midi

_RESOLUTION = 10080  # < 0.05 ms per tick at 120 BPM.


class StemTimelineError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Performed:
    onset: float
    offset: float
    pitch: int
    velocity: int
    program: int
    is_drum: bool


def _performed_notes(path: Path) -> list[_Performed]:
    """Read absolute seconds with note-on velocity, rejecting incomplete streams."""
    programs: dict[int, int] = defaultdict(int)
    active: dict[tuple[int, int], deque[tuple[float, int, int]]] = defaultdict(deque)
    notes: list[_Performed] = []
    elapsed = 0.0
    for message in mido.MidiFile(path):
        elapsed += float(message.time)
        if message.type == "program_change":
            programs[message.channel] = message.program
        elif message.type == "note_on" and message.velocity > 0:
            active[(message.channel, message.note)].append(
                (elapsed, programs[message.channel], message.velocity)
            )
        elif message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        ):
            pending = active[(message.channel, message.note)]
            if not pending:
                raise StemTimelineError("Selected stem MIDI contains an unmatched note-off")
            onset, program, velocity = pending.popleft()
            if elapsed <= onset:
                raise StemTimelineError("Selected stem MIDI contains a zero-duration note")
            notes.append(_Performed(
                onset, elapsed, message.note, velocity, program, message.channel == 9,
            ))
    if not notes or any(active.values()):
        raise StemTimelineError("Selected stem MIDI has no complete performed notes")
    return notes


def _tempo_grid(midi: mido.MidiFile):
    """Build tempo-accurate inverse seconds→ticks mapping for the first stem."""
    ppq = midi.ticks_per_beat
    if midi.type == 2 or ppq <= 0:
        raise StemTimelineError("Selected stem MIDI has an unsupported clock")
    events: list[tuple[int, int, int, mido.MetaMessage]] = []
    for track_index, track in enumerate(midi.tracks):
        tick = 0
        for index, message in enumerate(track):
            tick += message.time
            if message.is_meta and message.type in {
                "set_tempo", "time_signature", "key_signature",
            }:
                events.append((tick, track_index, index, message))
    events.sort(key=lambda event: event[:3])
    tick_points: list[int] = [0]
    second_points: list[float] = [0.0]
    tempo_points: list[int] = [500_000]
    prev_tick = 0
    now_seconds = 0.0
    active_tempo = 500_000
    for tick, _track, _index, message in events:
        if message.type != "set_tempo":
            continue
        if message.tempo <= 0:
            raise StemTimelineError("Selected stem tempo must be positive")
        if tick > prev_tick:
            now_seconds += (tick - prev_tick) * active_tempo / ppq / 1_000_000
            tick_points.append(tick)
            second_points.append(now_seconds)
            tempo_points.append(message.tempo)
        else:
            tempo_points[-1] = message.tempo
        prev_tick = tick
        active_tempo = message.tempo

    def seconds_to_tick(seconds: float) -> int:
        if not math.isfinite(seconds) or seconds < 0:
            raise StemTimelineError("Selected stem note time is invalid")
        index = max(0, bisect.bisect_right(second_points, seconds) - 1)
        original_tick = (
            tick_points[index]
            + (seconds - second_points[index]) * ppq * 1_000_000 / tempo_points[index]
        )
        return max(0, round(original_tick * _RESOLUTION / ppq))

    metadata: list[tuple[int, mido.MetaMessage]] = [
        (round(tick * _RESOLUTION / ppq), message.copy(time=0))
        for tick, _track, _index, message in events
    ]
    return seconds_to_tick, metadata


def _write_track(
    name: str, notes: list[_Performed], channel: int, seconds_to_tick,
) -> mido.MidiTrack:
    keys = {(note.is_drum, 0 if note.is_drum else note.program) for note in notes}
    if len(keys) != 1:
        raise StemTimelineError(
            f"{name} part contains multiple instrument identities; refusing silent GM changes"
        )
    is_drum, program = next(iter(keys))
    assigned = 9 if is_drum else channel
    events: list[tuple[int, int, mido.Message | mido.MetaMessage]] = [
        (0, 0, mido.MetaMessage("track_name", name=name, time=0)),
    ]
    if not is_drum:
        events.append((0, 1, mido.Message(
            "program_change", channel=assigned, program=program, time=0,
        )))
    for note in notes:
        start = seconds_to_tick(note.onset)
        end = max(start + 1, seconds_to_tick(note.offset))
        events.extend((
            (start, 3, mido.Message(
                "note_on", channel=assigned, note=note.pitch,
                velocity=note.velocity, time=0,
            )),
            (end, 2, mido.Message(
                "note_off", channel=assigned, note=note.pitch,
                velocity=0, time=0,
            )),
        ))
    events.sort(key=lambda item: (item[0], item[1]))
    track = mido.MidiTrack()
    previous = 0
    for tick, _kind, message in events:
        track.append(message.copy(time=tick - previous))
        previous = tick
    return track


def _validate_fidelity(expected: list[_Performed], result: Path) -> None:
    actual = midi_notes(result)
    if len(actual) != len(expected):
        raise StemTimelineError("Stem score assembly changed the number of performed notes")
    keys = lambda note: (note.is_drum, note.program if not note.is_drum else 0, note.pitch)
    left = sorted(expected, key=lambda note: (*keys(note), note.onset, note.offset))
    right = sorted(actual, key=lambda note: (*keys(note), note.onset, note.offset))
    for source, target in zip(left, right):
        if (
            keys(source) != keys(target)
            or abs(source.onset - target.onset) > 0.002
            or abs(source.offset - target.offset) > 0.002
        ):
            raise StemTimelineError(
                "Stem score assembly changed pitch, instrument or absolute note timing"
            )


def align_selected_role_scores(
    voice_musicxml: Path, guitar_musicxml: Path, output_musicxml: Path, stage: Path,
) -> None:
    """Create one score from independent stems, anchored to the vocal meter."""
    vocal_midi = stage / "voice-source.mid"
    guitar_midi = stage / "guitar-source.mid"
    musicxml_to_midi(voice_musicxml, vocal_midi)
    musicxml_to_midi(guitar_musicxml, guitar_midi)
    vocal = _performed_notes(vocal_midi)
    guitar = _performed_notes(guitar_midi)
    if all(note.is_drum for note in vocal) and all(note.is_drum for note in guitar):
        raise StemTimelineError("Two independent drum stems cannot share MIDI channel 10")
    seconds_to_tick, meta = _tempo_grid(mido.MidiFile(vocal_midi))

    midi = mido.MidiFile(type=1, ticks_per_beat=_RESOLUTION)
    clock = mido.MidiTrack()
    last = 0
    for tick, message in meta:
        clock.append(message.copy(time=tick - last))
        last = tick
    midi.tracks.append(clock)
    midi.tracks.append(_write_track("Voice", vocal, 0, seconds_to_tick))
    midi.tracks.append(_write_track("Guitar", guitar, 1, seconds_to_tick))

    assembled_midi = stage / "common-clock.mid"
    midi.save(assembled_midi)
    midi_to_musicxml(assembled_midi, output_musicxml)
    checked_midi = stage / "common-clock-roundtrip.mid"
    musicxml_to_midi(output_musicxml, checked_midi)
    _validate_fidelity(vocal + guitar, checked_midi)
