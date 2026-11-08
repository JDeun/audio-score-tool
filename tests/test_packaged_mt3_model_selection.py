"""Packaged engine UI/API must select only the published managed checkpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from audio_score_tool import engine_api
from audio_score_tool.api import app
from audio_score_tool.settings_store import SettingsStore


def test_packaged_engine_api_rejects_unsupplied_yourmt3(monkeypatch, tmp_path):
    from audio_score_tool import runtime_settings as runtime_module

    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(engine_api, "_store", store)
    monkeypatch.setenv("AST_PACKAGED", "1")
    monkeypatch.setenv("AST_COMPONENT_DIR", str(tmp_path / "components"))
    monkeypatch.setattr(engine_api, "published_managed_mt3_model", lambda: "mr_mt3")
    monkeypatch.setattr(runtime_module, "published_managed_mt3_model", lambda: "mr_mt3")
    client = TestClient(app)

    listed = client.get("/api/engines")
    assert listed.status_code == 200
    assert listed.json()["managed_mt3_model"] == "mr_mt3"
    assert listed.json()["selected"] == "mt3_infer"
    assert listed.json()["mt3_model"] == "mr_mt3"

    wrong = client.put("/api/engines", json={
        "usage_mode": "commercial",
        "transcription_engine": "mt3_infer",
        "mt3_model": "yourmt3",
    })
    assert wrong.status_code == 422
    assert "mr_mt3" in wrong.json()["detail"]
    assert store.read().get("mt3_model") is None

    accepted = client.put("/api/engines", json={
        "usage_mode": "commercial",
        "transcription_engine": "mt3_infer",
        "mt3_model": "mr_mt3",
    })
    assert accepted.status_code == 200
    assert accepted.json()["mt3_model"] == "mr_mt3"
    assert store.read()["mt3_model"] == "mr_mt3"
