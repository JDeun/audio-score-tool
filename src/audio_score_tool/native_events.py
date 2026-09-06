from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import mido


PAD = 0
BOS = 1
EOS = 2
TIME_SHIFT_BASE = 3
TIME_SHIFT_BINS = 100
TEMPO_BASE = TIME_SHIFT_BASE + TIME_SHIFT_BINS
TEMPO_MIN = 30
TEMPO_MAX = 240
TEMPO_BINS = TEMPO_MAX - TEMPO_MIN + 1
PROGRAM_BASE = TEMPO_BASE + TEMPO_BINS
PROGRAM_BINS = 129  # 0..127 melodic programs + 128 percussion
NOTE_ON_BASE = PROGRAM_BASE + PROGRAM_BINS
NOTE_OFF_BASE = NOTE_ON_BASE + 128
VELOCITY_BASE = NOTE_OFF_BASE + 128
VELOCITY_BINS = 32
VOCAB_SIZE = VELOCITY_BASE + VELOCITY_BINS
TIME_SHIFT_MS = 10


@dataclass(slots=True)
class DecodedNote:
    start_ms: int
    end_ms: int
    pitch: int
    velocity: int
    program: int


def time_shift_token(steps: int) -> int:
    if not 1 <= steps <= TIME_SHIFT_BINS:
        raise ValueError(f"time shift must be 1..{TIME_SHIFT_BINS}")
    return TIME_SHIFT_BASE + steps - 1


def tempo_token(bpm: int) -> int:
    bpm = max(TEMPO_MIN, min(TEMPO_MAX, int(round(bpm))))
    return TEMPO_BASE + bpm - TEMPO_MIN


def program_token(program: int) -> int:
    if not 0 <= program <= 128:
        raise ValueError("program must be 0..128")
    return PROGRAM_BASE + program


def note_on_token(pitch: int) -> int:
    if not 0 <= pitch <= 127:
        raise ValueError("pitch must be 0..127")
    return NOTE_ON_BASE + pitch


def note_off_token(pitch: int) -> int:
    if not 0 <= pitch <= 127:
        raise ValueError("pitch must be 0..127")
    return NOTE_OFF_BASE + pitch


def velocity_token(velocity: int) -> int:
    bucket = max(
        0,
        min(
            VELOCITY_BINS - 1,
            int(round(velocity / 127 * (VELOCITY_BINS - 1))),
        ),
    )
    return VELOCITY_BASE + bucket


def _emit_time(tokens: list[int], delta_ms: int) -> None:
    remaining = max(0, int(round(delta_ms / TIME_SHIFT_MS)))
    while remaining:
        step = min(remaining, TIME_SHIFT_BINS)
        tokens.append(time_shift_token(step))
        remaining -= step


def midi_to_tokens(path: Path, *, max_tokens: int | None = None) -> list[int]:
    midi = mido.MidiFile(path)
    merged = mido.merge_tracks(midi.tracks)
    tempo = 500_000
    initial_tempo = tempo
    saw_tempo = False
    absolute_seconds = 0.0
    program_by_channel = {channel: 0 for channel in range(16)}
    active_program: dict[tuple[int, int], int] = {}
    events: list[tuple[int, int, int, int, int]] = []
    # tuple: time_ms, sort_order, program, pitch, velocity; velocity<0 means note-off

    for message in merged:
        absolute_seconds += mido.tick2second(message.time, midi.ticks_per_beat, tempo)
        time_ms = int(round(absolute_seconds * 1000))
        if message.type == "set_tempo":
            tempo = message.tempo
            if not saw_tempo:
                initial_tempo = tempo
                saw_tempo = True
        elif message.type == "program_change":
            program_by_channel[message.channel] = message.program
        elif message.type == "note_on" and message.velocity > 0:
            program = 128 if message.channel == 9 else program_by_channel[message.channel]
            active_program[(message.channel, message.note)] = program
            events.append((time_ms, 1, program, message.note, message.velocity))
        elif message.type in {"note_off", "note_on"}:
            key = (message.channel, message.note)
            fallback = 128 if message.channel == 9 else program_by_channel[message.channel]
            program = active_program.pop(key, fallback)
            events.append((time_ms, 0, program, message.note, -1))

    initial_bpm = int(round(mido.tempo2bpm(initial_tempo)))
    tokens = [BOS, tempo_token(initial_bpm)]
    current_ms = 0
    current_program: int | None = None
    current_velocity: int | None = None

    for time_ms, _sort, program, pitch, velocity in sorted(events):
        _emit_time(tokens, time_ms - current_ms)
        current_ms = time_ms
        if current_program != program:
            tokens.append(program_token(program))
            current_program = program
        if velocity >= 0:
            if current_velocity != velocity:
                tokens.append(velocity_token(velocity))
                current_velocity = velocity
            tokens.append(note_on_token(pitch))
        else:
            tokens.append(note_off_token(pitch))
        if max_tokens is not None and len(tokens) >= max_tokens - 1:
            break

    tokens.append(EOS)
    return tokens


