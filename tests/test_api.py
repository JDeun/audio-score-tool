from fastapi.testclient import TestClient

from audio_score_tool.api import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "device_plan" in body
    assert "preflight" in body


def test_unknown_job_is_404():
    client = TestClient(app)
    response = client.get("/api/jobs/not-a-real-job")
    assert response.status_code == 404



def test_presets_endpoint():
    client = TestClient(app)
    response = client.get("/api/presets")
    assert response.status_code == 200
    body = response.json()
    assert body["recommended"] in {"fast", "balanced", "quality"}
    assert {item["key"] for item in body["presets"]} == {"fast", "balanced", "quality"}


def test_rejects_unsupported_audio_upload():
    client = TestClient(app)
    response = client.post(
        "/api/jobs",
        files={"file": ("not-audio.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415
