from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

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


def _bool_setting(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _settings() -> dict:
    saved = _store.read()
    try:
        visual_max_pages = max(1, min(8, int(saved.get("visual_validation_max_pages") or "4")))
    except ValueError:
        visual_max_pages = 4
    return {
        "enabled": _bool_setting(saved.get("llm_validation_enabled"), False),
        "base_url": saved.get("llm_validation_base_url") or _DEFAULT_BASE_URL,
        "model": saved.get("llm_validation_model") or _DEFAULT_MODEL,
        "api_key_env": saved.get("llm_validation_api_key_env") or None,
        "visual_enabled": _bool_setting(saved.get("visual_validation_enabled"), False),
        "visual_model": saved.get("visual_validation_model") or _DEFAULT_VISION_MODEL,
        "visual_max_pages": visual_max_pages,
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
        }
    )
    return _settings()


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
    use_visual = (
        payload.use_visual
        if payload and payload.use_visual is not None
        else settings["visual_enabled"]
    )

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

    combined_issues = list(deterministic["issues"])
    if llm_report:
        combined_issues.extend(llm_report["issues"])
    if visual_report:
        combined_issues.extend(visual_report["issues"])

    result = {
        "song_id": song_id,
        "revision": song.get("revision", 1),
        "ok": deterministic["ok"] and not any(
            issue.get("severity") == "error"
            for issue in [
                *((llm_report or {}).get("issues", [])),
                *((visual_report or {}).get("issues", [])),
            ]
        ),
        "deterministic": deterministic,
        "llm": llm_report,
        "visual": visual_report,
        "visual_skipped": visual_skipped,
        "issues": combined_issues,
        "policy": {
            "llm_is_advisory": True,
            "visual_is_advisory": True,
            "auto_edit": False,
            "audio_fidelity_requires_audio_evidence": True,
            "omr_visual_compare_uses_original_score_evidence": True,
        },
    }
    _songs.set_analysis(song_id, "validation_report", result)
    if visual_report:
        _songs.set_analysis(song_id, "omr_visual_validation", visual_report)
    return result


@router.get("/api/songs/{song_id}/validation")
def get_last_validation(song_id: str) -> dict:
    if not _songs.get(song_id):
        raise HTTPException(404, "Song not found")
    report = _songs.analysis(song_id, "validation_report")
    return {"report": report}
