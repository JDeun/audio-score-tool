"""No-network verification of MusicBrainz work writers and LRCLIB API fallback."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import enrichment, enrichment_api
from audio_score_tool.api import app
from audio_score_tool.song_store_v2 import SongStoreV2

_RECORDING = "01234567-89ab-cdef-0123-456789abcdef"
_WORK = "abcdef01-2345-6789-abcd-ef0123456789"


def test_work_relation_finds_real_composers_and_lyricists_only(monkeypatch):
    calls = []

    def mock_musicbrainz(path, params):
        calls.append((path, params))
        if path == f"recording/{_RECORDING}":
            return {
                "id": _RECORDING, "relations": [
                    {"target-type": "work", "type": "performance", "work": {"id": _WORK}}
                ],
            }
        if path == f"work/{_WORK}":
            return {
                "id": _WORK, "relations": [
                    {"target-type": "artist", "type": "composer",
                     "artist": {"name": "Composer 1"}},
                    {"target-type": "artist", "type": "composer",
                     "artist": {"name": "Composer 2"}},
                    {"target-type": "artist", "type": "lyricist",
                     "artist": {"name": "Lyricist A"}},
                    {"target-type": "artist", "type": "performer",
                     "artist": {"name": "Unrelated performer"}},
                ],
            }
        raise AssertionError(f"unexpected MusicBrainz lookup: {path}")

    monkeypatch.setattr(enrichment, "_musicbrainz_request", mock_musicbrainz)
    result = enrichment.lookup_musicbrainz_work_credits(_RECORDING)
    assert result["composer"] == "Composer 1, Composer 2"
    assert result["lyricist"] == "Lyricist A"
    assert result["work_mbid"] == _WORK
    assert result["status"] == "verified_work_relations"
    assert calls == [
        (f"recording/{_RECORDING}", {"inc": "work-rels"}),
        (f"work/{_WORK}", {"inc": "artist-rels"}),
    ]


def test_multiple_work_links_do_not_invent_songwriter(monkeypatch):
    def fake_request(_path, _params):
        return {
            "id": _RECORDING,
            "relations": [
                {"type": "performance", "target-type": "work",
                 "work": {"id": _WORK}},
                {"type": "performance", "target-type": "work",
                 "work": {"id": _RECORDING}},
            ],
        }

    monkeypatch.setattr(enrichment, "_musicbrainz_request", fake_request)
    found = enrichment.lookup_musicbrainz_work_credits(_RECORDING)
    assert found["status"] == "ambiguous_or_missing_work"
    assert found["composer"] is None
    assert found["lyricist"] is None


def test_lrclib_exact_lyrics_without_api_key_and_incorrect_track_rejected(monkeypatch):
    urls = []
    payload = {
        "trackName": "Example", "artistName": "The Band", "albumName": "Album",
        "plainLyrics": "First line\nSecond line", "syncedLyrics": None,
        "instrumental": False, "id": 42,
    }
    def mock_json(url, *, headers, timeout, max_bytes):
        urls.append((url, headers))
        return payload

    monkeypatch.setattr(enrichment, "_json_request", mock_json)
    lyrics = enrichment.fetch_lrclib_lyrics("Example", "The Band", album="Album")
    assert lyrics["provider"] == "lrclib"
    assert lyrics["lyrics"] == "First line\nSecond line"
    assert "api/get" in urls[0][0]
    assert "album_name=Album" in urls[0][0]
    assert "Authorization" not in urls[0][1]
    assert "User-Agent" in urls[0][1]
    payload["trackName"] = "Different song"
    assert enrichment.fetch_lrclib_lyrics("Example", "The Band") is None
    payload["trackName"] = "Example"
    payload["instrumental"] = True
    assert enrichment.fetch_lrclib_lyrics("Example", "The Band") is None


def test_lrclib_404_means_whisperx_fallback_other_errors_reported(monkeypatch):
    def missing(*_args, **_kwargs):
        raise enrichment.EnrichmentError("HTTP Error 404: Not Found")
    monkeypatch.setattr(enrichment, "_json_request", missing)
    assert enrichment.fetch_lrclib_lyrics("Song", "Artist") is None

    def unavailable(*_args, **_kwargs):
        raise enrichment.EnrichmentError("HTTP Error 429: Too Many Requests")
    monkeypatch.setattr(enrichment, "_json_request", unavailable)
    with pytest.raises(enrichment.EnrichmentError, match="429"):
        enrichment.fetch_lrclib_lyrics("Song", "Artist")
    assert enrichment.fetch_lrclib_lyrics("Song", None) is None


def test_manual_enrichment_defaults_to_lrclib_then_existing_whisperx(
    monkeypatch, tmp_path,
):
    store = SongStoreV2(
        path=tmp_path / "data.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    xml = tmp_path / "original.musicxml"
    xml.write_text(
        '<score-partwise version="4.0"><part-list><score-part id="P1">'
        '<part-name>Voice</part-name></score-part></part-list>'
        '<part id="P1"><measure number="1"><attributes><divisions>1</divisions>'
        '</attributes><note><pitch><step>C</step><octave>4</octave></pitch>'
        '<duration>1</duration><type>quarter</type></note></measure></part>'
        '</score-partwise>', encoding="utf-8",
    )
    assert store.sync_completed_jobs([{
        "job_id": "song-c1", "kind": "notation-import", "status": "done",
        "filename": "Song.musicxml", "result": {"musicxml": str(xml)},
    }]) == 1
    store.set_analysis("song-c1", "lyrics_transcript", {
        "segments": [{"words": [{"word": "hello", "start": 0.0, "end": 0.5}]}]
    })
    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(enrichment_api, "runtime_settings",
                        lambda: SimpleNamespace(usage_mode="personal"))
    monkeypatch.setattr(enrichment_api, "search_musicbrainz", lambda *_a: [])
    monkeypatch.setattr(enrichment_api, "fetch_lrclib_lyrics",
                        lambda *args, **kwargs: None)
    client = TestClient(app)
    response = client.post("/api/songs/song-c1/enrich", json={
        "title": "Example", "artist": "The Band", "auto_lyrics": True,
    })
    assert response.status_code == 200, response.text
    assert response.json()["lyrics_source"] == "whisperx"
    assert response.json()["lyrics"] is None

    monkeypatch.setattr(enrichment_api, "fetch_lrclib_lyrics",
                        lambda *args, **kwargs: {
                            "provider": "lrclib", "lyrics": "hello",
                            "synced": False, "source_payload": {},
                        })
    # No API output or lyrics text printed here; only provider provenance.
    response = client.post("/api/songs/song-c1/enrich", json={
        "title": "Example", "artist": "The Band", "apply_reference_lyrics": False,
    })
    assert response.status_code == 200
    assert response.json()["lyrics_source"] == "external_api"
    assert response.json()["lyrics"]["provider"] == "lrclib"
    assert store.analysis("song-c1", "external_lyrics")["provider"] == "lrclib"
