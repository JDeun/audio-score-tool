from pathlib import Path

from audio_score_tool import pipeline
from audio_score_tool.config import Settings
from audio_score_tool.transcription_engine import TranscriptionArtifacts

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions></attributes>
      <direction><sound tempo="120"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration></note>
    </measure>
  </part>
</score-partwise>
"""


def _value_after(args: list[object], flag: str) -> Path:
    idx = args.index(flag)
    return Path(args[idx + 1])


class FakeEngine:
    key = "fake"
    display_name = "Fake Engine"

    def transcribe(self, _audio, output_dir, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        midi = output_dir / "score.mid"
        xml = output_dir / "score.musicxml"
        pdf = output_dir / "full_score.pdf"
        midi.write_bytes(b"MThd")
        xml.write_text(MUSICXML, encoding="utf-8")
        pdf.write_bytes(b"%PDF")
        return TranscriptionArtifacts(midi, xml, pdf)


def _fake_whisper_output(args: list[object], source_name: str) -> None:
    out = _value_after(args, "--output_dir")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{source_name}.json").write_text(
        '{"segments":[{"words":['
        '{"word":"하나","start":0.0,"end":1.0,"score":0.9},'
        '{"word":"님","start":1.0,"end":1.4,"score":0.9}'
        "]}]}",
        encoding="utf-8",
    )


def test_full_pipeline_contract_without_model_downloads(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake-audio")
    progress: list[tuple[str, int]] = []

    def fake_run(command, args, **_kwargs):
        args = list(args)
        if command == "demucs":
            out = _value_after(args, "-o") / "htdemucs" / "song"
            out.mkdir(parents=True, exist_ok=True)
            (out / "vocals.wav").write_bytes(b"RIFF")
        elif command == "whisperx":
            _fake_whisper_output(args, "vocals")
        else:
            raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(pipeline, "resolve_transcription_engine", lambda _settings: FakeEngine())
    monkeypatch.setattr(pipeline, "command_exists", lambda command: command == "demucs")
    monkeypatch.setattr(pipeline, "run_command", fake_run)
    monkeypatch.setattr(pipeline, "_render_pdf", lambda *_args, **_kwargs: False)

    result = pipeline.transcribe(
        audio,
        tmp_path / "out",
        language="ko",
        progress=lambda stage, percent: progress.append((stage, percent)),
        settings=Settings(
            demucs_cmd="demucs",
            whisperx_cmd="whisperx",
        ),
    )

    assert result.midi_path.exists()
    assert result.vocals_path is not None
    assert result.lyric_musicxml_path is not None
    xml = result.lyric_musicxml_path.read_text(encoding="utf-8")
    assert "<text>하</text>" in xml
    assert "<text>나</text>" in xml
    assert "<text>님</text>" in xml
    assert progress[0] == ("transcription", 5)
    assert progress[-1] == ("complete", 100)
    assert result.warnings


def test_lyrics_fall_back_to_full_mix_without_demucs(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake-audio")
    whisper_sources: list[Path] = []

    def fake_run(command, args, **_kwargs):
        args = list(args)
        if command == "whisperx":
            whisper_sources.append(Path(args[0]))
            _fake_whisper_output(args, "song")
        else:
            raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(pipeline, "resolve_transcription_engine", lambda _settings: FakeEngine())
    monkeypatch.setattr(pipeline, "command_exists", lambda _command: False)
    monkeypatch.setattr(pipeline, "run_command", fake_run)
    monkeypatch.setattr(pipeline, "_render_pdf", lambda *_args, **_kwargs: False)

    result = pipeline.transcribe(
        audio,
        tmp_path / "out",
        language="ko",
        settings=Settings(whisperx_cmd="whisperx", demucs_cmd="demucs"),
    )

    assert whisper_sources == [audio.resolve()]
    assert result.vocals_path is None
    assert any("Demucs is not available" in warning for warning in result.warnings)
    alignment = (result.work_dir / "alignment.json").read_text(encoding="utf-8")
    assert '"vocal_separation": "full_mix_fallback"' in alignment
