from __future__ import annotations

from pathlib import Path

from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Demo</work-title></work>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch>
      <duration>1</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


def make_store(tmp_path: Path) -> SongStoreV2:
    return SongStoreV2(
        path=tmp_path / "app.sqlite3",
        cache_root=tmp_path / "cache",
        asset_root=tmp_path / "assets",
        export_root=tmp_path / "exports",
    )


def test_completed_job_is_ingested_into_sqlite_without_initial_exports(tmp_path: Path):
    source = tmp_path / "generated.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    midi = tmp_path / "generated.mid"
    midi.write_bytes(b"MThd")
    pdf = tmp_path / "generated.pdf"
    pdf.write_bytes(b"%PDF")

    store = make_store(tmp_path)
    created = store.sync_completed_jobs(
        [
            {
                "job_id": "song-1",
                "status": "done",
                "kind": "transcription",
                "filename": "demo.wav",
                "result": {
                    "musicxml": str(source),
                    "midi": str(midi),
                    "pdf": str(pdf),
                },
            }
        ]
    )

    assert created == 1
    assert "<score-partwise" in store.score_xml("song-1")
    song = store.get("song-1")
    assert song is not None
    assert song["exports"] == {}
    assert not (tmp_path / "exports" / "song-1").exists()
    assert Path(song["original_midi"]).is_file()


def test_song_get_does_not_overwrite_checked_out_edit_buffer(tmp_path: Path):
    source = tmp_path / "generated.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    store = make_store(tmp_path)
    store.sync_completed_jobs(
        [
            {
                "job_id": "song-1",
                "status": "done",
                "kind": "transcription",
                "filename": "demo.wav",
                "result": {"musicxml": str(source)},
            }
        ]
    )

    working = store.checkout_current("song-1")
    edited = MUSICXML.replace("<step>C</step>", "<step>D</step>")
    working.write_text(edited, encoding="utf-8")

    # Metadata reads happen in background polling. They must not rematerialize the
    # canonical DB version over the edit buffer before commit.
    assert store.get("song-1") is not None
    assert store.list()
    assert working.read_text(encoding="utf-8") == edited


def test_omr_jobs_keep_omr_source_provenance(tmp_path: Path):
    source = tmp_path / "generated.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    store = make_store(tmp_path)
    created = store.sync_completed_jobs(
        [
            {
                "job_id": "omr-1",
                "status": "done",
                "kind": "omr",
                "filename": "scanned-score.pdf",
                "result": {"musicxml": str(source)},
            }
        ]
    )

    assert created == 1
    song = store.get("omr-1")
    assert song is not None
    assert song["source_kind"] == "omr"


def test_revision_restores_score_metadata_and_publication_from_database(tmp_path: Path):
    source = tmp_path / "generated.musicxml"
    source.write_text(MUSICXML, encoding="utf-8")
    store = make_store(tmp_path)
    store.sync_completed_jobs(
        [
            {
                "job_id": "song-1",
                "status": "done",
                "filename": "demo.wav",
                "result": {"musicxml": str(source)},
            }
        ]
    )

    publication = {"bars_per_system": 4, "composer": "A"}
    assert store.snapshot_revision("song-1", publication) == 1
    working = store.checkout_current("song-1")
    working.write_text(
        MUSICXML.replace("<step>C</step>", "<step>D</step>"),
        encoding="utf-8",
    )
    store.commit_edit_from_path("song-1", working)
    store.update_metadata("song-1", title="Changed")

    restored_publication = store.restore_revision("song-1", 1)
    restored = store.get("song-1")
    assert restored is not None
    assert restored["revision"] == 1
    assert restored["title"] == "demo"
    assert "<step>C</step>" in store.score_xml("song-1")
    assert restored_publication == publication


def test_publication_settings_are_sqlite_backed(tmp_path: Path):
    store = PublicationStoreV2(
        path=tmp_path / "app.sqlite3",
        legacy_root=tmp_path / "legacy",
    )
    saved = store.write("song-1", {"bars_per_system": 3, "composer": "Composer"})

    assert saved["bars_per_system"] == 3
    assert store.read("song-1")["composer"] == "Composer"
    assert not (tmp_path / "legacy" / "song-1" / "publication.json").exists()
