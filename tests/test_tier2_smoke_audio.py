from __future__ import annotations

import struct
import wave
from pathlib import Path

from scripts.generate_tier2_smoke_audio import generate_fixture


def test_original_smoke_fixture_is_deterministic_and_articulated(tmp_path: Path):
    first = generate_fixture(tmp_path / "one.wav")
    second = generate_fixture(tmp_path / "two.wav")
    assert first.read_bytes() == second.read_bytes()
    with wave.open(str(first), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16_000
        assert wav.getnframes() == 16 * 16_000
        data = wav.readframes(16_000)
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    # Distinct attacks and harmonics, rather than silence/static chord sustained
    # throughout the recording.
    early = sum(abs(x) for x in samples[1_600:4_800])
    late = sum(abs(x) for x in samples[6_400:7_900])
    assert early > 1_000_000
    assert late > 100_000
    assert early != late
