from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path

from .managed_components import ComponentArtifact, ComponentIntegrityError, ComponentUnavailable

_CATALOG_FILENAME = "managed-component-catalog.json"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validated_identifier(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_IDENTIFIER.fullmatch(text) or text in {".", ".."}:
        raise ComponentIntegrityError(f"Managed component {label} is unsafe.")
    return text


def _required_metadata(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ComponentUnavailable(f"Managed component {label} is required for published artifacts.")
    return text


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        arch = machine or "unknown"
    if system == "darwin":
        system = "macos"
    elif system == "windows":
        system = "windows"
    else:
        system = "linux"
    return f"{system}-{arch}"


def catalog_path() -> Path:
    override = os.getenv("AST_COMPONENT_CATALOG")
    if override and os.getenv("AST_PACKAGED", "").strip() != "1":
        return Path(override).expanduser()
    return Path(__file__).with_name(_CATALOG_FILENAME)


def load_catalog() -> dict:
    path = catalog_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": 1, "components": {}}
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentUnavailable("Managed component catalog cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ComponentUnavailable("Managed component catalog schema is unsupported.")
    components = payload.get("components")
    if not isinstance(components, dict):
        raise ComponentUnavailable("Managed component catalog is invalid.")
    for component in components:
        _validated_identifier(component, label="name")
    return payload


def catalog_entry(component: str) -> dict | None:
    component = _validated_identifier(component, label="name")
    entry = load_catalog()["components"].get(component)
    return entry if isinstance(entry, dict) else None


def artifact_for(component: str, *, target: str | None = None) -> ComponentArtifact:
    component = _validated_identifier(component, label="name")
    entry = catalog_entry(component)
    if entry is None:
        raise ComponentUnavailable(f"No managed component catalog entry: {component}")
    artifacts = entry.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ComponentUnavailable(f"No managed artifacts are published for {component}.")
    target = target or platform_key()
    payload = artifacts.get(target)
    if not isinstance(payload, dict):
        raise ComponentUnavailable(f"No managed artifact is published for {component} on {target}.")
    merged = dict(payload)
    merged.setdefault("component", component)
    merged.setdefault("version", entry.get("version"))
    merged["component"] = _validated_identifier(merged.get("component"), label="name")
    merged["version"] = _validated_identifier(merged.get("version"), label="version")
    merged.setdefault("license", entry.get("license"))
    merged.setdefault("provenance", entry.get("provenance"))
    merged["license"] = _required_metadata(merged.get("license"), label="license")
    merged["provenance"] = _required_metadata(merged.get("provenance"), label="provenance")
    return ComponentArtifact.from_dict(merged)


def catalog_summary(component: str) -> dict:
    """Expose the *same* publication eligibility used by the release checker.

    A JSON object under artifacts[platform] is not sufficient evidence of a
    downloadable, redistribution-approved runtime. Setup Center must never
    show an install action that its stricter release contract would reject.
    This is metadata approval only: actual binary/runtime validation remains
    a separate clean-machine release acceptance.
    """
    try:
        component = _validated_identifier(component, label="name")
        entry = catalog_entry(component)
    except ComponentIntegrityError:
        return {
            "component": str(component),
            "published": False,
            "target": platform_key(),
            "integrity": "invalid-name",
            "publication_reason": "invalid-name",
        }
    target = platform_key()
    if entry is None:
        return {
            "component": component,
            "published": False,
            "target": target,
            "publication_reason": "component-not-in-catalog",
        }

    # Defer this import to avoid a catalog <-> readiness initialization cycle.
    # The checker validates the complete artifact schema, license/provenance,
    # upstream pin, redistribution approval and required tool names.
    from .managed_publication_readiness import check_publication

    check = check_publication(component, target)
    try:
        _validated_identifier(entry.get("version"), label="version")
        version_integrity = "valid"
    except ComponentIntegrityError:
        version_integrity = "invalid-version"

    return {
        "component": component,
        "published": check.ready,
        "target": target,
        "version": entry.get("version"),
        "license": entry.get("license"),
        "provenance": entry.get("provenance"),
        "integrity": version_integrity,
        "publication_reason": check.reason,
    }
