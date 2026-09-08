from pathlib import Path

from audio_score_tool.api import ToolPathSettings
from audio_score_tool.config import Settings
from audio_score_tool.notation_backend import backend_status
from audio_score_tool.setup_center_api import setup_center_status


def test_runtime_settings_and_tool_paths_do_not_expose_musescore():
    assert not hasattr(Settings(), "musescore_cmd")
    assert "musescore_cmd" not in ToolPathSettings.model_fields


def test_notation_backend_has_no_musescore_provider(monkeypatch):
    monkeypatch.setattr("audio_score_tool.notation_backend.music21_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.command_exists", lambda _command: False)

    status = backend_status(Settings())

    assert "musescore" not in status
    assert set(status) == {"music21", "lilypond", "musicxml2ly"}


def test_setup_center_has_no_musescore_component_or_renderer(monkeypatch):
    monkeypatch.setattr("audio_score_tool.setup_center_api.huggingface_authenticated", lambda: True)
    state = setup_center_status()

    component_keys = {item["key"] for item in state["components"]}
    assert "musescore" not in component_keys
    assert state["policy"]["musescore_required"] is False
    assert state["policy"]["pdf_renderer"] == "lilypond"


def test_product_runtime_sources_do_not_reference_musescore_command():
    repository = Path(__file__).resolve().parents[1]
    targets = [repository / "src" / "audio_score_tool", repository / "desktop" / "src"]
    files = [repository / ".env.example"]
    for root in targets:
        files.extend(path for path in root.rglob("*") if path.suffix in {".py", ".ts", ".tsx"})

    offenders = []
    for path in files:
        if "musescore_cmd" in path.read_text(encoding="utf-8", errors="ignore").lower():
            offenders.append(str(path.relative_to(repository)))

    assert offenders == []
