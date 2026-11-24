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


def test_rhythm_edit_after_fractional_pickup_preserves_later_notes(product):
    client, _, songs, _ = product
    quarter = ('<note><pitch><step>C</step><octave>4</octave></pitch>'
               '<duration>12</duration><type>quarter</type></note>')
    xml = ('<score-partwise version="4.0"><part-list><score-part id="P1">'
           '<part-name>Voice</part-name></score-part></part-list><part id="P1">'
           '<measure number="0" implicit="yes"><attributes><divisions>12</divisions>'
           '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
           '<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>'
           '<type>32nd</type><time-modification><actual-notes>3</actual-notes>'
           '<normal-notes>2</normal-notes></time-modification></note></measure>'
           '<measure number="1">' + quarter * 4 + '</measure></part></score-partwise>')
    imported = client.post("/api/import/notation", files={
        "file": ("pickup.musicxml", xml.encode(), "application/vnd.recordare.musicxml+xml")})
    assert imported.status_code == 202, imported.text
    song_id = imported.json()["job_id"]
    base = f"/api/songs/{song_id}"
    tokens = _rhythm_tokens(client, base)
    before = ET.fromstring(songs.score_xml(song_id))
    result = client.post(base + "/notes/rhythm-edit", json={
        **tokens, "action": "split", "note_ids": ["p0-m1-n0"],
        "left_note_type": "eighth"})
    assert result.status_code == 200, result.text
    assert result.json()["result"]["mapping"]["p0-m1-n1"] == ["p0-m1-n2"]
    after = ET.fromstring(songs.score_xml(song_id))
    ET.indent(before)
    ET.indent(after)
    assert ET.tostring(before.find("./part/measure/note")) == ET.tostring(after.find("./part/measure/note"))
    assert [note.findtext("duration") for note in after.findall("./part/measure")[1].findall("note")] == [
        "6", "6", "12", "12", "12"]


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


def _evidence_get(client, base, note_id, *, revision=None, score_sha256=None, generation=None,
                  include_pitch_observations=False):
    notes = client.get(base + "/notes").json()
    return client.get(base + f"/notes/{note_id}/evidence", params={
        "expected_revision": revision if revision is not None else notes["song"]["revision"],
        "expected_score_sha256": score_sha256 or notes["score_sha256"],
        "expected_generation": generation if generation is not None else notes["evidence_generation"],
        "include_pitch_observations": include_pitch_observations})


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


@pytest.fixture
def rhythm_product(product):
    import hashlib
    import json
    import wave

    client, _, songs, _ = product
    song_id = "owned-rhythm"
    asset = songs.asset_root / song_id
    model = asset / "model-evidence"
    (model / "vocal").mkdir(parents=True)
    (model / "context").mkdir()
    (model / "native").mkdir()
    score = model / "score.musicxml"
    score.write_text("""<score-partwise version="4.0">
      <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
      <part id="P1"><measure number="1">
        <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>120</per-minute>
        </metronome></direction-type><sound tempo="120"/></direction>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
        <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type></note>
        <note><rest/><duration>4</duration><type>quarter</type></note>
      </measure></part></score-partwise>""")
    midi = MidiFile(ticks_per_beat=480)
    track = MidiTrack([MetaMessage("set_tempo", tempo=500000)])
    for pitch in (60, 60, 64):
        track.append(Message("note_on", note=pitch, velocity=72))
        track.append(Message("note_off", note=pitch, time=480))
    midi.tracks.append(track)
    midi.save(model / "vocal/selected.mid")
    (model / "interpretation.json").write_text(json.dumps({
        "algorithm": "dominant_overlap_on_audio_sixteenth_grid_v1",
        "grid_audio_seconds": [0, .5, 1, 1.5, 2], "source_note_indices": [0, 1, 2, -1]}))
    audio = asset / "original-audio.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(32000))
    source_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
    (model / "recipe.json").write_text(json.dumps({
        "recipe_version": 1, "engine": "vocal_lead_v1", "status": "completed",
        "source_audio_sha256": source_sha, "model_audio_sha256": source_sha, "model_audio_normalized": False}))
    (model / "context/music_structure.json").write_text('{"trimmed":false,"media_start_seconds":0}')
    (model / "native/playback.json").write_text('{"duration":2}')
    files = []
    for path in sorted(model.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            files.append({"path": path.relative_to(model).as_posix(),
                          "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (model / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "job_id": song_id, "source_audio_sha256": source_sha,
        "selection": {"transcription_engine": "vocal_lead_v1"}, "files": files}))
    job = {"job_id": song_id, "status": "done", "kind": "transcription", "filename": "fixture.wav",
           "source_kind": "local", "score_mode": "lead_sheet", "transcription_engine": "vocal_lead_v1",
           "result": {"musicxml": str(score)}}
    assert songs.sync_completed_jobs([job]) == 1
    return client, songs, song_id, asset


