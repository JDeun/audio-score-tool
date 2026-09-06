from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .config import Settings
from .devices import detect_device_plan
from .lyrics import attach_lyrics_to_musicxml, expand_korean_syllables, load_whisperx_words
from .models import PipelineResult
from .runner import CommandError, command_exists, run_command


class PipelineError(RuntimeError):
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


def _render_pdf(musicxml: Path, pdf: Path, settings: Settings) -> bool:
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
        run_command(cmd, ["-o", pdf, musicxml], env=env)
        return pdf.exists()
    except CommandError:
        return False


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
    return {
        "ok": not missing,
        "missing": missing,
        "tools": tools,
        "device_plan": detect_device_plan().as_dict(),
    }


def transcribe(
    audio_path: Path,
    output_root: Path,
    *,
    language: str | None = None,
    skip_lyrics: bool = False,
    settings: Settings | None = None,
) -> PipelineResult:
    settings = settings or Settings()
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
    score_dir.mkdir()
    warnings: list[str] = []

    device = detect_device_plan()

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
        run_command(settings.muscriptor_cmd, muscriptor_args)
    except CommandError as exc:
        raise PipelineError(f"MuScriptor failed.\n{exc}") from exc

    midi_path = _find_one(score_dir, "score.mid")
    musicxml_path = _find_one(score_dir, "score.musicxml")
    full_pdf = _find_one(score_dir, "full_score.pdf")

    if skip_lyrics:
        return PipelineResult(
            work_dir=work_dir,
            score_dir=score_dir,
            midi_path=midi_path,
            musicxml_path=musicxml_path,
            lyric_musicxml_path=None,
            pdf_path=full_pdf,
            transcript_json_path=None,
            vocals_path=None,
            warnings=warnings,
        )

    # 2) Vocal isolation for lyrics ASR.
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
        )
    except CommandError as exc:
        raise PipelineError(f"Demucs failed.\n{exc}") from exc

    vocals_path = _find_one(stems_dir, "vocals.wav")

    # 3) Singing lyrics transcription + word-level forced alignment.
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
        run_command(settings.whisperx_cmd, whisper_args)
    except CommandError as exc:
        raise PipelineError(f"WhisperX failed.\n{exc}") from exc

    transcript_json = _find_whisper_json(lyrics_dir)
    words = load_whisperx_words(transcript_json)
    if not words:
        raise PipelineError("WhisperX completed but produced no word-level timings.")

    aligned_tokens = expand_korean_syllables(words) if language == "ko" else words

    # 4) Attach timed lyric tokens to the vocal-like MusicXML part.
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
        "device_plan": device.as_dict(),
    }
    (work_dir / "alignment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5) Re-render the lyric-enriched MusicXML if MuseScore is directly callable.
    lyric_pdf = work_dir / "score_with_lyrics.pdf"
    if not _render_pdf(lyric_musicxml, lyric_pdf, settings):
        lyric_pdf = full_pdf
        warnings.append(
            "Could not directly invoke MuseScore for score_with_lyrics.pdf; "
            "returning MuScriptor's full_score.pdf. The lyric-enriched MusicXML was generated."
        )

    return PipelineResult(
        work_dir=work_dir,
        score_dir=score_dir,
        midi_path=midi_path,
        musicxml_path=musicxml_path,
        lyric_musicxml_path=lyric_musicxml,
        pdf_path=lyric_pdf,
        transcript_json_path=transcript_json,
        vocals_path=vocals_path,
        warnings=warnings,
    )
