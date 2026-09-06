from __future__ import annotations

from pathlib import Path

from .config import Settings
from .settings_store import SettingsStore


def runtime_settings(
    *,
    muscriptor_model: str = "medium",
    whisperx_model: str = "small",
    store: SettingsStore | None = None,
) -> Settings:
    """Resolve persisted desktop settings on top of environment/defaults."""

    saved = (store or SettingsStore()).read()
    defaults = Settings()
    checkpoint = saved.get("native_checkpoint")
    engine = (saved.get("transcription_engine") or defaults.transcription_engine).strip().lower()
    if engine == "yourmt3":
        engine = "mt3_infer"
    return Settings(
        transcription_engine=engine,
        mt3_infer_cmd=(
            saved.get("mt3_infer_cmd")
            or saved.get("yourmt3_cmd")
            or defaults.mt3_infer_cmd
        ),
        mt3_model=saved.get("mt3_model") or defaults.mt3_model,
        muscriptor_cmd=saved.get("muscriptor_cmd") or defaults.muscriptor_cmd,
        native_engine_cmd=saved.get("native_engine_cmd") or defaults.native_engine_cmd,
        native_checkpoint=Path(checkpoint).expanduser() if checkpoint else defaults.native_checkpoint,
        demucs_cmd=saved.get("demucs_cmd") or defaults.demucs_cmd,
        whisperx_cmd=saved.get("whisperx_cmd") or defaults.whisperx_cmd,
        yt_dlp_cmd=saved.get("yt_dlp_cmd") or defaults.yt_dlp_cmd,
        musescore_cmd=saved.get("musescore_cmd") or defaults.musescore_cmd,
        muscriptor_model=muscriptor_model,
        whisperx_model=whisperx_model,
    )