def _rhythm_tokens(client, base):
    notes = client.get(base + "/notes").json()
    return {"expected_revision": notes["song"]["revision"], "expected_score_sha256": notes["score_sha256"],
            "expected_generation": notes["evidence_generation"]}


def test_rhythm_edit_rejects_changed_unselected_pitch(rhythm_product, monkeypatch):
    from audio_score_tool import song_routes

    client, songs, song_id, _ = rhythm_product
    base = f"/api/songs/{song_id}"
    tokens = _rhythm_tokens(client, base)
    before = songs.score_xml(song_id)
    original_edit = song_routes.rhythm_edit

    def change_unselected_pitch(path, *args, **kwargs):
        result = original_edit(path, *args, **kwargs)
        tree = ET.parse(path)
        tree.getroot().findall("./part/measure/note")[2].find("pitch/step").text = "D"
        tree.write(path, encoding="unicode")
        return result

    monkeypatch.setattr(song_routes, "rhythm_edit", change_unselected_pitch)
    response = client.post(base + "/notes/rhythm-edit", json={
        **tokens, "action": "split", "note_ids": ["p0-m0-n0"], "left_note_type": "eighth"})
    assert response.status_code == 422
    assert songs.score_xml(song_id) == before


@pytest.mark.parametrize("method,path,body,query", [
    ("PATCH", "/notes/p0-m0-n0/chord", {"symbol": "C"}, False),
    ("POST", "/notes/p0-m0-n0/insert", {"type": "eighth"}, False),
    ("DELETE", "/notes/p0-m0-n0", None, True),
    ("PATCH", "/measures/0/signature", {"key_fifths": 1}, False),
    ("POST", "/measures/0/insert-after", None, True),
    ("DELETE", "/measures/1", None, True),
])
def test_positional_edits_check_preconditions(rhythm_product, method, path, body, query):
    client, songs, song_id, _ = rhythm_product
    base = f"/api/songs/{song_id}"
    if path == "/measures/1":
        assert client.post(base + "/measures/0/insert-after").status_code == 200
    tokens = _rhythm_tokens(client, base)
    before = songs.score_xml(song_id)
    structure = client.get(base + "/structure").json()
    score = client.get(base + "/score")
    assert structure["song"]["revision"] == tokens["expected_revision"]
    assert structure["score_sha256"] == tokens["expected_score_sha256"]
    assert score.headers["etag"] == f'"{tokens["expected_score_sha256"]}"'
    assert score.headers["access-control-expose-headers"] == "ETag"
    target = songs.export_dir(song_id) / "score.mid"
    target.write_bytes(b"owned-export")

    def edit(expected):
        return client.request(method, base + path, **({"params": expected} if query else {"json": {**body, **expected}}))

    for field, value in (("expected_revision", tokens["expected_revision"] + 1),
                         ("expected_score_sha256", "0" * 64),
                         ("expected_generation", tokens["expected_generation"] + 1)):
        assert edit({**tokens, field: value}).status_code == 409
    assert edit({**tokens, "expected_score_sha256": "bad"}).status_code == 422
    assert songs.score_xml(song_id) == before
    assert target.read_bytes() == b"owned-export"
    assert edit(tokens).status_code == 200


