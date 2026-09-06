from __future__ import annotations

from dataclasses import asdict, dataclass

from .devices import detect_device_plan


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
        description="Lowest compute cost; best for CPU or quick drafts.",
    ),
    "balanced": ModelPreset(
        key="balanced",
        label="Balanced",
        muscriptor_model="medium",
        whisperx_model="small",
        description="Default quality/speed balance for most systems.",
    ),
    "quality": ModelPreset(
        key="quality",
        label="Quality",
        muscriptor_model="large",
        whisperx_model="large-v3",
        description="Highest configured model quality; requires substantially more compute.",
    ),
}


def recommended_preset() -> str:
    device = detect_device_plan()
    if device.muscriptor_device == "cpu":
        return "fast"
    if device.muscriptor_device == "mps":
        return "balanced"
    return "balanced"


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
