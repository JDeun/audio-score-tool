from __future__ import annotations

import wave
from pathlib import Path

import mido
import numpy as np

from audio_score_tool.config import Settings
from audio_score_tool.music_structure import (
    MusicStructureAnalysis,
    analyze_midi_meter_and_pickup,
    estimate_music_start,
    prepare_music_audio,
)


def test_music_start_detects_sustained_later_music() -> None:
    sample_rate = 22050
    intro = np.zeros(sample_rate * 3, dtype=np.float32)
    t = np.arange(sample_rate * 8, dtype=np.float32) / sample_rate
    carrier = 0.34 * np.sin(2 * np.pi * 220 * t)
    pulses = (np.sin(2 * np.pi * 2 * t) > 0.65).astype(np.float32)
    music = carrier * (0.55 + 0.45 * pulses)
    samples = np.concatenate([intro, music.astype(np.float32)])

    start, confidence = estimate_music_start(samples, sample_rate)

    assert 1.5 <= start <= 4.5
    assert confidence >= 0.65


def _write_pickup_midi(path: Path) -> None:
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    # One-quarter pickup at tick 0, then strong downbeats every four quarters from tick 480.
    track.append(mido.Message("note_on", note=67, velocity=55, time=0))
    track.append(mido.Message("note_off", note=67, velocity=0, time=240))
    track.append(mido.Message("note_on", note=60, velocity=120, time=240))
    for pitch in (62, 64, 65, 67, 69, 71, 72):
        track.append(mido.Message("note_off", note=60, velocity=0, time=120))
        track.append(mido.Message("note_on", note=pitch, velocity=72, time=360))
    mid.save(path)


def test_midi_pickup_analysis_emits_meter_and_tempo(tmp_path: Path) -> None:
    midi = tmp_path / "pickup.mid"
    _write_pickup_midi(midi)
    analysis = analyze_midi_meter_and_pickup(midi, MusicStructureAnalysis(music_start_seconds=3.0))

    assert analysis.meter_numerator == 4
    assert analysis.meter_denominator == 4
    assert analysis.tempo_bpm is not None
    assert 115 <= analysis.tempo_bpm <= 125
    assert analysis.first_downbeat_seconds is not None
    assert analysis.first_downbeat_seconds >= 3.0


def test_truncated_wav_skips_optional_start_analysis_without_hiding_engine_validation(tmp_path, monkeypatch):
    source = tmp_path / "truncated.wav"
    source.write_bytes(b"RIFF")
    monkeypatch.setattr("audio_score_tool.music_structure._decode_analysis_wav", lambda *a, **k: False)
    result, analysis = prepare_music_audio(source, tmp_path / "work", settings=Settings())
    assert result == source
    assert analysis.trimmed is False
    assert any("Music-start analysis was skipped" in warning for warning in analysis.warnings)


def test_pcm_wav_is_analyzed_directly_without_ffmpeg(tmp_path, monkeypatch):
    rate = 22050
    seconds = np.arange(rate * 6) / rate
    music = 0.3 * np.sin(2 * np.pi * 220 * seconds)
    audio = np.concatenate([np.zeros(rate * 3), music])
    source = tmp_path / "original.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((audio * 32767).astype("<i2").tobytes())
    monkeypatch.setattr("audio_score_tool.music_structure.command_exists", lambda _: False)
    result, analysis = prepare_music_audio(source, tmp_path / "work", settings=Settings())
    assert result == source
    assert analysis.method == "pcm-energy-spectral-flux"
    assert 1.5 <= analysis.music_start_seconds <= 4.5
    assert not analysis.trimmed
    assert not (tmp_path / "work" / "structure" / "analysis.wav").exists()


def test_missing_meter_cannot_trigger_pickup_rewriting(tmp_path):
    source = tmp_path / "unmetered.mid"
    _write_pickup_midi(source)
    midi = mido.MidiFile(source)
    for track in midi.tracks:
        track[:] = [m for m in track if m.type not in {"time_signature", "set_tempo"}]
    midi.save(source)
    result = analyze_midi_meter_and_pickup(source, MusicStructureAnalysis())
    assert result.meter_source == "fallback_4_4"
    assert result.tempo_source == "midi_default_120"
    assert result.tempo_bpm == 120
    assert result.pickup_confidence == 0
    assert result.first_downbeat_seconds is None
    assert any("display fallback" in warning for warning in result.warnings)


def test_midi_tempo_event_is_not_claimed_as_audio_estimate(tmp_path):
    source = tmp_path / "clock.mid"
    _write_pickup_midi(source)
    result = analyze_midi_meter_and_pickup(source, MusicStructureAnalysis())
    assert result.meter_source == result.tempo_source == "midi_event"
