"""Exercise the actual optional choir stage after synthetic AMT output."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import mido
import pytest

from audio_score_tool import choir_postprocess, pipeline_v2
from audio_score_tool.config import Settings
from audio_score_tool.metrics import midi_notes
from audio_score_tool.music_structure import MusicStructureAnalysis
from audio_score_tool.notation_backend import midi_to_musicxml, musicxml_to_midi
from audio_score_tool.transcription_engine import TranscriptionArtifacts


class ChordalEngine:
    display_name = "Synthetic AMT"

    def __init__(self, *, overlap: bool):
        self.overlap = overlap

    def transcribe(self, _audio, output_dir, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.append(mido.MetaMessage("set_tempo", tempo=666_667))
        track.append(mido.Message("program_change", program=1))
        messages = []
        for index in range(12):
            start = index * (240 if self.overlap else 480)
            for pitch in (48, 55, 60, 64, 67):
                messages.extend((
                    (start, 1, pitch + index % 2),
                    (start + 480, 0, pitch + index % 2),
                ))
        previous = 0
        for tick, on, pitch in sorted(messages):
            track.append(mido.Message(
                "note_on" if on else "note_off", note=pitch,
                velocity=80 if on else 0, time=tick - previous,
            ))
            previous = tick
        raw, xml = output_dir / "score.mid", output_dir / "score.musicxml"
        midi.save(raw)
        midi_to_musicxml(raw, xml)
        return TranscriptionArtifacts(raw, xml)


def _run(tmp_path: Path, monkeypatch, *, overlap=False, **kwargs):
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"original synthetic test source")
    engine = ChordalEngine(overlap=overlap)
    monkeypatch.setattr(pipeline_v2, "resolve_transcription_engine", lambda _: engine)
    monkeypatch.setattr(
        pipeline_v2, "prepare_music_audio",
        lambda source, *_args, **_kwargs: (source, MusicStructureAnalysis()),
    )
    monkeypatch.setattr(
        pipeline_v2, "detect_device_plan",
        lambda: SimpleNamespace(muscriptor_device="cpu", demucs_device="cpu"),
    )
    return pipeline_v2.transcribe(
        audio, tmp_path / "output", skip_lyrics=True,
        preserve_source_audio=False, settings=Settings(), **kwargs,
    )


def _assert_preserved(result, tmp_path):
    assert result.musicxml_path == result.score_dir / "score.musicxml"
    assert not (result.work_dir / "score_satb.musicxml").exists()
    playback = musicxml_to_midi(result.musicxml_path, tmp_path / "playback.mid")
    before, after = midi_notes(result.midi_path), midi_notes(playback)
    assert len(before) == len(after) == 60

    def order(event):
        return event.pitch, event.program, event.is_drum, event.onset, event.offset

    for left, right in zip(sorted(before, key=order), sorted(after, key=order), strict=True):
        assert (right.pitch, right.program, right.is_drum) == (
            left.pitch, left.program, left.is_drum,
        )
        assert right.onset == pytest.approx(left.onset, abs=1e-4)
        assert right.offset == pytest.approx(left.offset, abs=1e-4)


@pytest.mark.parametrize("overlap", [False, True])
def test_default_full_transcription_preserves_instrumental_polyphony(tmp_path, monkeypatch, overlap):
    result = _run(tmp_path, monkeypatch, overlap=overlap)

    _assert_preserved(result, tmp_path)
    report = json.loads(result.structure_report_path.read_text())
    assert report["choir"]["applied"] is False
    assert report["choir"]["reason"] == "disabled"


@pytest.mark.parametrize("overlap", [False, True])
def test_explicit_unsupported_choir_warns_and_finishes_with_original_score(tmp_path, monkeypatch, overlap):
    result = _run(tmp_path, monkeypatch, overlap=overlap, choir_mode="choir")

    _assert_preserved(result, tmp_path)
    assert any("Choir mode was requested" in warning for warning in result.warnings)
    report = json.loads(result.structure_report_path.read_text())
    assert report["choir"]["applied"] is False
    assert "require-manual-arrangement" in report["choir"]["reason"]


def test_choir_writer_failure_is_an_optional_warning_not_a_failed_transcription(tmp_path, monkeypatch):
    def failing_writer(*_args):
        raise RuntimeError("notation writer cannot express this duration")

    monkeypatch.setattr(choir_postprocess, "_split_chordal_part", failing_writer)
    result = _run(tmp_path, monkeypatch, choir_mode="choir")

    _assert_preserved(result, tmp_path)
    assert any("notation writer cannot express this duration" in warning for warning in result.warnings)


def test_choir_fidelity_failure_keeps_the_valid_score_available(tmp_path, monkeypatch):
    def changed_performance(_score, _part, candidate):
        # The candidate is never promoted when its performance cannot be proved.
        candidate.write_text("<score-partwise/>", encoding="utf-8")
        return choir_postprocess.ChoirResult(True, candidate, 1.0, "test", 1)

    monkeypatch.setattr(choir_postprocess, "_split_chordal_part", changed_performance)
    result = _run(tmp_path, monkeypatch, choir_mode="choir")

    _assert_preserved(result, tmp_path)
    assert any("Choir mode was requested" in warning for warning in result.warnings)
