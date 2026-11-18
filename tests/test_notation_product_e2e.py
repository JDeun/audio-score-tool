"""Real API + filesystem flow without invoking AI models."""
from __future__ import annotations

import xml.etree.ElementTree as ET
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
    publication_api_v2,
    revision_api_v2,
    song_delete_api,
    song_routes,
)
from audio_score_tool.api import app
from audio_score_tool.benchmark_edit_telemetry import read_edit_session, start_edit_session
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


def test_note_edit_rejects_stale_revision_and_score_hash(product):
    client, _, songs, _ = product
    uploaded = client.post("/api/import/notation", files={
        "file": ("fixture.musicxml", SCORE_XML.encode(), "application/vnd.recordare.musicxml+xml")})
    song_id = uploaded.json()["job_id"]
    notes = client.get(f"/api/songs/{song_id}/notes").json()
    note_id = notes["notes"][0]["note_id"]
    path = f"/api/songs/{song_id}/notes/{note_id}/structure"
    payload = {"step": "D", "expected_revision": notes["song"]["revision"],
               "expected_score_sha256": notes["score_sha256"]}
    assert client.patch(path, json={**payload, "expected_revision": 99}).status_code == 409
    assert client.patch(path, json={**payload, "expected_score_sha256": "0" * 64}).status_code == 409
    assert songs.get(song_id)["revision"] == notes["song"]["revision"]
    changed_layout = songs.checkout_current(song_id)
    changed_layout.write_text(changed_layout.read_text().replace("Owned fixture", "Layout changed"))
    songs.replace_current_from_path(song_id, changed_layout)
    assert client.patch(path, json=payload).status_code == 409
    notes = client.get(f"/api/songs/{song_id}/notes").json()
    payload["expected_score_sha256"] = notes["score_sha256"]
    assert client.patch(path, json=payload).status_code == 200
    assert client.patch(path, json=payload).status_code == 409


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
    monkeypatch.setattr(song_delete_api, "_song_store", songs)
    monkeypatch.setattr(song_delete_api, "_tombstones", tombstones)
    monkeypatch.setattr(notation_export_api, "_song_store", songs)
    monkeypatch.setattr(notation_export_api, "_publication_store", publication)
    monkeypatch.setattr(notation_export_api, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(export_api_v2, "_song_store", songs)
    monkeypatch.setattr(export_api_v2, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(revision_api_v2, "_song_store", songs)
    monkeypatch.setattr(credits_api, "_song_store", songs)
    monkeypatch.setattr(credits_api, "_publication_store", publication)
    monkeypatch.setattr(publication_api_v2, "_song_store", songs)
    monkeypatch.setattr(publication_api_v2, "_publication_store", publication)

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

    # V2 does not write a legacy export flag: list/detail derive availability
    # from the successfully published canonical managed export tree.
    final_status = client.get(f"/api/songs/{job_id}")
    assert final_status.status_code == 200
    assert final_status.json()["exports"] == {
        "musicxml": True, "pdf": True, "midi": True,
    }


def test_unsupported_notation_upload_does_not_create_a_song(product):
    client, jobs, songs, _root = product
    response = client.post(
        "/api/import/notation",
        files={"file": ("invalid.txt", b"not-a-score", "text/plain")},
    )
    assert response.status_code == 415
    assert jobs.list() == []
    assert songs.list() == []


def _import_ensemble(product):
    client, _jobs, songs, _root = product
    header = []
    bodies = []
    for index, (name, step, program) in enumerate(
        [("Voice", "C", 54), ("Guitar", "E", 25), ("Bass", "G", 34)], start=1,
    ):
        header.append(
            f'<score-part id="P{index}"><part-name>{name}</part-name>'
            f'<score-instrument id="I{index}"><instrument-name>{name}</instrument-name>'
            f'</score-instrument><midi-instrument id="I{index}">'
            f'<midi-channel>{index}</midi-channel><midi-program>{program}</midi-program>'
            '</midi-instrument></score-part>'
        )
        tempo = '<direction><sound tempo="90"/></direction>' if index == 1 else ''
        bodies.append(
            f'<part id="P{index}"><measure number="1"><attributes><divisions>480</divisions>'
            '<time><beats>4</beats><beat-type>4</beat-type></time>'
            '<clef><sign>G</sign><line>2</line></clef></attributes>'
            f'{tempo}<note><pitch><step>{step}</step><octave>4</octave></pitch>'
            '<duration>1920</duration><type>whole</type></note></measure></part>'
        )
    xml = ('<score-partwise version="4.0"><work><work-title>Owned ensemble</work-title></work>'
           '<part-list>' + ''.join(header) + '</part-list>' + ''.join(bodies) + '</score-partwise>')
    response = client.post(
        '/api/import/notation',
        files={'file': ('ensemble.musicxml', xml.encode(), 'application/xml')},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()['job_id']
    assert client.get(f'/api/songs/{job_id}').status_code == 200
    return job_id, songs.score_xml(job_id)


def test_selected_parts_publish_real_bundle_preserving_full_score_and_telemetry(product, monkeypatch):
    client, _jobs, songs, root = product
    song_id, original_xml = _import_ensemble(product)
    all_formats = ['musicxml', 'pdf', 'midi', 'parts']
    destination = root / 'published'
    full = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': all_formats, 'destination_dir': str(destination), 'expected_revision': 1,
    })
    assert full.status_code == 200, full.text
    full_tree = songs.export_root / song_id
    full_bytes = {path.relative_to(full_tree): path.read_bytes()
                  for path in full_tree.rglob('*') if path.is_file()}

    telemetry = root / 'selected.product.json'
    start_edit_session(telemetry, case_id='owned-ensemble', song_id=song_id)
    monkeypatch.setenv('AST_TIER2_TELEMETRY_FILE', str(telemetry))
    selected = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': all_formats, 'destination_dir': str(destination),
        'expected_revision': 1, 'part_ids': ['P3', 'P2'],
    })
    assert selected.status_code == 200, selected.text
    result = selected.json()
    assert result['export']['scope'] == 'selection'
    assert result['export']['part_ids'] == ['P2', 'P3']
    assert result['export']['revision'] == 1
    published = Path(result['destination'])
    assert '선택 파트' in published.name
    assert published != Path(full.json()['destination'])
    selected_xml = published / 'selected-score.musicxml'
    assert [part.get('id') for part in ET.parse(selected_xml).getroot().findall('part')] == ['P2', 'P3']
    assert (published / 'selected-score.pdf').read_bytes().startswith(b'%PDF')
    midi = MidiFile(published / 'selected-score.mid')
    assert sorted(message.note for track in midi.tracks for message in track
                  if message.type == 'note_on' and message.velocity > 0) == [64, 67]
    assert len(list((published / 'parts').glob('*.pdf'))) == 2
    assert len(list((published / 'parts').glob('*.musicxml'))) == 2
    assert not (published / 'score.pdf').exists()
    assert songs.score_xml(song_id) == original_xml
    assert songs.get(song_id)['revision'] == 1
    assert {path: (full_tree / path).read_bytes() for path in full_bytes} == full_bytes
    assert read_edit_session(telemetry)['successful_export'] is False
    assert read_edit_session(telemetry)['time_to_publish_seconds'] is None


