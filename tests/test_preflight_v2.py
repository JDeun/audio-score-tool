import sys

from audio_score_tool import preflight_v2
from audio_score_tool.config import Settings


def test_preflight_does_not_require_musescore(monkeypatch):
    settings = Settings(
        usage_mode="commercial",
        transcription_engine="mt3_infer",
        mt3_infer_cmd=sys.executable,
        mt3_model="yourmt3",
        whisperx_cmd=sys.executable,
        musescore_cmd=None,
        lilypond_cmd="definitely-not-installed-lilypond",
        musicxml2ly_cmd="definitely-not-installed-musicxml2ly",
    )
    monkeypatch.setattr(preflight_v2, "huggingface_authenticated", lambda: True)
    monkeypatch.setattr(
        "audio_score_tool.transcription_engine.backend_status",
        lambda _settings: {
            "music21": True,
            "lilypond": False,
            "musicxml2ly": False,
            "musescore": False,
        },
    )
    monkeypatch.setattr(
        preflight_v2,
        "backend_status",
        lambda _settings: {
            "music21": True,
            "lilypond": False,
            "musicxml2ly": False,
            "musescore": False,
        },
    )

    report = preflight_v2.preflight(settings)
    assert "musescore" not in report["missing"]
    assert any("PDF renderer" in warning for warning in report["warnings"])
