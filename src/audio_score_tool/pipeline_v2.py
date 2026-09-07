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
from .paths import song_assets_dir
from .pipeline import PipelineCancelled, PipelineError, _find_one, _find_whisper_json
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .transcription_engine import (
    TranscriptionEngineCancelled,
    TranscriptionEngineError,
    resolve_transcription_engine,
)


def _remove_eager_render_artifacts(score_dir: Path, initial_pdf: Path | None) -> None:
    if initial_pdf is not None:
        initial_pdf.unlink(missing_ok=True)
    for path in score_dir.rglob("*.pdf"):
        path.unlink(missing_ok=True)


def _preserve_source_audio(audio_path: Path, output_root: Path) -> Path | None:
    """Persist original input independently of the disposable Job workspace.

    Normal job output is ``jobs/<job-id>/outputs``. The song id is the job id, so
    preserving here covers local uploads and downloaded YouTube audio without coupling
    the ingestion code to either source route.
    """
    try:
        job_id = output_root.parent.name
        if not job_id:
            return None
        suffix = audio_path.suffix.lower() or ".audio"
        target = song_assets_dir() / job_id / f"original-audio{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != audio_path.stat().st_size:
            shutil.copy2(audio_path, target)
        return target
    except OSError:
        # Source preservation is validation support and must not make transcription fail.
        return None


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
    """Transcribe to editable canonical score data without creating final exports."""

    settings = settings or Settings()

    def emit(stage: str, percent: int) -> None:
        if progress is not None:
            progress(stage, percent)

    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        raise PipelineError(f"Audio file does not exist: {audio_path}")

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    _preserve_source_audio(audio_path, output_root)
    stem = audio_path.stem.replace(" ", "_")
    work_dir = output_root / stem
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    score_dir = work_dir / "score"
    lyrics_dir = work_dir / "lyrics"
    stems_dir = work_dir / "stems"
    score_dir.mkdir()
    warnings: list[str] = []

    device = detect_device_plan()
    engine = resolve_transcription_engine(settings)

    emit("transcription", 5)
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
    _remove_eager_render_artifacts(score_dir, artifacts.initial_pdf_path)
    emit("transcription", 50)

    emit("chord_analysis", 53)
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
    emit("chord_analysis", 60)

    if skip_lyrics:
        emit("complete", 100)
        return PipelineResult(
            work_dir=work_dir,
            score_dir=score_dir,
            midi_path=midi_path,
            musicxml_path=musicxml_path,
            lyric_musicxml_path=None,
            pdf_path=None,
            transcript_json_path=None,
            vocals_path=None,
            chord_report_path=chord_report if chord_report.exists() else None,
            part_pdfs=[],
            warnings=warnings,
        )

    emit("vocal_separation", 63)
    stems_dir.mkdir()
    vocals_path: Path | None = None
    lyrics_audio = audio_path
    if command_exists(settings.demucs_cmd):
        try:
            run_command(
                settings.demucs_cmd,
                ["--two-stems", "vocals", "-d", device.demucs_device, "-o", stems_dir, audio_path],
                cancel_event=cancel_event,
            )
            vocals_path = _find_one(stems_dir, "vocals.wav")
            lyrics_audio = vocals_path
        except CommandCancelled as exc:
            raise PipelineCancelled("Vocal separation cancelled.") from exc
        except (CommandError, PipelineError) as exc:
            warnings.append(
                "Demucs vocal separation failed; lyrics ASR is using the original mix instead. "
                f"Details: {exc}"
            )
    else:
        warnings.append(
            "Demucs is not available; lyrics ASR is using the original mix. "
            "Install Demucs only if isolated vocals improve lyric accuracy."
        )

    emit("vocal_separation", 72)
    emit("lyrics_asr", 75)
    lyrics_dir.mkdir()
    whisper_args: list[str | Path] = [
        lyrics_audio,
        "--model",
        settings.whisperx_model,
        "--device",
        device.whisperx_device,
        "--compute_type",
        device.whisperx_compute_type,
        "--output_dir",
        lyrics_dir,
        "--output_format",
        "json",
    ]
    if language:
        whisper_args += ["--language", language]

    try:
        run_command(settings.whisperx_cmd, whisper_args, cancel_event=cancel_event)
    except CommandCancelled as exc:
        raise PipelineCancelled("Lyrics transcription cancelled.") from exc
    except CommandError as exc:
        raise PipelineError(f"WhisperX failed.\n{exc}") from exc

    transcript_json = _find_whisper_json(lyrics_dir)
    words = load_whisperx_words(transcript_json)
    if not words:
        raise PipelineError("WhisperX completed but produced no word-level timings.")
    emit("lyrics_asr", 88)

    aligned_tokens = expand_korean_syllables(words) if language == "ko" else words
    emit("lyric_alignment", 91)
    lyric_musicxml = work_dir / "score_with_lyrics.musicxml"
    part_id, attached = attach_lyrics_to_musicxml(musicxml_path, lyric_musicxml, aligned_tokens)
    metadata = {
        "language": language,
        "selected_part_id": part_id,
        "word_count": len(words),
        "lyric_token_count": len(aligned_tokens),
        "attached_token_count": attached,
        "automatic_chord_count": len(inferred_chords),
        "transcription_engine": engine.key,
        "vocal_separation": "demucs" if vocals_path else "full_mix_fallback",
        "device_plan": device.as_dict(),
        "export_policy": "deferred_until_user_export",
    }
    (work_dir / "alignment.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    emit("complete", 100)
    return PipelineResult(
        work_dir=work_dir,
        score_dir=score_dir,
        midi_path=midi_path,
        musicxml_path=musicxml_path,
        lyric_musicxml_path=lyric_musicxml,
        pdf_path=None,
        transcript_json_path=transcript_json,
        vocals_path=vocals_path,
        chord_report_path=chord_report if chord_report.exists() else None,
        part_pdfs=[],
        warnings=warnings,
    )