@pytest.mark.parametrize('part_ids', [[], ['P1', 'P1'], ['missing'], [''], ['P1', 'missing']])
def test_invalid_selected_parts_cannot_publish_or_replace_prior_export(product, part_ids):
    client, _jobs, songs, root = product
    song_id, original_xml = _import_ensemble(product)
    prior = client.post(f'/api/songs/{song_id}/export', json={'formats': ['musicxml']})
    assert prior.status_code == 200, prior.text
    prior_path = songs.export_root / song_id / 'score.musicxml'
    before = prior_path.read_bytes()
    response = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': ['musicxml'], 'destination_dir': str(root / 'published'),
        'part_ids': part_ids, 'expected_revision': 1,
    })
    assert response.status_code == 422, response.text
    assert prior_path.read_bytes() == before
    assert songs.score_xml(song_id) == original_xml
    assert not (songs.export_root / song_id / 'selection').exists()


def test_selection_only_does_not_advertise_full_exports_and_stale_revision_is_rejected(product):
    client, _jobs, songs, root = product
    song_id, _xml = _import_ensemble(product)
    request = {'formats': ['musicxml'], 'destination_dir': str(root / 'published'),
               'part_ids': ['P2'], 'expected_revision': 2}
    stale = client.post(f'/api/songs/{song_id}/export-to', json=request)
    assert stale.status_code == 409
    request['expected_revision'] = 1
    result = client.post(f'/api/songs/{song_id}/export-to', json=request)
    assert result.status_code == 200, result.text
    assert result.json()['song']['exports'] == {'musicxml': False, 'pdf': False, 'midi': False}
    assert songs.get(song_id)['exports'] == {}


def test_failed_selected_pdf_preserves_previous_selection_and_canonical_score(product, monkeypatch):
    from audio_score_tool.notation_backend import NotationBackendError

    client, _jobs, songs, root = product
    song_id, original_xml = _import_ensemble(product)
    first = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': ['musicxml'], 'destination_dir': str(root / 'published'), 'part_ids': ['P1'],
    })
    assert first.status_code == 200, first.text
    selection = songs.export_root / song_id / 'selection'
    before = {path.name: path.read_bytes() for path in selection.iterdir()}

    def fail_pdf(*_args, **_kwargs):
        raise NotationBackendError('injected renderer failure')

    monkeypatch.setattr(notation_export_api, 'render_pdf', fail_pdf)
    failed = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': ['musicxml', 'pdf'], 'destination_dir': str(root / 'published'),
        'part_ids': ['P2'], 'expected_revision': 1,
    })
    assert failed.status_code == 500
    assert {path.name: path.read_bytes() for path in selection.iterdir()} == before
    assert songs.score_xml(song_id) == original_xml


