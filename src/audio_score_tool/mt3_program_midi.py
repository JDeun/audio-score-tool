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
    """Serialize exactly the model-decoded note programs as separate tracks.

    MIDI type 1 uses independent tracks plus distinct pitched channels, so
    program_change messages cannot change another simultaneous instrument.
    Fail rather than collapse >15 different melodic programs into one channel.
    """
    if type(ticks_per_quarter) is not int or not 1 <= ticks_per_quarter <= 32767:
        raise ValueError("Unsupported MIDI time resolution")
    events_by_group: dict[tuple[bool, int], list[tuple[int, int, int, int]]] = defaultdict(list)
    for note in notes:
        pitch = getattr(note, "pitch", None)
        velocity = getattr(note, "velocity", None)
        program = getattr(note, "program", None)
        drum = getattr(note, "is_drum", None)
        start = getattr(note, "start_time", None)
        end = getattr(note, "end_time", None)
        if (
            type(pitch) is not int or not 0 <= pitch <= 127
            or type(velocity) is not int or not 0 <= velocity <= 127
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
        key = (drum, 0 if drum else program)
        # End note events come first at equal tick to prevent accidental overlaps.
        events_by_group[key].extend([
            (begin, 1, pitch, velocity),
            (finish, 0, pitch, 0),
        ])

    instruments = sorted(program for drum, program in events_by_group if not drum)
    if len(instruments) > len(PITCHED_MIDI_CHANNELS):
        raise ValueError("Decoded MR-MT3 contains more pitched programs than MIDI channels")

    midi = mido.MidiFile(type=1, ticks_per_beat=ticks_per_quarter)
    if not events_by_group:
        tempo = mido.MidiTrack()
        tempo.append(mido.MetaMessage("set_tempo", tempo=MIDI_TEMPO, time=0))
        midi.tracks.append(tempo)
        return midi

    channel_for = {program: PITCHED_MIDI_CHANNELS[i] for i, program in enumerate(instruments)}
    for index, (drum, program) in enumerate(sorted(events_by_group)):
        channel = 9 if drum else channel_for[program]
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage(
            "track_name", name="Drums" if drum else f"GM {program}", time=0,
        ))
        if index == 0:
            track.append(mido.MetaMessage("set_tempo", tempo=MIDI_TEMPO, time=0))
        if not drum:
            track.append(mido.Message(
                "program_change", program=program, channel=channel, time=0,
            ))
        previous = 0
        for tick, kind, pitch, velocity in sorted(
            events_by_group[(drum, program)], key=lambda item: (item[0], item[1], item[2])
        ):
            track.append(mido.Message(
                "note_on" if kind else "note_off",
                note=pitch,
                velocity=velocity,
                channel=channel,
                time=max(0, tick - previous),
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
