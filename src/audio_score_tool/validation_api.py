from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .audio_symbol_validation import AudioSymbolValidationError, validate_audio_symbol
from .paths import song_assets_dir
from .runtime_settings import runtime_settings
from .score_validation import deterministic_validate, llm_validate
from .settings_store import SettingsStore
from .song_store_v2 import SongStoreV2
from .visual_validation import VisualValidationError, validate_omr_visual

router = APIRouter(tags=["score-validation"])
_store = SettingsStore()
_songs = SongStoreV2()

_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
_DEFAULT_MODEL = "qwen3.5:9b"
_DEFAULT_VISION_MODEL = "qwen2.5vl:7b"


class ValidationSettingsPayload(BaseModel):
    enabled: bool = False
    base_url: str = Field(default=_DEFAULT_BASE_URL, max_length=500)
    model: str = Field(default=_DEFAULT_MODEL, min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, max_length=100)
    visual_enabled: bool = False
    visual_model: str = Field(default=_DEFAULT_VISION_MODEL, min_length=1, max_length=200)
    visual_max_pages: int = Field(default=4, ge=1, le=8)
    audio_enabled: bool = False
    audio_threshold: float = Field(default=0.42, ge=0.1, le=0.9)
    validation_soundfont: str | None = Field(default=None, max_length=1000)
    ffmpeg_cmd: str | None = Field(default=None, max_length=1000)
    fluidsynth_cmd: str | None = Field(default=None, max_length=1000)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an http(s) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("non-local LLM endpoints must use https")
        return value


class ValidateRequest(BaseModel):
    use_llm: bool | None = None
    use_visual: bool | None = None
    use_audio: bool | None = None


