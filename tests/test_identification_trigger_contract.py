"""Check that the documented identification trigger is explicit and safe."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from audio_score_tool import enrichment_api
from audio_score_tool.api import app


class IdentificationFixtureStore:
    def __init__(self, root: Path):
        self.asset_root = root / "assets"
        self.saved: dict[str, dict] = {}
        self.song = {
            "song_id": "song-1",
            "title": "Owned source",
            "artist": None,
            "revision": 1,
        }

    def get(self, song_id: str) -> dict | None:
        return self.song if song_id == "song-1" else None

    def analysis(self, song_id: str, kind: str) -> dict | None:
        return self.saved.get(f"{song_id}:{kind}")

    def set_analysis(self, song_id: str, kind: str, data: dict) -> None:
        self.saved[f"{song_id}:{kind}"] = data


def test_explicit_identification_skips_song_without_audio_and_avoids_external_calls(
    tmp_path: Path, monkeypatch,
):
    store = IdentificationFixtureStore(tmp_path)
    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(
        enrichment_api,
        "identify_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No original audio means no identification and no external service")
        ),
    )
    response = TestClient(app).post("/api/songs/song-1/identify-source", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "no_audio"
    assert response.json()["applied"] is False
    assert store.song["revision"] == 1
    assert store.analysis("song-1", "source_identification")["status"] == "no_audio"


def test_identification_requires_explicit_post_and_respects_cache(
    tmp_path: Path, monkeypatch,
):
    store = IdentificationFixtureStore(tmp_path)
    audio = store.asset_root / "song-1" / "original-audio.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"owned audio fixture")
    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(
        enrichment_api, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="commercial"),
    )
    seen: list[str] = []

    def local_tag_result(path: Path, **_kwargs) -> dict:
        seen.append(str(path))
        return {
            "embedded_tags": {
                "title": "Owned source",
                "artist": "Artist from local tag",
                "isrc": None,
            },
            "selected": {
                "title": "Owned source",
                "artist": "Artist from local tag",
                "confidence": 1.0,
            },
            "acoustid": {"attempted": False, "candidates": [], "error": None},
            "policy": {"order": ["embedded_tags"]},
        }

    monkeypatch.setattr(enrichment_api, "identify_source", local_tag_result)
    monkeypatch.setattr(
        enrichment_api, "search_musicbrainz",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("High-confidence local tags must not trigger fuzzy search")
        ),
    )
    client = TestClient(app)

    # Exposing a POST route does not authorize a GET/background identification.
    assert client.get("/api/songs/song-1/identify-source").status_code == 405
    assert seen == []

    request = {
        "apply_high_confidence_metadata": False,
        "musicbrainz_commercial_entitlement": False,
        "acoustid_commercial_entitlement": False,
    }
    first = client.post("/api/songs/song-1/identify-source", json=request)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "identified"
    assert first.json()["applied"] is False
    assert store.song["title"] == "Owned source"
    assert store.song["artist"] is None
    assert store.song["revision"] == 1
    assert seen == [str(audio)]

    cached = client.post("/api/songs/song-1/identify-source", json=request)
    assert cached.status_code == 200
    assert cached.json() == first.json()
    assert seen == [str(audio)]

    fresh = client.post(
        "/api/songs/song-1/identify-source",
        json={**request, "refresh": True},
    )
    assert fresh.status_code == 200
    assert seen == [str(audio), str(audio)]


def test_product_docs_do_not_claim_unimplemented_auto_enrichment():
    root = Path(__file__).resolve().parents[1]
    source_doc = (root / "docs/SOURCE_IDENTIFICATION.ko.md").read_text(encoding="utf-8")
    enrich_doc = (root / "docs/ENRICHMENT.ko.md").read_text(encoding="utf-8")
    editor_doc = (root / "docs/EDITOR.ko.md").read_text(encoding="utf-8")
    controller = (root / "desktop/src/EnrichmentController.tsx").read_text(
        encoding="utf-8"
    )

    assert "별도의 자동 실행 `SourceIdentificationController`가 없습니다" in source_doc
    assert "`SourceIdentificationController`가 자동으로 식별" not in enrich_doc
    assert "POST /api/songs/{song_id}/identify-source" in source_doc
    assert "identifyOriginal" in controller
    assert 'fetch(`${API}/api/songs/${target.songId}/identify-source`' in controller
    assert "Homebrew" in source_doc  # explicitly disallowed, not recommended
    assert "설치하지 않습니다" in source_doc
    assert "MuseScore 4가 필요합니다" not in editor_doc
    assert "Verovio" in editor_doc and "fpdf2" in editor_doc