def test_print_opens_exact_generated_pdf_and_rejects_changed_or_missing_output(product, monkeypatch):
    client, _jobs, songs, root = product
    song_id, _xml = _import_ensemble(product)
    selected = client.post(f'/api/songs/{song_id}/export-to', json={
        'formats': ['pdf'], 'destination_dir': str(root / 'published'), 'part_ids': ['P2'],
    })
    assert selected.status_code == 200, selected.text
    receipt = selected.json()['export']
    opened = []
    monkeypatch.setattr(export_api_v2, 'open_pdf_document', lambda path: opened.append(path))
    payload = {'scope': 'selection', 'export_id': receipt['export_id'], 'expected_revision': 1}
    response = client.post(f'/api/songs/{song_id}/export/open-pdf', json=payload)
    assert response.status_code == 200
    original_pdf = songs.export_root / song_id / 'selection' / 'selected-score.pdf'
    assert len(opened) == 1
    assert opened[0].is_relative_to(root / 'cache' / 'pdf-viewer')
    assert opened[0].name == 'selected-score.pdf'
    assert opened[0].read_bytes() == original_pdf.read_bytes()
    assert client.post(f'/api/songs/{song_id}/export/open-pdf', json={
        **payload, 'export_id': 'previous-export',
    }).status_code == 409
    assert client.post(f'/api/songs/{song_id}/export/open-pdf', json={
        **payload, 'expected_revision': 2,
    }).status_code == 409
    assert client.post(f'/api/songs/{song_id}/export/open-pdf', json={
        **payload, 'scope': '../selection',
    }).status_code == 422
    (songs.export_root / song_id / 'selection' / 'selected-score.pdf').unlink()
    assert client.post(f'/api/songs/{song_id}/export/open-pdf', json=payload).status_code == 404
    assert len(opened) == 1


def test_unchanged_rest_chord_preserves_revision_exports_and_telemetry(product, monkeypatch):
    client, _jobs, songs, root = product
    xml = SCORE_XML.replace(
        '<note><pitch><step>C</step><octave>4</octave></pitch>\n      <duration>1920</duration><type>whole</type></note>',
        '<harmony><root><root-step>C</root-step></root><kind>major</kind></harmony>'
        '<note><rest/><duration>960</duration><type>half</type></note>'
        '<note><rest/><duration>960</duration><type>half</type></note>',
    )
    assert '<rest/>' in xml
    response = client.post('/api/import/notation', files={'file': ('rest.musicxml', xml.encode(), 'application/xml')})
    assert response.status_code == 202, response.text
    song_id = response.json()['job_id']
    assert client.get(f'/api/songs/{song_id}').status_code == 200
    notes = client.get(f'/api/songs/{song_id}/notes').json()
    anchor = notes['chords'][0]['note_id']
    empty = next(note['note_id'] for note in notes['notes'] if note['note_id'] != anchor)
    assert all(note['rest'] for note in notes['notes'])
    exported = client.post(f'/api/songs/{song_id}/export', json={'formats': ['musicxml']})
    assert exported.status_code == 200, exported.text
    export_path = songs.export_root / song_id / 'score.musicxml'
    before_export, before_xml = export_path.read_bytes(), songs.score_xml(song_id)
    telemetry = root / 'chord-telemetry.json'
    start_edit_session(telemetry, case_id='chord', song_id=song_id)
    monkeypatch.setenv('AST_TIER2_TELEMETRY_FILE', str(telemetry))
    for note_id, symbol in ((anchor, ' C '), (empty, '')):
        result = client.patch(f'/api/songs/{song_id}/notes/{note_id}/chord', json={'symbol': symbol})
        assert result.status_code == 200, result.text
        assert result.json()['song']['revision'] == 1
        assert songs.score_xml(song_id) == before_xml
        assert export_path.read_bytes() == before_export
        with songs._connect() as conn:
            assert conn.execute('SELECT count(*) FROM song_revisions WHERE song_id=?', (song_id,)).fetchone()[0] == 0
    assert read_edit_session(telemetry)['total_edit_actions'] == 0
    assert read_edit_session(telemetry)['manual_chord_edits'] == 0
    edit = client.patch(f'/api/songs/{song_id}/notes/{anchor}/chord', json={'symbol': 'Am7'})
    assert edit.status_code == 200, edit.text
    assert songs.get(song_id)['revision'] == 2
    assert songs.score_xml(song_id) != before_xml
    assert not export_path.exists()
    with songs._connect() as conn:
        assert conn.execute('SELECT count(*) FROM song_revisions WHERE song_id=?', (song_id,)).fetchone()[0] == 1
    assert read_edit_session(telemetry)['manual_chord_edits'] == 1
    assert read_edit_session(telemetry)['total_edit_actions'] == 1


