from __future__ import annotations

from pathlib import Path

import numpy as np

from audio_score_tool import audio_symbol_validation as av
from audio_score_tool import pipeline_v2


def test_chroma_tracks_pitch_class():
    sr = 22050
    seconds = 1.0
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    a4 = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    chroma = av._chroma(a4, sr)
    assert chroma.shape[0] == 12
    assert chroma.shape[1] > 0
    dominant = int(np.argmax(np.mean(chroma, axis=1)))
    assert dominant == 9  # A pitch class


def test_alignment_finds_positive_source_delay():
    synth = np.zeros(64, dtype=np.float32)
    synth[[4, 12, 25, 42]] = 1.0
    source = np.zeros(64, dtype=np.float32)
    source[[9, 17, 30, 47]] = 1.0
    shift = av._best_shift(source, synth, max_shift=10)
    assert shift == 5


def test_preserve_source_audio_uses_managed_asset(tmp_path: Path, monkeypatch):
    source = tmp_path / "input.wav"
    source.write_bytes(b"test-audio")
    output_root = tmp_path / "jobs" / "song-123" / "outputs"
    output_root.mkdir(parents=True)
    assets = tmp_path / "assets"
    monkeypatch.setattr(pipeline_v2, "song_assets_dir", lambda: assets)

    target = pipeline_v2._preserve_source_audio(source, output_root)

    assert target == assets / "song-123" / "original-audio.wav"
    assert target.read_bytes() == b"test-audio"
