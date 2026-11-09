"""No-source/no-match metadata must be Unknown without losing the score or ASR."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from audio_score_tool import automatic_song_enrichment as automatic
from audio_score_tool import enrichment_api
from audio_score_tool.publication_store_v2 import PublicationStoreV2
from audio_score_tool.song_store_v2 import SongStoreV2

MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <work><work-title>Original</work-title></work>
  <movement-title>Original</movement-title>
  <part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>
  <type>quarter</type><lyric><text>recognized ASR word</text></lyric></note>
  </measure></part>
</score-partwise>
"""


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    def factory(filename: str):
        store = SongStoreV2(
            path=tmp_path / "songs.sqlite3",
            cache_root=tmp_path / "cache",
            asset_root=tmp_path / "assets",
            export_root=tmp_path / "exports",
        )
        publication = PublicationStoreV2(path=store.path, legacy_root=tmp_path / "legacy")
        xml = tmp_path / "score.musicxml"
        xml.write_text(MUSICXML, encoding="utf-8")
        job = {
            "job_id": "song-1",
            "status": "done",
            "kind": "transcription",
            "source_kind": "local",
            "auto_enrich": True,
            "filename": filename,
            "score_mode": "full",
            "result": {"musicxml": str(xml)},
        }
        assert store.sync_completed_jobs([job]) == 1
        monkeypatch.setattr(automatic, "SongStoreV2", lambda: store)
        monkeypatch.setattr(enrichment_api, "_store", store)
        monkeypatch.setattr(enrichment_api, "_publication", publication)
        monkeypatch.setattr(
            enrichment_api, "runtime_settings",
            lambda: SimpleNamespace(usage_mode="personal"),
        )
        return store, publication, job
    return factory


def _assert_unknown_score(store, publication):
    song = store.get("song-1")
    assert song["title"] == "Unknown"
    assert song["artist"] == "Unknown"
    assert song["revision"] == 2
    credits = publication.read("song-1")
    for field in ("album", "performer", "release_date", "composer", "lyricist"):
        assert credits[field] == "Unknown"
    xml = store.score_xml("song-1")
    assert "Unknown" in xml
    # Prior genuine acoustic lyrics survive unknown identity and metadata edits.
    assert "recognized ASR word" in xml


def test_unparseable_filename_does_not_call_provider_and_marks_unknown(
    prepared, monkeypatch,
):
    store, publication, job = prepared("29382793__random.mp3")
    job["_source_lookup_hints"] = None
    monkeypatch.setattr(
        automatic, "enrich_song",
        lambda *_args, **_kwargs: pytest.fail("No search terms: must not call API"),
    )
    report = automatic.enrich_completed_job(job)
    assert report["status"] == "unknown"
    assert report["query_issued"] is False
    assert report["source_hint"] == "missing"
    assert store.analysis("song-1", "automatic_enrichment")["status"] == "unknown"
    _assert_unknown_score(store, publication)


def test_wrong_song_high_ranked_api_candidate_is_not_accepted(
    prepared, monkeypatch,
):
    store, publication, job = prepared("Green Day - American Idiot.mp3")
    monkeypatch.setattr(
        enrichment_api, "search_musicbrainz",
        lambda *_args, **_kwargs: [
            {
                "provider": "musicbrainz",
                "title": "Completely Different",
                "artist": "Another Band",
                "recording_mbid": None,
                "score": 100,
            }
        ],
    )
    monkeypatch.setattr(
        enrichment_api, "lookup_musicbrainz_work_credits",
        lambda *_args, **_kwargs: pytest.fail("Mismatched candidate must not load work"),
    )
    result = automatic.enrich_completed_job(job)
    assert result["status"] == "unknown"
    assert result["query_issued"] is True
    assert result["matched"] is False
    _assert_unknown_score(store, publication)


def test_later_verified_match_replaces_only_automatic_unknown_placeholders(
    prepared, monkeypatch,
):
    store, publication, job = prepared("unrecognized_input.wav")
    job["_source_lookup_hints"] = None
    assert automatic.enrich_completed_job(job)["status"] == "unknown"
    # A user can later supply a known artist/title or fix the file metadata.
    known = {
        "provider": "musicbrainz",
        "title": "Confirmed song",
        "artist": "Confirmed Band",
        "album": "Official album",
        "first_release_date": "2004-09-21",
        "composer": "Composer from Work",
        "lyricist": "Lyricist from Work",
        "songwriters_verified": True,
    }
    song = store.get("song-1")
    assert enrichment_api._apply_metadata(
        "song-1", song, known, song["title"], song["artist"],
    )
    updated = store.get("song-1")
    assert updated["title"] == "Confirmed song"
    assert updated["artist"] == "Confirmed Band"
    credits = publication.read("song-1")
    assert credits["album"] == "Official album"
    assert credits["performer"] == "Confirmed Band"
    assert credits["composer"] == "Composer from Work"
    assert credits["lyricist"] == "Lyricist from Work"
    assert credits["release_date"] == "2004-09-21"
    assert "recognized ASR word" in store.score_xml("song-1")


def test_unresolved_lookup_must_not_replace_intervening_user_edit(
    prepared, monkeypatch,
):
    store, _, job = prepared("Band - Track.mp3")
    new_score = store.checkout_current("song-1")
    store.commit_edit_from_path("song-1", new_score)
    before = store.get("song-1")
    xml = store.score_xml("song-1")
    monkeypatch.setattr(
        automatic, "enrich_song",
        lambda *_args, **_kwargs: {
            "metadata": {"selected": None, "applied": False, "error": "429"},
        },
    )
    report = automatic.enrich_completed_job(job)
    assert report["status"] == "unknown_not_applied"
    assert store.get("song-1") == before
    assert store.score_xml("song-1") == xml
    assert report["error"] == "429"


def test_opted_out_job_does_not_overwrite_metadata_or_call_api(prepared, monkeypatch):
    store, _, job = prepared("nonsense.mp3")
    job["auto_enrich"] = False
    monkeypatch.setattr(
        automatic, "enrich_song",
        lambda *_args, **_kwargs: pytest.fail("Opted-out job must not use API"),
    )
    assert automatic.enrich_completed_job(job)["status"] == "disabled"
    assert store.get("song-1")["title"] == "nonsense"
    assert store.get("song-1")["revision"] == 1
