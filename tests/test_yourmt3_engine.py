from pathlib import Path

from audio_score_tool import transcription_engine
from audio_score_tool.config import Settings


def test_yourmt3_compatibility_provider_transcribes_and_converts_musicxml(tmp_path: Path, monkeypatch):
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio")
    output = tmp_path / "score"
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(transcription_engine, "command_exists", lambda _command: True)
    monkeypatch.setattr(
        transcription_engine,
        "backend_status",
        lambda _settings: {
            "music21": True,
            "lilypond": False,
            "musicxml2ly": False,
        },
    )

    def fake_run(command, args, **_kwargs):
        argv = [str(item) for item in args]
        calls.append((command, argv))
        destination = Path(argv[argv.index("-o") + 1])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"midi")

    def fake_midi_to_musicxml(source: Path, destination: Path):
        assert source == output / "score.mid"
        destination.write_text("<score-partwise/>", encoding="utf-8")
        return destination

    monkeypatch.setattr(transcription_engine, "run_command", fake_run)
    monkeypatch.setattr(transcription_engine, "midi_to_musicxml", fake_midi_to_musicxml)

    settings = Settings(
        transcription_engine="yourmt3",
        mt3_infer_cmd="mt3-infer",
        mt3_model="yourmt3",
    )
    engine = transcription_engine.resolve_transcription_engine(settings)
    artifacts = engine.transcribe(audio, output, device="mps")

    assert artifacts.midi_path == output / "score.mid"
    assert artifacts.musicxml_path == output / "score.musicxml"
    assert artifacts.midi_path.exists()
    assert artifacts.musicxml_path.exists()
    assert calls == [
        (
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
    ]
