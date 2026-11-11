"""Contract tests for bounded real-audio GMD range research."""
from __future__ import annotations

import io
import math
import wave

import numpy as np
import pytest

from scripts.gmd_audio_range_probe import (
    MAX_REQUEST_BYTES,
    RangeNotSupported,
    RangeZipReader,
    decode_excerpt,
    detect_audio_roles,
    match_times,
    select_audio_rows,
)


def test_range_reader_refuses_oversized_reads_without_network():
    reader = RangeZipReader.__new__(RangeZipReader)
    reader.size = 3000000
    reader.pos = 0
    reader.cache = b""
    reader.cache_start = 0
    reader.closed = False
    reader._fetch = lambda start, length: bytes([start % 251]) * length
    assert len(reader.read(100)) == 100
    assert reader.tell() == 100
    reader.seek(-50, 1)
    assert reader.tell() == 50
    reader.seek(-1, 2)
    assert reader.tell() == 2999999
    assert len(reader.read(5)) == 1
    with pytest.raises(RangeNotSupported):
        reader.read(MAX_REQUEST_BYTES + 1)
    reader.close()


def test_match_counts_one_to_one_without_oracle_time_shift():
    a = match_times([.10, .30, .5], [.11, .11, .51])
    assert a["matched"] == 2
    assert a["truth"] == 3
    assert a["predicted"] == 3
    assert a["f1"] == pytest.approx(2 / 3)
    assert match_times([], [])["f1"] == 0


def test_selection_follows_predeclared_metadata_only_constraints():
    rows = [
        {"id": "test_a", "split": "test", "time_signature": "4-4",
         "beat_type": "beat", "duration": "18", "audio_filename": "a.wav"},
        {"id": "test_fill", "split": "test", "time_signature": "4-4",
         "beat_type": "fill", "duration": "5", "audio_filename": "b.wav"},
        {"id": "valid_34", "split": "validation", "time_signature": "3-4",
         "beat_type": "beat", "duration": "150", "audio_filename": "c.wav"},
        {"id": "train34", "split": "train", "time_signature": "3-4",
         "beat_type": "beat", "duration": "10", "audio_filename": "d.wav"},
    ]
    ids = {x["id"] for x in select_audio_rows(rows)}
    assert ids == {"test_a", "test_fill", "valid_34"}


def test_wave_excerpt_is_decoded_without_reference_or_track_labels():
    sr = 16000
    t = np.arange(sr * 4) / sr
    audio = np.int16(np.sin(2 * np.pi * 100 * t) * 8000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    samples, duration, rate = decode_excerpt(buf.getvalue(), seconds=4)
    assert rate == sr
    assert duration == pytest.approx(4)
    assert len(samples) == sr * 4
    assert np.all(np.isfinite(samples))


def test_audio_detector_handles_impulse_and_silence_without_reference():
    sr = 16000
    t = np.arange(sr * 4) / sr
    audio = np.zeros_like(t, dtype=np.float32)
    for pos in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        index = int(pos * sr)
        length = 800
        tx = np.arange(length) / sr
        audio[index:index+length] += (
            .75 * np.exp(-100 * tx) * np.sin(2 * np.pi * 100 * tx)
        )
    result = detect_audio_roles(audio)
    assert len(result) > 0
    assert all(0 <= x < 4 and role in ("kick", "backbeat")
               and math.isfinite(power) for x, role, power in result)
    assert detect_audio_roles(np.zeros_like(audio)) == []


def test_invalid_audio_fails_closed():
    with pytest.raises(ValueError):
        detect_audio_roles(np.array([float("nan")] * 3000))