def _bool_setting(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _settings() -> dict:
    saved = _store.read()
    runtime = runtime_settings(store=_store)
    try:
        visual_max_pages = max(1, min(8, int(saved.get("visual_validation_max_pages") or "4")))
    except ValueError:
        visual_max_pages = 4
    try:
        audio_threshold = max(0.1, min(0.9, float(saved.get("audio_validation_threshold") or "0.42")))
    except ValueError:
        audio_threshold = 0.42
    return {
        "enabled": _bool_setting(saved.get("llm_validation_enabled"), False),
        "base_url": saved.get("llm_validation_base_url") or _DEFAULT_BASE_URL,
        "model": saved.get("llm_validation_model") or _DEFAULT_MODEL,
        "api_key_env": saved.get("llm_validation_api_key_env") or None,
        "visual_enabled": _bool_setting(saved.get("visual_validation_enabled"), False),
        "visual_model": saved.get("visual_validation_model") or _DEFAULT_VISION_MODEL,
        "visual_max_pages": visual_max_pages,
        "audio_enabled": _bool_setting(saved.get("audio_validation_enabled"), False),
        "audio_threshold": audio_threshold,
        "validation_soundfont": saved.get("validation_soundfont") or None,
        "ffmpeg_cmd": saved.get("ffmpeg_cmd") or runtime.ffmpeg_cmd,
        "fluidsynth_cmd": saved.get("fluidsynth_cmd") or runtime.fluidsynth_cmd,
        "audio_tools": {
            "soundfont_configured": bool(runtime.validation_soundfont and runtime.validation_soundfont.is_file()),
        },
    }


def _analysis_context(song_id: str) -> dict:
    result = {}
    for kind in ("automatic_chords", "lyric_alignment"):
        value = _songs.analysis(song_id, kind)
        if value is not None:
            result[kind] = value
    transcript = _songs.analysis(song_id, "lyrics_transcript")
    if transcript is not None:
        if isinstance(transcript, dict) and isinstance(transcript.get("segments"), list):
            result["lyrics_transcript_sample"] = {
                **{key: value for key, value in transcript.items() if key != "segments"},
                "segments": transcript["segments"][:12],
            }
        else:
            result["lyrics_transcript_sample"] = transcript
    return result


def _source_audio(song_id: str) -> Path | None:
    root = song_assets_dir() / song_id
    candidates = sorted(root.glob("original-audio.*")) if root.exists() else []
    return candidates[0] if candidates else None


@router.get("/api/validation/settings")
def get_validation_settings() -> dict:
    return _settings()


@router.put("/api/validation/settings")
def update_validation_settings(payload: ValidationSettingsPayload) -> dict:
    _store.update(
        {
            "llm_validation_enabled": payload.enabled,
            "llm_validation_base_url": payload.base_url,
            "llm_validation_model": payload.model,
            "llm_validation_api_key_env": payload.api_key_env,
            "visual_validation_enabled": payload.visual_enabled,
            "visual_validation_model": payload.visual_model,
            "visual_validation_max_pages": payload.visual_max_pages,
            "audio_validation_enabled": payload.audio_enabled,
            "audio_validation_threshold": payload.audio_threshold,
            "validation_soundfont": payload.validation_soundfont,
            "ffmpeg_cmd": payload.ffmpeg_cmd,
            "fluidsynth_cmd": payload.fluidsynth_cmd,
        }
    )
    return get_validation_settings()


@router.post("/api/songs/{song_id}/validate")
def validate_song(song_id: str, payload: ValidateRequest | None = None) -> dict:
    song = _songs.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    try:
        xml_text = _songs.score_xml(song_id)
        deterministic = deterministic_validate(xml_text)
    except Exception as exc:
        raise HTTPException(422, f"Could not validate MusicXML: {exc}") from exc

    settings = _settings()
    use_llm = payload.use_llm if payload and payload.use_llm is not None else settings["enabled"]
    use_visual = payload.use_visual if payload and payload.use_visual is not None else settings["visual_enabled"]
    use_audio = payload.use_audio if payload and payload.use_audio is not None else settings["audio_enabled"]

    llm_report = None
    if use_llm:
        try:
            llm_report = llm_validate(
                deterministic_report=deterministic,
                analyses=_analysis_context(song_id),
                base_url=str(settings["base_url"]),
                model=str(settings["model"]),
                api_key_env=str(settings["api_key_env"]) if settings["api_key_env"] else None,
            )
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc

    visual_report = None
    visual_skipped = None
    if use_visual:
        try:
            visual_report = validate_omr_visual(
                song_id=song_id,
                xml_text=xml_text,
                base_url=str(settings["base_url"]),
                model=str(settings["visual_model"]),
                api_key_env=str(settings["api_key_env"]) if settings["api_key_env"] else None,
                max_pages=int(settings["visual_max_pages"]),
            )
        except VisualValidationError as exc:
            visual_skipped = str(exc)

    audio_report = None
    audio_skipped = None
    if use_audio:
        source_audio = _source_audio(song_id)
        runtime = runtime_settings(store=_store)
        if source_audio is None:
            audio_skipped = "보존된 원본 음원이 없습니다. 기존 곡은 다시 채보하면 이후 audio-symbol 검증이 가능합니다."
        elif runtime.validation_soundfont is None:
            audio_skipped = "audio-symbol 검증용 SoundFont(.sf2/.sf3)를 설정하세요."
        else:
            try:
                audio_report = validate_audio_symbol(
                    source_audio=source_audio,
                    xml_text=xml_text,
                    working_musicxml=_songs.checkout_current(song_id),
                    ffmpeg_cmd=runtime.ffmpeg_cmd,
                    fluidsynth_cmd=runtime.fluidsynth_cmd,
                    soundfont_path=runtime.validation_soundfont,
                    threshold=float(settings["audio_threshold"]),
                )
            except AudioSymbolValidationError as exc:
                audio_skipped = str(exc)

    combined_issues = list(deterministic["issues"])
    if llm_report:
        combined_issues.extend(llm_report["issues"])
    if visual_report:
        combined_issues.extend(visual_report["issues"])
    if audio_report:
        combined_issues.extend(audio_report["issues"])

    result = {
        "song_id": song_id,
        "revision": song.get("revision", 1),
        "ok": deterministic["ok"] and not any(
            issue.get("severity") == "error"
            for issue in [
                *((llm_report or {}).get("issues", [])),
                *((visual_report or {}).get("issues", [])),
                *((audio_report or {}).get("issues", [])),
            ]
        ),
        "deterministic": deterministic,
        "llm": llm_report,
        "visual": visual_report,
        "visual_skipped": visual_skipped,
        "audio": audio_report,
        "audio_skipped": audio_skipped,
        "issues": combined_issues,
        "policy": {
            "llm_is_advisory": True,
            "visual_is_advisory": True,
            "audio_symbol_is_evidence": True,
            "auto_edit": False,
            "omr_visual_compare_uses_original_score_evidence": True,
            "audio_compare_uses_original_audio_evidence": True,
        },
    }
    _songs.set_analysis(song_id, "validation_report", result)
    if visual_report:
        _songs.set_analysis(song_id, "omr_visual_validation", visual_report)
    if audio_report:
        _songs.set_analysis(song_id, "audio_symbol_validation", audio_report)
    return result


@router.get("/api/songs/{song_id}/validation")
def get_last_validation(song_id: str) -> dict:
    if not _songs.get(song_id):
        raise HTTPException(404, "Song not found")
    report = _songs.analysis(song_id, "validation_report")
    return {"report": report}
