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



def test_downloaded_weights_do_not_claim_runtime_is_ready(monkeypatch):
    """Caching a gated model does not mean its inference CLI can be executed."""
    from audio_score_tool.config import Settings

    monkeypatch.setattr(models, "_model_cached", lambda _repo_id: (True, 4096))
    settings = Settings(usage_mode="personal", muscriptor_cmd="missing-muscriptor")
    pending = models._model_payload("small", settings, runtime_ready=False)
    assert pending["weights_cached"] is True
    assert pending["cached_bytes"] == 4096
    assert pending["runtime_ready"] is False
    assert pending["ready"] is False
    runnable = models._model_payload("small", settings, runtime_ready=True)
    assert runnable["ready"] is True

    commercial = models._model_payload(
        "small", Settings(usage_mode="commercial"), runtime_ready=True,
    )
    assert commercial["allowed_for_usage_mode"] is False
    assert commercial["ready"] is False


def test_server_rejects_selection_with_missing_cache_or_muscriptor_command(
    monkeypatch, tmp_path,
):
    from audio_score_tool.config import Settings
    from audio_score_tool.settings_store import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr(models, "_store", store)
    monkeypatch.setattr(
        models, "runtime_settings",
        lambda: Settings(usage_mode="personal", muscriptor_cmd="missing-muscriptor"),
    )
    monkeypatch.setattr(models, "command_exists", lambda _: False)
    monkeypatch.setattr(models, "_model_cached", lambda _: (True, 1024))
    client = TestClient(app)
    response = client.post(
        "/api/models/select", json={"family": "muscriptor", "variant": "small"},
    )
    assert response.status_code == 409
    assert "실행 런타임" in response.json()["detail"]
    assert not store.read().get("transcription_engine")

    monkeypatch.setattr(models, "command_exists", lambda _: True)
    monkeypatch.setattr(models, "_model_cached", lambda _: (False, 0))
    response = client.post(
        "/api/models/select", json={"family": "muscriptor", "variant": "small"},
    )
    assert response.status_code == 409
    assert "가중치" in response.json()["detail"]
    assert not store.read().get("transcription_engine")


def test_server_selects_only_runnable_personal_model_and_preserves_unrelated_settings(
    monkeypatch, tmp_path,
):
    from audio_score_tool.config import Settings
    from audio_score_tool.settings_store import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    store.update({"mt3_model": "mr_mt3", "usage_mode": "personal"})
    monkeypatch.setattr(models, "_store", store)
    monkeypatch.setattr(
        models, "runtime_settings",
        lambda: Settings(usage_mode="personal", muscriptor_cmd="fake-muscriptor"),
    )
    monkeypatch.setattr(models, "command_exists", lambda _: True)
    monkeypatch.setattr(models, "_model_cached", lambda _: (True, 1024))
    monkeypatch.setattr(models, "model_manager_status", lambda: {"models": []})
    response = TestClient(app).post(
        "/api/models/select", json={"family": "muscriptor", "variant": "medium"},
    )
    assert response.status_code == 200
    assert response.json()["selected"] is True
    assert response.json()["variant"] == "medium"
    saved = store.read()
    assert saved["transcription_engine"] == "muscriptor"
    assert saved["muscriptor_model"] == "medium"
    assert saved["mt3_model"] == "mr_mt3"
    assert saved["usage_mode"] == "personal"


def test_server_denies_commercial_muscriptor_even_if_cached(monkeypatch, tmp_path):
    from audio_score_tool.config import Settings

    monkeypatch.setattr(
        models, "runtime_settings",
        lambda: Settings(usage_mode="commercial", muscriptor_cmd="fake-muscriptor"),
    )
    monkeypatch.setattr(models, "_model_cached", lambda _: (True, 1024))
    monkeypatch.setattr(models, "command_exists", lambda _: True)
    response = TestClient(app).post(
        "/api/models/select", json={"family": "muscriptor", "variant": "large"},
    )
    assert response.status_code == 422
    assert "비상업" in response.json()["detail"]


def test_desktop_manager_never_enables_unrunnable_cached_model():
    source = (
        Path(__file__).resolve().parents[1] / "desktop/src/ModelManager.tsx"
    ).read_text(encoding="utf-8")
    assert "/api/models/select" in source
    assert "model.weights_cached && !model.selected" in source
    assert "disabled={busy || !model.ready}" in source
    assert "가중치만 준비됨" in source
