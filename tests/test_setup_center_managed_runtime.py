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
    for key in ("transcription_engine", "whisperx", "demucs", "youtube_runtime", "audiveris", "audio_validation"):
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
    monkeypatch.setattr(setup, "check_publication", lambda *_: type("Approved", (), {"ready": True})())
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


def test_setup_remove_calls_owned_component_manager(monkeypatch):
    from audio_score_tool import setup_center_api as setup

    calls: list[str] = []

    def remove(component: str):
        calls.append(component)
        return {"component": component, "removed": True, "cleanup_pending": False}

    monkeypatch.setattr(setup, "remove_component_artifact", remove)
    monkeypatch.setattr(setup, "setup_center_status", lambda: {"core_ready": True})
    client = TestClient(app)
    response = client.post("/api/setup/remove", json={"component": "audiveris"})
    assert response.status_code == 200
    assert response.json()["removed"]["removed"] is True
    assert calls == ["audiveris"]
    assert client.post("/api/setup/remove", json={"component": "desktop_runtime"}).status_code == 409


def test_unpublished_demucs_cannot_be_installed_from_setup_center():
    from audio_score_tool.managed_publication_readiness import check_publication
    from audio_score_tool.managed_component_catalog import platform_key

    status = TestClient(app).get("/api/setup/center")
    assert status.status_code == 200
    separator = next(item for item in status.json()["components"] if item["key"] == "demucs")
    assert separator["tier"] == "optional"
    assert separator["auto_install"] is False
    assert separator["catalog"]["published"] is False
    assert check_publication("demucs", platform_key()).reason == "artifact-not-published"
    assert TestClient(app).post("/api/setup/install", json={"component": "demucs"}).status_code == 409
