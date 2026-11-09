"""Bind queued transcription choices without persisting executable paths or secrets.

Runtime locations and usage policy are resolved again when a job runs. Engine
and model choices belong to the job, so a later settings change may make that
job unavailable, but must never silently select another transcription model.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .config import Settings, packaged_runtime

ENGINES = frozenset({"mt3_infer", "muscriptor", "native"})
MT3_MODELS = frozenset({"mr_mt3", "yourmt3"})
MUSCRIPTOR_MODELS = frozenset({"small", "medium", "large"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def validate_job_selection(
    engine: str | None, mt3_model: str | None, native_sha256: str | None,
    *, selection_version: int | None = None,
) -> None:
    """NULL identity is historical/unknown, never an inferred previous model."""
    version = (0 if engine is None else 1) if selection_version is None else selection_version
    if type(version) is not int or version not in {0, 1}:
        raise ValueError("Job model selection version is invalid")
    if version == 0:
        if engine is not None:
            raise ValueError("Historical job model identity must remain unknown")
        if mt3_model is not None or native_sha256 is not None:
            raise ValueError("Job model identity is incomplete: transcription engine is missing")
        return
    if engine is None:
        raise ValueError("Job transcription engine is missing")
    if engine not in ENGINES:
        raise ValueError("Job transcription engine is invalid")
    if engine == "mt3_infer":
        if mt3_model not in MT3_MODELS:
            raise ValueError("Job MT3 model is missing or invalid")
    elif mt3_model is not None:
        raise ValueError("Job MT3 model belongs to a different transcription engine")
    if engine == "native":
        if not isinstance(native_sha256, str) or not _SHA256.fullmatch(native_sha256):
            raise ValueError("Job Native checkpoint identity is missing or invalid")
    elif native_sha256 is not None:
        raise ValueError("Job Native checkpoint belongs to a different transcription engine")


def _native_checkpoint_sha256(settings: Settings) -> str:
    checkpoint = settings.native_checkpoint
    if checkpoint is None:
        raise ValueError("The job's Native checkpoint is not configured")
    digest = hashlib.sha256()
    try:
        with checkpoint.expanduser().open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ValueError("The job's Native checkpoint is unavailable") from exc
    return digest.hexdigest()


def _check_current_policy(settings: Settings) -> None:
    if settings.transcription_engine == "muscriptor" and settings.usage_mode == "commercial":
        raise ValueError(
            "This job selected MuScriptor, which cannot run in the current commercial mode. "
            "Choose personal mode or create a new job with a permitted engine."
        )
    if packaged_runtime():
        if settings.transcription_engine == "native":
            raise ValueError("This job's Native engine is not supported in the packaged app")
        if settings.transcription_engine == "mt3_infer":
            from .runtime_settings import published_managed_mt3_model

            approved = published_managed_mt3_model()
            if approved and settings.mt3_model != approved:
                raise ValueError(
                    f"This job selected {settings.mt3_model}, but this packaged app "
                    f"supports {approved}. Create a new job to use the available model."
                )


def transcription_job_selection(settings: Settings) -> dict[str, str | int | None]:
    """Snapshot logical model choices; only Native needs a custom file identity."""
    engine = settings.transcription_engine
    if engine == "yourmt3":
        engine = "mt3_infer"
    selected = replace(settings, transcription_engine=engine)
    _check_current_policy(selected)
    result = {
        "transcription_selection_version": 1,
        "transcription_engine": engine,
        "mt3_model": settings.mt3_model if engine == "mt3_infer" else None,
        "native_checkpoint_sha256": _native_checkpoint_sha256(selected) if engine == "native" else None,
        "muscriptor_model": settings.muscriptor_model,
        "whisperx_model": settings.whisperx_model,
    }
    validate_job_selection(
        engine, result["mt3_model"], result["native_checkpoint_sha256"], selection_version=1,
    )
    if engine == "muscriptor" and settings.muscriptor_model not in MUSCRIPTOR_MODELS:
        raise ValueError("Job MuScriptor model is missing or invalid")
    if not isinstance(settings.whisperx_model, str) or not settings.whisperx_model.strip():
        raise ValueError("Job WhisperX model is missing or invalid")
    return result


def restore_transcription_job_settings(settings: Settings, job: Mapping[str, Any]) -> Settings:
    """Restore a saved selection under today's permissions and runtime locations.

    Only legacy jobs without an engine identity use the current engine. Their
    next attempt records that choice explicitly, without relabelling old runs.
    """
    engine, mt3 = job.get("transcription_engine"), job.get("mt3_model")
    native_sha = job.get("native_checkpoint_sha256")
    validate_job_selection(
        engine, mt3, native_sha, selection_version=job.get("transcription_selection_version"),
    )
    if engine == "muscriptor" and job.get("muscriptor_model") not in MUSCRIPTOR_MODELS:
        raise ValueError("Job MuScriptor model is missing or invalid")
    if engine is not None and (
        not isinstance(job.get("whisperx_model"), str) or not job["whisperx_model"].strip()
    ):
        raise ValueError("Job WhisperX model is missing or invalid")
    selected = replace(
        settings,
        transcription_engine=engine or settings.transcription_engine,
        mt3_model=mt3 if engine == "mt3_infer" else settings.mt3_model,
        muscriptor_model=job.get("muscriptor_model") or settings.muscriptor_model,
        whisperx_model=job.get("whisperx_model") or settings.whisperx_model,
    )
    _check_current_policy(selected)
    if engine == "native" and _native_checkpoint_sha256(selected) != native_sha:
        raise ValueError(
            "This job's Native checkpoint has changed. Restore the original model "
            "or create a new job; the previous job will not use different weights."
        )
    return selected
