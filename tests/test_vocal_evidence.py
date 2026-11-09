import wave

import numpy as np
import pytest
from music21 import converter, instrument, note, stream, tempo

from audio_score_tool import selected_stem_score as stems
from audio_score_tool import vocal_evidence as ve
from audio_score_tool.audio_symbol_validation import AudioSymbolValidationError


def tone(frequency, seconds=2.0, sr=11025):
    at = np.arange(round(sr * seconds)) / sr
    return (0.8 * np.sin(2 * np.pi * frequency * at)).astype(np.float32)


def test_actual_waveform_fundamental_distinguishes_octaves_and_abstains_on_silence():
    for frequency, expected in [(220, 57), (440, 69), (880, 81), (110, 45)]:
        times, pitches = ve.pitch_track(tone(frequency), 11025)
        assert np.isfinite(pitches).mean() > 0.95
        assert np.nanmedian(pitches) == pytest.approx(expected, abs=0.1)
        report = ve.compare_notes([{"pitch": expected + 12, "start_seconds": 0.0,
                                    "end_seconds": 2.0}], times, pitches)
        assert report["octave_suspects"] == 1
        assert report["consistent_notes"] == 0
    _, silent = ve.pitch_track(np.zeros(11025), 11025)
    assert not np.isfinite(silent).any()


def test_harmonic_vocal_and_unpitched_noise_do_not_become_expert_truth():
    audio = tone(220) + 0.6 * tone(440) + 0.3 * tone(660)
    times, pitches = ve.pitch_track(audio, 11025)
    assert np.nanmedian(pitches) == pytest.approx(57, abs=0.1)
    rng = np.random.default_rng(0)
    _, noise = ve.pitch_track(rng.normal(0, 0.2, 22050), 11025)
    assert not np.isfinite(noise).any()
    report = ve.compare_notes([{"pitch": 57, "start_seconds": 0, "end_seconds": 2}], times, pitches)
    assert report["consistent_notes"] == 1
    assert report["whole_song_accuracy"] is None
    assert report["policy"]["reference_is_expert_ground_truth"] is False


def test_short_unstable_and_unvoiced_notes_are_not_counted_as_correct():
    times = np.arange(30) * 0.02
    for pitches in (np.full(30, np.nan), np.tile([60, 64, 67], 10)):
        report = ve.compare_notes([{"pitch": 60, "start_seconds": 0, "end_seconds": 0.6}], times, pitches)
        assert report["compared_notes"] == 0


def two_part_score(path):
    score = stream.Score()
    for pitches, inst in [(["A3", "B3"], instrument.Vocalist()),
                          (["E4"] * 10, instrument.Guitar())]:
        part = stream.Part()
        part.insert(0, inst)
        part.insert(0, tempo.MetronomeMark(number=120))
        for pitch in pitches:
            part.append(note.Note(pitch, quarterLength=2 if len(pitches) == 2 else 0.4))
        score.insert(0, part)
    score.write("musicxml", fp=str(path))
    return score


def test_vocal_selection_rejects_larger_leaking_guitar_and_preserves_selected_notes(tmp_path, monkeypatch):
    path = tmp_path / "score.musicxml"
    two_part_score(path)
    times = np.arange(100) * 0.02
    pitches = np.where(times < 1, 57.0, 59.0)
    monkeypatch.setattr(ve, "vocal_pitch_track", lambda *_a, **_k: (times, pitches))
    destination = tmp_path / "voice.musicxml"
    stems._main_part(path, destination, part_name="Voice", vocal_audio=tmp_path / "vocals.wav")
    actual = converter.parse(str(destination))
    assert [n.pitch.nameWithOctave for n in actual.parts[0].flatten().notes] == ["A3", "B3"]
    assert (tmp_path / "part-selection.json").is_file()


def test_ambiguous_and_missing_vocal_evidence_never_fall_back_to_note_count(tmp_path, monkeypatch):
    path = tmp_path / "score.musicxml"
    score = two_part_score(path)
    score.parts[1].clear()
    score.parts[1].append(note.Note("A3", quarterLength=2))
    score.parts[1].append(note.Note("B3", quarterLength=2))
    score.write("musicxml", fp=str(path))
    times = np.arange(100) * 0.02
    for pitches in (np.full(100, np.nan), np.where(times < 1, 57.0, 59.0)):
        monkeypatch.setattr(ve, "vocal_pitch_track", lambda *_a, **_k: (times, pitches))
        with pytest.raises(AudioSymbolValidationError):
            ve.select_vocal_part(path, tmp_path / "vocals.wav", ffmpeg_cmd="ffmpeg")
    with pytest.raises(stems.SelectedScoreError, match="waveform"):
        stems._main_part(path, tmp_path / "destination.musicxml", part_name="Voice")


def test_score_observations_preserve_ties_and_tempo_changes():
    score = stream.Score()
    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=120))
    part.insert(2, tempo.MetronomeMark(number=60))
    part.insert(0, note.Note("A3", quarterLength=2))
    part.insert(2, note.Note("B3", quarterLength=2))
    score.insert(0, part)
    events = ve.part_notes(score, part, origin_seconds=3.0)
    assert [(x["start_seconds"], x["end_seconds"]) for x in events] == [(3, 4), (4, 6)]


def test_real_decoder_then_pitch_analysis_without_optional_ml_dependencies(tmp_path):
    from audio_score_tool.config import Settings
    from audio_score_tool.runner import command_exists
    command = Settings().ffmpeg_cmd
    if not command_exists(command):
        pytest.skip("ffmpeg not installed")
    path = tmp_path / "vocals.wav"
    audio = tone(440, sr=22050)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes((audio * 30000).astype("<i2").tobytes())
    times, pitches = ve.vocal_pitch_track(path, ffmpeg_cmd=command)
    assert len(times) > 10
    assert np.nanmedian(pitches) == pytest.approx(69, abs=0.1)
