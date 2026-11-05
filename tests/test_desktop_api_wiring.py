"""Guard literal desktop API calls against silent route drift in FastAPI.

This is deliberately a *route-existence* check, not a replacement for endpoint
integration tests or Tauri packaged-runtime acceptance.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from audio_score_tool.api import app

ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "desktop" / "src"
FETCH_TEMPLATE = re.compile(r"fetch\(\s*`\$\{API\}(/api/[^\`]+)\`")
DYNAMIC_SEGMENT = re.compile(r"\$\{[^}]+\}")
SERVER_SEGMENT = re.compile(r"\{[^}]+\}")


def _normalize_client_path(template: str) -> str:
    """Normalize JS interpolations to FastAPI-style path components."""
    path = template.split("?", 1)[0]
    return DYNAMIC_SEGMENT.sub("{param}", path)


def _normalize_server_path(route: str) -> str:
    """Normalize FastAPI path parameter names for structural comparison."""
    return SERVER_SEGMENT.sub("{param}", route)


def test_all_literal_react_api_fetch_urls_resolve_to_fastapi_routes():
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    actual = {_normalize_server_path(route) for route in response.json()["paths"]}
    checked = 0
    missing = []
    for path in sorted(UI_SOURCE.glob("*.tsx")):
        source = path.read_text(encoding="utf-8")
        for match in FETCH_TEMPLATE.finditer(source):
            checked += 1
            template = match.group(1)
            if "${action}" in template:
                # This UI action is a finite TypeScript union, not an arbitrary
                # FastAPI path parameter. Check every possible URL explicitly.
                if path.name != "SongWorkspace.tsx" or (
                    'action: "undo" | "restore" | "export"' not in source
                ):
                    missing.append(f"{path.name}: unbounded dynamic action: {template}")
                    continue
                endpoints = [
                    _normalize_client_path(template.replace("${action}", action))
                    for action in ("undo", "restore", "export")
                ]
                for endpoint in endpoints:
                    if endpoint not in actual:
                        missing.append(f"{path.name}: {endpoint}")
                continue
            if _normalize_client_path(template) not in actual:
                missing.append(f"{path.name}: {template}")
    assert checked >= 30, "No longer inspecting the desktop's API fetch calls"
    assert not missing, (
        "Desktop URLs without registered FastAPI routes:\n"
        + "\n".join(missing)
        + "\nRegistered routes: "
        + ", ".join(sorted(actual))
    )
