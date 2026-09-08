from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from audio_score_tool.api_token import ApiTokenMiddleware


def _client() -> TestClient:
    async def api_read(_request):
        return JSONResponse({"ok": True})

    async def public_read(_request):
        return JSONResponse({"public": True})

    app = Starlette(
        routes=[
            Route("/api/private", api_read, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/public", public_read, methods=["GET"]),
        ]
    )
    return TestClient(ApiTokenMiddleware(app))


def test_api_token_disabled_in_development(monkeypatch):
    monkeypatch.delenv("AST_API_TOKEN", raising=False)
    response = _client().get("/api/private")
    assert response.status_code == 200


def test_api_token_protects_reads_when_configured(monkeypatch):
    monkeypatch.setenv("AST_API_TOKEN", "secret-token")
    client = _client()

    missing = client.get("/api/private")
    assert missing.status_code == 401

    invalid = client.get("/api/private", headers={"X-AudioScore-Token": "wrong"})
    assert invalid.status_code == 401

    valid = client.get("/api/private", headers={"X-AudioScore-Token": "secret-token"})
    assert valid.status_code == 200


def test_api_token_keeps_preflight_and_non_api_paths_available(monkeypatch):
    monkeypatch.setenv("AST_API_TOKEN", "secret-token")
    client = _client()

    preflight = client.options("/api/private")
    assert preflight.status_code < 400

    public = client.get("/public")
    assert public.status_code == 200