def test_rhythm_undo_survives_failed_concurrent_edit(rhythm_product, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from fastapi import FastAPI

    client, songs, song_id, asset = rhythm_product
    # Separate workers do not share the application's in-process mutation lane.
    separate_worker = FastAPI()
    separate_worker.include_router(song_routes.router)
    client = TestClient(separate_worker)
    base = f"/api/songs/{song_id}"
    tokens = _rhythm_tokens(client, base)
    songs.update_metadata(song_id, title="Before edit", artist="Original artist")
    publication = song_routes._publication_store.write(song_id, {"subtitle": "Before edit"})
    before_xml = songs.score_xml(song_id)
    before_song = songs.get(song_id)
    artifacts = {p: p.read_bytes() for p in asset.rglob("*") if p.is_file()}
    reached, release = Event(), Event()
    commit = songs.commit_edit_from_path
    other_store = SongStoreV2(path=songs.path, cache_root=songs.cache_root,
                              asset_root=songs.asset_root, export_root=songs.export_root)

    def paused_commit(*args, **kwargs):
        reached.set()
        assert release.wait(10)
        return commit(*args, **kwargs)

    monkeypatch.setattr(songs, "commit_edit_from_path", paused_commit)
    monkeypatch.setattr(song_routes, "_discard_snapshot", other_store.discard_snapshot)
    payload = {**tokens, "action": "split", "note_ids": ["p0-m0-n0"], "left_note_type": "eighth"}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, base + "/notes/rhythm-edit", json=payload)
        try:
            assert reached.wait(10)
            failed = client.post(base + "/notes/rhythm-edit", json={**payload, "left_note_type": "half"})
            assert failed.status_code == 422, failed.text
            with songs._connect() as conn:
                assert conn.execute("SELECT count(*) FROM song_revisions WHERE song_id=?", (song_id,)).fetchone()[0] == 0
        finally:
            release.set()
        result = future.result(timeout=10)
    assert result.status_code == 200, result.text
    assert songs.get(song_id)["revision"] == tokens["expected_revision"] + 1
    assert client.post(base + "/undo").status_code == 200
    restored = songs.get(song_id)
    assert restored["revision"] == tokens["expected_revision"]
    assert (restored["title"], restored["artist"]) == ("Before edit", "Original artist")
    assert songs.score_xml(song_id) == before_xml
    assert song_routes._publication_store.read(song_id) == publication
    assert restored["source_kind"] == before_song["source_kind"]
    assert all(path.read_bytes() == contents for path, contents in artifacts.items())


