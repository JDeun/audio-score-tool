"""Restore decoded MR-MT3 instrument programs when writing MIDI.

mt3-infer 0.2.0's MRMT3Adapter.decode() receives program-bearing notes from
vocab_utils, but writes every pitched note onto channel 0 in one MIDI track
without a program_change. The upstream model's GM programs are lost before
AudioScoreTool's MIDI-to-MusicXML converter sees the music.

This patch replaces ONLY MRMT3Adapter.decode in our own CLI process. It uses
the upstream tokenizer and note decoder unchanged; no instrument is inferred
from a reference score, test-set metadata or audio heuristics. Any model or
runner change must be independently reviewed before patching a new version.
"""
from __future__ import annotations

import math
import sys
from collections import defaultdict
from importlib.metadata import version
from typing import Any, Iterable

import mido

PINNED_UPSTREAM_VERSION = "0.2.0"
MIDI_TEMPO = 500_000  # 120 beats per minute, matches upstream serialisation
PITCHED_MIDI_CHANNELS = tuple(channel for channel in range(16) if channel != 9)


def midi_from_program_notes(
    notes: Iterable[Any], *, ticks_per_quarter: int = 220,
) -> mido.MidiFile:
    """Serialize model-decoded GM programs with safe, time-aware channel reuse.

    A song may contain >15 *distinct* instruments sequentially while using
    <=15 at any one moment. Recycle pitched channels only after their previous
    instrument's notes have ended at a strictly earlier tick. Preserve one
    separate MIDI track for each decoded GM program; track events record the
    actual assigned channel on every note and program change.

    If 16+ programs require channels simultaneously, fail closed rather than
    flattening unrelated instrument identities or dropping any notes.
    """
    if type(ticks_per_quarter) is not int or not 1 <= ticks_per_quarter <= 32767:
        raise ValueError("Unsupported MIDI time resolution")

    validated: list[tuple[int, int, tuple[bool, int], int, int]] = []
    for note in notes:
        pitch = getattr(note, "pitch", None)
        velocity = getattr(note, "velocity", None)
        program = getattr(note, "program", None)
        drum = getattr(note, "is_drum", None)
        start = getattr(note, "start_time", None)
        end = getattr(note, "end_time", None)
        if (
            type(pitch) is not int or not 0 <= pitch <= 127
            # MIDI note-on velocity 0 means note-off, not a quiet performed
            # note. Reject it instead of silently losing a decoded onset.
            or type(velocity) is not int or not 1 <= velocity <= 127
            or type(program) is not int or not 0 <= program <= 127
            or type(drum) is not bool
            or type(start) not in {int, float}
            or type(end) not in {int, float}
            or not math.isfinite(start) or not math.isfinite(end)
            or start < 0 or end <= start
        ):
            raise ValueError("Invalid model-decoded MR-MT3 note")
        begin = round(start * ticks_per_quarter * 1_000_000 / MIDI_TEMPO)
        finish = max(begin + 1, round(end * ticks_per_quarter * 1_000_000 / MIDI_TEMPO))
        validated.append((begin, finish, (drum, 0 if drum else program), pitch, velocity))

    midi = mido.MidiFile(type=1, ticks_per_beat=ticks_per_quarter)
    if not validated:
        tempo = mido.MidiTrack()
        tempo.append(mido.MetaMessage("set_tempo", tempo=MIDI_TEMPO, time=0))
        midi.tracks.append(tempo)
        return midi

    # Each model-inferred program gets a distinct score track, regardless of
    # which MIDI channel it needs at a particular point in time.
    events_by_group: dict[tuple[bool, int], list[tuple[int, int, int, int, int]]] = (
        defaultdict(list)
    )
    timeline = []
    for index, (begin, finish, _group, _pitch, _velocity) in enumerate(validated):
        timeline.append((begin, 1, index))  # on
        timeline.append((finish, 0, index))  # off
    timeline.sort()

    active_channel: dict[int, int] = {}
    active_counts: dict[int, int] = defaultdict(int)
    assigned: dict[int, int] = {}
    last_program: dict[int, int] = {}
    released_at = {channel: -1 for channel in PITCHED_MIDI_CHANNELS}

    for tick, event_kind, index in timeline:
        _start, _end, (is_drum, program), pitch, velocity = validated[index]
        group = (is_drum, program)
        if event_kind == 0:
            channel = assigned[index]
            events_by_group[group].append((tick, 0, pitch, 0, channel))
            if not is_drum:
                active_counts[program] -= 1
                if active_counts[program] == 0:
                    del active_channel[program]
                    released_at[channel] = tick
        else:
            if is_drum:
                channel = 9
            elif program in active_channel:
                channel = active_channel[program]
            else:
                occupied = set(active_channel.values())
                free = [
                    ch for ch in PITCHED_MIDI_CHANNELS
                    if ch not in occupied
                    and (
                        released_at[ch] < tick
                        # A note-off and retrigger on the SAME instrument,
                        # channel and tick are serialized off-before-on in
                        # that program's single track, without program change.
                        or last_program.get(ch) == program
                    )
                ]
                if not free:
                    raise ValueError(
                        "Decoded MR-MT3 has more simultaneous pitched "
                        "programs than safely available MIDI channels"
                    )
                channel = free[0]
                active_channel[program] = channel
                if last_program.get(channel) != program:
                    # A channel can change owners only while no previous note
                    # is active on it. Program changes precede note-on.
                    events_by_group[group].append((tick, 1, program, 0, channel))
                    last_program[channel] = program
            assigned[index] = channel
            if not is_drum:
                active_counts[program] += 1
            events_by_group[group].append((tick, 2, pitch, velocity, channel))

    for track_idx, (drum, program) in enumerate(sorted(events_by_group)):
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage(
            "track_name", name="Drums" if drum else f"GM {program}", time=0,
        ))
        if track_idx == 0:
            track.append(mido.MetaMessage("set_tempo", tempo=MIDI_TEMPO, time=0))
        previous = 0
        for tick, event_kind, value, velocity, channel in sorted(
            events_by_group[(drum, program)], key=lambda item: (item[0], item[1], item[2])
        ):
            delta = max(0, tick - previous)
            if event_kind == 1:
                track.append(mido.Message(
                    "program_change", program=value, channel=channel, time=delta,
                ))
            else:
                track.append(mido.Message(
                    "note_on" if event_kind == 2 else "note_off",
                    note=value, velocity=velocity, channel=channel, time=delta,
                ))
            previous = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
    return midi


