"""Real API + filesystem flow without invoking AI models."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mido import Message, MetaMessage, MidiFile, MidiTrack

from audio_score_tool import (
    credits_api,
    direct_score_import_api,
    export_api_v2,
    notation_export_api,
    revision_api_v2,
    song_routes,
)
from audio_score_tool.api import app
from audio_score_tool.job_store import JobStore
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2
from audio_score_tool.song_tombstones import SongTombstoneStore

SCORE_XML = """<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <work><work-title>Owned fixture</work-title></work>
  <movement-title>Owned fixture</movement-title>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure implicit="no" number="1">
    <attributes><divisions>480</divisions>
      <key><fifths>0</fifths><mode>major</mode></key>
      <time><beats>4</beats><beat-type>4</beat-type></time>
      <clef><sign>G</sign><line>2</line></clef>
    </attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1920</duration><type>whole</type></note>
  </measure></part>
</score-partwise>
"""


def _midi_fixture() -> bytes:
    song = MidiFile(ticks_per_beat=480)
    track = MidiTrack()
    track.append(MetaMessage("track_name", name="Owned fixture", time=0))
    track.append(Message("program_change", channel=0, program=0, time=0))
    track.append(Message("note_on", channel=0, note=60, velocity=80, time=0))
    track.append(Message("note_off", channel=0, note=60, velocity=0, time=1920))
    track.append(MetaMessage("end_of_track", time=0))
    song.tracks.append(track)
    buffer = BytesIO()
    song.save(file=buffer)
    return buffer.getvalue()


@pytest.fixture
def product(tmp_path: Path, monkeypatch):
    db = tmp_path / "canonical.sqlite3"
    jobs_dir = tmp_path / "jobs"
    store = JobStore(db)
    songs = SongStoreV2(
        path=db,
        cache_root=tmp_path / "cache" / "scores",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "managed-exports",
    )
    publication = PublicationStoreV2(path=db, legacy_root=tmp_path / "legacy-songs")
    tombstones = SongTombstoneStore(db)

    monkeypatch.setattr(direct_score_import_api, "_store", store)
    monkeypatch.setattr(direct_score_import_api, "jobs_dir", lambda: jobs_dir)
    monkeypatch.setattr(song_routes, "_job_store", store)
    monkeypatch.setattr(song_routes, "_song_store", songs)
    monkeypatch.setattr(song_routes, "_publication_store", publication)
    monkeypatch.setattr(song_routes, "_tombstones", tombstones)
    monkeypatch.setattr(notation_export_api, "_song_store", songs)
    monkeypatch.setattr(notation_export_api, "_publication_store", publication)
    monkeypatch.setattr(notation_export_api, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(export_api_v2, "_song_store", songs)
    monkeypatch.setattr(revision_api_v2, "_song_store", songs)
    monkeypatch.setattr(credits_api, "_song_store", songs)
    monkeypatch.setattr(credits_api, "_publication_store", publication)

    class InlineThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(direct_score_import_api, "Thread", InlineThread)
    return TestClient(app), store, songs, tmp_path


@pytest.mark.parametrize("input_kind", ["musicxml", "mid"])
def test_import_library_edit_undo_and_real_publish_bundle(product, input_kind: str):
    client, jobs, songs, root = product
    if input_kind == "musicxml":
        contents = SCORE_XML.encode("utf-8")
        media = "application/vnd.recordare.musicxml+xml"
    else:
        contents = _midi_fixture()
        media = "audio/midi"

    uploaded = client.post(
        "/api/import/notation",
        files={"file": (f"owned-fixture.{input_kind}", contents, media)},
    )
    assert uploaded.status_code == 202, uploaded.text
    job_id = uploaded.json()["job_id"]
    completed = jobs.get(job_id)
    assert completed is not None
    assert completed["kind"] == "notation-import"
    assert completed["status"] == "done", completed.get("error")
    assert Path(completed["result"]["musicxml"]).is_file()

    library = client.get("/api/songs")
    assert library.status_code == 200, library.text
    entries = library.json()["songs"]
    assert any(row["song_id"] == job_id for row in entries)
    song = next(row for row in entries if row["song_id"] == job_id)
    assert song["source_kind"] == "notation"
    assert song["revision"] == 1

    notes = client.get(f"/api/songs/{job_id}/notes")
    assert notes.status_code == 200, notes.text
    note_ids = [item["note_id"] for item in notes.json()["notes"] if not item["rest"]]
    assert note_ids, "canonical score should include at least one editable note"
    note_id = note_ids[0]

    edit = client.patch(f"/api/songs/{job_id}/notes/{note_id}/structure", json={"lyric": "Draft"})
    assert edit.status_code == 200, edit.text
    assert songs.get(job_id)["revision"] == 2
    assert "Draft" in songs.score_xml(job_id)

    undo = client.post(f"/api/songs/{job_id}/undo")
    assert undo.status_code == 200, undo.text
    assert songs.get(job_id)["revision"] == 1
    assert "Draft" not in songs.score_xml(job_id)

    edited_again = client.patch(
        f"/api/songs/{job_id}/notes/{note_id}/structure",
        json={"lyric": "Final"},
    )
    assert edited_again.status_code == 200, edited_again.text
    assert "Final" in songs.score_xml(job_id)

    destination = root / "user-published"
    publish = client.post(
        f"/api/songs/{job_id}/export-to",
        json={
            "formats": ["musicxml", "midi", "pdf", "parts"],
            "destination_dir": str(destination),
        },
    )
    assert publish.status_code == 200, publish.text
    published = Path(publish.json()["destination"])
    assert published.parent == destination
    assert (published / "score.musicxml").is_file()
    assert "Final" in (published / "score.musicxml").read_text(encoding="utf-8")
    assert (published / "score.mid").read_bytes().startswith(b"MThd")
    assert (published / "score.pdf").read_bytes().startswith(b"%PDF")
    assert any(path.stat().st_size > 100 for path in (published / "parts").glob("*.pdf"))
    assert any((published / "parts").glob("*.musicxml"))
    assert songs.get(job_id)["revision"] == 2


def test_unsupported_notation_upload_does_not_create_a_song(product):
    client, jobs, songs, _root = product
    response = client.post(
        "/api/import/notation",
        files={"file": ("invalid.txt", b"not-a-score", "text/plain")},
    )
    assert response.status_code == 415
    assert jobs.list() == []
    assert songs.list() == []
