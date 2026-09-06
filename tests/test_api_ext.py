from fastapi.testclient import TestClient

from audio_score_tool.api_ext import app


def test_song_workspace_routes_are_reachable():
    client = TestClient(app)

    response = client.get("/api/songs")
    assert response.status_code == 200
    assert "songs" in response.json()

    missing = client.get("/api/songs/not-a-real-song")
    assert missing.status_code == 404


def test_advanced_score_editor_routes_are_mounted():
    client = TestClient(app)

    structure = client.get("/api/songs/not-a-real-song/structure")
    assert structure.status_code == 404

    insert = client.post(
        "/api/songs/not-a-real-song/notes/p0-m0-n0/insert",
        json={"position": "after", "type": "quarter"},
    )
    assert insert.status_code == 404

    signature = client.patch(
        "/api/songs/not-a-real-song/measures/0/signature",
        json={"beats": 3, "beat_type": 4},
    )
    assert signature.status_code == 404


def test_transcription_engine_route_is_mounted():
    client = TestClient(app)
    response = client.get("/api/engines")
    assert response.status_code == 200
    body = response.json()
    assert body["selected"] in {"muscriptor", "native"}
    assert {item["key"] for item in body["engines"]} == {"muscriptor", "native"}
