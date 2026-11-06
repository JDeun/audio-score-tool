from pathlib import Path

import pytest

from audio_score_tool import pipeline_v2
from audio_score_tool.config import Settings
from audio_score_tool.pipeline import PipelineCancelled
from audio_score_tool.runner import CommandCancelled, CommandError
from audio_score_tool.transcription_engine import TranscriptionArtifacts

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


class FakeEngine:
    key = "fake"
    display_name = "Fixture transcription"

    def transcribe(self, _audio, output_dir, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        midi = output_dir / "score.mid"
        xml = output_dir / "score.musicxml"
        midi.write_bytes(b"MThd")
        xml.write_text(MUSICXML, encoding="utf-8")
        return TranscriptionArtifacts(midi, xml)


def _prepared(tmp_path: Path, monkeypatch):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fixture")
    monkeypatch.setattr(pipeline_v2, "resolve_transcription_engine", lambda _: FakeEngine())
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        whisperx_cmd="test-whisperx",
        demucs_cmd="test-demucs",
    )
    return audio, settings


def test_missing_optional_whisperx_keeps_usable_score(tmp_path: Path, monkeypatch):
    audio, settings = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_v2, "command_exists", lambda _cmd: False)
    result = pipeline_v2.transcribe(
        audio, tmp_path / "out", settings=settings, skip_lyrics=False
    )
    assert result.musicxml_path.is_file()
    assert result.midi_path.is_file()
    assert result.lyric_musicxml_path is None
    assert any("WhisperX" in text for text in result.warnings)


def test_optional_whisperx_process_failure_does_not_erase_musicxml(
    tmp_path: Path, monkeypatch
):
    audio, settings = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_v2, "command_exists", lambda cmd: cmd == "test-whisperx")

    def fail_asr(*_args, **_kwargs):
        raise CommandError("injected WhisperX failure")

    monkeypatch.setattr(pipeline_v2, "run_command", fail_asr)
    result = pipeline_v2.transcribe(audio, tmp_path / "out", settings=settings)
    assert result.musicxml_path.is_file()
    assert result.midi_path.is_file()
    assert result.transcript_json_path is None
    assert result.lyric_musicxml_path is None
    assert any("injected WhisperX failure" in text for text in result.warnings)


def test_empty_word_timing_is_nonfatal_to_base_score(tmp_path: Path, monkeypatch):
    audio, settings = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_v2, "command_exists", lambda cmd: cmd == "test-whisperx")
    monkeypatch.setattr(pipeline_v2, "run_command", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_v2, "_find_whisper_json", lambda _: tmp_path / "empty.json")
    monkeypatch.setattr(pipeline_v2, "load_whisperx_words", lambda _: [])
    result = pipeline_v2.transcribe(audio, tmp_path / "out", settings=settings)
    assert result.musicxml_path.is_file()
    assert result.lyric_musicxml_path is None
    assert any("word-level" in text for text in result.warnings)


def test_real_cancellation_is_not_downgraded_to_warning(tmp_path: Path, monkeypatch):
    audio, settings = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline_v2, "command_exists", lambda cmd: cmd == "test-whisperx")

    def cancel(*_args, **_kwargs):
        raise CommandCancelled("user cancelled")

    monkeypatch.setattr(pipeline_v2, "run_command", cancel)
    with pytest.raises(PipelineCancelled):
        pipeline_v2.transcribe(audio, tmp_path / "out", settings=settings)
