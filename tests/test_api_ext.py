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
    body = settings.json()
    assert body["enabled"] is False
    assert body["llm_required"] is False
    assert body["llm_transport"] == "openai_compatible_api"
    assert body["remote_api_supported"] is True
    assert "visual_enabled" in body
    assert "audio_enabled" in body
    assert "audio_threshold" in body
    assert "ffmpeg_cmd" in body
    assert "fluidsynth_cmd" in body

    missing = client.post(
        "/api/songs/not-a-real-song/validate",
        json={"use_llm": False, "use_visual": False, "use_audio": False},
    )
    assert missing.status_code == 404


def test_setup_center_route_separates_core_and_optional_features():
    client = TestClient(app)
    response = client.get("/api/setup/center")
    assert response.status_code == 200
    body = response.json()
    assert body["platform"] in {"macos", "windows", "linux"}
    assert body["policy"]["llm_required"] is False
    assert body["policy"]["musescore_required"] is False
    assert body["policy"]["developer_toolchain_required"] is False
    assert body["policy"]["optional_features_do_not_block_core"] is True
    components = {item["key"]: item for item in body["components"]}
    assert "uv_runtime" in components
    assert components["transcription_engine"]["tier"] == "core"
    assert components["llm"]["tier"] == "optional"
    assert components["audiveris"]["tier"] == "optional"
    assert components["ffmpeg"]["tier"] == "optional"


def test_setup_center_rejects_untrusted_install_recipe():
    client = TestClient(app)
    response = client.post("/api/setup/install", json={"component": "arbitrary-shell-command"})
    assert response.status_code == 422


def test_model_manager_route_exposes_explicit_download_policy():
    client = TestClient(app)
    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert body["policy"]["automatic_download"] is False
    assert body["policy"]["explicit_user_action_required"] is True
    assert body["policy"]["auth_token_stored_by_app"] is False
    assert body["selected_muscriptor_model"] in {"small", "medium", "large"}
    models = {item["variant"]: item for item in body["models"]}
    assert {"small", "medium", "large"} == set(models)
    assert models["large"]["license"] == "CC BY-NC 4.0"
    assert models["large"]["commercial_allowed"] is False
    assert models["large"]["weight_bytes"] > models["medium"]["weight_bytes"]


def test_model_manager_rejects_unknown_model():
    client = TestClient(app)
    response = client.post(
        "/api/models/download",
        json={"family": "muscriptor", "variant": "ultra"},
    )
    assert response.status_code == 404


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