def test_direct_export_initializes_single_staff_layout_and_preserves_explicit_setting(product):
    client, jobs, songs, _root = product
    response = client.post('/api/import/notation', files={
        'file': ('owned.musicxml', SCORE_XML.replace('<note><pitch>',
            '<harmony><root><root-step>C</root-step></root><kind>major</kind></harmony>'
            '<note><pitch>', 1).encode(), 'application/vnd.recordare.musicxml+xml')})
    assert response.status_code == 202
    song_id = response.json()['job_id']
    assert jobs.get(song_id)['status'] == 'done'
    # Export is the first Song request and therefore initializes publication.
    result = client.post(f'/api/songs/{song_id}/export', json={'formats': ['musicxml', 'midi'],
                                                               'expected_revision': 1})
    assert result.status_code == 200, result.text
    assert song_routes._publication_store.read(song_id)['systems_per_page'] == 8
    assert songs.get(song_id)['revision'] == 1
    xml = ET.fromstring(songs.score_xml(song_id))
    assert xml.findtext('./part/measure/note/pitch/step') == 'C'
    assert xml.findtext('./part/measure/note/duration') == '1920'
    assert xml.findtext('./part/measure/harmony/root/root-step') == 'C'
    result = client.patch(f'/api/songs/{song_id}/publication', json={'systems_per_page': 5})
    assert result.status_code == 200, result.text
    revision = songs.get(song_id)['revision']
    result = client.post(f'/api/songs/{song_id}/export', json={'formats': ['musicxml'],
                                                               'expected_revision': revision})
    assert result.status_code == 200, result.text
    assert song_routes._publication_store.read(song_id)['systems_per_page'] == 5
    assert songs.get(song_id)['revision'] == revision
    stale = client.post(f'/api/songs/{song_id}/export', json={'formats': ['musicxml'],
                                                              'expected_revision': revision - 1})
    assert stale.status_code == 409


def test_initial_layout_cannot_overwrite_concurrent_publication_edit(product, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    client, jobs, songs, _root = product
    response = client.post('/api/import/notation', files={
        'file': ('owned.musicxml', SCORE_XML.encode(), 'application/vnd.recordare.musicxml+xml')})
    assert response.status_code == 202
    song_id = response.json()['job_id']
    assert jobs.get(song_id)['status'] == 'done'
    reached, release, first = Event(), Event(), Lock()
    original = song_routes.initial_publication_settings

    def paused(path):
        if first.acquire(blocking=False):
            reached.set()
            assert release.wait(10)
        return original(path)

    monkeypatch.setattr(song_routes, 'initial_publication_settings', paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.get, '/api/songs')
        assert reached.wait(10)
        try:
            changed = client.patch(f'/api/songs/{song_id}/publication', json={
                'systems_per_page': 3, 'subtitle': 'owned-title'})
            assert changed.status_code == 200, changed.text
        finally:
            release.set()
        assert pending.result(timeout=10).status_code == 200
    assert songs.get(song_id)['revision'] == 2
    settings = song_routes._publication_store.read(song_id)
    assert (settings['systems_per_page'], settings['subtitle']) == (3, 'owned-title')
    assert 'owned-title' in songs.score_xml(song_id)


def test_initial_publication_rejects_stale_xml_even_if_revision_is_same(product):
    import sqlite3

    client, _jobs, songs, _root = product
    response = client.post('/api/import/notation', files={
        'file': ('owned.musicxml', SCORE_XML.encode(), 'application/vnd.recordare.musicxml+xml')})
    song_id = response.json()['job_id']
    client.get('/api/songs')
    with sqlite3.connect(songs.path) as conn:
        conn.execute('DELETE FROM publication_settings WHERE song_id=?', (song_id,))
    snapshot = songs.export_snapshot(song_id)
    existing_export = songs.export_dir(song_id) / 'score.pdf'
    existing_export.write_bytes(b'previous export')
    updated = snapshot.current_score_xml.replace('<step>C</step>', '<step>D</step>')
    assert updated != snapshot.current_score_xml
    with sqlite3.connect(songs.path) as conn:
        conn.execute('UPDATE songs SET current_score_xml=? WHERE song_id=?', (updated, song_id))
    assert not songs.initialize_publication(snapshot, {'systems_per_page': 8}, snapshot.current_score_xml)
    assert songs.score_xml(song_id) == updated
    assert existing_export.read_bytes() == b'previous export'
    assert not song_routes._publication_store.exists(song_id)


def test_initial_layout_preserves_legacy_publication_settings(product):
    import json

    client, _jobs, songs, _root = product
    response = client.post('/api/import/notation', files={
        'file': ('owned.musicxml', SCORE_XML.encode(), 'application/vnd.recordare.musicxml+xml')})
    song_id = response.json()['job_id']
    legacy = song_routes._publication_store.legacy_root / song_id / 'publication.json'
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({'systems_per_page': 5, 'subtitle': 'legacy'}))
    assert client.get('/api/songs').status_code == 200
    assert song_routes._publication_store.read(song_id)['systems_per_page'] == 5
    assert song_routes._publication_store.read(song_id)['subtitle'] == 'legacy'
    assert songs.get(song_id)['revision'] == 1


