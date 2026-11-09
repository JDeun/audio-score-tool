from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from audio_score_tool import credits_api, enrichment_api, revision_api_v2
from audio_score_tool.api import app
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Original title</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>
"""


@pytest.fixture
def state(tmp_path: Path, monkeypatch):
    store = SongStoreV2(
        path=tmp_path / "canonical.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    source = tmp_path / "Original title.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    assert store.sync_completed_jobs([{
        "job_id": "song-1",
        "kind": "notation-import",
        "status": "done",
        "filename": "Original title.musicxml",
        "result": {"musicxml": str(source)},
    }]) == 1
    publication = PublicationStoreV2(
        path=store.path, legacy_root=tmp_path / "legacy"
    )
    publication.write("song-1", {"composer": "Original composer"})

    def require(song_id: str) -> dict:
        row = store.get(song_id)
        if row is None:
            raise HTTPException(404, "Song not found")
        return row

    monkeypatch.setattr(enrichment_api, "_store", store)
    monkeypatch.setattr(enrichment_api, "_publication", publication)
    monkeypatch.setattr(revision_api_v2, "_song_store", store)
    monkeypatch.setattr(revision_api_v2, "_require_song", require)
    monkeypatch.setattr(
        revision_api_v2,
        "_public",
        lambda row: {
            "song_id": row["song_id"],
            "title": row["title"],
            "artist": row["artist"],
            "revision": row["revision"],
        },
    )
    return store, publication


def _snapshot_count(store: SongStoreV2) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(
            "SELECT count(*) FROM song_revisions WHERE song_id='song-1'"
        ).fetchone()[0]


def _apply(store, *, title="New title", artist="New artist"):
    current = store.get("song-1")
    assert current is not None
    return enrichment_api._apply_metadata(
        "song-1", current,
        {"title": title, "artist": artist},
        current["title"], current["artist"],
    )


def test_identified_title_artist_and_score_commit_once_and_undo_together(state):
    store, publication = state
    old_xml = store.score_xml("song-1")
    export = store.export_dir("song-1") / "score.pdf"
    export.write_bytes(b"%PDF fixture")

    assert _apply(store)
    current = store.get("song-1")
    assert current is not None
    assert current["title"] == "New title"
    assert current["artist"] == "New artist"
    assert current["revision"] == 2
    assert "New title" in store.score_xml("song-1")
    assert _snapshot_count(store) == 1
    assert not export.exists()
    assert publication.read("song-1")["composer"] == "Original composer"

    result = TestClient(app).post("/api/songs/song-1/undo")
    assert result.status_code == 200, result.text
    restored = store.get("song-1")
    assert restored is not None
    assert restored["title"] == "Original title"
    assert restored["artist"] is None
    assert restored["revision"] == 1
    assert store.score_xml("song-1") == old_xml
    assert _snapshot_count(store) == 0
    assert publication.read("song-1")["composer"] == "Original composer"


def test_artist_only_change_creates_one_undo_revision(state):
    store, _ = state
    old_xml = store.score_xml("song-1")
    assert _apply(store, title="Original title", artist="New artist")
    assert store.get("song-1")["revision"] == 2
    assert store.get("song-1")["artist"] == "New artist"
    assert store.score_xml("song-1") == old_xml
    assert _snapshot_count(store) == 1

    undo = TestClient(app).post("/api/songs/song-1/undo")
    assert undo.status_code == 200, undo.text
    assert store.get("song-1")["artist"] is None
    assert store.get("song-1")["revision"] == 1


def test_repeat_identical_metadata_has_no_revision_or_export_invalidation(state):
    store, _ = state
    old_xml = store.score_xml("song-1")
    export = store.export_dir("song-1") / "score.pdf"
    export.write_bytes(b"%PDF unchanged")
    assert _apply(store, title="Original title", artist=None)
    assert store.get("song-1")["revision"] == 1
    assert store.score_xml("song-1") == old_xml
    assert _snapshot_count(store) == 0
    assert export.is_file()


def test_injected_sql_error_rolls_back_metadata_score_and_snapshot(state):
    store, publication = state
    before = store.score_xml("song-1")
    export = store.export_dir("song-1") / "score.pdf"
    export.write_bytes(b"%PDF previous")
    with sqlite3.connect(store.path) as conn:
        conn.executescript("""
        CREATE TRIGGER reject_identification
        BEFORE UPDATE ON songs
        WHEN NEW.revision > OLD.revision
        BEGIN
          SELECT RAISE(ABORT, 'injected commit failure');
        END;
        """)

    assert _apply(store) is False
    current = store.get("song-1")
    assert current["title"] == "Original title"
    assert current["artist"] is None
    assert current["revision"] == 1
    assert store.score_xml("song-1") == before
    assert publication.read("song-1")["composer"] == "Original composer"
    assert _snapshot_count(store) == 0
    assert export.read_bytes() == b"%PDF previous"


def test_late_identification_cannot_overwrite_newer_user_revision(state):
    store, _ = state
    stale_song = store.get("song-1")
    assert stale_song is not None
    path = store.checkout_current("song-1")
    # Another user edit commits while the external identifier is resolving.
    store.commit_edit_from_path("song-1", path)
    assert store.get("song-1")["revision"] == 2

    assert enrichment_api._apply_metadata(
        "song-1", stale_song,
        {"title": "Stale network result", "artist": "Stale artist"},
        stale_song["title"], stale_song["artist"],
    ) is False
    current = store.get("song-1")
    assert current["revision"] == 2
    assert current["title"] == "Original title"
    assert current["artist"] is None
    assert "Stale network result" not in store.score_xml("song-1")



def test_verified_album_performer_and_writers_are_atomic_and_undoable(state):
    store, publication = state
    old_xml = store.score_xml("song-1")
    selected = {
        "provider": "musicbrainz",
        "title": "Matched song",
        "artist": "Verified vocalist",
        "album": "Verified album",
        "first_release_date": "2004-09-21",
        "composer": "Actual composer",
        "lyricist": "Actual lyricist",
        "songwriters_verified": True,
    }
    before = store.get("song-1")
    assert enrichment_api._apply_metadata(
        "song-1", before, selected, before["title"], before["artist"]
    )
    next_song = store.get("song-1")
    assert next_song["revision"] == before["revision"] + 1
    assert next_song["title"] == "Matched song"
    assert next_song["artist"] == "Verified vocalist"
    updated = publication.read("song-1")
    assert updated["album"] == "Verified album"
    assert updated["performer"] == "Verified vocalist"
    assert updated["release_date"] == "2004-09-21"
    assert updated["composer"] == "Original composer"  # user-entered value wins
    assert updated["lyricist"] == "Actual lyricist"
    xml = store.score_xml("song-1")
    assert "Verified album" in xml
    assert "Actual lyricist" in xml
    assert "Verified vocalist" in xml
    assert _snapshot_count(store) == 1

    # Matching again must not clear exports or add a redundant revision.
    export = store.export_dir("song-1") / "score.pdf"
    export.write_bytes(b"%PDF protected")
    assert enrichment_api._apply_metadata(
        "song-1", next_song, selected, next_song["title"], next_song["artist"]
    )
    assert store.get("song-1")["revision"] == next_song["revision"]
    assert export.read_bytes() == b"%PDF protected"

    undone = TestClient(app).post("/api/songs/song-1/undo")
    assert undone.status_code == 200, undone.text
    restored = store.get("song-1")
    assert restored["title"] == before["title"]
    assert restored["artist"] == before["artist"]
    assert restored["revision"] == before["revision"]
    assert store.score_xml("song-1") == old_xml
    current_publication = publication.read("song-1")
    assert current_publication["composer"] == "Original composer"
    assert current_publication["album"] == ""
    assert current_publication["performer"] == ""


def test_missing_work_relations_never_guess_that_performer_is_composer(state):
    store, publication = state
    selected = {
        "provider": "musicbrainz",
        "title": "Matched",
        "artist": "Group Name",
        "composer": "Group Name",
        "songwriters_verified": False,
    }
    song = store.get("song-1")
    assert enrichment_api._apply_metadata(
        "song-1", song, selected, song["title"], song["artist"]
    )
    current = publication.read("song-1")
    assert current["performer"] == "Group Name"
    assert current["composer"] == "Original composer"
    assert current["lyricist"] == ""


def test_failed_publication_metadata_write_rolls_back_all_fields(state):
    store, publication = state
    before = store.get("song-1")
    old = store.score_xml("song-1")
    with sqlite3.connect(store.path) as conn:
        conn.executescript("""
            CREATE TRIGGER reject_enrichment
            BEFORE UPDATE ON songs
            BEGIN SELECT RAISE(ABORT, 'rollback-test'); END;
        """)
    selected = {
        "provider": "musicbrainz", "title": "Failed",
        "artist": "Artist", "album": "Album",
    }
    assert enrichment_api._apply_metadata(
        "song-1", before, selected, before["title"], before["artist"]
    ) is False
    assert store.get("song-1")["revision"] == before["revision"]
    assert store.score_xml("song-1") == old
    assert publication.read("song-1")["album"] == ""
    assert _snapshot_count(store) == 0



def test_manual_metadata_save_then_exact_api_requery_preserves_user_edits(
    state, monkeypatch,
):
    """A recovered Unknown score can be edited, saved and enriched in one Song."""
    store, publication = state
    original = store.get("song-1")
    assert original is not None

    store.set_analysis("song-1", "automatic_enrichment", {"status": "unknown"})
    assert enrichment_api._apply_metadata(
        "song-1", original,
        {"provider": "unresolved", "title": "Unknown", "artist": "Unknown"},
        original["title"], original["artist"],
    )
    assert store.get("song-1")["revision"] == 2
    assert publication.read("song-1")["album"] == "Unknown"
    assert publication.read("song-1")["composer"] == "Original composer"

    def require_song(song_id):
        row = store.get(song_id)
        if row is None:
            raise HTTPException(404, "Song not found")
        return row

    monkeypatch.setattr(credits_api, "_song_store", store)
    monkeypatch.setattr(credits_api, "_publication_store", publication)
    monkeypatch.setattr(credits_api, "_require_song", require_song)
    client = TestClient(app)
    saved = client.patch("/api/songs/song-1/credits", json={
        "title": "American Idiot",
        "artist": "Green Day",
        "expected_revision": 2,
        "album": "User-entered album",
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["song"]["revision"] == 3
    assert store.get("song-1")["title"] == "American Idiot"

    query_calls = []
    def search(title, artist):
        query_calls.append((title, artist))
        return [
            {"provider": "musicbrainz", "title": "Another Song",
             "artist": "Another Band", "recording_mbid": None, "score": 100},
            {"provider": "musicbrainz", "title": "American Idiot",
             "artist": "Green Day", "album": "Verified album",
             "recording_mbid": "01234567-89ab-cdef-0123-456789abcdef",
             "score": 99},
        ]

    monkeypatch.setattr(enrichment_api, "search_musicbrainz", search)
    monkeypatch.setattr(enrichment_api, "lookup_musicbrainz_work_credits",
                        lambda *_args: {
                            "composer": "Verified songwriter",
                            "lyricist": "Verified lyricist",
                            "work_mbid": "abcdef01-2345-6789-abcd-ef0123456789",
                            "status": "verified_work_relations",
                        })
    monkeypatch.setattr(enrichment_api, "runtime_settings",
                        lambda: SimpleNamespace(usage_mode="personal"))
    enriched = client.post("/api/songs/song-1/enrich", json={
        "title": "American Idiot",
        "artist": "Green Day",
        "require_exact_match": True,
        "apply_reference_lyrics": False,
        "auto_lyrics": False,
    })
    assert enriched.status_code == 200, enriched.text
    assert query_calls == [("American Idiot", "Green Day")]
    assert enriched.json()["metadata"]["selected"]["title"] == "American Idiot"
    assert enriched.json()["metadata"]["applied"] is True
    assert len(enriched.json()["metadata"]["candidates"]) == 1
    assert store.get("song-1")["revision"] == 4
    actual = publication.read("song-1")
    assert actual["album"] == "User-entered album"
    assert actual["composer"] == "Original composer"
    assert actual["lyricist"] == "Verified lyricist"
    assert actual["performer"] == "Green Day"
    assert "Verified lyricist" in store.score_xml("song-1")

    # Revert only the API enrichment; the user's manual metadata survives.
    undone = client.post("/api/songs/song-1/undo")
    assert undone.status_code == 200, undone.text
    assert store.get("song-1")["revision"] == 3
    assert publication.read("song-1")["album"] == "User-entered album"
    assert publication.read("song-1")["lyricist"] == "Unknown"


def test_metadata_popup_stale_revision_returns_409_without_partial_changes(
    state, monkeypatch,
):
    store, publication = state

    def require_song(song_id):
        row = store.get(song_id)
        if row is None:
            raise HTTPException(404, "Song not found")
        return row

    monkeypatch.setattr(credits_api, "_song_store", store)
    monkeypatch.setattr(credits_api, "_publication_store", publication)
    monkeypatch.setattr(credits_api, "_require_song", require_song)
    old_xml = store.score_xml("song-1")
    prior = publication.read("song-1")
    response = TestClient(app).patch("/api/songs/song-1/credits", json={
        "title": "Stale title",
        "artist": "Stale artist",
        "album": "Stale album",
        "expected_revision": 19,
    })
    assert response.status_code == 409
    assert store.get("song-1")["revision"] == 1
    assert store.score_xml("song-1") == old_xml
    assert publication.read("song-1") == prior
