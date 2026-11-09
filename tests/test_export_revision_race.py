from __future__ import annotations

import errno
import json
import shutil
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from audio_score_tool import export_api_v2, notation_export_api, song_routes
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_mutation_lock import SongMutationSerializationMiddleware
from audio_score_tool.song_store_v2 import SongStoreV2

SCORE = """<score-partwise version="4.0"><work><work-title>Original</work-title></work>
<part-list><score-part id="P1"><part-name>Piano</part-name></score-part>
<score-part id="P2"><part-name>Guitar</part-name></score-part></part-list>
<part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
</measure></part><part id="P2"><measure number="1"><attributes><divisions>1</divisions></attributes>
<note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
</measure></part></score-partwise>"""


@pytest.fixture
def state(tmp_path: Path, monkeypatch):
    kwargs = {
        "path": tmp_path / "songs.sqlite3", "cache_root": tmp_path / "cache" / "scores",
        "asset_root": tmp_path / "assets", "export_root": tmp_path / "managed-exports",
    }
    songs = SongStoreV2(**kwargs)
    source = tmp_path / "Original.musicxml"
    source.write_text(SCORE, encoding="utf-8")
    songs.sync_completed_jobs([{
        "job_id": "song-1", "status": "done", "kind": "notation-import",
        "filename": "Original.musicxml", "result": {"musicxml": str(source)},
    }])
    publication = PublicationStoreV2(path=songs.path, legacy_root=tmp_path / "legacy")
    publication.write("song-1", {"composer": "Old composer"})
    # The automatic metadata worker uses a different Store instance and bypasses
    # HTTP serialization. Keep that real SQLite boundary in these regressions.
    worker = SongStoreV2(**kwargs)

    def require(song_id):
        song = songs.get(song_id)
        if song is None:
            raise HTTPException(404, "Song not found")
        return song

    for module in [notation_export_api, export_api_v2, song_routes]:
        monkeypatch.setattr(module, "_song_store", songs)
        monkeypatch.setattr(module, "_require_song", require)
    for module in [notation_export_api, song_routes]:
        monkeypatch.setattr(module, "_publication_store", publication)
    monkeypatch.setattr(notation_export_api, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(export_api_v2, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(notation_export_api, "backend_status", lambda _: {
        "music21": True, "verovio": True, "fpdf2": True,
    })
    monkeypatch.setattr(notation_export_api, "render_pdf", lambda _source, target, **_: (
        target.write_bytes(b"%PDF-1.4 complete snapshot"), "fixture",
    ))
    application = FastAPI()
    application.include_router(notation_export_api.router)
    application.include_router(export_api_v2.router)
    application.add_middleware(SongMutationSerializationMiddleware)
    return TestClient(application), songs, worker, publication, tmp_path


def _commit_metadata(worker: SongStoreV2, publication: PublicationStoreV2):
    return worker.commit_identified_metadata(
        "song-1", title="Fresh title", artist="Fresh artist",
        score_xml=SCORE.replace("Original", "Fresh title"),
        publication=publication.read("song-1"), expected_revision=1,
        next_publication={**publication.read("song-1"), "composer": "Fresh composer"},
    )


@pytest.mark.parametrize("endpoint", ["export", "export-to"])
@pytest.mark.parametrize("selected", [False, True])
def test_worker_metadata_commit_during_render_rejects_stale_publication(
    state, monkeypatch, endpoint: str, selected: bool,
):
    client, songs, worker, publication, root = state
    previous = songs.export_dir("song-1") / "score.pdf"
    previous.write_bytes(b"%PDF previous revision")
    rendered_xml = []

    def render_while_metadata_arrives(source, target, **_kwargs):
        rendered_xml.append(source.read_text())
        # A real commit must finish during rendering, proving no long-lived DB
        # writer lock is held for rendering. It also invalidates the old exports.
        assert _commit_metadata(worker, publication)["revision"] == 2
        target.write_bytes(b"%PDF obsolete render")

    monkeypatch.setattr(notation_export_api, "render_pdf", render_while_metadata_arrives)
    body = {"formats": ["musicxml", "pdf"], "expected_revision": 1}
    if selected:
        body["part_ids"] = ["P2"]
    if endpoint == "export-to":
        body["destination_dir"] = str(root / "published")
    response = client.post(f"/api/songs/song-1/{endpoint}", json=body)
    assert response.status_code == 409, response.text
    assert "Original" in rendered_xml[0] and "Old composer" in rendered_xml[0]
    assert "Fresh title" not in rendered_xml[0] and "Fresh composer" not in rendered_xml[0]
    assert songs.get("song-1")["revision"] == 2
    assert songs.get("song-1")["title"] == "Fresh title"
    assert "Fresh title" in songs.score_xml("song-1")
    assert publication.read("song-1")["composer"] == "Fresh composer"
    assert not (songs.export_root / "song-1").exists()
    if endpoint == "export-to":
        assert list((root / "published").iterdir()) == []


def test_snapshot_uses_atomic_latest_xml_metadata_and_publication(state, monkeypatch):
    client, songs, worker, publication, _root = state
    original_require = notation_export_api._require_song

    def require_then_worker_commits(song_id):
        old_row = original_require(song_id)
        _commit_metadata(worker, publication)
        return old_row

    monkeypatch.setattr(notation_export_api, "_require_song", require_then_worker_commits)
    response = client.post("/api/songs/song-1/export", json={"formats": ["musicxml"]})
    assert response.status_code == 200, response.text
    assert response.json()["export"]["revision"] == 2
    xml = ET.parse(songs.export_root / "song-1" / "score.musicxml").getroot()
    assert xml.findtext("work/work-title") == "Fresh title"
    assert xml.findtext("identification/creator[@type='composer']") == "Fresh composer"


def test_publication_change_without_revision_change_also_rejects_stale_render(state, monkeypatch):
    client, songs, _worker, publication, _root = state

    def render(source, target, **_kwargs):
        publication.write("song-1", {"composer": "Changed separately"})
        target.write_bytes(b"%PDF old publication")

    monkeypatch.setattr(notation_export_api, "render_pdf", render)
    response = client.post("/api/songs/song-1/export", json={"formats": ["pdf"]})
    assert response.status_code == 409, response.text
    assert songs.get("song-1")["revision"] == 1
    assert not (songs.export_root / "song-1").exists()


def test_worker_commit_during_desktop_copy_never_activates_partial_or_stale_files(state, monkeypatch):
    client, songs, worker, publication, root = state
    original_copy = shutil.copytree
    sources = []

    def copy_then_metadata(src, dst, *args, **kwargs):
        sources.append(Path(src))
        result = original_copy(src, dst, *args, **kwargs)
        assert not Path(src).is_relative_to(songs.export_root)
        _commit_metadata(worker, publication)
        return result

    monkeypatch.setattr(shutil, "copytree", copy_then_metadata)
    destination = root / "published"
    response = client.post("/api/songs/song-1/export-to", json={
        "formats": ["musicxml", "pdf"], "destination_dir": str(destination),
        "part_ids": ["P2"], "expected_revision": 1,
    })
    assert sources
    assert response.status_code == 409, response.text
    assert songs.get("song-1")["revision"] == 2
    assert list(destination.iterdir()) == []
    assert not (songs.export_root / "song-1").exists()


def test_explicit_cache_invalidation_during_copy_cannot_remove_immutable_copy_source(state, monkeypatch):
    client, songs, worker, _publication, root = state
    original_copy = shutil.copytree
    previous = songs.export_dir("song-1") / "score.pdf"
    previous.write_bytes(b"%PDF prior")

    def copy_while_cache_is_cleared(src, dst, *args, **kwargs):
        worker.clear_exports("song-1")
        assert Path(src).is_dir()
        return original_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", copy_while_cache_is_cleared)
    response = client.post("/api/songs/song-1/export-to", json={
        "formats": ["musicxml", "pdf"], "destination_dir": str(root / "published"),
        "expected_revision": 1,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    destination = Path(data["destination"])
    assert (destination / "score.pdf").read_bytes() == b"%PDF-1.4 complete snapshot"
    assert (destination / "score.musicxml").is_file()
    assert json.loads((destination / ".export.json").read_text()) == data["export"]


def test_final_activation_guard_serializes_a_different_store_writer(state, monkeypatch):
    client, songs, worker, publication, root = state
    publishing = notation_export_api._publish_export_tree
    attempted = threading.Event()
    finished = threading.Event()
    errors = []
    threads = []

    def metadata_worker():
        attempted.set()
        try:
            _commit_metadata(worker, publication)
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    def publish_with_contending_worker(*args, **kwargs):
        thread = threading.Thread(target=metadata_worker, daemon=True)
        threads.append(thread)
        thread.start()
        assert attempted.wait(2)
        assert not finished.wait(0.05), "metadata writer crossed the final activation guard"
        return publishing(*args, **kwargs)

    monkeypatch.setattr(notation_export_api, "_publish_export_tree", publish_with_contending_worker)
    response = client.post("/api/songs/song-1/export-to", json={
        "formats": ["musicxml", "pdf"], "destination_dir": str(root / "published"),
        "expected_revision": 1,
    })
    assert response.status_code == 200, response.text
    assert finished.wait(3)
    for thread in threads:
        thread.join(timeout=1)
    assert not errors
    assert songs.get("song-1")["revision"] == 2
    # The export was fully activated while revision 1 was current; the later
    # worker retires only the app-owned cache, not the completed desktop copy.
    destination = Path(response.json()["destination"])
    assert response.json()["export"]["revision"] == 1
    assert (destination / "score.pdf").is_file()
    assert "Original" in (destination / "score.musicxml").read_text()
    assert not (songs.export_root / "song-1").exists()


def test_cache_publish_failure_removes_desktop_copy_and_preserves_previous_export(state, monkeypatch):
    client, songs, _worker, _publication, root = state
    previous = songs.export_dir("song-1") / "score.pdf"
    previous.write_bytes(b"%PDF previous")

    def fail_publish(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "injected full disk")

    monkeypatch.setattr(notation_export_api, "_publish_export_tree", fail_publish)
    response = client.post("/api/songs/song-1/export-to", json={
        "formats": ["musicxml", "pdf"], "destination_dir": str(root / "published"),
    })
    assert response.status_code == 507, response.text
    assert previous.read_bytes() == b"%PDF previous"
    assert list((root / "published").iterdir()) == []


def test_destination_inside_managed_exports_is_rejected(state):
    client, songs, _worker, _publication, _root = state
    response = client.post("/api/songs/song-1/export-to", json={
        "formats": ["musicxml"], "destination_dir": str(songs.export_root / "song-1"),
    })
    assert response.status_code == 422


def test_viewer_reads_exact_pdf_after_worker_invalidates_original_export(state, monkeypatch):
    client, songs, worker, publication, root = state
    generated = client.post("/api/songs/song-1/export", json={
        "formats": ["pdf"], "part_ids": ["P2"], "expected_revision": 1,
    })
    assert generated.status_code == 200, generated.text
    receipt = generated.json()["export"]
    original = songs.export_root / "song-1" / "selection" / "selected-score.pdf"
    expected = original.read_bytes()
    opened = []

    def launch_then_read_after_metadata(path):
        # This synchronous write also proves native launch is outside the SQL
        # writer guard. The viewer opens its path only after invalidation.
        _commit_metadata(worker, publication)
        assert not original.exists()
        assert path.is_relative_to(root / "cache" / "pdf-viewer")
        assert path.read_bytes() == expected
        opened.append(path)

    monkeypatch.setattr(export_api_v2, "open_pdf_document", launch_then_read_after_metadata)
    response = client.post("/api/songs/song-1/export/open-pdf", json={
        "scope": receipt["scope"], "export_id": receipt["export_id"], "expected_revision": 1,
    })
    assert response.status_code == 200, response.text
    assert len(opened) == 1 and opened[0].read_bytes() == expected
    assert songs.get("song-1")["revision"] == 2


def test_viewer_copy_failure_never_launches_native_viewer(state, monkeypatch):
    client, songs, _worker, _publication, root = state
    generated = client.post("/api/songs/song-1/export", json={"formats": ["pdf"]})
    receipt = generated.json()["export"]
    opened = []

    def fail_copy(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "injected viewer cache full")

    monkeypatch.setattr(shutil, "copyfile", fail_copy)
    monkeypatch.setattr(export_api_v2, "open_pdf_document", lambda path: opened.append(path))
    response = client.post("/api/songs/song-1/export/open-pdf", json={
        "scope": "full", "export_id": receipt["export_id"], "expected_revision": 1,
    })
    assert response.status_code == 507, response.text
    assert not opened
    assert (songs.export_root / "song-1" / "score.pdf").is_file()
    assert list((root / "cache" / "pdf-viewer").iterdir()) == []


def test_export_guard_does_not_recheckout_or_reparse_canonical_score(state, monkeypatch):
    client, songs, _worker, _publication, _root = state

    def reject_checkout(*_args, **_kwargs):
        pytest.fail("export response rechecked out canonical XML inside its writer guard")

    monkeypatch.setattr(songs, "checkout_current", reject_checkout)
    response = client.post("/api/songs/song-1/export", json={"formats": ["musicxml"]})
    assert response.status_code == 200, response.text
    assert response.json()["parts"] == response.json()["song"]["parts"]
    assert [part["part_id"] for part in response.json()["parts"]] == ["P1", "P2"]
