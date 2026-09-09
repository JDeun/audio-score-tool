from __future__ import annotations

import json
import os
import platform
from pathlib import Path

from .managed_components import ComponentArtifact, ComponentUnavailable

_CATALOG_FILENAME = "managed-component-catalog.json"


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
    return payload


def catalog_entry(component: str) -> dict | None:
    entry = load_catalog()["components"].get(component)
    return entry if isinstance(entry, dict) else None


def artifact_for(component: str, *, target: str | None = None) -> ComponentArtifact:
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
    merged.setdefault("license", entry.get("license"))
    merged.setdefault("provenance", entry.get("provenance"))
    return ComponentArtifact.from_dict(merged)


def catalog_summary(component: str) -> dict:
    entry = catalog_entry(component)
    target = platform_key()
    if entry is None:
        return {"component": component, "published": False, "target": target}
    artifacts = entry.get("artifacts") if isinstance(entry.get("artifacts"), dict) else {}
    return {
        "component": component,
        "published": isinstance(artifacts.get(target), dict),
        "target": target,
        "version": entry.get("version"),
        "license": entry.get("license"),
        "provenance": entry.get("provenance"),
    }
