"""Guard desktop API method/path contracts against silent FastAPI drift.

The front end uses literal `fetch(` API templates. Ensure the actual method,
including any finite dynamic action, exists in the canonical OpenAPI schema.
Payload/response integration contracts are tested separately with TestClient.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api import app

ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "desktop" / "src"
FETCH_TEMPLATE = re.compile(r"fetch\(\s*`\$\{API\}(/api/[^\`]+)\`")
DYNAMIC_SEGMENT = re.compile(r"\$\{[^}]+\}")
SERVER_SEGMENT = re.compile(r"\{[^}]+\}")
EXPLICIT_METHOD = re.compile(r'^,\s*\{\s*method:\s*["\x27]([A-Z]+)["\x27]')


def _normalize_client_path(template: str) -> str:
    """Normalize JS interpolations to FastAPI-style path components."""
    path = template.split("?", 1)[0]
    return DYNAMIC_SEGMENT.sub("{param}", path)


def _normalize_server_path(route: str) -> str:
    """Normalize FastAPI path parameter names for structural comparison."""
    return SERVER_SEGMENT.sub("{param}", route)


def _client_method(after_template: str) -> str:
    """Parse the first fetch option, refusing ambiguous dynamic request methods."""
    tail = after_template.lstrip()
    if tail.startswith(")"):
        return "GET"
    match = EXPLICIT_METHOD.match(tail)
    if match and match.group(1) in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        return match.group(1)
    raise ValueError("Unbounded or unrecognized fetch method; add a typed contract test")


def _expand_client_path(path: Path, source: str, template: str) -> list[str]:
    if "${action}" not in template:
        return [_normalize_client_path(template)]
    # This is a finite TS union; each dynamic endpoint needs its own server route.
    if path.name != "SongWorkspace.tsx" or (
        'action: "undo" | "restore" | "export"' not in source
    ):
        raise ValueError(f"{path.name}: unbounded dynamic action: {template}")
    return [
        _normalize_client_path(template.replace("${action}", action))
        for action in ("undo", "restore", "export")
    ]


def _missing_contracts(
    source_file: Path, source: str, server_methods: set[tuple[str, str]]
) -> tuple[int, list[str]]:
    checked = 0
    missing: list[str] = []
    for match in FETCH_TEMPLATE.finditer(source):
        checked += 1
        template = match.group(1)
        try:
            method = _client_method(source[match.end():])
            for endpoint in _expand_client_path(source_file, source, template):
                if (endpoint, method) not in server_methods:
                    missing.append(f"{source_file.name}: {method} {endpoint}")
        except ValueError as exc:
            missing.append(f"{source_file.name}: {exc}")
    return checked, missing


def test_all_literal_react_api_fetch_urls_resolve_to_fastapi_routes():
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    methods = {
        (_normalize_server_path(path), method.upper())
        for path, route in response.json()["paths"].items()
        for method in route
        if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    checked = 0
    missing: list[str] = []
    for path in sorted(UI_SOURCE.glob("*.tsx")):
        inspected, invalid = _missing_contracts(
            path, path.read_text(encoding="utf-8"), methods
        )
        checked += inspected
        missing.extend(invalid)

    assert checked >= 30, "No longer inspecting the desktop's API fetch calls"
    assert not missing, (
        "Desktop method/path contracts missing in FastAPI:\n"
        + "\n".join(missing)
        + "\nRegistered: "
        + ", ".join(f"{m} {p}" for p, m in sorted(methods))
    )


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (");", "GET"),
        (', { method: "POST", body: value });', "POST"),
        (' , {\nmethod: "PATCH", headers: {} });', "PATCH"),
        (', { method: "DELETE" });', "DELETE"),
    ],
)
def test_method_parser_handles_actual_frontend_forms(options: str, expected: str):
    assert _client_method(options) == expected


def test_method_contract_guard_rejects_route_existing_with_wrong_verb():
    count, missing = _missing_contracts(
        Path("Fixture.tsx"),
        'fetch(`${API}/api/songs/some-song`, { method: "POST" });',
        {("/api/songs/some-song", "GET")},
    )
    assert count == 1
    assert missing == ["Fixture.tsx: POST /api/songs/some-song"]


def test_unbounded_dynamic_method_fails_closed():
    with pytest.raises(ValueError, match="Unbounded"):
        _client_method(', { method: dynamicMethod }')