def test_rhythm_edits_preserve_source_topology_and_export_timing(rhythm_product):
    from audio_score_tool.metrics import midi_notes

    client, songs, song_id, asset = rhythm_product
    base = f"/api/songs/{song_id}"
    url = base + "/notes/rhythm-edit"
    artifacts = {p: p.read_bytes() for p in asset.rglob("*") if p.is_file()}
    first, second, third, fourth = [f"p0-m0-n{i}" for i in range(4)]
    source_ids = [_evidence_get(client, base, note).json()["evidence"]["source_id"]
                  for note in (first, second, third)]
    assert len(set(source_ids)) == 3

    def edit(action, note_ids, **duration):
        previous = _rhythm_tokens(client, base)
        payload = {**previous, "action": action, "note_ids": note_ids, **duration}
        response = client.post(url, json=payload)
        assert response.status_code == 200, response.text
        assert client.post(url, json=payload).status_code == 409
        return response.json()["result"]

    split = edit("split", [first], left_note_type="eighth")
    assert split["mapping"][first] == [first, second]
    assert split["mapping"][second] == [third]
    assert split["mapping"][third] == [fourth]
    child_a = _evidence_get(client, base, first).json()
    child_b = _evidence_get(client, base, second).json()
    assert child_a["schema_version"] == child_b["schema_version"] == 2
    assert child_a["evidence"]["source_ids"] == child_b["evidence"]["source_ids"] == [source_ids[0]]
    assert child_a["evidence"]["performed_seconds"] == child_b["evidence"]["performed_seconds"] == {"start": 0, "end": .5}
    assert child_b["evidence"]["written_quarters"] == {"start": .5, "end": 1}
    assert child_b["patch"]["operation"] == "split"

    merge = edit("merge", [second, third])
    assert merge["mapping"][second] == merge["mapping"][third] == [second]
    assert merge["mapping"][fourth] == [third]
    merged = _evidence_get(client, base, second).json()["evidence"]
    assert merged["source_ids"] == source_ids[:2]
    assert merged["source_id"] is None and merged["source_audio_seek_seconds"] is None
    assert [source["source_audio_seek_seconds"] for source in merged["sources"]] == [0, .5]
    assert merged["written_quarters"] == {"start": .5, "end": 2}

    boundary = edit("boundary", [third, fourth], left_note_type="eighth")
    assert boundary["edit"]["outputs"][0]["written_quarters"] == {"start": 2, "end": 2.5}
    moved = _evidence_get(client, base, third).json()["evidence"]
    assert moved["grid_seconds"] == {"start": 1, "end": 1.5}
    assert moved["source_ids"] == [source_ids[2]]
    assert moved["written_quarters"] == {"start": 2, "end": 2.5}

    pitch = client.patch(base + f"/notes/{second}/structure",
                         json={**_rhythm_tokens(client, base), "step": "D"})
    assert pitch.status_code == 200, pitch.text
    pitched = _evidence_get(client, base, second).json()
    assert pitched["evidence"]["source_ids"] == pitched["patch"]["source_ids"] == source_ids[:2]
    assert pitched["patch"]["after_pitch"] == 62
    assert _evidence_get(client, base, first).json()["evidence"]["source_ids"] == [source_ids[0]]

    deleted = edit("delete", [third])
    assert deleted["mapping"][third] == []
    removed = _evidence_get(client, base, third).json()
    assert removed["status"] == "unavailable"
    assert removed["patch"]["inputs"][0]["source_ids"] == [source_ids[2]]
    assert removed["patch"]["outputs"][0]["source_ids"] == []
    assert removed["patch"]["outputs"][0]["pitch"] is None
    assert _evidence_get(client, base, second).json()["evidence"]["source_ids"] == source_ids[:2]

    final_tokens = _rhythm_tokens(client, base)
    result = client.post(base + "/export", json={"formats": ["midi"],
                         "expected_revision": final_tokens["expected_revision"]})
    assert result.status_code == 200, result.text
    output = midi_notes(songs.export_root / song_id / "score.mid")
    assert [(n.pitch, n.onset, n.offset) for n in output] == [(60, 0, .25), (62, .25, 1)]
    assert sum(int(n.text) for n in ET.fromstring(songs.score_xml(song_id)).findall("./part/measure/note/duration")) == 16
    assert all(path.read_bytes() == contents for path, contents in artifacts.items())

    assert client.post(base + "/undo").status_code == 200
    old = client.get(base + f"/notes/{second}/evidence", params=final_tokens)
    assert old.status_code == 409
    assert _evidence_get(client, base, second).json()["status"] == "unavailable"
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches WHERE song_id=?", (song_id,)).fetchone()[0] == 5


def test_rhythm_edit_inner_failure_and_malformed_lineage(rhythm_product):
    client, songs, song_id, _ = rhythm_product
    base = f"/api/songs/{song_id}"
    url = base + "/notes/rhythm-edit"
    token = _rhythm_tokens(client, base)
    note_id = "p0-m0-n0"
    payload = {**token, "action": "split", "note_ids": [note_id], "left_note_type": "eighth"}
    target = songs.export_dir(song_id) / "score.mid"
    target.write_bytes(b"owned-export")
    assert client.post(url, json={**payload, "expected_generation": token["expected_generation"] + 1}).status_code == 409
    assert client.post(url, json={**payload, "note_ids": [note_id, note_id]}).status_code == 422
    assert client.post(url, json={**payload, "left_note_type": "half"}).status_code == 422
    assert target.read_bytes() == b"owned-export"
    before = songs.evidence_snapshot(song_id)
    with songs._connect() as conn:
        conn.execute("CREATE TRIGGER fail_rhythm BEFORE INSERT ON note_evidence_patches "
                     "BEGIN SELECT RAISE(ABORT, 'owned failure'); END")
    response = client.post(url, json=payload)
    assert response.status_code == 422 and "owned failure" in response.text
    assert songs.evidence_snapshot(song_id) == before
    assert target.read_bytes() == b"owned-export"
    with songs._connect() as conn:
        assert conn.execute("SELECT count(*) FROM note_evidence_patches").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM song_revisions WHERE song_id=?", (song_id,)).fetchone()[0] == 0
        conn.execute("DROP TRIGGER fail_rhythm")
    assert client.post(url, json=payload).status_code == 200
    after = _rhythm_tokens(client, base)
    for value, reason in (('{"schema_version":99,"locators":{}}', "unsupported_lineage"),
                          ('{"schema_version":1,"locators":{"p0-m0-n0":["absent"]}}', "invalid_lineage"),
                          ('{"schema_version":1,"locators":', "invalid_lineage")):
        with songs._connect() as conn:
            conn.execute("UPDATE note_evidence_state SET lineage_json=? WHERE song_id=?", (value, song_id))
        response = _evidence_get(client, base, note_id)
        assert response.json()["status"] == "unavailable" and response.json()["reason"] == reason
        stable = songs.evidence_snapshot(song_id)
        assert client.post(url, json={**payload, **after}).status_code == 422
        assert songs.evidence_snapshot(song_id) == stable


