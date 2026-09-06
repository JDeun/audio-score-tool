from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app


def test_song_workspace_routes_are_reachable():
    client = TestClient(app)

    response = client.get("/api/songs")
    assert response.status_code == 200
    assert "songs" in response.json()

    missing = client.get("/api/songs/not-a-real-song")
    assert missing.status_code == 404
