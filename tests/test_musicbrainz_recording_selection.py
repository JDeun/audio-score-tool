"""End-to-end selected album/recording metadata, no media download or internet.

The client supplies only MusicBrainz MBIDs and a revision. The backend re-fetches
the recording, verifies its artist/title and release association, then uses the
existing atomic Song/MusicXML publication update and Undo.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from audio_score_tool import credits_api, enrichment, enrichment_api, revision_api_v2
from audio_score_tool.api import app
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2

_RECORDING_1 = "00000000-0000-0000-0000-000000000001"
_RECORDING_2 = "00000000-0000-0000-0000-000000000002"
_RELEASE_1 = "11111111-1111-1111-1111-111111111111"
_RELEASE_2 = "22222222-2222-2222-2222-222222222222"
_WORK = "33333333-3333-3333-3333-333333333333"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>American Idiot</work-title></work>
  <movement-title>American Idiot</movement-title>
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1</duration><type>quarter</type>
      <lyric><text>Original STT word</text></lyric></note>
  </measure></part>
</score-partwise>
"""


@pytest.fixture
def example(tmp_path, monkeypatch):
    store = SongStoreV2(
        path=tmp_path / "song.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    score = tmp_path / "American Idiot.musicxml"
    score.write_text(XML, encoding="utf-8")
    assert store.sync_completed_jobs([{
        "job_id": "selected-song", "kind": "notation-import",
        "status": "done", "filename": "American Idiot.musicxml",
        "result": {"musicxml": str(score)},
    }]) == 1
    publication = PublicationStoreV2(path=store.path, legacy_root=tmp_path / "legacy")

    def require_song(song_id: str):
        record = store.get(song_id)
        if record is None:
            raise HTTPException(404, "Song not found")
        return record

    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(enrichment_api, "_publication", publication)
    monkeypatch.setattr(credits_api, "_song_store", store)
    monkeypatch.setattr(credits_api, "_publication_store", publication)
    monkeypatch.setattr(credits_api, "_require_song", require_song)
    monkeypatch.setattr(revision_api_v2, "_song_store", store)
    monkeypatch.setattr(revision_api_v2, "_require_song", require_song)
    monkeypatch.setattr(revision_api_v2, "_public", lambda row: {
        "song_id": row["song_id"], "title": row["title"],
        "artist": row["artist"], "revision": row["revision"],
    })
    monkeypatch.setattr(
        enrichment_api, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="personal"),
    )
    client = TestClient(app)
    saved = client.patch("/api/songs/selected-song/credits", json={
        "title": "American Idiot", "artist": "Green Day",
        "expected_revision": 1, "album": "Unknown",
        "composer": "Unknown", "lyricist": "Unknown",
        "arranger": "User-arranged", "rights": "Private notes",
    })
    assert saved.status_code == 200, saved.text
    assert store.get("selected-song")["revision"] == 2
    return client, store, publication


def _mock_recording_api(
    monkeypatch, *, missing_release=False, wrong_artist=False,
    work=True, linked_in_release=False,
):
    calls = []

    def response(path, params):
        calls.append((path, params))
        if path == f"recording/{_RECORDING_2}" and params == {
            "inc": "artist-credits+releases",
        }:
            return {
                "id": _RECORDING_2,
                "title": "American Idiot",
                "artist-credit": [{
                    "name": "Other Artist" if wrong_artist else "Green Day",
                    "artist": {"name": "Other Artist" if wrong_artist else "Green Day"},
                }],
                "releases": [] if missing_release else [{
                    "id": _RELEASE_2, "title": "Studio Album", "date": "2004-09-21",
                }],
            }
        if path == f"release/{_RELEASE_2}" and params == {"inc": "recordings"}:
            return {
                "id": _RELEASE_2, "title": "Studio Album",
                "date": "2004-09-21",
                "media": [{"tracks": [{
                    "recording": {
                        "id": _RECORDING_2 if linked_in_release else _RECORDING_1,
                    },
                }]}],
            }
        if path == f"recording/{_RECORDING_2}" and params == {"inc": "work-rels"}:
            return {
                "id": _RECORDING_2, "relations": [{
                    "target-type": "work", "type": "performance",
                    "work": {"id": _WORK},
                }] if work else [],
            }
        if path == f"work/{_WORK}" and params == {"inc": "artist-rels"}:
            return {
                "id": _WORK, "relations": [{
                    "target-type": "artist", "type": "composer",
                    "artist": {"name": "Verified composer"},
                }, {
                    "target-type": "artist", "type": "lyricist",
                    "artist": {"name": "Verified lyricist"},
                }],
            }
        raise AssertionError(f"Unexpected MusicBrainz request: {path} {params}")

    monkeypatch.setattr(enrichment, "_musicbrainz_request", response)
    return calls


