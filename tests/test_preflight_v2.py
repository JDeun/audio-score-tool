import sys

from audio_score_tool import preflight_v2
from audio_score_tool.config import Settings


def test_preflight_keeps_pdf_renderer_optional_without_musescore(monkeypatch):
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="yourmt3",
        whisperx_cmd=sys.executable,
        lilypond_cmd="definitely-not-installed-lilypond",
        musicxml2ly_cmd="definitely-not-installed-musicxml2ly",
    )
    monkeypatch.setattr(preflight_v2, "huggingface_authenticated", lambda: True)
    monkeypatch.setattr(
        preflight_v2,
        "backend_status",
        lambda _settings: {
            "music21": True,
            "lilypond": False,
            "musicxml2ly": False,
        },
    )

    report = preflight_v2.preflight(settings)

    assert report["ok"] is True
    assert "musescore_optional" not in report["tools"]
    assert "musescore" not in report["notation_backends"]
    assert any("LilyPond" in warning for warning in report["warnings"])
