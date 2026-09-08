from __future__ import annotations

from .config import Settings
from .notation_backend import backend_status
from .omr import audiveris_status
from .runner import command_exists
from .system_status import huggingface_authenticated
from .transcription_engine import resolve_transcription_engine


def preflight(settings: Settings | None = None, *, require_lyrics: bool = True) -> dict:
    settings = settings or Settings()
    engine = resolve_transcription_engine(settings)
    notation = backend_status(settings)
    omr = audiveris_status(settings.audiveris_cmd)
    tools = {
        "mt3_infer": command_exists(settings.mt3_infer_cmd),
        "muscriptor": command_exists(settings.muscriptor_cmd),
        "native_engine": command_exists(settings.native_engine_cmd),
        "transcription_engine": engine.ready(),
        "demucs": command_exists(settings.demucs_cmd),
        "whisperx": command_exists(settings.whisperx_cmd),
        "music21": notation["music21"],
        "lilypond": notation["lilypond"],
        "musicxml2ly": notation["musicxml2ly"],
        "audiveris_optional": bool(omr["ready"]),
    }

    missing: list[str] = []
    if not engine.ready():
        missing.append(f"transcription_engine:{engine.key}")
    if require_lyrics and not tools["whisperx"]:
        missing.append("whisperx")
    if engine.key == "muscriptor" and not huggingface_authenticated():
        missing.append("huggingface_auth")

    # PDF rendering is not a core transcription requirement. Users can edit/export
    # MusicXML and MIDI without LilyPond and add PDF rendering later.
    warnings: list[str] = []
    if not (notation["lilypond"] and notation["musicxml2ly"]):
        warnings.append("PDF renderer unavailable: install LilyPond (including musicxml2ly).")
    if not omr["ready"]:
        warnings.append("OMR unavailable: install Audiveris to import PDF/image scores.")

    return {
        "ok": not missing,
        "missing": missing,
        "warnings": warnings,
        "tools": tools,
        "notation_backends": notation,
        "omr": omr,
        "engine": engine.describe(),
    }
