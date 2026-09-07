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


def test_desktop_export_destination_route_is_mounted():
    client = TestClient(app)
    response = client.post(
        "/api/songs/not-a-real-song/export-to",
        json={"formats": ["musicxml"], "destination_dir": "/tmp"},
    )
    assert response.status_code == 404


def test_transcription_engine_routes_are_mounted():
    client = TestClient(app)
    response = client.get("/api/engines")
    assert response.status_code == 200
    body = response.json()
    assert body["usage_mode"] in {"personal", "commercial"}
    assert body["selected"] in {"mt3_infer", "muscriptor", "native"}
    keys = {item["key"] for item in body["engines"]}
    assert {"mt3_infer", "muscriptor", "native"} <= keys
    assert "recommendation" in body


def test_validation_routes_are_mounted():
    client = TestClient(app)
    settings = client.get("/api/validation/settings")
    assert settings.status_code == 200
    assert "enabled" in settings.json()

    missing = client.post("/api/songs/not-a-real-song/validate", json={"use_llm": False})
    assert missing.status_code == 404


def test_omr_and_notation_routes_are_mounted():
    client = TestClient(app)

    omr = client.get("/api/omr/status")
    assert omr.status_code == 200
    assert omr.json()["provider"] == "audiveris"

    notation = client.get("/api/notation")
    assert notation.status_code == 200
    body = notation.json()
    assert body["policy"]["musescore_required"] is False
    assert "music21" in body["backends"]

    missing = client.post("/api/songs/not-a-real-song/export", json={"formats": ["musicxml"]})
    assert missing.status_code == 404
