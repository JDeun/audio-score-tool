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
        "verovio": notation["verovio"],
        "fpdf2": notation["fpdf2"],
        "embedded_pdf": notation["verovio"] and notation["fpdf2"],
        "audiveris_optional": bool(omr["ready"]),
    }

    missing: list[str] = []
    if not engine.ready():
        missing.append(f"transcription_engine:{engine.key}")
    if require_lyrics and not tools["whisperx"]:
        missing.append("whisperx")
    if engine.key == "muscriptor" and not huggingface_authenticated():
        missing.append("huggingface_auth")
    if not tools["embedded_pdf"]:
        missing.append("embedded_pdf_renderer")

    warnings: list[str] = []
    if not omr["ready"]:
        warnings.append(
            "OMR is optional and currently unavailable. PDF/image score import requires a bundled or configured OMR backend."
        )

    return {
        "ok": not missing,
        "missing": missing,
        "warnings": warnings,
        "tools": tools,
        "notation_backends": notation,
        "omr": omr,
        "engine": engine.describe(),
    }
