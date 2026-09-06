from __future__ import annotations

from pathlib import Path

import pytest

from audio_score_tool.musicxml_editor import (
    MusicXMLEditError,
    score_summary,
    snapshot,
    undo_last,
    update_note,
)
from audio_score_tool.song_store import SongStore

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Demo</work-title></work>
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>1</duration><voice>1</voice><type>quarter</type>
        <lyric><text>안</text></lyric>
      </note>
      <note>
        <pitch><step>D</step><octave>4</octave></pitch>
        <duration>1</duration><voice>1</voice><type>quarter</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def write_score(path: Path) -> Path:
    path.write_text(MUSICXML, encoding="utf-8")
    return path


def test_musicxml_note_edit_and_undo(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    revisions = tmp_path / "revisions"

    before = score_summary(score)
    assert before["notes"][0]["step"] == "C"
    assert before["notes"][0]["lyric"] == "안"

    snapshot(score, revisions, 1)
    update_note(
        score,
        "p0-m0-n0",
        {"step": "F", "alter": 1, "octave": 5, "lyric": "녕"},
    )
    after = score_summary(score)
    assert after["notes"][0]["step"] == "F"
    assert after["notes"][0]["alter"] == 1
    assert after["notes"][0]["octave"] == 5
    assert after["notes"][0]["lyric"] == "녕"

    assert undo_last(score, revisions) is not None
    restored = score_summary(score)
    assert restored["notes"][0]["step"] == "C"
    assert restored["notes"][0]["lyric"] == "안"


def test_musicxml_rejects_invalid_pitch_step(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    with pytest.raises(MusicXMLEditError):
        update_note(score, "p0-m0-n0", {"step": "H"})


def test_song_store_materializes_completed_jobs(tmp_path: Path):
    source_xml = write_score(tmp_path / "source.musicxml")
    source_midi = tmp_path / "source.mid"
    source_midi.write_bytes(b"MThd")
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF")

    store = SongStore(path=tmp_path / "songs.sqlite3", root=tmp_path / "songs")
    created = store.sync_completed_jobs(
        [
            {
                "job_id": "job-1",
                "kind": "transcription",
                "status": "done",
                "filename": "my-song.wav",
                "result": {
                    "musicxml": str(source_xml),
                    "midi": str(source_midi),
                    "pdf": str(source_pdf),
                },
            }
        ]
    )

    assert created == 1
    song = store.get("job-1")
    assert song is not None
    assert song["title"] == "my-song"
    assert song["revision"] == 1
    assert Path(song["original_musicxml"]).exists()
    assert Path(song["current_musicxml"]).exists()

    assert store.sync_completed_jobs([]) == 0
