"""Prevent UI↔FastAPI payload drift at the published OpenAPI boundary."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from audio_score_tool.api import app


def _openapi() -> dict:
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _body_contract(spec: dict, path: str, method: str, media_type: str = "application/json"):
    operation = spec["paths"][path][method.lower()]
    schema = operation["requestBody"]["content"][media_type]["schema"]
    if "$ref" in schema:
        return spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


@pytest.mark.parametrize(
    ("path", "method", "media_type", "fields"),
    [
        (
            "/api/jobs/youtube", "POST", "application/json",
            {"url", "authorized", "language", "skip_lyrics", "preset",
             "muscriptor_model", "whisperx_model"},
        ),
        (
            "/api/jobs", "POST", "multipart/form-data",
            {"file", "preset", "skip_lyrics", "muscriptor_model", "whisperx_model"},
        ),
        (
            "/api/songs/{song_id}/credits", "PATCH", "application/json",
            {"title", "artist", "expected_revision", "composer", "lyricist",
             "arranger", "rights", "subtitle"},
        ),
        (
            "/api/songs/{song_id}/export-to", "POST", "application/json",
            {"destination_dir", "formats"},
        ),
        (
            "/api/engines", "PUT", "application/json",
            {"usage_mode", "transcription_engine", "mt3_model", "muscriptor_model"},
        ),
        (
            "/api/setup/install", "POST", "application/json",
            {"component"},
        ),
    ],
)
def test_critical_request_contract_fields_stay_in_openapi(
    path: str, method: str, media_type: str, fields: set[str]
):
    spec = _openapi()
    schema = _body_contract(spec, path, method, media_type)
    assert fields <= set(schema["properties"]), (
        f"{method} {path} no longer accepts desktop fields: "
        f"{fields - set(schema['properties'])}"
    )


@pytest.mark.parametrize(
    ("path", "method", "required"),
    [
        ("/api/jobs/youtube", "POST", {"url"}),
        ("/api/jobs", "POST", {"file"}),
        ("/api/songs/{song_id}/credits", "PATCH", {"title", "expected_revision"}),
        ("/api/songs/{song_id}/export-to", "POST", {"destination_dir"}),
        ("/api/engines", "PUT", {"transcription_engine"}),
    ],
)
def test_required_client_inputs_cannot_disappear_silently(
    path: str, method: str, required: set[str]
):
    schema = _body_contract(
        _openapi(), path, method,
        "multipart/form-data" if path == "/api/jobs" else "application/json",
    )
    assert required <= set(schema.get("required", []))


def test_backend_status_responses_keep_desktop_rendering_fields():
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    data = health.json()
    assert isinstance(data["packaged_runtime"], bool)
    assert isinstance(data["preflight"]["ok"], bool)
    assert isinstance(data["preflight"]["tools"], dict)
    assert "recommended" in data["presets"]
    assert "jobs_bytes" in data["system"]

    engines = client.get("/api/engines")
    assert engines.status_code == 200
    payload = engines.json()
    assert isinstance(payload["packaged_runtime"], bool)
    assert "usage_mode" in payload and "selected" in payload
    assert isinstance(payload["engines"], list)

    status = client.get("/api/setup/center")
    assert status.status_code == 200
    setup = status.json()
    assert isinstance(setup["components"], list)
    assert isinstance(setup["core_ready"], bool)
    assert setup["policy"]["managed_component_system_path_fallback"] is False

    jobs = client.get("/api/jobs?limit=1")
    assert jobs.status_code == 200
    assert isinstance(jobs.json()["jobs"], list)
