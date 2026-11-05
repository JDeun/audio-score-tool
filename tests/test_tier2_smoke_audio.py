from __future__ import annotations

import wave
from pathlib import Path

from scripts.generate_tier2_smoke_audio import generate_fixture


def test_original_smoke_fixture_is_deterministic(tmp_path: Path):
    first = generate_fixture(tmp_path / "one.wav")
    second = generate_fixture(tmp_path / "two.wav")
    assert first.read_bytes() == second.read_bytes()
    with wave.open(str(first), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16_000
        assert wav.getnframes() == 8 * 16_000
