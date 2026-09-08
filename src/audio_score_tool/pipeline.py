from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from threading import Event

from .auto_chords import apply_inferred_chords
from .config import Settings
from .devices import detect_device_plan
from .lyrics import attach_lyrics_to_musicxml, expand_korean_syllables, load_whisperx_words
from .models import PipelineResult
from .musicxml_parts import extract_part_musicxml, list_score_parts
from .notation_backend import NotationBackendError, render_pdf
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .system_status import huggingface_authenticated
from .transcription_engine import (
    TranscriptionEngineCancelled,
    TranscriptionEngineError,
    available_engines,
    resolve_transcription_engine,
)


class PipelineError(RuntimeError):
    pass


class PipelineCancelled(PipelineError):
    pass


def _find_one(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise PipelineError(f"Expected output not found: {name} under {root}")
    return matches[0]


def _find_whisper_json(output_dir: Path) -> Path:
    candidates = sorted(output_dir.glob("*.json"))
    if not candidates:
        candidates = sorted(output_dir.rglob("*.json"))
    if not candidates:
        raise PipelineError(f"WhisperX JSON output not found under {output_dir}")
    return candidates[0]


def _render_pdf(
    musicxml: Path,
    pdf: Path,
    settings: Settings,
    cancel_event: Event | None = None,
) -> bool:
    try:
        render_pdf(musicxml, pdf, settings=settings, cancel_event=cancel_event)
        return pdf.exists()
    except CommandCancelled:
        raise
    except NotationBackendError:
        return False


def _render_instrument_parts(
    musicxml: Path,
    output_dir: Path,
    settings: Settings,
    cancel_event: Event | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for part in list_score_parts(musicxml):
        slug = str(part["slug"])
        part_xml = output_dir / f"{slug}.musicxml"
        part_pdf = output_dir / f"{slug}.pdf"
        extract_part_musicxml(musicxml, str(part["part_id"]), part_xml)
        if _render_pdf(part_xml, part_pdf, settings, cancel_event):
            rendered.append(part_pdf)
    return rendered


def preflight(settings: Settings | None = None, *, require_lyrics: bool = True) -> dict:
    settings = settings or Settings()
    engine = resolve_transcription_engine(settings)
    tools = {
        "yourmt3": command_exists(settings.yourmt3_cmd),
        "muscriptor": command_exists(settings.muscriptor_cmd),
        "native_engine": command_exists(settings.native_engine_cmd),
        "transcription_engine": engine.ready(),
        "demucs": command_exists(settings.demucs_cmd),
        "whisperx": command_exists(settings.whisperx_cmd),
    }
    missing: list[str] = []
    if not engine.ready():
        missing.append(f"transcription_engine:{engine.key}")
    if require_lyrics and not tools["whisperx"]:
        missing.append("whisperx")

    hf_ready = huggingface_authenticated()
    if engine.key == "muscriptor" and not hf_ready:
        missing.append("huggingface_auth")

    return {
        "ok": not missing,
        "missing": missing,
        "tools": tools,
        "optional": {
            "demucs": tools["demucs"],
            "demucs_note": "Demucs가 없으면 가사 ASR을 원본 믹스에서 실행합니다.",
        },
        "huggingface_authenticated": hf_ready,
        "device_plan": detect_device_plan().as_dict(),
        "transcription_engine": engine.key,
        "engines": available_engines(settings),
    }


def transcribe(
    audio_path: Path,
    output_root: Path,
    *,
    language: str | None = None,
    skip_lyrics: bool = False,
    settings: Settings | None = None,
    progress: Callable[[str, int], None] | None = None,
    cancel_event: Event | None = None,
) -> PipelineResult:
    settings = settings or Settings()

    def emit(stage: str, percent: int) -> None:
        if progress is not None:
            progress(stage, percent)

    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        raise PipelineError(f"Audio file does not exist: {audio_path}")

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stem = audio_path.stem.replace(" ", "_")
    work_dir = output_root / stem
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    score_dir = work_dir / "score"
    lyrics_dir = work_dir / "lyrics"
    stems_dir = work_dir / "stems"
    parts_dir = work_dir / "parts"
    score_dir.mkdir()
    warnings: list[str] = []

    device = detect_device_plan()
    engine = resolve_transcription_engine(settings)

    emit("transcription", 5)

    # 1) Full multi-instrument transcription. The rest of AudioScoreTool only depends
    # on the engine contract: score.mid + score.musicxml (+ optional initial PDF).
    try:
        artifacts = engine.transcribe(
            audio_path,
            score_dir,
            device=device.muscriptor_device,
            cancel_event=cancel_event,
        )
    except TranscriptionEngineCancelled as exc:
        raise PipelineCancelled("Transcription cancelled.") from exc
    except TranscriptionEngineError as exc:
        raise PipelineError(f"{engine.display_name} failed.\n{exc}") from exc

    midi_path = artifacts.midi_path
    musicxml_path = artifacts.musicxml_path
    initial_full_pdf = artifacts.initial_pdf_path
    emit("transcription", 47)

    # 2) Infer a chord progression from the multi-instrument notation.
    emit("chord_analysis", 50)
    chord_report = work_dir / "chords.json"
    try:
        inferred_chords = apply_inferred_chords(musicxml_path, report_path=chord_report)
        if not inferred_chords:
            warnings.append(
                "Automatic chord analysis did not find sufficiently confident chord changes. "
                "The score remains editable in the Chord inspector."
            )
    except (OSError, ValueError, ET.ParseError) as exc:
        inferred_chords = []
        warnings.append(f"Automatic chord analysis was skipped: {exc}")
    emit("chord_analysis", 56)

    if skip_lyrics:
        final_pdf = work_dir / "score_with_chords.pdf"
        if not _render_pdf(musicxml_path, final_pdf, settings, cancel_event):
            final_pdf = initial_full_pdf
            warnings.append(
                "Could not render the chord-enriched full score with LilyPond. "
                "MusicXML still contains the inferred chord symbols."
            )
        try:
            part_pdfs = _render_instrument_parts(
                musicxml_path,
                parts_dir,
                settings,
                cancel_event,
            )
        except CommandCancelled as exc:
            raise PipelineCancelled("Part rendering cancelled.") from exc
        emit("complete", 100)
        return PipelineResult(
            work_dir=work_dir,
            score_dir=score_dir,
            midi_path=midi_path,
            musicxml_path=musicxml_path,
            lyric_musicxml_path=None,
            pdf_path=final_pdf,
            transcript_json_path=None,
            vocals_path=None,
            chord_report_path=chord_report if chord_report.exists() else None,
            part_pdfs=part_pdfs,
            warnings=warnings,
        )

    emit("vocal_separation", 60)

    # 3) Vocal isolation is an optional lyrics-quality enhancement. If Demucs is not
    # available, use the original mix so transcription can still complete.
    vocals_path = audio_path
    if command_exists(settings.demucs_cmd):
        try:
            run_command(
                settings.demucs_cmd,
                ["--two-stems", "vocals", "-o", stems_dir, audio_path],
                cancel_event=cancel_event,
            )
            vocals_path = _find_one(stems_dir, "vocals.wav")
        except CommandCancelled as exc:
            raise PipelineCancelled("Vocal separation cancelled.") from exc
        except (CommandError, PipelineError) as exc:
            warnings.append(f"Demucs was skipped; using the original mix for lyrics: {exc}")
            vocals_path = audio_path
    else:
        warnings.append("Demucs is unavailable; using the original mix for lyrics transcription.")
    emit("vocal_separation", 70)

    # 4) WhisperX lyrics transcription.
    emit("lyrics_asr", 72)
    if not command_exists(settings.whisperx_cmd):
        raise PipelineError("WhisperX is unavailable. Install it or rerun with lyrics disabled.")
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    whisper_args: list[object] = [
        vocals_path,
        "--model",
        settings.whisperx_model,
        "--output_dir",
        lyrics_dir,
        "--output_format",
        "json",
        "--device",
        device.whisperx_device,
        "--compute_type",
        device.whisperx_compute_type,
    ]
    if language:
        whisper_args.extend(["--language", language])
    try:
        run_command(settings.whisperx_cmd, whisper_args, cancel_event=cancel_event)
    except CommandCancelled as exc:
        raise PipelineCancelled("Lyrics transcription cancelled.") from exc
    except CommandError as exc:
        raise PipelineError(f"WhisperX failed.\n{exc}") from exc

    transcript_json = _find_whisper_json(lyrics_dir)
    words = load_whisperx_words(transcript_json)
    if language == "ko":
        words = expand_korean_syllables(words)
    emit("lyrics_asr", 86)

    # 5) Attach lyric syllables/words while preserving the engine score structure.
    emit("lyric_alignment", 88)
    lyric_musicxml = work_dir / "score_with_lyrics.musicxml"
    attach_lyrics_to_musicxml(musicxml_path, lyric_musicxml, words)
    emit("lyric_alignment", 92)

    # 6) PDF and instrument part rendering are optional delivery conveniences. Their
    # absence must never discard a valid MusicXML result.
    emit("rendering", 94)
    final_pdf = work_dir / "score_with_lyrics.pdf"
    if not _render_pdf(lyric_musicxml, final_pdf, settings, cancel_event):
        final_pdf = initial_full_pdf
        warnings.append(
            "Could not render the lyric score with LilyPond. MusicXML remains available."
        )
    try:
        part_pdfs = _render_instrument_parts(
            lyric_musicxml,
            parts_dir,
            settings,
            cancel_event,
        )
    except CommandCancelled as exc:
        raise PipelineCancelled("Part rendering cancelled.") from exc
    emit("complete", 100)

    return PipelineResult(
        work_dir=work_dir,
        score_dir=score_dir,
        midi_path=midi_path,
        musicxml_path=musicxml_path,
        lyric_musicxml_path=lyric_musicxml,
        pdf_path=final_pdf,
        transcript_json_path=transcript_json,
        vocals_path=vocals_path,
        chord_report_path=chord_report if chord_report.exists() else None,
        part_pdfs=part_pdfs,
        warnings=warnings,
    )
