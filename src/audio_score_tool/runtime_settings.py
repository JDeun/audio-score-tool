from __future__ import annotations

from pathlib import Path

from .config import Settings
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

    return Settings(
        usage_mode=usage_mode,
        transcription_engine=engine,
        mt3_infer_cmd=(saved.get("mt3_infer_cmd") or saved.get("yourmt3_cmd") or defaults.mt3_infer_cmd),
        mt3_model=(saved.get("mt3_model") or defaults.mt3_model),
        muscriptor_cmd=saved.get("muscriptor_cmd") or defaults.muscriptor_cmd,
        muscriptor_model=(muscriptor_model or saved.get("muscriptor_model") or defaults.muscriptor_model),
        native_engine_cmd=saved.get("native_engine_cmd") or defaults.native_engine_cmd,
        native_checkpoint=Path(checkpoint).expanduser() if checkpoint else defaults.native_checkpoint,
        demucs_cmd=saved.get("demucs_cmd") or defaults.demucs_cmd,
        whisperx_cmd=saved.get("whisperx_cmd") or defaults.whisperx_cmd,
        yt_dlp_cmd=saved.get("yt_dlp_cmd") or defaults.yt_dlp_cmd,
        audiveris_cmd=saved.get("audiveris_cmd") or defaults.audiveris_cmd,
        ffmpeg_cmd=saved.get("ffmpeg_cmd") or defaults.ffmpeg_cmd,
        fluidsynth_cmd=saved.get("fluidsynth_cmd") or defaults.fluidsynth_cmd,
        validation_soundfont=Path(soundfont).expanduser() if soundfont else defaults.validation_soundfont,
        whisperx_model=whisperx_model,
    )
