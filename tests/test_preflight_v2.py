import sys

from audio_score_tool import preflight_v2
from audio_score_tool.config import Settings


def test_preflight_uses_embedded_pdf_renderer_without_system_notation_tools(monkeypatch):
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="yourmt3",
        whisperx_cmd=sys.executable,
    )
    monkeypatch.setattr(preflight_v2, "huggingface_authenticated", lambda: True)
    monkeypatch.setattr(
        preflight_v2,
        "backend_status",
        lambda _settings: {
            "music21": True,
            "verovio": True,
            "fpdf2": True,
        },
    )

    report = preflight_v2.preflight(settings)

    assert report["ok"] is True
    assert report["tools"]["embedded_pdf"] is True
    assert "musescore" not in report["notation_backends"]
    assert "lilypond" not in report["notation_backends"]
    assert "musicxml2ly" not in report["notation_backends"]
    assert not any("LilyPond" in warning for warning in report["warnings"])


def test_preflight_fails_packaged_runtime_when_embedded_pdf_dependency_is_missing(monkeypatch):
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        whisperx_cmd=sys.executable,
    )
    monkeypatch.setattr(preflight_v2, "huggingface_authenticated", lambda: True)
    monkeypatch.setattr(
        preflight_v2,
        "backend_status",
        lambda _settings: {
            "music21": True,
            "verovio": False,
            "fpdf2": True,
        },
    )

    report = preflight_v2.preflight(settings)

    assert report["ok"] is False
    assert "embedded_pdf_renderer" in report["missing"]
