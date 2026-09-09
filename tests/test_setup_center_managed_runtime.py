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
