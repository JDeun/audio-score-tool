from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

from .auto_chords import apply_inferred_chords
from .choir_postprocess import reconstruct_satb
from .config import Settings, packaged_runtime
from .demucs_runtime import demucs_repo_args, managed_demucs_repository
from .devices import detect_device_plan
from .lyrics import attach_lyrics_to_musicxml, expand_korean_syllables, load_whisperx_words
from .models import PipelineResult
from .music_structure import (
    analyze_midi_meter_and_pickup,
    prepare_music_audio,
    write_structure_report,
)
from .paths import song_assets_dir
from .pickup_normalization import normalize_pickup_measure
from .pipeline import PipelineCancelled, PipelineError, _find_one, _find_whisper_json
from .reference_lyrics import align_reference_lyrics
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .score_requests import validate_engine_score_mode, validate_score_mode
from .selected_stem_score import SelectedScoreError, transcribe_selected_stems
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
    """Persist original input independently of the disposable Job workspace."""
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
        return None


def transcribe(
    audio_path: Path,
    output_root: Path,
    *,
    language: str | None = None,
    skip_lyrics: bool = False,
    score_mode: str = "full",
    choir_mode: str = "off",
    reference_lyrics: dict[str, Any] | None = None,
    settings: Settings | None = None,
    progress: Callable[[str, int], None] | None = None,
    cancel_event: Event | None = None,
    preserve_source_audio: bool = True,
) -> PipelineResult:
    """Transcribe to editable canonical score data without creating final exports."""

    settings = settings or Settings()
    score_mode = validate_score_mode(score_mode)
    choir_mode = choir_mode.strip().lower()
    if score_mode != "full":
        choir_mode = "off"  # Never reinterpret selected stem roles as a choir.
    if choir_mode not in {"auto", "choir", "off"}:
        raise PipelineError("choir_mode must be auto, choir, or off")

    def emit(stage: str, percent: int) -> None:
        if progress is not None:
            progress(stage, percent)

    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        raise PipelineError(f"Audio file does not exist: {audio_path}")

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if preserve_source_audio:
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
    validate_engine_score_mode(score_mode, engine.key)

    emit("music_structure", 3)
    try:
        transcription_audio, structure = prepare_music_audio(
            audio_path,
            work_dir,
            settings=settings,
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise PipelineCancelled("Music-start analysis cancelled.") from exc
    warnings.extend(structure.warnings)
    if structure.trimmed:
        warnings.append(
            f"Detected a non-musical intro and started transcription at approximately "
            f"{structure.music_start_seconds:.2f}s (confidence {structure.start_confidence:.2f})."
        )

    selected_vocals_path: Path | None = None
    emit("stem_separation" if score_mode != "full" else "transcription", 8)
    try:
        if score_mode == "full" or engine.key == "sheetsage2":
            artifacts = engine.transcribe(
                transcription_audio,
                score_dir,
                device=device.muscriptor_device,
                cancel_event=cancel_event,
            )
        else:
            artifacts, selected_vocals_path, selected_warnings = transcribe_selected_stems(
                transcription_audio, score_dir, stems_dir,
                score_mode=score_mode, settings=settings, engine=engine,
                device=device.muscriptor_device,
                demucs_device=device.demucs_device,
                cancel_event=cancel_event,
            )
            warnings.extend(selected_warnings)
    except TranscriptionEngineCancelled as exc:
        raise PipelineCancelled("Transcription cancelled.") from exc
    except (TranscriptionEngineError, SelectedScoreError) as exc:
        raise PipelineError(f"{engine.display_name} failed.\n{exc}") from exc

    midi_path = artifacts.midi_path
    musicxml_path = artifacts.musicxml_path
    _remove_eager_render_artifacts(score_dir, artifacts.initial_pdf_path)
    emit("music_structure", 48)

    structure = analyze_midi_meter_and_pickup(midi_path, structure)
    if engine.key == "sheetsage2":
        analysis = json.loads((score_dir / "analysis.json").read_text())
        structure.meter_source = "sheetsage2_audio_model"
        structure.tempo_source = "sheetsage2_audio_grid"
        downbeats = analysis.get("downbeats", [])
        structure.first_downbeat_seconds = downbeats[0]["time_seconds"] if downbeats else None
        # The model's notation is already metrical; do not apply a second MIDI heuristic.
        structure.pickup_confidence = 0.0
    warnings.extend(warning for warning in structure.warnings if warning not in warnings)
    pickup_result = normalize_pickup_measure(
        musicxml_path,
        work_dir / "score_with_pickup.musicxml",
        pickup_quarters=structure.pickup_quarters,
        numerator=structure.meter_numerator,
        denominator=structure.meter_denominator,
        confidence=structure.pickup_confidence,
    )
    if pickup_result.applied:
        musicxml_path = work_dir / "score_with_pickup.musicxml"
        warnings.append(
            f"Normalized an anacrusis/pickup of {structure.pickup_quarters:.2f} quarter notes."
        )
    elif structure.pickup_quarters > 0:
        warnings.append(
            "A possible pickup was detected but the generated score timing was not rewritten "
            f"({pickup_result.reason}); the structure report keeps the estimate for manual review."
        )

    choir_output = work_dir / "score_satb.musicxml"
    choir_result = reconstruct_satb(musicxml_path, choir_output, mode=choir_mode)
    if choir_result.applied:
        musicxml_path = choir_output
        warnings.append(
            f"Reconstructed SATB voices ({choir_result.reason}, confidence {choir_result.confidence:.2f})."
        )
    elif choir_mode == "choir":
        warnings.append(
            f"Choir mode was requested but SATB reconstruction was not safe: {choir_result.reason}."
        )

    structure_report = write_structure_report(
        work_dir / "music_structure.json",
        structure,
        pickup_normalization=pickup_result.as_dict(),
        choir=choir_result.as_dict(),
        transcription_audio=str(transcription_audio),
    )
    emit("transcription", 52)

    emit("chord_analysis", 55)
    chord_report = work_dir / "chords.json"
    try:
        if engine.key == "sheetsage2":
            inferred_chords = analysis.get("chords", [])
            chord_report.write_text(json.dumps({"source": "sheetsage2", "chords": inferred_chords}))
        else:
            inferred_chords = apply_inferred_chords(musicxml_path, report_path=chord_report)
        if not inferred_chords and score_mode != "lead_sheet":
            warnings.append(
                "Automatic chord analysis did not find sufficiently confident chord changes. "
                "The score remains editable in the Chord inspector."
            )
    except (OSError, ValueError, ET.ParseError) as exc:
        inferred_chords = []
        warnings.append(f"Automatic chord analysis was skipped: {exc}")
    emit("chord_analysis", 62)

    def score_without_lyrics() -> PipelineResult:
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
            structure_report_path=structure_report,
            part_pdfs=[],
            warnings=warnings,
        )

    if skip_lyrics:
        return score_without_lyrics()

    # Lyrics are optional evidence/enrichment: never discard a valid AMT score
    # just because the managed WhisperX component is missing.
    if not command_exists(settings.whisperx_cmd):
        warnings.append("WhisperX is unavailable. Lyrics were skipped; the base score is preserved.")
        return score_without_lyrics()

    def run_optional_lyrics() -> PipelineResult:
        emit("vocal_separation", 65)
        stems_dir.mkdir(exist_ok=True)
        vocals_path: Path | None = selected_vocals_path
        lyrics_audio = vocals_path or transcription_audio
        if vocals_path is not None:
            pass  # Reuse the already isolated vocal stem.
        elif command_exists(settings.demucs_cmd) and (
            not packaged_runtime() or managed_demucs_repository(settings) is not None
        ):
            try:
                run_command(
                    settings.demucs_cmd,
                    [
                        "--two-stems",
                        "vocals",
                        *demucs_repo_args(settings),
                        "-d",
                        device.demucs_device,
                        "-o",
                        stems_dir,
                        transcription_audio,
                    ],
                    cancel_event=cancel_event,
                )
                vocals_path = _find_one(stems_dir, "vocals.wav")
                lyrics_audio = vocals_path
            except CommandCancelled as exc:
                raise PipelineCancelled("Vocal separation cancelled.") from exc
            except (CommandError, PipelineError) as exc:
                warnings.append(
                    "Demucs vocal separation failed; lyrics ASR is using the music-region mix instead. "
                    f"Details: {exc}"
                )
        else:
            warnings.append(
                "Demucs is not available; lyrics ASR is using the music-region mix. "
                "Install Demucs only if isolated vocals improve lyric accuracy."
            )

        emit("vocal_separation", 74)
        emit("lyrics_asr", 77)
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
        emit("lyrics_asr", 89)

        aligned_tokens = expand_korean_syllables(words) if language == "ko" else words
        lyrics_source = "whisperx"
        reference_stats: dict[str, Any] | None = None
        # API lyrics are the text reference; WhisperX is still necessary for
        # acoustic word timing and score-note alignment.
        if reference_lyrics and isinstance(reference_lyrics.get("lyrics"), str):
            try:
                candidate, stats = align_reference_lyrics(
                    json.loads(transcript_json.read_text(encoding="utf-8")),
                    reference_lyrics["lyrics"],
                    language=language,
                )
                reference_stats = stats
                if candidate and stats.get("coverage", 0) >= 0.3:
                    aligned_tokens = candidate
                    lyrics_source = str(reference_lyrics.get("provider") or "external_api")
                else:
                    warnings.append(
                        "External lyric text did not align reliably with the acoustic "
                        "transcript; using WhisperX transcription instead."
                    )
            except (ValueError, TypeError, KeyError, OSError) as exc:
                warnings.append(
                    f"External lyric alignment could not be verified ({type(exc).__name__}); "
                    "using WhisperX transcription instead."
                )
        emit("lyric_alignment", 92)
        lyric_musicxml = work_dir / "score_with_lyrics.musicxml"
        part_id, attached = attach_lyrics_to_musicxml(musicxml_path, lyric_musicxml, aligned_tokens)
        metadata = {
            "language": language,
            "lyrics_source": lyrics_source,
            "external_lyrics_available": reference_lyrics is not None,
            "external_lyrics_alignment": reference_stats,
            "selected_part_id": part_id,
            "word_count": len(words),
            "lyric_token_count": len(aligned_tokens),
            "attached_token_count": attached,
            "automatic_chord_count": len(inferred_chords),
            "transcription_engine": engine.key,
            "vocal_separation": "demucs" if vocals_path else "full_mix_fallback",
            "device_plan": device.as_dict(),
            "export_policy": "deferred_until_user_export",
            "music_structure": structure.as_dict(),
            "pickup_normalization": pickup_result.as_dict(),
            "choir": choir_result.as_dict(),
        }
        (work_dir / "alignment.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

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
            structure_report_path=structure_report,
            part_pdfs=[],
            warnings=warnings,
        )

    try:
        return run_optional_lyrics()
    except PipelineCancelled:
        # User cancellation is intentional and must still abort the Job.
        raise
    except Exception as exc:
        # A broken optional ASR/alignment path is not evidence that the
        # independently generated canonical MusicXML/MIDI is invalid.
        warnings.append(
            f"Optional lyrics processing failed; base score preserved "
            f"({type(exc).__name__}): {exc}"
        )
        return score_without_lyrics()
