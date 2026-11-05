"""Deterministic note-level consensus ensemble for two standard MIDI predictions.

Uses the project's declared mido runtime dependency rather than an undeclared
pretty_midi installation. Tempo maps are decoded before matching note events.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import mido


@dataclass(frozen=True, slots=True)
class NoteEvent:
    pitch: int
    start: float
    end: float
    velocity: int
    program: int
    is_drum: bool


def _read_events(path: Path) -> dict[tuple[int, bool], list[NoteEvent]]:
    midi = mido.MidiFile(str(path))
    elapsed = 0.0
    tempo = 500_000
    programs = [0] * 16
    active: dict[tuple[int, int], deque[tuple[float, int, int]]] = defaultdict(deque)
    groups: dict[tuple[int, bool], list[NoteEvent]] = defaultdict(list)

    # merge_tracks returns absolute track ordering as delta ticks, with meta
    # tempo events applied for each subsequent delta across every MIDI track.
    for message in mido.merge_tracks(midi.tracks):
        elapsed += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        if message.type == "set_tempo":
            tempo = message.tempo
            continue
        if message.is_meta:
            continue
        channel = getattr(message, "channel", None)
        if channel is None:
            continue
        if message.type == "program_change":
            programs[channel] = message.program
            continue
        if message.type not in {"note_on", "note_off"}:
            continue
        identity = (channel, message.note)
        if message.type == "note_on" and message.velocity > 0:
            active[identity].append((elapsed, message.velocity, programs[channel]))
            continue
        if not active[identity]:
            continue
        start, velocity, program = active[identity].popleft()
        if elapsed <= start:
            continue
        is_drum = channel == 9
        instrument = (0 if is_drum else program, is_drum)
        groups[instrument].append(
            NoteEvent(message.note, start, elapsed, velocity, instrument[0], is_drum)
        )
    return groups


def _write_events(path: Path, groups: dict[tuple[int, bool], list[NoteEvent]]) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=960)
    global_track = mido.MidiTrack()
    global_track.append(mido.MetaMessage("set_tempo", tempo=500_000, time=0))
    midi.tracks.append(global_track)

    melodic_keys = sorted(key for key in groups if not key[1] and groups[key])
    if len(melodic_keys) > 15:
        raise ValueError("Standard MIDI supports at most 15 simultaneous melodic channels.")
    channels = [*range(0, 9), *range(10, 16)]
    for index, instrument in enumerate(sorted(key for key in groups if groups[key])):
        program, is_drum = instrument
        channel = 9 if is_drum else channels[melodic_keys.index(instrument)]
        track = mido.MidiTrack()
        if not is_drum:
            track.append(mido.Message("program_change", channel=channel, program=program, time=0))
        events: list[tuple[int, int, int, mido.Message]] = []
        for note in groups[instrument]:
            start_tick = max(0, round(note.start * 1920))
            end_tick = max(start_tick + 1, round(note.end * 1920))
            events.append((
                start_tick, 1, note.pitch,
                mido.Message("note_on", channel=channel, note=note.pitch, velocity=note.velocity),
            ))
            events.append((
                end_tick, 0, note.pitch,
                mido.Message("note_off", channel=channel, note=note.pitch, velocity=0),
            ))
        previous = 0
        # Stable key sort avoids comparing mido.Message objects when identical
        # notes yield equal (tick, priority, pitch) tuples.
        for tick, _order, _pitch, message in sorted(events, key=lambda item: item[:3]):
            message.time = tick - previous
            track.append(message)
            previous = tick
        midi.tracks.append(track)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.save(str(path))


def ensemble(
    first: Path,
    second: Path,
    output: Path,
    *,
    onset_tolerance: float = 0.09,
    min_overlap: float = 0.35,
) -> dict:
    """Keep pitch/program matched notes with sufficient overlap and onset agreement.

    The algorithm favors precision over recall and does not substitute for a
    reference-annotated note-F1 comparison.
    """
    if (
        not math.isfinite(onset_tolerance)
        or not math.isfinite(min_overlap)
        or onset_tolerance <= 0
        or not 0 < min_overlap <= 1
    ):
        raise ValueError("Invalid consensus thresholds")

    a, b = _read_events(first), _read_events(second)
    count_a = sum(map(len, a.values()))
    count_b = sum(map(len, b.values()))
    matched: dict[tuple[int, bool], list[NoteEvent]] = defaultdict(list)
    match_count = 0

    for instrument, source_notes in sorted(a.items()):
        candidates = b.get(instrument, [])
        used: set[int] = set()
        for note in sorted(source_notes, key=lambda n: (n.start, n.pitch, n.end)):
            best = None
            best_score = float("-inf")
            for index, other in enumerate(candidates):
                if index in used or other.pitch != note.pitch:
                    continue
                if abs(note.start - other.start) > onset_tolerance:
                    continue
                overlap_seconds = max(
                    0.0, min(note.end, other.end) - max(note.start, other.start)
                )
                duration = max(note.end - note.start, other.end - other.start)
                overlap = overlap_seconds / duration if duration > 0 else 0.0
                if overlap < min_overlap:
                    continue
                score = overlap - abs(note.start - other.start)
                if score > best_score:
                    best, best_score = index, score
            if best is None:
                continue
            other = candidates[best]
            start = (note.start + other.start) / 2
            end = (note.end + other.end) / 2
            if end <= start:
                continue
            used.add(best)
            matched[instrument].append(
                NoteEvent(
                    pitch=note.pitch,
                    start=start,
                    end=end,
                    velocity=round((note.velocity + other.velocity) / 2),
                    program=instrument[0],
                    is_drum=instrument[1],
                )
            )
            match_count += 1

    _write_events(output, matched)
    return {
        "method": "pitch_program_onset_overlap_consensus",
        "source_notes": [count_a, count_b],
        "matched_notes": match_count,
        "onset_tolerance_seconds": onset_tolerance,
        "min_overlap": min_overlap,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(ensemble(args.first, args.second, args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
