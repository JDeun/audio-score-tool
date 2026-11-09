"""Keep MusicXML instrument programs distinct in exported multitrack MIDI."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

import mido


def preserve_program_channels(path: Path) -> None:
    """Repair music21's channel-1 fallback when many programs share a score.

    The intermediate tracks still carry their own correct program changes.
    Allocate from that track-local evidence, preserving original ticks, track
    metadata and tempo map. Reuse a channel only after its previous notes end.
    """
    midi = mido.MidiFile(path)
    pending_notes = defaultdict(deque)
    tick = 0
    for message in mido.merge_tracks(midi.tracks):
        tick += message.time
        if message.type == "note_on" and message.velocity > 0:
            pending_notes[(message.channel, message.note)].append(tick)
        elif message.type in {"note_on", "note_off"}:
            pending = pending_notes[(message.channel, message.note)]
            if not pending or tick <= pending.popleft():
                raise ValueError("MIDI export produced an unmatched or zero-duration note")
    if any(pending_notes.values()):
        raise ValueError("MIDI export produced an unterminated note")
    events = []
    used = defaultdict(set)
    for track_index, track in enumerate(midi.tracks):
        tick = 0
        programs = defaultdict(int)
        for index, message in enumerate(track):
            tick += message.time
            if message.type == "program_change":
                programs[message.channel] = message.program
            if message.type == "note_on" and message.velocity > 0 and message.channel != 9:
                used[message.channel].add(programs[message.channel])
            events.append((tick, track_index, index, message))
    if all(len(programs) <= 1 for programs in used.values()):
        return
    # Changing expressive per-channel bends or pedals requires independent
    # allocation beyond program identity. Never silently erase those controls.
    if any(message.type in {"pitchwheel", "control_change", "aftertouch", "polytouch"}
           and not (message.type == "pitchwheel" and message.pitch == 0)
           for _, _, _, message in events):
        raise ValueError("MIDI program channel collision includes unsupported channel controls")

    def priority(message):
        if message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            return 0
        if message.type == "program_change":
            return 1
        return 2

    events.sort(key=lambda event: (event[0], priority(event[3]), event[1], event[2]))
    programs = defaultdict(int)
    active_program = {}
    active_count = defaultdict(int)
    last_program = {}
    released = {channel: -1 for channel in range(16) if channel != 9}
    pending = defaultdict(deque)
    output = [[] for _ in midi.tracks]
    for tick, track_index, _index, message in events:
        if message.type == "program_change":
            programs[(track_index, message.channel)] = message.program
            continue
        if message.type in {"note_on", "note_off"}:
            key = (track_index, message.channel, message.note)
            if message.type == "note_on" and message.velocity > 0:
                program = programs[(track_index, message.channel)]
                if message.channel == 9:
                    channel = 9
                elif program in active_program:
                    channel = active_program[program]
                else:
                    occupied = set(active_program.values())
                    channel = next((ch for ch in released if ch not in occupied
                                    and (released[ch] < tick or last_program.get(ch) == program)), None)
                    if channel is None:
                        raise ValueError("Score needs more safely available MIDI instrument channels")
                    active_program[program] = channel
                    if last_program.get(channel) != program:
                        output[track_index].append((tick, mido.Message(
                            "program_change", channel=channel, program=program,
                        )))
                        last_program[channel] = program
                pending[key].append((channel, program))
                if channel != 9:
                    active_count[program] += 1
            else:
                if not pending[key]:
                    raise ValueError("Exported MIDI contains an unmatched note-off")
                channel, program = pending[key].popleft()
                if channel != 9:
                    active_count[program] -= 1
                    if active_count[program] == 0:
                        del active_program[program]
                        released[channel] = tick
            output[track_index].append((tick, message.copy(channel=channel, time=0)))
        elif message.is_meta or not hasattr(message, "channel"):
            output[track_index].append((tick, message.copy(time=0)))
        # Zero pitchwheel resets were emitted only to initialize old channels.
        # The replacement channels use ordinary, unbent pitches throughout.
    if any(pending.values()):
        raise ValueError("Exported MIDI contains unterminated notes")
    tracks = []
    for source in output:
        track = mido.MidiTrack()
        previous = 0
        for tick, message in sorted(source, key=lambda event: event[0]):
            track.append(message.copy(time=tick - previous))
            previous = tick
        tracks.append(track)
    midi.tracks = tracks
    midi.save(path)
