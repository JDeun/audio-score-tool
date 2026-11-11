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
    revision_api_v2,
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
    monkeypatch.setattr(export_api_v2, "cache_dir", lambda: tmp_path / "cache")
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
