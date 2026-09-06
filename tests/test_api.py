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
