from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from .score_validation import deterministic_validate, llm_validate
from .settings_store import SettingsStore
from .song_store_v2 import SongStoreV2

router = APIRouter(tags=["score-validation"])
_store = SettingsStore()
_songs = SongStoreV2()

_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
_DEFAULT_MODEL = "qwen3.5:9b"


class ValidationSettingsPayload(BaseModel):
    enabled: bool = False
    base_url: str = Field(default=_DEFAULT_BASE_URL, max_length=500)
    model: str = Field(default=_DEFAULT_MODEL, min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, max_length=100)

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


def _bool_setting(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _settings() -> dict:
    saved = _store.read()
    return {
        "enabled": _bool_setting(saved.get("llm_validation_enabled"), False),
        "base_url": saved.get("llm_validation_base_url") or _DEFAULT_BASE_URL,
        "model": saved.get("llm_validation_model") or _DEFAULT_MODEL,
        "api_key_env": saved.get("llm_validation_api_key_env") or None,
    }


def _analysis_context(song_id: str) -> dict:
    result = {}
    for kind in ("automatic_chords", "lyric_alignment"):
        value = _songs.analysis(song_id, kind)
        if value is not None:
            result[kind] = value
    transcript = _songs.analysis(song_id, "lyrics_transcript")
    if transcript is not None:
        # Full WhisperX output can be very large. The LLM critic only needs a bounded
        # sample because timing correctness must ultimately be verified against audio.
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
    requested = payload.use_llm if payload and payload.use_llm is not None else settings["enabled"]
    llm_report = None
    if requested:
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

    combined_issues = list(deterministic["issues"])
    if llm_report:
        combined_issues.extend(llm_report["issues"])
    result = {
        "song_id": song_id,
        "revision": song.get("revision", 1),
        "ok": deterministic["ok"] and not any(
            issue.get("severity") == "error" for issue in (llm_report or {}).get("issues", [])
        ),
        "deterministic": deterministic,
        "llm": llm_report,
        "issues": combined_issues,
        "policy": {
            "llm_is_advisory": True,
            "auto_edit": False,
            "audio_fidelity_requires_audio_evidence": True,
        },
    }
    _songs.set_analysis(song_id, "validation_report", result)
    return result


@router.get("/api/songs/{song_id}/validation")
def get_last_validation(song_id: str) -> dict:
    if not _songs.get(song_id):
        raise HTTPException(404, "Song not found")
    report = _songs.analysis(song_id, "validation_report")
    return {"report": report}