def test_initial_layout_retires_exports_only_after_success(product):
    import copy
    import sqlite3

    client, _jobs, songs, _root = product
    score = ET.fromstring(SCORE_XML)
    part = score.find('part')
    first = part.find('measure')
    for number in range(2, 41):
        measure = copy.deepcopy(first)
        measure.set('number', str(number))
        measure.remove(measure.find('attributes'))
        part.append(measure)
    response = client.post('/api/import/notation', files={
        'file': ('owned.musicxml', ET.tostring(score), 'application/vnd.recordare.musicxml+xml')})
    song_id = response.json()['job_id']
    with sqlite3.connect(songs.path) as conn:
        conn.execute("CREATE TRIGGER reject_initial_layout BEFORE UPDATE OF current_score_xml ON songs "
                     "BEGIN SELECT RAISE(ABORT, 'layout fail'); END")
    result = client.post(f'/api/songs/{song_id}/export', json={
        'formats': ['musicxml', 'pdf'], 'expected_revision': 1})
    assert result.status_code == 200, result.text
    export = songs.export_root / song_id
    old_xml = (export / 'score.musicxml').read_bytes()
    old_pdf = (export / 'score.pdf').read_bytes()
    assert not song_routes._publication_store.exists(song_id)
    assert ET.fromstring(old_xml).find('./part/measure[@number="21"]/print').get('new-page') == 'yes'
    # A failed retry must leave the existing export intact.
    assert client.get(f'/api/songs/{song_id}').status_code == 200
    assert (export / 'score.musicxml').read_bytes() == old_xml
    assert (export / 'score.pdf').read_bytes() == old_pdf
    with sqlite3.connect(songs.path) as conn:
        conn.execute('DROP TRIGGER reject_initial_layout')
    detail = client.get(f'/api/songs/{song_id}')
    assert detail.status_code == 200
    assert detail.json()['revision'] == 1
    assert not any(detail.json()['exports'].values())
    assert song_routes._publication_store.read(song_id)['systems_per_page'] == 8
    assert client.get(f'/api/songs/{song_id}/files/pdf').status_code == 404
    current = client.get(f'/api/songs/{song_id}/files/musicxml')
    assert current.status_code == 200
    assert ET.fromstring(current.content).find('./part/measure[@number="33"]/print').get('new-page') == 'yes'
    assert not export.exists()
    result = client.post(f'/api/songs/{song_id}/export', json={
        'formats': ['musicxml', 'pdf'], 'expected_revision': 1})
    assert result.status_code == 200, result.text
    assert ET.parse(export / 'score.musicxml').find('./part/measure[@number="33"]/print').get('new-page') == 'yes'
    assert (export / 'score.pdf').read_bytes().startswith(b'%PDF')


def _retained_vocal_fixture(product):
    import hashlib
    import json
    import wave

    client, _, songs, _ = product
    xml = '''<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
    <part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>1</beats><beat-type>4</beat-type></time></attributes>
    <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type><sound tempo="120"/></direction>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><tie type="start"/><type>quarter</type><notations><tied type="start"/></notations></note></measure>
    <measure number="2"><harmony><root><root-step>C</root-step></root><kind>major</kind></harmony><note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><tie type="stop"/><type>quarter</type><notations><tied type="stop"/></notations></note>
    <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>60</per-minute></metronome></direction-type><sound tempo="60"/></direction>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note></measure></part></score-partwise>'''
    response = client.post("/api/import/notation", files={"file": (
        "fixture.musicxml", xml.encode(), "application/vnd.recordare.musicxml+xml")})
    assert response.status_code == 202
    song_id = response.json()["job_id"]
    client.get(f"/api/songs/{song_id}/notes")
    root = songs.asset_root / song_id / "model-evidence"
    (root / "vocal").mkdir(parents=True)
    midi = MidiFile(ticks_per_beat=480)
    track = MidiTrack([
        MetaMessage("set_tempo", tempo=500000, time=0),
        Message("note_on", note=60, velocity=80, time=0),
        Message("note_off", note=60, velocity=0, time=960),
        MetaMessage("set_tempo", tempo=1000000, time=0),
        Message("note_on", note=60, velocity=80, time=0),
        Message("note_off", note=60, velocity=0, time=480),
    ])
    midi.tracks.append(track)
    midi.save(root / "vocal/selected.mid")
    (root / "score.musicxml").write_text(xml)
    (root / "interpretation.json").write_text(json.dumps({
        "algorithm": "dominant_overlap_on_audio_sixteenth_grid_v1",
        "grid_audio_seconds": [0, .5, 1, 2], "source_note_indices": [0, 0, 1]}))
    audio = root.parent / "original-audio.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 16000)
    audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    (root / "beat.npz").write_bytes(b"owned beat fixture")
    beat_sha = hashlib.sha256((root / "beat.npz").read_bytes()).hexdigest()
    clock = {"source_sha256": audio_sha, "prediction_sha256": beat_sha}
    (root / "beat.runtime.json").write_text(json.dumps({**clock, "source_frames": 16000,
                                                       "source_sample_rate": 8000}))
    (root / "context").mkdir()
    (root / "native").mkdir()
    (root / "context/music_structure.json").write_text('{"trimmed":false,"media_start_seconds":0}')
    (root / "native/playback.json").write_text('{"duration":2}')
    (root / "recipe.json").write_text(json.dumps({"recipe_version": 3,
        "engine": "vocal_lead_v1", "status": "completed", "source_audio_sha256": audio_sha,
        "model_audio_sha256": audio_sha, "model_audio_normalized": False, "beat_clock": clock}))
    files = []
    for name in ("score.musicxml", "vocal/selected.mid", "interpretation.json", "recipe.json",
                 "beat.npz", "beat.runtime.json", "context/music_structure.json", "native/playback.json"):
        data = (root / name).read_bytes()
        files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (root / "manifest.json").write_text(json.dumps({"schema_version": 1, "job_id": song_id,
        "selection": {"transcription_engine": "vocal_lead_v1"}, "source_audio_sha256": audio_sha,
        "files": files}))
    from audio_score_tool.note_evidence import baseline, baseline_fingerprint, score_hash

    links, rows, clock, manifest_hash = baseline(songs.asset_root, song_id)
    fingerprint = baseline_fingerprint(links, rows, clock, manifest_hash)
    with songs._connect() as conn:
        conn.execute("""UPDATE note_evidence_state SET active=1, revision=1,
            score_sha256=?, baseline_sha256=? WHERE song_id=?""",
            (score_hash(songs.score_xml(song_id)), fingerprint, song_id))
    return client, songs, song_id, root


