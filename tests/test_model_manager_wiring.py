"""Ensure the desktop's Hugging Face session actions match the registered API."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from audio_score_tool import model_manager_api as models
from audio_score_tool.api import app


def test_desktop_hugging_face_auth_uses_server_session_route():
    source = (
        Path(__file__).resolve().parents[1] / "desktop/src/ModelManager.tsx"
    ).read_text(encoding="utf-8")
    assert source.count("/api/models/hf-auth/session") == 2
    assert "/api/models/hf-auth/token" not in source


def test_session_auth_and_revocation_are_wired_without_external_requests(monkeypatch):
    seen = []

    class FakeHfApi:
        def __init__(self, token: str):
            seen.append(("client", token))

        def whoami(self):
            return {"name": "ci-test-user"}

    def fake_set(token, name):
        seen.append(("set", token, name))

    def fake_clear():
        seen.append(("clear",))

    monkeypatch.setattr(models, "HfApi", FakeHfApi)
    monkeypatch.setattr(models, "set_session", fake_set)
    monkeypatch.setattr(models, "clear_session", fake_clear)
    monkeypatch.setattr(models, "model_manager_status", lambda: {"models": []})
    client = TestClient(app)
    response = client.post(
        "/api/models/hf-auth/session", json={"token": "hf_ci_test_not_real"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "identity": "ci-test-user",
        "status": {"models": []},
    }
    response = client.delete("/api/models/hf-auth/session")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "status": {"models": []}}
    assert seen == [
        ("client", "hf_ci_test_not_real"),
        ("set", "hf_ci_test_not_real", "ci-test-user"),
        ("clear",),
    ]
