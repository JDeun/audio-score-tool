from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from audio_score_tool import credits_api, revision_api_v2
from audio_score_tool.api import app
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Demo</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><rest/><duration>4</duration><type>whole</type></note>
  </measure></part>
</score-partwise>
"""


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = SongStoreV2(
        path=tmp_path / "app.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )
    publication = PublicationStoreV2(
        path=store.path,
        legacy_root=tmp_path / "legacy",
    )
    source = tmp_path / "generated.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    assert store.sync_completed_jobs(
        [{
            "job_id": "song-1",
            "kind": "notation-import",
            "status": "done",
            "filename": "demo.musicxml",
            "result": {"musicxml": str(source)},
        }]
    ) == 1
    publication.write("song-1", {"composer": "Original"})
    export = store.export_dir("song-1") / "score.pdf"
    export.write_bytes(b"%PDF-1.4")

    def require(song_id: str):
        row = store.get(song_id)
        if row is None:
            raise HTTPException(404, "Song not found")
        return row

    def public(row: dict) -> dict:
        return {
            "song_id": row["song_id"],
            "title": row["title"],
            "artist": row["artist"],
            "revision": row["revision"],
        }

    monkeypatch.setattr(credits_api, "_require_song", require)
    monkeypatch.setattr(credits_api, "_song_store", store)
    monkeypatch.setattr(credits_api, "_publication_store", publication)
    monkeypatch.setattr(credits_api, "_public", public)
    monkeypatch.setattr(revision_api_v2, "_require_song", require)
    monkeypatch.setattr(revision_api_v2, "_song_store", store)
    monkeypatch.setattr(revision_api_v2, "_public", public)
    return store, publication, export


def _credit_request(expected_revision: int = 1) -> dict:
    return {
        "title": "Published title",
        "artist": "Publishing artist",
        "expected_revision": expected_revision,
        "subtitle": "Piano & Voice",
        "composer": "New composer",
        "lyricist": "Lyricist",
        "arranger": "Arranger",
        "rights": "© Licensed source",
        "title_font_size": 30,
        "subtitle_font_size": 13,
        "credit_font_size": 10,
    }


def _snapshot_count(store: SongStoreV2) -> int:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(
            "SELECT count(*) FROM song_revisions WHERE song_id='song-1'"
        ).fetchone()[0]


def test_atomic_credits_commit_updates_song_publication_xml_and_one_revision(stores):
    store, publication, export = stores
    response = TestClient(app).patch(
        "/api/songs/song-1/credits", json=_credit_request()
    )
    assert response.status_code == 200, response.text

    song = store.get("song-1")
    assert song is not None
    assert song["revision"] == 2
    assert song["title"] == "Published title"
    assert song["artist"] == "Publishing artist"
    assert publication.read("song-1")["composer"] == "New composer"
    assert publication.read("song-1")["subtitle"] == "Piano & Voice"
    assert _snapshot_count(store) == 1
    assert not export.exists(), "stale PDF exports must be invalidated"

    root = ET.fromstring(store.score_xml("song-1"))
    assert root.findtext("./work/work-title") == "Published title"
    credits = [node.findtext("credit-words") for node in root.findall("credit")]
    assert "Published title" in credits
    assert "Piano & Voice" in credits
    assert "작곡  New composer" in credits
    assert "© Licensed source" in credits


def test_one_undo_restores_metadata_publication_and_musicxml_together(stores):
    store, publication, _export = stores
    client = TestClient(app)
    assert client.patch(
        "/api/songs/song-1/credits", json=_credit_request()
    ).status_code == 200
    undone = client.post("/api/songs/song-1/undo")
    assert undone.status_code == 200, undone.text
    assert store.get("song-1")["revision"] == 1
    assert store.get("song-1")["title"] == "demo"
    assert store.get("song-1")["artist"] is None
    assert publication.read("song-1")["composer"] == "Original"
    assert "Published title" not in store.score_xml("song-1")
    assert _snapshot_count(store) == 0


def test_publication_sql_failure_rolls_back_title_xml_revision_and_snapshot(stores):
    store, publication, export = stores
    before_xml = store.score_xml("song-1")
    with sqlite3.connect(store.path) as conn:
        conn.executescript("""
            CREATE TRIGGER deny_credit_publication_write
            BEFORE UPDATE ON publication_settings
            BEGIN
              SELECT RAISE(ABORT, 'injected publication failure');
            END;
        """)

    response = TestClient(app).patch(
        "/api/songs/song-1/credits", json=_credit_request()
    )
    assert response.status_code == 500, response.text
    assert store.get("song-1")["revision"] == 1
    assert store.get("song-1")["title"] == "demo"
    assert store.get("song-1")["artist"] is None
    assert store.score_xml("song-1") == before_xml
    assert publication.read("song-1")["composer"] == "Original"
    assert _snapshot_count(store) == 0
    assert export.is_file(), "valid previous export must survive a failed save"


def test_stale_credit_revision_fails_closed_without_any_partial_changes(stores):
    store, publication, export = stores
    response = TestClient(app).patch(
        "/api/songs/song-1/credits",
        json=_credit_request(expected_revision=99),
    )
    assert response.status_code == 409, response.text
    assert store.get("song-1")["revision"] == 1
    assert store.get("song-1")["title"] == "demo"
    assert publication.read("song-1")["composer"] == "Original"
    assert _snapshot_count(store) == 0
    assert export.is_file()


def test_invalid_credits_payload_is_rejected_before_writes(stores):
    store, publication, _export = stores
    response = TestClient(app).patch(
        "/api/songs/song-1/credits",
        json={**_credit_request(), "title_font_size": 999},
    )
    assert response.status_code == 422
    assert store.get("song-1")["revision"] == 1
    assert publication.read("song-1")["composer"] == "Original"
