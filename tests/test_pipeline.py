from pathlib import Path

from audio_score_tool import pipeline
from audio_score_tool.config import Settings

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


def test_full_pipeline_contract_without_model_downloads(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"fake-audio")
    progress: list[tuple[str, int]] = []

    def fake_run(command, args, **_kwargs):
        args = list(args)
        if command == "muscriptor":
            out = _value_after(args, "--output")
            out.mkdir(parents=True, exist_ok=True)
            (out / "score.mid").write_bytes(b"MThd")
            (out / "score.musicxml").write_text(MUSICXML, encoding="utf-8")
            (out / "full_score.pdf").write_bytes(b"%PDF")
        elif command == "demucs":
            out = _value_after(args, "-o") / "htdemucs" / "song"
            out.mkdir(parents=True, exist_ok=True)
            (out / "vocals.wav").write_bytes(b"RIFF")
        elif command == "whisperx":
            out = _value_after(args, "--output_dir")
            out.mkdir(parents=True, exist_ok=True)
            (out / "vocals.json").write_text(
                '{"segments":[{"words":['
                '{"word":"하나","start":0.0,"end":1.0,"score":0.9},'
                '{"word":"님","start":1.0,"end":1.4,"score":0.9}'
                "]}]}",
                encoding="utf-8",
            )
        else:
            raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(pipeline, "run_command", fake_run)
    monkeypatch.setattr(pipeline, "_render_pdf", lambda *_args, **_kwargs: False)

    result = pipeline.transcribe(
        audio,
        tmp_path / "out",
        language="ko",
        progress=lambda stage, percent: progress.append((stage, percent)),
        settings=Settings(
            muscriptor_cmd="muscriptor",
            demucs_cmd="demucs",
            whisperx_cmd="whisperx",
        ),
    )

    assert result.midi_path.exists()
    assert result.lyric_musicxml_path is not None
    xml = result.lyric_musicxml_path.read_text(encoding="utf-8")
    assert "<text>하</text>" in xml
    assert "<text>나</text>" in xml
    assert "<text>님</text>" in xml
    assert progress[0] == ("transcription", 5)
    assert progress[-1] == ("complete", 100)
    assert result.warnings