@pytest.mark.parametrize("input_kind", ["musicxml", "mid"])
def test_legacy_rhythm_edit_keeps_missing_sources_explicit(product, input_kind):
    client, _, songs, _ = product
    source = ((SCORE_XML.encode(), "application/vnd.recordare.musicxml+xml")
              if input_kind == "musicxml" else (_midi_fixture(), "audio/midi"))
    imported = client.post("/api/import/notation", files={"file": (f"legacy.{input_kind}", *source)})
    assert imported.status_code == 202, imported.text
    song_id = imported.json()["job_id"]
    base = f"/api/songs/{song_id}"
    result = client.post(base + "/notes/rhythm-edit", json={
        **_rhythm_tokens(client, base), "action": "split", "note_ids": ["p0-m0-n0"], "left_note_type": "half"})
    assert result.status_code == 200, result.text
    evidence = _evidence_get(client, base, "p0-m0-n1").json()
    assert evidence["status"] == "unavailable" and evidence["reason"] == "lineage_unavailable"
    assert evidence["patch"]["operation"] == "split"
    assert all(not entry["source_ids"] for entry in evidence["patch"]["outputs"])
    _, state = songs.evidence_snapshot(song_id)
    assert not state["active"] and state["lineage_json"] is None
    if input_kind == "mid":
        written = ET.fromstring(songs.score_xml(song_id)).findall("./part/measure/note")
        assert len(written) == 2
        assert written[0].find("instrument").get("id") == written[1].find("instrument").get("id")
        assert written[0].get("dynamics") == written[1].get("dynamics")


def test_rhythm_lineage_migration_keeps_admitted_baseline(rhythm_product):
    client, songs, song_id, _ = rhythm_product
    base = f"/api/songs/{song_id}"
    before, state = songs.evidence_snapshot(song_id)
    with songs._connect() as conn:
        conn.execute("ALTER TABLE note_evidence_state DROP COLUMN lineage_json")
    reopened = SongStoreV2(path=songs.path, cache_root=songs.cache_root,
                           asset_root=songs.asset_root, export_root=songs.export_root)
    assert reopened.evidence_snapshot(song_id) == (before, state)
    evidence = _evidence_get(client, base, "p0-m0-n0").json()
    assert evidence["status"] == "linked" and evidence["schema_version"] == 1


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


