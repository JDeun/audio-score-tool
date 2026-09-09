from __future__ import annotations

from pathlib import Path

from .config import Settings, packaged_runtime
from .settings_store import SettingsStore


def runtime_settings(
    *,
    muscriptor_model: str | None = None,
    whisperx_model: str = "small",
    store: SettingsStore | None = None,
) -> Settings:
    """Resolve persisted desktop settings on top of environment/defaults.

    Unknown/retired keys in the persisted JSON are deliberately ignored so older
    installations remain forward-compatible when an integration is removed.
    In packaged mode, persisted executable paths are also ignored: release builds
    may execute only AudioScoreTool-owned managed components.
    """

    saved = (store or SettingsStore()).read()
    defaults = Settings()
    checkpoint = saved.get("native_checkpoint")
    soundfont = saved.get("validation_soundfont")
    usage_mode = (saved.get("usage_mode") or defaults.usage_mode).strip().lower()
    if usage_mode not in {"personal", "commercial"}:
        usage_mode = "personal"

    explicit_engine = saved.get("transcription_engine")
    if explicit_engine:
        engine = explicit_engine.strip().lower()
        if engine == "yourmt3":
            engine = "mt3_infer"
    else:
        engine = "muscriptor" if usage_mode == "personal" else "mt3_infer"

    if usage_mode == "commercial" and engine == "muscriptor":
        engine = "mt3_infer"

    def command_value(key: str, default: str, *legacy_keys: str) -> str:
        if packaged_runtime():
            return default
        for candidate in (key, *legacy_keys):
            value = saved.get(candidate)
            if value:
                return str(value)
        return default

    return Settings(
        usage_mode=usage_mode,
        transcription_engine=engine,
        mt3_infer_cmd=command_value(
            "mt3_infer_cmd", defaults.mt3_infer_cmd, "yourmt3_cmd"
        ),
        mt3_model=(saved.get("mt3_model") or defaults.mt3_model),
        muscriptor_cmd=command_value("muscriptor_cmd", defaults.muscriptor_cmd),
        muscriptor_model=(muscriptor_model or saved.get("muscriptor_model") or defaults.muscriptor_model),
        native_engine_cmd=command_value("native_engine_cmd", defaults.native_engine_cmd),
        native_checkpoint=Path(checkpoint).expanduser() if checkpoint else defaults.native_checkpoint,
        demucs_cmd=command_value("demucs_cmd", defaults.demucs_cmd),
        whisperx_cmd=command_value("whisperx_cmd", defaults.whisperx_cmd),
        yt_dlp_cmd=command_value("yt_dlp_cmd", defaults.yt_dlp_cmd),
        audiveris_cmd=command_value("audiveris_cmd", defaults.audiveris_cmd),
        ffmpeg_cmd=command_value("ffmpeg_cmd", defaults.ffmpeg_cmd),
        fluidsynth_cmd=command_value("fluidsynth_cmd", defaults.fluidsynth_cmd),
        validation_soundfont=Path(soundfont).expanduser() if soundfont else defaults.validation_soundfont,
        whisperx_model=whisperx_model,
    )
