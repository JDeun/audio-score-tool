from __future__ import annotations

from fastapi.testclient import TestClient

from audio_score_tool import engine_api, runtime_services
from audio_score_tool.api import app
from audio_score_tool.settings_store import SettingsStore


def test_packaged_api_reports_managed_mode_and_rejects_ignored_command_overrides(
    tmp_path, monkeypatch,
):
    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(runtime_services, "_settings_store", store)
    monkeypatch.setattr(engine_api, "_store", store)
    monkeypatch.setenv("AST_PACKAGED", "1")

    client = TestClient(app)
    health = client.get("/api/health")
    setup = client.get("/api/setup")
    engines = client.get("/api/engines")
    assert health.status_code == setup.status_code == engines.status_code == 200
    assert health.json()["packaged_runtime"] is True
    assert setup.json()["packaged_runtime"] is True
    assert engines.json()["packaged_runtime"] is True

    rejected = client.put(
        "/api/settings/tool-paths",
        json={"muscriptor_cmd": "/tmp/overridden-muscriptor"},
    )
    assert rejected.status_code == 409
    assert "구성요소" in rejected.json()["detail"]
    assert store.read().get("muscriptor_cmd") is None


def test_source_development_keeps_explicit_tool_path_override(
    tmp_path, monkeypatch,
):
    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(runtime_services, "_settings_store", store)
    monkeypatch.setattr(engine_api, "_store", store)
    monkeypatch.delenv("AST_PACKAGED", raising=False)

    client = TestClient(app)
    assert client.get("/api/health").json()["packaged_runtime"] is False
    assert client.get("/api/engines").json()["packaged_runtime"] is False
    response = client.put(
        "/api/settings/tool-paths",
        json={"muscriptor_cmd": "/custom/developer-muscriptor"},
    )
    assert response.status_code == 200, response.text
    assert store.read()["muscriptor_cmd"] == "/custom/developer-muscriptor"
