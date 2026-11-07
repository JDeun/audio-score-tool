"""Synthesize original, articulated polyphonic music for actual AMT CI inference.

No copyrighted source audio or commercial soundfont is used. Eight bars of
deterministic chord/melody notes have separate attacks and decays, unlike a
continuous sine chord that real note-onset models may legitimately ignore.
This fixture proves product execution, not transcription quality.
"""
from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path

_SAMPLE_RATE = 16_000
_BEAT_SECONDS = 0.5
_BAR_SECONDS = 2.0
_BARS = (
    ((48, 52, 55), (60, 64, 67, 72)),  # C
    ((53, 57, 60), (65, 69, 72, 77)),  # F
    ((55, 59, 62), (67, 71, 74, 79)),  # G
    ((48, 52, 55), (72, 67, 64, 60)),  # C
    ((57, 60, 64), (69, 72, 76, 81)),  # Am
    ((53, 57, 60), (65, 69, 72, 77)),  # F
    ((55, 59, 62), (67, 71, 74, 79)),  # G
    ((48, 52, 55), (72, 67, 64, 60)),  # C
)


def _frequency(midi_note: int) -> float:
    return 440.0 * 2 ** ((midi_note - 69) / 12)


def _piano_voice(frequency: float, absolute_time: float, age: float, *, decay: float) -> float:
    if age < 0:
        return 0.0
    # An articulated, non-clicking attack distinguishes notes from a static
    # waveform; the 4 partials supply a piano/keyboard-like non-sinusoidal timbre.
    envelope = min(1.0, age * 80) * math.exp(-decay * age)
    phase = 2 * math.pi * frequency * absolute_time
    harmonics = (
        math.sin(phase)
        + 0.37 * math.sin(2 * phase)
        + 0.16 * math.sin(3 * phase)
        + 0.07 * math.sin(4 * phase)
    ) / 1.60
    return envelope * harmonics


def generate_fixture(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = bytearray()
    duration = len(_BARS) * _BAR_SECONDS
    for n in range(int(_SAMPLE_RATE * duration)):
        time = n / _SAMPLE_RATE
        bar_index = min(len(_BARS) - 1, int(time // _BAR_SECONDS))
        bass_notes, melody_notes = _BARS[bar_index]
        bar_age = time - bar_index * _BAR_SECONDS
        beat_index = min(3, int(bar_age // _BEAT_SECONDS))
        beat_age = bar_age - beat_index * _BEAT_SECONDS

        # Independent quarter-note melodic attacks and sustained triads.
        melody = _piano_voice(
            _frequency(melody_notes[beat_index]), time, beat_age, decay=3.2
        ) * max(0.0, min(1.0, (_BEAT_SECONDS - beat_age) * 25))
        harmony = sum(
            _piano_voice(_frequency(pitch), time, bar_age, decay=1.25)
            for pitch in bass_notes
        ) / len(bass_notes)
        mixed = max(-0.95, min(0.95, 0.65 * melody + 0.32 * harmony))
        pcm.extend(struct.pack("<h", round(mixed * 24000)))

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(_SAMPLE_RATE)
        output.writeframes(pcm)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(generate_fixture(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
