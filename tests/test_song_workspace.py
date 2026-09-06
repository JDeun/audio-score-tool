from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from audio_score_tool.chord_editor import ChordEditError, set_chord_at_note
from audio_score_tool.chord_listing import list_chords
from audio_score_tool.musicxml_editor import (
    MusicXMLEditError,
    score_summary,
    snapshot,
    undo_last,
    update_note,
)
from audio_score_tool.publication_layout import apply_publication_layout
from audio_score_tool.publication_store import PublicationStore
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


def write_multi_measure_score(path: Path, measures: int = 8) -> Path:
    body = []
    for index in range(measures):
        attributes = (
            "<attributes><divisions>1</divisions><time><beats>4</beats>"
            "<beat-type>4</beat-type></time></attributes>"
            if index == 0
            else ""
        )
        body.append(
            f'<measure number="{index + 1}">{attributes}'
            "<note><pitch><step>C</step><octave>4</octave></pitch>"
            "<duration>4</duration><voice>1</voice><type>whole</type></note></measure>"
        )
    path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<score-partwise version=\"4.0\">"
        "<work><work-title>Commercial Demo</work-title></work>"
        "<part-list><score-part id=\"P1\"><part-name>Voice</part-name></score-part></part-list>"
        f"<part id=\"P1\">{''.join(body)}</part></score-partwise>",
        encoding="utf-8",
    )
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


def test_new_alter_is_inserted_before_octave(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    update_note(score, "p0-m0-n0", {"alter": 1})

    root = ET.parse(score).getroot()
    pitch = root.find("./part/measure/note/pitch")
    assert pitch is not None
    assert [child.tag.rsplit("}", 1)[-1] for child in pitch] == ["step", "alter", "octave"]


def test_musicxml_rejects_invalid_pitch_step(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    with pytest.raises(MusicXMLEditError):
        update_note(score, "p0-m0-n0", {"step": "H"})


def test_chord_symbol_is_inserted_above_selected_note(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    set_chord_at_note(score, "p0-m0-n0", "F#m7")
    set_chord_at_note(score, "p0-m0-n1", "G/B")

    chords = list_chords(score)
    assert [item["symbol"] for item in chords] == ["F♯m7", "G/B"]
    assert chords[0]["note_id"] == "p0-m0-n0"
    assert chords[1]["note_id"] == "p0-m0-n1"

    root = ET.parse(score).getroot()
    measure_children = [child.tag.rsplit("}", 1)[-1] for child in root.find("./part/measure")]
    first_harmony = measure_children.index("harmony")
    first_note = measure_children.index("note")
    assert first_harmony < first_note


def test_chord_symbol_can_be_removed_and_invalid_symbol_rejected(tmp_path: Path):
    score = write_score(tmp_path / "score.musicxml")
    set_chord_at_note(score, "p0-m0-n0", "Cmaj7")
    set_chord_at_note(score, "p0-m0-n0", "")
    assert list_chords(score) == []

    with pytest.raises(ChordEditError):
        set_chord_at_note(score, "p0-m0-n0", "H7")


def test_publication_layout_forces_system_and_page_breaks_and_credits(tmp_path: Path):
    score = write_multi_measure_score(tmp_path / "score.musicxml")
    apply_publication_layout(
        score,
        title="판매용 악보",
        settings={
            "bars_per_system": 2,
            "systems_per_page": 2,
            "system_distance_mm": 12,
            "first_page_title_space_mm": 40,
            "composer": "Composer",
            "lyricist": "Lyricist",
            "arranger": "Arranger",
            "subtitle": "Piano & Vocal",
            "rights": "© 2026 Demo",
        },
    )

    root = ET.parse(score).getroot()
    measures = root.findall("./part/measure")
    assert measures[2].find("print").get("new-system") == "yes"
    assert measures[4].find("print").get("new-page") == "yes"
    credits = [node.findtext("credit-words") for node in root.findall("credit")]
    assert "판매용 악보" in credits
    assert "Piano & Vocal" in credits
    assert "작곡  Composer" in credits
    assert "작사  Lyricist" in credits
    assert "편곡  Arranger" in credits
    assert "© 2026 Demo" in credits
    page_layout = root.find("./defaults/page-layout")
    assert page_layout is not None
    assert page_layout.find("page-width") is not None
    assert page_layout.find("page-margins") is not None


def test_publication_settings_are_revisioned(tmp_path: Path):
    store = PublicationStore(root=tmp_path / "songs")
    revisions = tmp_path / "songs" / "song-1" / "revisions"
    store.write("song-1", {"bars_per_system": 4, "composer": "A"})
    store.snapshot("song-1", revisions, 1)
    store.write("song-1", {"bars_per_system": 3, "composer": "B"})

    assert store.read("song-1")["bars_per_system"] == 3
    assert store.restore_snapshot("song-1", revisions, 1) is True
    assert store.read("song-1")["bars_per_system"] == 4
    assert store.read("song-1")["composer"] == "A"


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


def test_song_store_clears_stale_exports(tmp_path: Path):
    store = SongStore(path=tmp_path / "songs.sqlite3", root=tmp_path / "songs")
    export_dir = store.export_dir("song-1")
    pdf = export_dir / "score.pdf"
    midi = export_dir / "score.mid"
    pdf.write_bytes(b"%PDF")
    midi.write_bytes(b"MThd")

    store.clear_exports("song-1")

    assert not pdf.exists()
    assert not midi.exists()
