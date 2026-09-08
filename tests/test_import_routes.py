from audio_score_tool.api_ext import app


def _route_count(path: str, method: str) -> int:
    return sum(
        1
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    )


def test_score_import_routes_have_single_public_owner():
    assert _route_count("/api/import/score", "POST") == 1
    assert _route_count("/api/import/notation", "POST") == 1
