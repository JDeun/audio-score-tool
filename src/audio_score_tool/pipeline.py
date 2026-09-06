from __future__ import annotations

import json
import os
import platform
import shutil
from collections.abc import Callable
from pathlib import Path
from threading import Event

from .auto_chords import apply_inferred_chords
from .config import Settings
from .devices import detect_device_plan
from .lyrics import attach_lyrics_to_musicxml, expand_korean_syllables, load_whisperx_words
from .models import PipelineResult
from .musicxml_parts import extract_part_musicxml, list_score_parts
from .runner import CommandCancelled, CommandError, command_exists, run_command
from .system_status import huggingface_authenticated


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


def _resolve_musescore(settings: Settings) -> str | None:
    if settings.musescore_cmd:
        return settings.musescore_cmd
    env_path = os.getenv("MUSCRIPTOR_MUSESCORE")
    if env_path:
        return env_path
    for candidate in ("mscore", "musescore", "MuseScore4", "musescore4", "MuseScore"):
        if shutil.which(candidate):
            return candidate
    for candidate in (
        "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
        str(Path("~/MuseScore.AppImage").expanduser()),
        str(Path("~/Applications/MuseScore.AppImage").expanduser()),
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _render_pdf(
    musicxml: Path,
    pdf: Path,
    settings: Settings,
    cancel_event: Event | None = None,
) -> bool:
    cmd = _resolve_musescore(settings)
    if not cmd:
        return False
    try:
        env = None
        if platform.system() == "Linux":
            env = {
                "QT_QPA_PLATFORM": "offscreen",
                "MU_QT_QPA_PLATFORM": "offscreen",
            }
        run_command(cmd, ["-o", pdf, musicxml], env=env, cancel_event=cancel_event)
        return pdf.exists()
    except CommandCancelled:
        raise
    except CommandError:
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
    tools = {
        "muscriptor": command_exists(settings.muscriptor_cmd),
        "demucs": command_exists(settings.demucs_cmd),
        "whisperx": command_exists(settings.whisperx_cmd),
        "musescore_override_or_path": _resolve_musescore(settings) is not None,
    }
    missing = ["muscriptor"] if not tools["muscriptor"] else []
    if not tools["musescore_override_or_path"]:
        missing.append("musescore")
    if require_lyrics:
        missing += [name for name in ("demucs", "whisperx") if not tools[name]]
    hf_ready = huggingface_authenticated()
    if not hf_ready:
        missing.append("huggingface_auth")
    return {
        "ok": not missing,
        "missing": missing,
        "tools": tools,
        "huggingface_authenticated": hf_ready,
        "device_plan": detect_device_plan().as_dict(),
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

    emit("transcription", 5)

    # 1) Full multi-instrument transcription + quantized score.
    muscriptor_args = [
        "transcribe",
        audio_path,
        "--format",
        "sheets",
        "--output",
        score_dir,
        "--device",
        device.muscriptor_device,
        "--model",
        settings.muscriptor_model,
        "--detect-tempo",
        "best-effort",
    ]
    try:
        run_command(settings.muscriptor_cmd, muscriptor_args, cancel_event=cancel_event)
    except CommandCancelled as exc:
        raise PipelineCancelled("Transcription cancelled.") from exc
    except CommandError as exc:
        raise PipelineError(f"MuScriptor failed.\n{exc}") from exc

    midi_path = _find_one(score_dir, "score.mid")
    musicxml_path = _find_one(score_dir, "score.musicxml")
    mu_full_pdf = _find_one(score_dir, "full_score.pdf")
    emit("transcription", 47)

    # 2) Infer a chord progression from the already separated multi-instrument notation.
    emit("chord_analysis", 50)
    chord_report = work_dir / "chords.json"
    try:
        inferred_chords = apply_inferred_chords(musicxml_path, report_path=chord_report)
        if not inferred_chords:
            warnings.append(
                "Automatic chord analysis did not find sufficiently confident chord changes. "
                "The score remains editable in the Chord inspector."
            )
    except (OSError, ValueError, ET.ParseError) as exc:  # type: ignore[name-defined]
        inferred_chords = []
        warnings.append(f"Automatic chord analysis was skipped: {exc}")
    emit("chord_analysis", 56)

    if skip_lyrics:
        final_pdf = work_dir / "score_with_chords.pdf"
        if not _render_pdf(musicxml_path, final_pdf, settings, cancel_event):
            final_pdf = mu_full_pdf
            warnings.append(
                "Could not re-render the chord-enriched full score; returning MuScriptor's "
                "initial full_score.pdf. MusicXML still contains the inferred chord symbols."
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

    # 3) Vocal isolation for lyrics ASR. Other score parts come from MuScriptor's
    # multi-instrument transcription; Demucs is only needed here for lyrics quality.
    stems_dir.mkdir()
    try:
        run_command(
            settings.demucs_cmd,
            [
                "--two-stems",
                "vocals",
                "-d",
                device.demucs_device,
                "-o",
                stems_dir,
                audio_path,
            ],
            cancel_event=cancel_event,
        )
    except CommandCancelled as exc:
        raise PipelineCancelled("Vocal separation cancelled.") from exc
    except CommandError as exc:
        raise PipelineError(f"Demucs failed.\n{exc}") from exc

    vocals_path = _find_one(stems_dir, "vocals.wav")
    emit("vocal_separation", 70)
    emit("lyrics_asr", 73)

    # 4) Singing lyrics transcription + word-level forced alignment.
    lyrics_dir.mkdir()
    whisper_args: list[str | Path] = [
        vocals_path,
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
    emit("lyrics_asr", 85)
    words = load_whisperx_words(transcript_json)
    if not words:
        raise PipelineError("WhisperX completed but produced no word-level timings.")

    aligned_tokens = expand_korean_syllables(words) if language == "ko" else words

    emit("lyric_alignment", 87)

    # 5) Attach timed lyric tokens to the vocal-like MusicXML part. Since the chord
    # symbols were already inserted, the resulting MusicXML contains both lyrics and harmony.
    lyric_musicxml = work_dir / "score_with_lyrics.musicxml"
    part_id, attached = attach_lyrics_to_musicxml(
        musicxml_path,
        lyric_musicxml,
        aligned_tokens,
    )
    metadata = {
        "language": language,
        "selected_part_id": part_id,
        "word_count": len(words),
        "lyric_token_count": len(aligned_tokens),
        "attached_token_count": attached,
        "automatic_chord_count": len(inferred_chords),
        "device_plan": device.as_dict(),
    }
    (work_dir / "alignment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    emit("rendering", 93)

    # 6) Render the final full score and one PDF per detected instrument from the
    # same lyric/chord-enriched MusicXML.
    lyric_pdf = work_dir / "score_with_lyrics.pdf"
    try:
        rendered = _render_pdf(lyric_musicxml, lyric_pdf, settings, cancel_event)
        part_pdfs = _render_instrument_parts(
            lyric_musicxml,
            parts_dir,
            settings,
            cancel_event,
        )
    except CommandCancelled as exc:
        raise PipelineCancelled("Score rendering cancelled.") from exc

    if not rendered:
        lyric_pdf = mu_full_pdf
        warnings.append(
            "Could not directly invoke MuseScore for score_with_lyrics.pdf; "
            "returning MuScriptor's initial full_score.pdf. The lyric/chord-enriched "
            "MusicXML was generated correctly."
        )

    emit("complete", 100)

    return PipelineResult(
        work_dir=work_dir,
        score_dir=score_dir,
        midi_path=midi_path,
        musicxml_path=musicxml_path,
        lyric_musicxml_path=lyric_musicxml,
        pdf_path=lyric_pdf,
        transcript_json_path=transcript_json,
        vocals_path=vocals_path,
        chord_report_path=chord_report if chord_report.exists() else None,
        part_pdfs=part_pdfs,
        warnings=warnings,
    )