def decode_tokens(tokens: list[int]) -> tuple[int, list[DecodedNote]]:
    time_ms = 0
    bpm = 120
    program = 0
    velocity = 96
    active: dict[tuple[int, int], tuple[int, int]] = {}
    notes: list[DecodedNote] = []

    for token in tokens:
        if token in {PAD, BOS}:
            continue
        if token == EOS:
            break
        if TIME_SHIFT_BASE <= token < TEMPO_BASE:
            time_ms += (token - TIME_SHIFT_BASE + 1) * TIME_SHIFT_MS
        elif TEMPO_BASE <= token < PROGRAM_BASE:
            bpm = TEMPO_MIN + token - TEMPO_BASE
        elif PROGRAM_BASE <= token < NOTE_ON_BASE:
            program = token - PROGRAM_BASE
        elif NOTE_ON_BASE <= token < NOTE_OFF_BASE:
            pitch = token - NOTE_ON_BASE
            active[(program, pitch)] = (time_ms, velocity)
        elif NOTE_OFF_BASE <= token < VELOCITY_BASE:
            pitch = token - NOTE_OFF_BASE
            key = (program, pitch)
            if key in active:
                start_ms, start_velocity = active.pop(key)
                if time_ms > start_ms:
                    notes.append(
                        DecodedNote(start_ms, time_ms, pitch, start_velocity, program)
                    )
        elif VELOCITY_BASE <= token < VOCAB_SIZE:
            bucket = token - VELOCITY_BASE
            velocity = max(
                1,
                int(round(bucket / (VELOCITY_BINS - 1) * 127)),
            )

    for (active_program, pitch), (start_ms, start_velocity) in active.items():
        notes.append(
            DecodedNote(
                start_ms,
                max(time_ms, start_ms + 100),
                pitch,
                start_velocity,
                active_program,
            )
        )
    notes.sort(key=lambda note: (note.start_ms, note.program, note.pitch))
    return bpm, notes


def tokens_to_midi(
    tokens: list[int],
    output: Path,
    *,
    ticks_per_beat: int = 480,
) -> Path:
    bpm, notes = decode_tokens(tokens)
    tempo = mido.bpm2tempo(bpm)
    midi = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    midi.tracks.append(conductor)

    programs = sorted({note.program for note in notes})
    melodic_channels = [channel for channel in range(16) if channel != 9]
    melodic_index = 0
    for program in programs:
        track = mido.MidiTrack()
        midi.tracks.append(track)
        if program == 128:
            channel = 9
        else:
            channel = melodic_channels[melodic_index % len(melodic_channels)]
            melodic_index += 1
            track.append(
                mido.Message("program_change", program=program, channel=channel, time=0)
            )
        events: list[tuple[int, int, mido.Message]] = []
        for note in (item for item in notes if item.program == program):
            start_ticks = int(
                round(mido.second2tick(note.start_ms / 1000, ticks_per_beat, tempo))
            )
            end_ticks = int(
                round(mido.second2tick(note.end_ms / 1000, ticks_per_beat, tempo))
            )
            events.append(
                (
                    start_ticks,
                    1,
                    mido.Message(
                        "note_on",
                        note=note.pitch,
                        velocity=note.velocity,
                        channel=channel,
                    ),
                )
            )
            events.append(
                (
                    end_ticks,
                    0,
                    mido.Message(
                        "note_off",
                        note=note.pitch,
                        velocity=0,
                        channel=channel,
                    ),
                )
            )
        last_tick = 0
        for tick, _order, message in sorted(events, key=lambda event: (event[0], event[1])):
            message.time = max(0, tick - last_tick)
            last_tick = tick
            track.append(message)

    output.parent.mkdir(parents=True, exist_ok=True)
    midi.save(output)
    return output
