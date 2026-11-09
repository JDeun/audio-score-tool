"""The alternate engine settings API must not bypass Model Manager readiness.

The tests do not download weights, execute models or approve commercial use.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from audio_score_tool import engine_api
from audio_score_tool.api import app
from audio_score_tool.config import Settings
from audio_score_tool.settings_store import SettingsStore


def _isolate_settings(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "engine-settings.json")
    store.update({
        "usage_mode": "personal", "transcription_engine": "mt3_infer",
        "mt3_model": "mr_mt3",
    })
    monkeypatch.setattr(engine_api, "_store", store)
    monkeypatch.setattr(engine_api, "packaged_runtime", lambda: False)
    monkeypatch.setattr(engine_api, "published_managed_mt3_model", lambda: None)
    return store


def test_personal_recommendation_is_a_candidate_not_a_release_approval(monkeypatch):
    monkeypatch.setattr(engine_api, "published_managed_mt3_model", lambda: None)
    monkeypatch.setattr(engine_api.MuScriptorEngine, "ready", lambda _self: False)
    policy = engine_api._recommendation(Settings(
        usage_mode="personal", muscriptor_model="small",
    ))
    assert policy["engine"] == "muscriptor"
    assert policy["model"] == "small"
    assert policy["currently_runnable"] is False
    assert policy["release_approved_default"] is False
    assert "준비되지 않았" in policy["reason"]


def test_unready_muscriptor_cannot_be_selected_via_engine_settings(
    tmp_path, monkeypatch,
):
    store = _isolate_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(engine_api.MuScriptorEngine, "ready", lambda _self: False)
    response = TestClient(app).put("/api/engines", json={
        "usage_mode": "personal", "transcription_engine": "muscriptor",
        "muscriptor_model": "large",
    })
    assert response.status_code == 409
    assert "모델 관리자" in response.json()["detail"]
    assert store.read()["transcription_engine"] == "mt3_infer"


def test_ready_muscriptor_variant_selection_preserves_other_settings(
    tmp_path, monkeypatch,
):
    store = _isolate_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(engine_api.MuScriptorEngine, "ready", lambda _self: True)
    response = TestClient(app).put("/api/engines", json={
        "usage_mode": "personal", "transcription_engine": "muscriptor",
        "muscriptor_model": "medium",
    })
    assert response.status_code == 200, response.text
    assert response.json()["selected"] == "muscriptor"
    assert response.json()["recommendation"]["release_approved_default"] is False
    assert store.read()["muscriptor_model"] == "medium"
    assert store.read()["mt3_model"] == "mr_mt3"


def test_packaged_app_rejects_unapproved_native_and_custom_commands(
    tmp_path, monkeypatch,
):
    store = _isolate_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(engine_api, "packaged_runtime", lambda: True)
    client = TestClient(app)
    response = client.put("/api/engines", json={
        "usage_mode": "personal", "transcription_engine": "native",
        "native_checkpoint": "/tmp/model.ckpt",
    })
    assert response.status_code == 409
    assert "배포 앱" in response.json()["detail"]

    response = client.put("/api/engines", json={
        "usage_mode": "commercial", "transcription_engine": "mt3_infer",
        "mt3_model": "mr_mt3", "mt3_infer_cmd": "/usr/bin/python",
    })
    assert response.status_code == 409
    assert "사용자 지정 실행 명령" in response.json()["detail"]
    assert store.read()["transcription_engine"] == "mt3_infer"
    assert store.read()["usage_mode"] == "personal"


def test_commercial_muscriptor_is_rejected_before_readiness_check(
    tmp_path, monkeypatch,
):
    store = _isolate_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        engine_api.MuScriptorEngine, "ready",
        lambda _self: (_ for _ in ()).throw(AssertionError("must not probe NC weights")),
    )
    response = TestClient(app).put("/api/engines", json={
        "usage_mode": "commercial", "transcription_engine": "muscriptor",
        "muscriptor_model": "small",
    })
    assert response.status_code == 422
    assert store.read()["usage_mode"] == "personal"
