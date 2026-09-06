from pathlib import Path

from audio_score_tool.config import Settings
from audio_score_tool import transcription_engine


def test_yourmt3_provider_transcribes_and_converts_musicxml(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "score"
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(transcription_engine, "command_exists", lambda _command: True)
    monkeypatch.setattr(transcription_engine, "_resolve_musescore", lambda _settings: "musescore")

    def fake_run(command, args, **_kwargs):
        argv = [str(item) for item in args]
        calls.append((command, argv))
        destination = Path(argv[argv.index("-o") + 1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"output")

    monkeypatch.setattr(transcription_engine, "run_command", fake_run)

    settings = Settings(transcription_engine="yourmt3", yourmt3_cmd="mt3-infer")
    engine = transcription_engine.YourMT3Engine(settings)
    artifacts = engine.transcribe(audio, output, device="mps")

    assert artifacts.midi_path == output / "score.mid"
    assert artifacts.musicxml_path == output / "score.musicxml"
    assert artifacts.midi_path.exists()
    assert artifacts.musicxml_path.exists()
    assert calls[0] == (
        "mt3-infer",
        [
            "transcribe",
            str(audio),
            "-o",
            str(output / "score.mid"),
            "-m",
            "yourmt3",
            "--device",
            "mps",
        ],
    )
    assert calls[1][0] == "musescore"
