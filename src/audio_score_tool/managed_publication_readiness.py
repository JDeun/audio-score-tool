from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .managed_component_catalog import load_catalog
from .managed_components import ComponentArtifact, ComponentError

CORE_COMPONENTS = ("transcription_engine", "youtube_runtime")
OPTIONAL_COMPONENTS = ("audiveris", "whisperx", "audio_validation")
STABLE_TARGETS = ("windows-x86_64", "macos-aarch64")


@dataclass(frozen=True, slots=True)
class PublicationCheck:
    component: str
    target: str
    ready: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "target": self.target,
            "ready": self.ready,
            "reason": self.reason,
        }


def _artifact_payload(component: str, target: str) -> dict[str, Any] | None:
    catalog = load_catalog()
    entry = catalog.get("components", {}).get(component)
    if not isinstance(entry, dict):
        return None
    artifacts = entry.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    payload = artifacts.get(target)
    if not isinstance(payload, dict):
        return None
    merged = dict(payload)
    merged.setdefault("component", component)
    merged.setdefault("version", entry.get("version"))
    merged.setdefault("license", entry.get("license"))
    merged.setdefault("provenance", entry.get("provenance"))
    return merged


def check_publication(component: str, target: str) -> PublicationCheck:
    payload = _artifact_payload(component, target)
    if payload is None:
        return PublicationCheck(component, target, False, "artifact-not-published")
    try:
        artifact = ComponentArtifact.from_dict(payload)
    except ComponentError as exc:
        return PublicationCheck(component, target, False, str(exc))
    if not (artifact.license or "").strip():
        return PublicationCheck(component, target, False, "license-missing")
    if not (artifact.provenance or "").strip():
        return PublicationCheck(component, target, False, "provenance-missing")
    return PublicationCheck(component, target, True)


def publication_readiness(
    *,
    components: tuple[str, ...] = CORE_COMPONENTS,
    targets: tuple[str, ...] = STABLE_TARGETS,
) -> dict[str, Any]:
    checks = [check_publication(component, target) for component in components for target in targets]
    return {
        "schema_version": "1",
        "components": list(components),
        "targets": list(targets),
        "ready": bool(checks) and all(check.ready for check in checks),
        "checks": [check.as_dict() for check in checks],
    }