def _evidence_get(client, base, note_id, *, revision=None, score_sha256=None, generation=None):
    notes = client.get(base + "/notes").json()
    return client.get(base + f"/notes/{note_id}/evidence", params={
        "expected_revision": revision if revision is not None else notes["song"]["revision"],
        "expected_score_sha256": score_sha256 or notes["score_sha256"],
        "expected_generation": generation if generation is not None else notes["evidence_generation"]})


def test_vocal_note_evidence_edit_undo_and_branch(product):
    client, songs, song_id, root = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    notes = client.get(base + "/notes").json()
    evidence = _evidence_get(client, base, "p0-m0-n0").json()
    assert evidence["status"] == "linked", evidence
    assert evidence["evidence"]["source_audio_seek_seconds"] == 0
    assert evidence["evidence"]["source_audio_seek_basis"] == "interpreted_grid"
    assert evidence["evidence"]["locators"] == ["p0-m0-n0", "p0-m1-n0"]
    assert evidence["evidence"]["grid_seconds"] == {"start": 0, "end": 1}
    second = _evidence_get(client, base, "p0-m1-n1").json()
    assert second["status"] == "linked", second
    assert second["evidence"]["grid_seconds"] == {"start": 1, "end": 2}
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    patch = {"step": "D", "expected_revision": 1, "expected_score_sha256": notes["score_sha256"]}
    assert client.patch(base + "/notes/p0-m1-n1/structure", json=patch).status_code == 200
    edited = _evidence_get(client, base, "p0-m1-n1").json()
    assert edited["status"] == "linked", edited
    assert edited["evidence"] == second["evidence"]
    assert edited["patch"]["before_sha256"] == notes["score_sha256"]
    assert edited["patch"]["after_sha256"] == edited["score_sha256"]
    assert edited["patch"]["after_generation"] == edited["patch"]["before_generation"] + 1
    assert edited["patch"]["reason"] == "manual_pitch_edit"
    next_notes = client.get(base + "/notes").json()
    assert client.patch(base + "/notes/p0-m1-n1/structure", json={
        "step": "E", "expected_revision": 2,
        "expected_score_sha256": next_notes["score_sha256"]}).status_code == 200
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "linked"
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == before
    assert _evidence_get(client, base, "p0-m0-n0", revision=1).status_code == 409
    assert client.post(base + "/undo").status_code == 200
    assert client.post(base + "/undo").status_code == 200
    assert _evidence_get(client, base, "p0-m0-n0").json()["status"] == "unavailable"
    assert client.post(base + "/notes/p0-m1-n1/insert", json={"position": "before"}).status_code == 200
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches WHERE song_id=?", (song_id,)).fetchone()[0] == 2
    assert client.delete(base).status_code == 200
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches WHERE song_id=?", (song_id,)).fetchone()[0] == 0


def test_untracked_pitch_edit_does_not_carry_evidence(product):
    client, _, song_id, _ = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    assert client.patch(base + "/notes/p0-m1-n1/structure", json={"step": "D"}).status_code == 200
    result = _evidence_get(client, base, "p0-m1-n1").json()
    assert result["status"] == "unavailable" and result["reason"] == "lineage_unavailable"


