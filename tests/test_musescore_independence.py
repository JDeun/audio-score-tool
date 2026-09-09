from pathlib import Path

from audio_score_tool.api import ToolPathSettings
from audio_score_tool.config import Settings
from audio_score_tool.notation_backend import backend_status
from audio_score_tool.setup_center_api import setup_center_status


def test_runtime_settings_and_tool_paths_do_not_expose_external_notation_apps():
    settings = Settings()
    for key in ("musescore_cmd", "lilypond_cmd", "musicxml2ly_cmd"):
        assert not hasattr(settings, key)
        assert key not in ToolPathSettings.model_fields


def test_notation_backend_is_embedded(monkeypatch):
    monkeypatch.setattr("audio_score_tool.notation_backend.music21_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.verovio_available", lambda: True)
    monkeypatch.setattr("audio_score_tool.notation_backend.fpdf2_available", lambda: True)

    status = backend_status(Settings())

    assert status == {"music21": True, "verovio": True, "fpdf2": True}
    assert "musescore" not in status
    assert "lilypond" not in status
    assert "musicxml2ly" not in status


def test_setup_center_declares_self_contained_notation_policy(monkeypatch):
    monkeypatch.setattr("audio_score_tool.setup_center_api.huggingface_authenticated", lambda: True)
    state = setup_center_status()

    component_keys = {item["key"] for item in state["components"]}
    assert "musescore" not in component_keys
    assert "lilypond" not in component_keys
    assert state["policy"]["musescore_required"] is False
    assert state["policy"]["lilypond_required"] is False
    assert state["policy"]["pdf_renderer"] == "embedded-verovio-fpdf2"
    assert state["policy"]["system_package_manager_required"] is False


def test_product_runtime_sources_do_not_reference_retired_notation_commands():
    repository = Path(__file__).resolve().parents[1]
    targets = [repository / "src" / "audio_score_tool", repository / "desktop" / "src"]
    files = [repository / ".env.example"]
    for root in targets:
        files.extend(path for path in root.rglob("*") if path.suffix in {".py", ".ts", ".tsx"})

    retired = ("musescore_cmd", "lilypond_cmd", "musicxml2ly_cmd")
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        if any(key in text for key in retired):
            offenders.append(str(path.relative_to(repository)))

    assert offenders == []
