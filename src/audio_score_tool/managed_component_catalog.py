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
    return ComponentArtifact.from_dict(merged)


def catalog_summary(component: str) -> dict:
    try:
        component = _validated_identifier(component, label="name")
        entry = catalog_entry(component)
    except ComponentIntegrityError:
        return {"component": str(component), "published": False, "target": platform_key(), "integrity": "invalid-name"}
    target = platform_key()
    if entry is None:
        return {"component": component, "published": False, "target": target}
    artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), dict) else {}
    version = entry.get("version")
    version_safe = False
    try:
        _validated_identifier(version, label="version")
        version_safe = True
    except ComponentIntegrityError:
        pass
    return {
        "component": component,
        "published": version_safe and isinstance(artifacts.get(target), dict),
        "target": target,
        "version": version,
        "license": entry.get("license"),
        "provenance": entry.get("provenance"),
        "integrity": "valid" if version_safe else "invalid-version",
    }