def test_vocal_prefix_survives_split_merge_and_preserves_baseline(rhythm_product):
    import hashlib
    import json
    import shutil

    import numpy as np

    from audio_score_tool.note_evidence import baseline, baseline_fingerprint
    from audio_score_tool.vocal_hypotheses import build, write

    client, songs, song_id, asset = rhythm_product
    root = asset / 'model-evidence'
    base = f'/api/songs/{song_id}'
    before = _evidence_get(client, base, 'p0-m0-n0').json()
    vocal = root / 'vocal'
    shutil.copyfile(vocal / 'selected.mid', vocal / 'score.mid')
    (vocal / 'score.runtime.json').write_text('{}')
    hz = np.full(201, 440.)
    np.savez(vocal / 'pitch.npz', times=np.arange(201) * .01, hz=hz, raw_hz=hz,
             periodicity=np.ones(201), loudness_db_a=np.zeros(201))
    receipt = {'schema_version': 2, 'source_frames': 32000, 'source_sample_rate': 16000, 'hop': 160,
               'source_sha256': 'a' * 64,
               'prediction_sha256': hashlib.sha256((vocal / 'pitch.npz').read_bytes()).hexdigest()}
    (vocal / 'pitch.runtime.json').write_text(json.dumps(receipt))
    prefix = build(vocal / 'score.mid', vocal / 'selected.mid', vocal / 'pitch.npz', receipt,
                   receipt['source_sha256'], vocal / 'score.runtime.json', vocal / 'pitch.runtime.json')
    sha = write(vocal / 'note-hypotheses.json', prefix)
    recipe = json.loads((root / 'recipe.json').read_text())
    recipe.update(vocal_hypotheses={'schema_version': 1, 'sha256': sha}, pitch_verifier=receipt,
                  melody={'runtime': {}})
    (root / 'recipe.json').write_text(json.dumps(recipe))
    def refresh_manifest():
        manifest = json.loads((root / 'manifest.json').read_text())
        manifest['files'] = []
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.name != 'manifest.json':
                data = path.read_bytes()
                manifest['files'].append({'path': path.relative_to(root).as_posix(), 'bytes': len(data),
                                          'sha256': hashlib.sha256(data).hexdigest()})
        (root / 'manifest.json').write_text(json.dumps(manifest))
        links, rows, clock, manifest_hash = baseline(songs.asset_root, song_id)
        with songs._connect() as conn:
            conn.execute('UPDATE note_evidence_state SET baseline_sha256=? WHERE song_id=?',
                         (baseline_fingerprint(links, rows, clock, manifest_hash), song_id))
    refresh_manifest()
    after = _evidence_get(client, base, 'p0-m0-n0').json()
    assert after['evidence'] == before['evidence']
    assert 'pitch_observations' not in after
    viewed = _evidence_get(client, base, 'p0-m0-n0', include_pitch_observations=True).json()
    assert viewed['evidence'] == after['evidence'] and viewed['evidence_generation'] == after['evidence_generation']
    assert viewed['pitch_observations']['status'] == 'available'
    original_window = viewed['pitch_observations']['sources'][0]
    source = after['vocal_hypotheses']['sources'][0]
    assert source['status'] == 'linked' and source['model_segments'][0]['release_seconds'] == .5
    # A well-hashed unsupported extension cannot invalidate the established baseline.
    recipe['vocal_hypotheses']['schema_version'] = 9
    (root / 'recipe.json').write_text(json.dumps(recipe))
    refresh_manifest()
    unknown = _evidence_get(client, base, 'p0-m0-n0', include_pitch_observations=True).json()
    assert unknown['evidence'] == before['evidence']
    assert unknown['vocal_hypotheses']['status'] == 'unavailable'
    assert unknown['pitch_observations']['reason'] == 'unsupported'
    recipe['vocal_hypotheses']['schema_version'] = 1
    (root / 'recipe.json').write_text(json.dumps(recipe))
    refresh_manifest()
    url = base + '/notes/rhythm-edit'
    split = client.post(url, json={**_rhythm_tokens(client, base), 'action': 'split',
                                  'note_ids': ['p0-m0-n0'], 'left_note_type': 'eighth'})
    assert split.status_code == 200, split.text
    assert _evidence_get(client, base, 'p0-m0-n1').json()['vocal_hypotheses']['sources'][0] == source
    split_window = _evidence_get(client, base, 'p0-m0-n1', include_pitch_observations=True).json()
    assert split_window['pitch_observations']['sources'][0] == original_window
    merge = client.post(url, json={**_rhythm_tokens(client, base), 'action': 'merge',
                                  'note_ids': ['p0-m0-n1', 'p0-m0-n2']})
    assert merge.status_code == 200, merge.text
    merged = _evidence_get(client, base, 'p0-m0-n1', include_pitch_observations=True).json()
    assert len(merged['vocal_hypotheses']['sources']) == 2
    assert [row['source_id'] for row in merged['pitch_observations']['sources']] == merged['evidence']['source_ids']
    assert merged['evidence']['source_audio_seek_seconds'] is None
    assert client.post(base + '/undo').status_code == 200
    undone = _evidence_get(client, base, 'p0-m0-n0', include_pitch_observations=True).json()
    assert undone['status'] == undone['pitch_observations']['status'] == 'unavailable'


