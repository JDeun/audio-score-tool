from pathlib import Path

import pytest

from audio_score_tool.config import Settings
from audio_score_tool.notation_backend import (
    NotationBackendUnavailable,
    backend_status,
    musicxml_to_pdf_lilypond,
    render_pdf,
)


def test_lilypond_export_does_not_leak_work_files(tmp_path: Path, monkeypatch):
    source = tmp_path / "score.musicxml"
    source.write_text("<score-partwise version='4.0'><part-list/></score-partwise>", encoding="utf-8")
    target = tmp_path / "exports" / "score.pdf"

    monkeypatch.setattr("audio_score_tool.notation_backend.command_exists", lambda _command: True)

    def fake_run(command, args, **_kwargs):
        args = [str(value) for value in args]
        if command == "musicxml2ly":
            output = Path(args[args.index("-o") + 1])
            output.write_text("\\version \"2.26.0\"", encoding="utf-8")
        elif command == "lilypond":
            output_base = Path(args[args.index("-o") + 1])
            output_base.with_suffix(".pdf").write_bytes(b"%PDF-test")

        class Result:
            stdout = ""

        return Result()

    monkeypatch.setattr("audio_score_tool.notation_backend.run_command", fake_run)
    settings = Settings(lilypond_cmd="lilypond", musicxml2ly_cmd="musicxml2ly")

    result = musicxml_to_pdf_lilypond(source, target, settings=settings)

    assert result == target
    assert target.read_bytes() == b"%PDF-test"
    assert not any(path.name.startswith(".lilypond-work") for path in target.parent.rglob("*"))
    assert not any(path.suffix == ".ly" for path in target.parent.rglob("*"))


def test_backend_status_has_no_musescore_surface(monkeypatch):
    monkeypatch.setattr("audio_score_tool.notation_backend.music21_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.command_exists", lambda _command: True)

    status = backend_status(Settings(lilypond_cmd="lilypond", musicxml2ly_cmd="musicxml2ly"))

    assert status == {"music21": True, "lilypond": True, "musicxml2ly": True}
    assert "musescore" not in status


def test_render_pdf_does_not_fallback_to_musescore(tmp_path: Path, monkeypatch):
    source = tmp_path / "score.musicxml"
    source.write_text("<score-partwise version='4.0'><part-list/></score-partwise>", encoding="utf-8")
    target = tmp_path / "score.pdf"
    monkeypatch.setattr("audio_score_tool.notation_backend.command_exists", lambda _command: False)

    with pytest.raises(NotationBackendUnavailable, match="LilyPond"):
        render_pdf(
            source,
            target,
            settings=Settings(lilypond_cmd="missing-lilypond", musicxml2ly_cmd="missing-musicxml2ly"),
        )