def test_explicit_recording_album_choice_fills_unknown_credits_and_can_undo(
    example, monkeypatch,
):
    client, store, publication = example
    calls = _mock_recording_api(monkeypatch)

    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 200, result.text
    assert result.json()["applied"] is True
    assert result.json()["changed"] is True
    assert store.get("selected-song")["revision"] == 3
    assert store.get("selected-song")["title"] == "American Idiot"
    assert store.get("selected-song")["artist"] == "Green Day"
    fields = publication.read("selected-song")
    assert fields["album"] == "Studio Album"
    assert fields["release_date"] == "2004-09-21"
    assert fields["performer"] == "Green Day"
    assert fields["composer"] == "Verified composer"
    assert fields["lyricist"] == "Verified lyricist"
    assert fields["arranger"] == "User-arranged"
    assert fields["rights"] == "Private notes"
    assert "Original STT word" in store.score_xml("selected-song")
    assert len(calls) == 3
    provenance = store.analysis("selected-song", "selected_musicbrainz_recording")
    assert provenance["recording_mbid"] == _RECORDING_2
    assert provenance["release_mbid"] == _RELEASE_2
    assert provenance["writer_relations_verified"] is True
    assert "lyrics" not in provenance

    undo = client.post("/api/songs/selected-song/undo")
    assert undo.status_code == 200, undo.text
    assert store.get("selected-song")["revision"] == 2
    assert publication.read("selected-song")["album"] == "Unknown"
    assert publication.read("selected-song")["composer"] == "Unknown"
    assert "Original STT word" in store.score_xml("selected-song")


def test_release_mbid_must_be_proven_linked_to_selected_recording(
    example, monkeypatch,
):
    client, store, publication = example
    calls = _mock_recording_api(monkeypatch, missing_release=True)
    original_xml = store.score_xml("selected-song")
    original_credits = publication.read("selected-song")
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 422
    assert "not verified" in result.json()["detail"]
    assert len(calls) == 2
    assert store.get("selected-song")["revision"] == 2
    assert store.score_xml("selected-song") == original_xml
    assert publication.read("selected-song") == original_credits


def test_selected_release_link_can_be_verified_from_release_tracks_beyond_recording_page(
    example, monkeypatch,
):
    client, store, publication = example
    calls = _mock_recording_api(
        monkeypatch, missing_release=True, linked_in_release=True,
    )
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2,
        "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 200, result.text
    assert store.get("selected-song")["revision"] == 3
    assert publication.read("selected-song")["album"] == "Studio Album"
    assert any(path == f"release/{_RELEASE_2}" for path, _ in calls)
    assert len(calls) == 4


def test_wrong_artist_recording_cannot_override_correct_song(
    example, monkeypatch,
):
    client, store, publication = example
    calls = _mock_recording_api(monkeypatch, wrong_artist=True)
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 422
    assert "일치하지 않습니다" in result.json()["detail"]
    assert len(calls) == 1
    assert store.get("selected-song")["revision"] == 2
    assert publication.read("selected-song")["album"] == "Unknown"


def test_missing_work_credits_does_not_guess_composer(example, monkeypatch):
    client, _, publication = example
    _mock_recording_api(monkeypatch, work=False)
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 200, result.text
    assert result.json()["selection"]["writer_relations_verified"] is False
    assert publication.read("selected-song")["composer"] == "Unknown"
    assert publication.read("selected-song")["lyricist"] == "Unknown"
    assert publication.read("selected-song")["album"] == "Studio Album"


def test_user_entered_album_never_overwritten_by_explicit_recording(
    example, monkeypatch,
):
    client, _, publication = example
    manual = client.patch("/api/songs/selected-song/credits", json={
        "title": "American Idiot", "artist": "Green Day",
        "expected_revision": 2, "album": "Personal edition",
    })
    assert manual.status_code == 200
    _mock_recording_api(monkeypatch)
    chosen = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 3,
    })
    assert chosen.status_code == 200, chosen.text
    assert publication.read("selected-song")["album"] == "Personal edition"
    assert publication.read("selected-song")["composer"] == "Verified composer"


@pytest.mark.parametrize("invalid", [
    "javascript:alert(1)",
    "../../../../../../etc/passwd",
    "00000000-0000-0000-0000-000000000002/other",
])
def test_invalid_recording_id_is_rejected_before_any_request(
    example, monkeypatch, invalid,
):
    client, store, _ = example
    monkeypatch.setattr(enrichment, "_musicbrainz_request",
                        lambda *_args: pytest.fail("Invalid ID must not reach HTTP"))
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": invalid, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 422
    assert store.get("selected-song")["revision"] == 2


def test_stale_selection_returns_409_before_http(example, monkeypatch):
    client, store, _ = example
    monkeypatch.setattr(enrichment, "_musicbrainz_request",
                        lambda *_args: pytest.fail("Stale revision must not use HTTP"))
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 1,
    })
    assert result.status_code == 409
    assert store.get("selected-song")["revision"] == 2


def test_provider_outage_cannot_partially_update_song(example, monkeypatch):
    client, store, publication = example
    original_xml = store.score_xml("selected-song")
    old_credits = publication.read("selected-song")
    def outage(*_args, **_kwargs):
        raise enrichment.EnrichmentError("HTTP Error 503: Service Unavailable")

    monkeypatch.setattr(enrichment, "_musicbrainz_request", outage)
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 503
    assert store.get("selected-song")["revision"] == 2
    assert publication.read("selected-song") == old_credits
    assert store.score_xml("selected-song") == original_xml


def test_unlicensed_commercial_session_requires_explicit_access(
    example, monkeypatch,
):
    client, store, _ = example
    monkeypatch.setattr(
        enrichment_api, "runtime_settings",
        lambda: SimpleNamespace(usage_mode="commercial"),
    )
    monkeypatch.setattr(enrichment, "_musicbrainz_request",
                        lambda *_args: pytest.fail("Must not query without entitlement"))
    result = client.post("/api/songs/selected-song/select-recording", json={
        "recording_mbid": _RECORDING_2, "release_mbid": _RELEASE_2,
        "expected_revision": 2,
    })
    assert result.status_code == 422
    assert store.get("selected-song")["revision"] == 2
