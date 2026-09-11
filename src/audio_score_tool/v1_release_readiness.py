from __future__ import annotations

from pathlib import Path
from typing import Any

from .managed_publication_readiness import CORE_COMPONENTS, STABLE_TARGETS, publication_readiness
from .release_quality_approval import load_quality_approval


def v1_release_readiness(*, repository_root: Path) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    quality = load_quality_approval(
        repository_root / "release" / "v1-quality-approval.json",
        repository_root=repository_root,
    )
    managed = publication_readiness(components=CORE_COMPONENTS, targets=STABLE_TARGETS)
    return {
        "ready": bool(managed["ready"]),
        "quality": quality,
        "managed_runtime": managed,
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
