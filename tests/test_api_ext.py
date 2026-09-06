from audio_score_tool.api_ext import app


def test_song_workspace_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/songs" in paths
    assert "/api/songs/{song_id}/score" in paths
    assert "/api/songs/{song_id}/notes/{note_id}" in paths
    assert "/api/songs/{song_id}/export" in paths