def test_fresh_fixed_job_prefix_is_admitted_to_note_api(rhythm_product, tmp_path, monkeypatch):
    import hashlib
    import json
    import shutil

    import numpy as np

    from audio_score_tool import song_store_v2
    from audio_score_tool.vocal_hypotheses import build, write

    client, songs, _, asset = rhythm_product
    jobs = tmp_path / 'fresh-jobs'
    song_id = 'fresh-vocal-prefix'
    job_root = jobs / song_id
    score = job_root / 'outputs/input/score'
    vocal = score / 'vocal'
    vocal.mkdir(parents=True)
    source = asset / 'model-evidence'
    for name in ('score.musicxml', 'interpretation.json'):
        shutil.copyfile(source / name, score / name)
    for name in ('score.mid', 'selected.mid'):
        shutil.copyfile(source / 'vocal/selected.mid', vocal / name)
    shutil.copyfile(vocal / 'selected.mid', score / 'score.mid')
    shutil.copyfile(asset / 'original-audio.wav', job_root / 'input.wav')
    shutil.copyfile(source / 'context/music_structure.json', score.parent / 'music_structure.json')
    for folder in ('native', 'structure/native'):
        target = score / folder
        target.mkdir(parents=True)
        (target / 'score.abc').write_text('X:1\nK:C\nC|')
    (score / 'native/playback.json').write_text('{"duration":2}')
    (score / 'structure/native/melody_vocal.mid').write_bytes(b'fixture')
    (score / 'structure/analysis.json').write_text('{}')
    (vocal / 'score.runtime.json').write_text('{}')
    hz = np.full(201, 440.)
    np.savez(vocal / 'pitch.npz', times=np.arange(201) * .01, hz=hz, raw_hz=hz,
             periodicity=np.ones(201), loudness_db_a=np.zeros(201))
    tiny = {'schema_version': 2, 'source_frames': 32000, 'source_sample_rate': 16000, 'hop': 160,
            'source_sha256': 'a' * 64,
            'prediction_sha256': hashlib.sha256((vocal / 'pitch.npz').read_bytes()).hexdigest()}
    (vocal / 'pitch.runtime.json').write_text(json.dumps(tiny))
    prefix = build(vocal / 'score.mid', vocal / 'selected.mid', vocal / 'pitch.npz', tiny,
                   tiny['source_sha256'], vocal / 'score.runtime.json', vocal / 'pitch.runtime.json')
    sha = write(vocal / 'note-hypotheses.json', prefix)
    audio_sha = hashlib.sha256((job_root / 'input.wav').read_bytes()).hexdigest()
    recipe = {'recipe_version': 2, 'engine': 'vocal_lead_v1', 'status': 'completed',
              'source_audio_sha256': audio_sha, 'model_audio_sha256': audio_sha, 'model_audio_normalized': False,
              'pitch_verifier': tiny, 'melody': {'runtime': {}},
              'vocal_hypotheses': {'schema_version': 1, 'sha256': sha}}
    (score / 'recipe.json').write_text(json.dumps(recipe))
    monkeypatch.setattr(song_store_v2, 'jobs_dir', lambda: jobs)
    job = {'job_id': song_id, 'status': 'done', 'kind': 'transcription', 'filename': 'fixture.wav',
           'source_kind': 'local', 'score_mode': 'lead_sheet', 'transcription_engine': 'vocal_lead_v1',
           'result': {'score_dir': str(score), 'musicxml': str(score / 'score.musicxml'),
                      'midi': str(score / 'score.mid')}}
    assert songs.sync_completed_jobs([job]) == 1
    shutil.rmtree(job_root)
    from audio_score_tool import pitch_observation_window
    window_reader = pitch_observation_window.pitch_observation_window
    monkeypatch.setattr(pitch_observation_window, 'pitch_observation_window',
                        lambda *args: pytest.fail('default evidence must not read frame windows'))
    result = _evidence_get(client, f'/api/songs/{song_id}', 'p0-m0-n0').json()
    assert result['status'] == 'linked', result
    assert result['vocal_hypotheses']['sources'][0]['model_segments'][0]['pitch'] == 60
    assert result['evidence']['source_audio_seek_seconds'] == 0
    assert 'pitch_observations' not in result
    monkeypatch.setattr(pitch_observation_window, 'pitch_observation_window', window_reader)
    viewed = _evidence_get(client, f'/api/songs/{song_id}', 'p0-m0-n0', include_pitch_observations=True).json()
    assert viewed['evidence'] == result['evidence']
    assert viewed['pitch_observations']['status'] == 'available'
    assert _evidence_get(client, f'/api/songs/{song_id}', 'p0-m0-n0',
                         generation=viewed['evidence_generation'] + 1, include_pitch_observations=True).status_code == 409