def install_mr_mt3_program_preservation() -> None:
    """Patch only the reviewed 0.2.0 adapter in the current CLI subprocess."""
    actual = version("mt3-infer")
    if actual != PINNED_UPSTREAM_VERSION:
        raise RuntimeError(
            f"MR-MT3 instrument-preserving bridge requires mt3-infer "
            f"{PINNED_UPSTREAM_VERSION}, found {actual}"
        )
    from mt3_infer.adapters import vocab_utils
    from mt3_infer.adapters.mr_mt3 import MRMT3Adapter

    if getattr(MRMT3Adapter.decode, "_ast_program_preserving_v1", False):
        return

    def _decode(self: Any, outputs: Any) -> mido.MidiFile:
        if not isinstance(outputs, dict):
            raise ValueError("Invalid MR-MT3 token output")
        tokens, frame_times = outputs["tokens"], outputs["frame_times"]
        if len(tokens) != len(frame_times):
            raise ValueError("MR-MT3 token frames and timestamps disagree")
        predictions = []
        for segment, times in zip(tokens, frame_times):
            valid = segment[segment >= 0]
            if len(valid):
                predictions.append({
                    "est_tokens": valid,
                    "start_time": float(times[0]),
                })
        note_sequence, _invalid, _dropped = vocab_utils.decode_and_combine_predictions(
            predictions, self.codec
        )
        return midi_from_program_notes(
            note_sequence.notes, ticks_per_quarter=note_sequence.ticks_per_quarter,
        )

    _decode._ast_program_preserving_v1 = True  # type: ignore[attr-defined]
    MRMT3Adapter.decode = _decode


def main() -> int:
    """MT3 CLI-compatible entry point, retaining original flags and models."""
    # --version/list/help should never import PyTorch or load a checkpoint.
    args = sys.argv[1:]
    if "transcribe" in args:
        model = None
        for i, arg in enumerate(args[:-1]):
            if arg in {"-m", "--model"}:
                model = args[i + 1]
        if model == "mr_mt3":
            install_mr_mt3_program_preservation()

    from mt3_infer.cli import main as upstream_main

    return upstream_main()