def test_vocal_note_evidence_patch_rollback(product):
    client, songs, song_id, _ = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    notes = client.get(base + "/notes").json()
    before = songs.score_xml(song_id)
    _, before_state = songs.evidence_snapshot(song_id)
    exports = songs.export_dir(song_id)
    contents = {name: f"owned fixture {name}".encode() for name in
                ("score.musicxml", "score.mid", "score.pdf", "receipt.json")}
    for name, data in contents.items():
        (exports / name).write_bytes(data)
    external = product[3] / "external-copy.musicxml"
    external.write_bytes(b"external fixture")
    advertised = songs.get(song_id)["exports"]
    with songs._connect() as conn:
        conn.execute("CREATE TRIGGER fail_evidence BEFORE INSERT ON note_evidence_patches "
                     "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
    response = client.patch(base + "/notes/p0-m1-n1/structure", json={
        "step": "D", "expected_revision": notes["song"]["revision"],
        "expected_score_sha256": notes["score_sha256"]})
    assert response.status_code == 422
    assert songs.score_xml(song_id) == before
    assert songs.get(song_id)["revision"] == notes["song"]["revision"]
    assert songs.evidence_snapshot(song_id)[1] == before_state
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "linked"
    assert songs.get(song_id)["exports"] == advertised
    assert {name: (exports / name).read_bytes() for name in contents} == contents
    assert external.read_bytes() == b"external fixture"
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches").fetchone()[0] == 0


def test_vocal_note_evidence_invalid_and_legacy_are_unavailable(product):
    import hashlib
    import json

    client, _, song_id, root = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    interpretation_path = root / "interpretation.json"
    interpretation = json.loads(interpretation_path.read_text())
    interpretation["algorithm"] = "unknown_version"
    interpretation_path.write_text(json.dumps(interpretation))
    entry = next(entry for entry in manifest["files"] if entry["path"] == "interpretation.json")
    data = interpretation_path.read_bytes()
    entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    result = _evidence_get(client, base, "p0-m1-n1").json()
    assert result["status"] == "unavailable" and result["reason"] == "unsupported_interpretation"
    interpretation_path.write_text("malformed")
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"
    manifest_path.unlink()
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"
    response = client.post("/api/import/notation", files={"file": (
        "legacy.musicxml", SCORE_XML.encode(), "application/vnd.recordare.musicxml+xml")})
    legacy_id = response.json()["job_id"]
    legacy = _evidence_get(client, f"/api/songs/{legacy_id}", "p0-m0-n0").json()
    assert legacy["status"] == "unavailable" and legacy["reason"] == "lineage_unavailable"


def test_vocal_note_evidence_ambiguous_score_abstains(product):
    import hashlib
    import json

    client, songs, song_id, root = _retained_vocal_fixture(product)
    score_path = root / "score.musicxml"
    tree = ET.fromstring(score_path.read_text())
    part_list = tree.find("part-list")
    part = tree.find("part")
    assert part_list is not None and part is not None
    duplicate = ET.fromstring(ET.tostring(part))
    duplicate.set("id", "P2")
    part_list.append(ET.fromstring('<score-part id="P2"><part-name>Voice 2</part-name></score-part>'))
    tree.append(duplicate)
    xml = ET.tostring(tree, encoding="unicode")
    score_path.write_text(xml)
    working = songs.checkout_current(song_id)
    working.write_text(xml)
    songs.replace_current_from_path(song_id, working)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(entry for entry in manifest["files"] if entry["path"] == "score.musicxml")
    data = score_path.read_bytes()
    entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    from audio_score_tool.note_evidence import score_hash
    with songs._connect() as conn:
        conn.execute("UPDATE note_evidence_state SET active=1, score_sha256=? WHERE song_id=?",
                     (score_hash(xml), song_id))
    result = _evidence_get(client, f"/api/songs/{song_id}", "p0-m0-n0").json()
    assert result["status"] == "ambiguous", result


def test_evidence_rejects_orphaned_edge_and_identical_replacement(product):
    client, _, song_id, _ = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    notes = client.get(base + "/notes").json()
    patch = {"step": "D", "expected_revision": 1, "expected_score_sha256": notes["score_sha256"],
             "expected_generation": notes["evidence_generation"]}
    assert client.patch(base + "/notes/p0-m1-n1/structure", json=patch).status_code == 200
    old = client.get(base + "/notes").json()
    assert client.post(base + "/undo").status_code == 200
    assert client.patch(base + "/notes/p0-m1-n1/structure", json={"step": "D"}).status_code == 200
    current = client.get(base + "/notes").json()
    assert current["score_sha256"] == old["score_sha256"]
    assert current["evidence_generation"] != old["evidence_generation"]
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"
    assert _evidence_get(client, base, "p0-m1-n1", revision=2,
                         score_sha256=old["score_sha256"], generation=old["evidence_generation"]).status_code == 409
    assert client.post(base + "/undo").status_code == 200
    assert client.patch(base + "/notes/p0-m1-n1/structure", json={"step": "E"}).status_code == 200
    assert _evidence_get(client, base, "p0-m1-n1", revision=2,
                         score_sha256=old["score_sha256"]).status_code == 409

    client2, _, song2, _ = _retained_vocal_fixture(product)
    base2 = f"/api/songs/{song2}"
    assert client2.post(base2 + "/notes/p0-m1-n1/insert", json={"position": "before", "step": "C"}).status_code == 200
    assert client2.delete(base2 + "/notes/p0-m1-n2").status_code == 200
    assert _evidence_get(client2, base2, "p0-m1-n1").json()["status"] == "unavailable"


def test_direct_sql_score_write_invalidates_evidence_even_for_identical_bytes(product):
    client, songs, song_id, _ = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    before = client.get(base + "/notes").json()
    with songs._connect() as conn:
        conn.execute("UPDATE songs SET current_score_xml=current_score_xml WHERE song_id=?", (song_id,))
    after = client.get(base + "/notes").json()
    assert before["score_sha256"] == after["score_sha256"]
    assert after["evidence_generation"] > before["evidence_generation"]
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"


def test_evidence_seek_requires_verified_source_and_beat(product):
    import hashlib
    import json

    client, songs, song_id, root = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    assert _evidence_get(client, base, "p0-m1-n1").json()["evidence"]["source_audio_seek_seconds"] == 1
    audio = root.parent / "original-audio.wav"
    saved = audio.read_bytes()
    audio.write_bytes(saved + b"changed")
    result = _evidence_get(client, base, "p0-m1-n1").json()
    assert result["status"] == "linked" and result["evidence"]["source_audio_seek_seconds"] is None
    audio.write_bytes(saved)
    receipt = root / "beat.runtime.json"
    data = json.loads(receipt.read_text())
    data["source_sha256"] = "0" * 64
    receipt.write_text(json.dumps(data))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(e for e in manifest["files"] if e["path"] == "beat.runtime.json")
    raw = receipt.read_bytes()
    entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    from audio_score_tool.note_evidence import baseline, baseline_fingerprint
    links, rows, clock, digest = baseline(songs.asset_root, song_id)
    with songs._connect() as conn:
        conn.execute("UPDATE note_evidence_state SET baseline_sha256=? WHERE song_id=?",
                     (baseline_fingerprint(links, rows, clock, digest), song_id))
    result = _evidence_get(client, base, "p0-m1-n1").json()
    assert result["status"] == "linked" and result["evidence"]["source_audio_seek_seconds"] is None


def test_evidence_get_is_read_only_and_checks_snapshot(product, monkeypatch):
    client, _, song_id, _ = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    notes = client.get(base + "/notes").json()
    monkeypatch.setattr(song_routes, "_sync", lambda: pytest.fail("evidence GET must not sync"))
    url = base + "/notes/p0-m1-n1/evidence"
    params = {"expected_revision": notes["song"]["revision"],
              "expected_score_sha256": notes["score_sha256"],
              "expected_generation": notes["evidence_generation"]}
    assert client.get(url, params=params).json()["status"] == "linked"
    assert client.get(url, params={**params, "expected_score_sha256": "0" * 64}).status_code == 409
    assert client.get(url, params={**params, "expected_revision": 0}).status_code == 422


def test_verified_fixed_ingest_admits_lineage_and_first_layout(product, monkeypatch):
    import json
    import shutil

    from audio_score_tool import song_store_v2

    client, songs, _, root = _retained_vocal_fixture(product)
    new_id = "owned-fixed-ingest"
    destination = songs.asset_root / new_id
    shutil.copytree(root.parent, destination)
    receipt = destination / "model-evidence/manifest.json"
    manifest = json.loads(receipt.read_text())
    manifest["job_id"] = new_id
    receipt.write_text(json.dumps(manifest))
    score = destination / "model-evidence/score.musicxml"
    job = {"job_id": new_id, "status": "done", "kind": "transcription", "filename": "fixture.wav",
           "source_kind": "local", "score_mode": "lead_sheet", "transcription_engine": "vocal_lead_v1",
           "result": {"musicxml": str(score)}}
    monkeypatch.setattr(song_store_v2, "SettingsStore", lambda: type("Settings", (), {"read": lambda self: {}})())
    assert songs.sync_completed_jobs([job]) == 1
    snapshot, state = songs.evidence_snapshot(new_id)
    assert state and state["active"] == 1
    assert songs.initialize_publication(snapshot, {}, snapshot.current_score_xml)
    _, state = songs.evidence_snapshot(new_id)
    assert state and state["active"] == 1
    assert _evidence_get(client, f"/api/songs/{new_id}", "p0-m1-n1").json()["status"] == "linked"


def test_pitch_outside_evidence_range_still_saves(product):
    client, songs, song_id, root = _retained_vocal_fixture(product)
    base = f"/api/songs/{song_id}"
    notes = client.get(base + "/notes").json()
    original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    response = client.patch(base + "/notes/p0-m1-n1/structure", json={
        "step": "B", "octave": 9, "expected_revision": notes["song"]["revision"],
        "expected_score_sha256": notes["score_sha256"],
        "expected_generation": notes["evidence_generation"]})
    assert response.status_code == 200, response.text
    assert songs.get(song_id)["revision"] == 2
    updated = client.get(base + "/notes").json()
    note = next(n for n in updated["notes"] if n["note_id"] == "p0-m1-n1")
    assert note["step"] == "B" and note["octave"] == 9
    assert _evidence_get(client, base, "p0-m1-n1").json()["status"] == "unavailable"
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches WHERE song_id=?", (song_id,)).fetchone()[0] == 0
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
