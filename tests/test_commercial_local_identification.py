"""Commercial local-tag identification never needs an unrelated external license."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from audio_score_tool import enrichment_api, source_identification
from audio_score_tool.api import app


class LocalSongStore:
    def __init__(self, root: Path):
        self.asset_root = root / "assets"
        self.song = {
            "song_id": "song-1",
            "title": "Original title",
            "artist": None,
            "revision": 1,
        }
        self.saved: dict[str, dict] = {}

    def get(self, song_id: str) -> dict | None:
        return self.song if song_id == "song-1" else None

    def analysis(self, song_id: str, key: str) -> dict | None:
        return self.saved.get(f"{song_id}:{key}")

    def set_analysis(self, song_id: str, key: str, value: dict) -> None:
        self.saved[f"{song_id}:{key}"] = value


def _configure(tmp_path: Path, monkeypatch):
    store = LocalSongStore(tmp_path)
    source = store.asset_root / "song-1" / "original-audio.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture without external rights")
    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(
        enrichment_api, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="commercial"),
    )
    monkeypatch.setattr(
        enrichment_api,
        "search_musicbrainz",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No commercial MusicBrainz entitlement was provided")
        ),
    )
    monkeypatch.setattr(
        enrichment_api,
        "search_musicbrainz_by_isrc",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No commercial MusicBrainz entitlement was provided")
        ),
    )
    monkeypatch.setattr(
        source_identification,
        "lookup_acoustid",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("No commercial AcoustID entitlement was provided")
        ),
    )
    monkeypatch.delenv("AST_MUSICBRAINZ_COMMERCIAL_ENTITLED", raising=False)
    monkeypatch.delenv("AST_ACOUSTID_COMMERCIAL_ENTITLED", raising=False)
    return store, source


def test_commercial_song_identifies_local_tags_without_external_entitlements(
    tmp_path: Path, monkeypatch,
):
    store, _source = _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(
        source_identification,
        "read_embedded_tags",
        lambda _path: {
            "provider": "embedded_tags",
            "title": "Recorded locally",
            "artist": "Owned artist",
            "album": None,
            "isrc": None,
            "confidence": 1.0,
        },
    )

    # Keep all actual HTTP/serialization and source-identification policy code.
    response = TestClient(app).post(
        "/api/songs/song-1/identify-source",
        json={
            "refresh": True,
            "apply_high_confidence_metadata": False,
            "musicbrainz_commercial_entitlement": False,
            "acoustid_commercial_entitlement": False,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "identified"
    assert result["selected"]["title"] == "Recorded locally"
    assert result["selected_confidence"] >= 0.92
    assert result["policy"]["musicbrainz_commercial_entitlement"] is False
    assert result["policy"]["acoustid_commercial_entitlement"] is False
    assert result["applied"] is False
    assert store.song["revision"] == 1


def test_commercial_isrc_without_entitlement_stays_offline(
    tmp_path: Path, monkeypatch,
):
    store, _source = _configure(tmp_path, monkeypatch)
    monkeypatch.delenv("ACOUSTID_CLIENT_KEY", raising=False)
    monkeypatch.setattr(
        source_identification,
        "read_embedded_tags",
        lambda _path: {
            "provider": "embedded_tags",
            "title": "Possibly tagged",
            "artist": None,
            "album": None,
            "isrc": "USRC17607839",
            "confidence": 0.86,
        },
    )
    response = TestClient(app).post(
        "/api/songs/song-1/identify-source",
        json={
            "refresh": True,
            "apply_high_confidence_metadata": False,
            "musicbrainz_commercial_entitlement": False,
            "acoustid_commercial_entitlement": False,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["applied"] is False
    assert result["musicbrainz_error"] == "commercial MusicBrainz Web Service entitlement not confirmed"
    assert result["acoustid"]["attempted"] is False
    assert store.song["revision"] == 1
