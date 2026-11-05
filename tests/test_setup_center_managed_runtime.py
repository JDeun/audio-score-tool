from __future__ import annotations

from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app


def test_setup_center_exposes_managed_integrity_contract():
    client = TestClient(app)
    response = client.get("/api/setup/center")
    assert response.status_code == 200
    body = response.json()
    assert body["policy"]["managed_component_integrity"] == "sha256+atomic-state+root-containment"
    assert body["policy"]["managed_component_system_path_fallback"] is False
    components = {item["key"]: item for item in body["components"]}
    for key in ("transcription_engine", "whisperx", "youtube_runtime", "audiveris", "audio_validation"):
        item = components[key]
        assert isinstance(item["managed_status"], dict)
        assert isinstance(item["catalog"], dict)
        assert item["catalog"]["target"]
        assert item["auto_install"] is item["catalog"]["published"]


def test_setup_recover_endpoint_is_idempotent():
    client = TestClient(app)
    first = client.post("/api/setup/recover")
    second = client.post("/api/setup/recover")
    assert first.status_code == 200
    assert second.status_code == 200
    assert "removed_component_staging" in first.json()["recovery"]
    assert second.json()["recovery"]["removed_component_staging"] == 0


def test_setup_install_calls_catalog_and_verifier_not_user_supplied_url(monkeypatch):
    from audio_score_tool import setup_center_api as setup

    calls: list[tuple[str, object]] = []
    artifact = object()

    def lookup(component: str):
        calls.append(("catalog", component))
        return artifact

    def install(item):
        calls.append(("install", item))
        return {"ready": True, "integrity": "verified"}

    monkeypatch.setattr(setup, "artifact_for", lookup)
    monkeypatch.setattr(setup, "install_component_artifact", install)
    monkeypatch.setattr(setup, "setup_center_status", lambda: {"core_ready": False})
    client = TestClient(app)
    response = client.post(
        "/api/setup/install",
        json={"component": "transcription_engine"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "installed": {"ready": True, "integrity": "verified"},
        "setup": {"core_ready": False},
    }
    assert calls == [("catalog", "transcription_engine"), ("install", artifact)]


def test_setup_install_rejects_unmanaged_component():
    client = TestClient(app)
    response = client.post("/api/setup/install", json={"component": "desktop_runtime"})
    assert response.status_code == 409


def test_desktop_setup_center_wires_install_recovery_and_published_gate():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "desktop/src/SetupCenter.tsx"
    ).read_text(encoding="utf-8")
    assert "${API}/api/setup/install" in source
    assert "${API}/api/setup/recover" in source
    assert "component.auto_install && component.catalog?.published" in source
