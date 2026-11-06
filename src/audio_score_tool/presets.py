from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ModelPreset:
    key: str
    label: str
    muscriptor_model: str
    whisperx_model: str
    description: str

    def as_dict(self) -> dict:
        return asdict(self)


PRESETS = {
    "fast": ModelPreset(
        key="fast",
        label="Fast",
        muscriptor_model="small",
        whisperx_model="small",
        description="Explicit speed-first override for drafts or constrained hardware.",
    ),
    "balanced": ModelPreset(
        key="balanced",
        label="Balanced",
        muscriptor_model="medium",
        whisperx_model="small",
        description="Explicit quality/speed compromise.",
    ),
    "quality": ModelPreset(
        key="quality",
        label="Quality",
        muscriptor_model="large",
        whisperx_model="large-v3",
        description="Default: highest configured transcription/lyrics quality; substantially slower.",
    ),
}


def recommended_preset() -> str:
    # Product policy: correctness and edit-distance-to-final-score matter more than latency.
    # Users on constrained hardware can still explicitly select Fast or Balanced.
    return "quality"


def list_presets() -> dict:
    recommended = recommended_preset()
    return {
        "recommended": recommended,
        "presets": [preset.as_dict() for preset in PRESETS.values()],
    }


def resolve_preset(key: str) -> ModelPreset:
    if key == "auto":
        key = recommended_preset()
    try:
        return PRESETS[key]
    except KeyError as exc:
        raise ValueError(f"Unknown preset: {key}") from exc


def resolve_job_models(
    preset: str,
    *,
    selected_muscriptor_model: str,
    selected_whisperx_model: str = "small",
    muscriptor_override: str | None = None,
    whisperx_override: str | None = None,
) -> tuple[str, str]:
    """Resolve effective per-Job models, independent of model-quality evaluation.

    The desktop Model Manager controls the saved default for the *auto* option.
    Fast/balanced/quality are explicit overrides; custom requests supply named
    model overrides with one of those valid presets as their fallback.
    """

    configured = resolve_preset(preset)
    if preset == "auto":
        fallback_muscriptor = selected_muscriptor_model
        fallback_whisperx = selected_whisperx_model
    else:
        fallback_muscriptor = configured.muscriptor_model
        fallback_whisperx = configured.whisperx_model
    return (
        muscriptor_override or fallback_muscriptor,
        whisperx_override or fallback_whisperx,
    )
