"""Generate original deterministic chord audio for CI smoke tests."""
from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path


def generate_fixture(path: Path) -> Path:
    sample_rate = 16_000
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = bytearray()
    for n in range(sample_rate * 8):
        t = n / sample_rate
        frequencies = (261.63, 329.63, 392.0) if t < 4 else (349.23, 440.0, 523.25)
        amplitude = sum(math.sin(2 * math.pi * freq * t) for freq in frequencies) / 3
        pcm.extend(struct.pack("<h", int(amplitude * 7_000)))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
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
