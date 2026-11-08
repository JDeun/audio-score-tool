from __future__ import annotations

from pathlib import Path
from typing import Any

from .managed_publication_readiness import (
    CORE_COMPONENTS,
    STABLE_TARGETS,
    _artifact_payload,
    publication_readiness,
)
from .release_quality_approval import load_quality_approval


def verify_release_model_binding(quality: dict[str, Any]) -> dict[str, Any]:
    """Bind #34 benchmark approval to both exact, independently approved OS payloads.

    A native Windows executable ZIP and a macOS ZIP can have different SHA-256
    values, but the selected checkpoint bytes and pinned model/runtime identity
    must match. This does not replace remote-byte or legal sign-off verification.
    """
    engine = quality.get("engine")
    if not isinstance(engine, dict) or engine.get("id") != "mt3_infer":
        raise RuntimeError("v1 release quality has no supported commercial MT3 engine")
    expected = {
        "model_revision": engine.get("model_revision"),
        "runtime_revision": engine.get("runtime_revision"),
        "checkpoint_sha256": engine.get("artifact_sha256"),
    }
    if not all(isinstance(v, str) and v.strip() for v in expected.values()):
        raise RuntimeError("v1 approved model identity is incomplete")
    models: dict[str, str] = {}
    for target in STABLE_TARGETS:
        payload = _artifact_payload("transcription_engine", target)
        identity = payload.get("model_identity") if isinstance(payload, dict) else None
        if not isinstance(identity, dict):
            raise RuntimeError(f"v1 model identity missing: {target}")
        for name, value in expected.items():
            if identity.get(name) != value:
                raise RuntimeError(f"v1 model mismatch: {target}.{name}")
        if (
            identity.get("model_key") != "mr_mt3"
            or identity.get("checkpoint_path") != "checkpoints/mr_mt3/mt3.pth"
        ):
            raise RuntimeError(f"v1 model key/path mismatch: {target}")
        models[target] = identity["checkpoint_sha256"]
    return {
        "ready": True,
        "engine_id": engine["id"],
        "model_key": "mr_mt3",
        "model_revision": expected["model_revision"],
        "runtime_revision": expected["runtime_revision"],
        "checkpoint_sha256": expected["checkpoint_sha256"],
        "targets": list(models),
    }


def v1_release_readiness(*, repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    quality = load_quality_approval(
        repository_root / "release" / "v1-quality-approval.json",
        repository_root=repository_root,
    )
    managed = publication_readiness(components=CORE_COMPONENTS, targets=STABLE_TARGETS)
    model_binding = verify_release_model_binding(quality)
    return {
        "ready": bool(managed["ready"] and model_binding["ready"]),
        "quality": quality,
        "managed_runtime": managed,
        "model_binding": model_binding,
    }


def assert_v1_release_ready(*, repository_root: Path) -> dict[str, Any]:
    report = v1_release_readiness(repository_root=repository_root)
    if not report["managed_runtime"]["ready"]:
        failures = [
            f"{check['component']}@{check['target']}:{check['reason']}"
            for check in report["managed_runtime"]["checks"]
            if not check["ready"]
        ]
        detail = ", ".join(failures) or "unknown"
        raise RuntimeError(f"v1 managed runtime publication is incomplete: {detail}")
    return report
