"""Contract probe tests use synthetic API payloads and no network."""
from __future__ import annotations

import json

from audio_score_tool.enrichment import EnrichmentError
from scripts.check_metadata_providers_live import check_live_providers


def test_live_probe_reports_verified_metadata_without_disclosing_lyrics():
    words = "synthetic private test lyric secret goes here"
    def musicbrainz(title, artist, *, limit):
        assert (title, artist, limit) == ("American Idiot", "Green Day", 5)
        return [{
            "title": title, "artist": artist, "score": 99,
            "recording_mbid": "00000000-0000-0000-0000-000000000001",
            "album": "Example recording album",
        }]

    def work(mbid):
        assert mbid.endswith("1")
        return {
            "status": "verified_work_relations",
            "composer": "Some verified composer",
            "lyricist": "Some verified lyricist",
        }

    def lyrics(title, artist, *, album):
        assert (title, artist) == ("I Want to Live", "Borislav Slavov")
        assert album.startswith("Baldur's Gate 3")
        return {
            "provider": "lrclib",
            "lyrics": words,
            "synced": True,
            "source_payload": {"trackName": title, "artistName": artist},
        }

    result = check_live_providers(
        recording_search=musicbrainz,
        work_lookup=work,
        lyrics_fetch=lyrics,
    )
    assert result["both_provider_contracts_live"] is True
    assert result["providers"]["musicbrainz"]["composer_relation_present"] is True
    assert result["providers"]["musicbrainz"]["lyricist_relation_present"] is True
    assert result["providers"]["lrclib"]["synced_available"] is True
    assert result["models_run"] is False
    assert result["any_media_uploaded"] is False
    report = json.dumps(result)
    assert words not in report
    assert "lyrics" not in result["providers"]["lrclib"]


def test_live_probe_rejects_other_song_despite_high_search_score():
    def musicbrainz(_title, _artist, *, limit):
        return [{
            "title": "Different track",
            "artist": "Another group",
            "score": 100,
            "recording_mbid": "00000000-0000-0000-0000-000000000001",
        }]

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("Wrong-identity work lookup must not occur")

    result = check_live_providers(
        recording_search=musicbrainz,
        work_lookup=should_not_run,
        lyrics_fetch=lambda *_args, **_kwargs: None,
    )
    assert result["both_provider_contracts_live"] is False
    assert result["providers"]["musicbrainz"]["status"] == "inconclusive"
    assert result["providers"]["musicbrainz"]["reason"] == "no_verified_recording_candidate"
    assert result["providers"]["lrclib"]["reason"] == "no_exact_lyrics_match"


def test_live_probe_distinguishes_remote_outage_without_logging_content():
    def offline(*_args, **_kwargs):
        raise EnrichmentError("HTTP Error 429: external redacted sensitive response")

    result = check_live_providers(
        recording_search=offline,
        lyrics_fetch=offline,
    )
    assert result["both_provider_contracts_live"] is False
    assert result["providers"]["musicbrainz"]["reason"] == "EnrichmentError"
    assert result["providers"]["lrclib"]["reason"] == "EnrichmentError"
    assert "external redacted" not in json.dumps(result)


def test_live_probe_rejects_empty_lyrics_contract():
    result = check_live_providers(
        recording_search=lambda *_args, **_kwargs: [],
        lyrics_fetch=lambda *_args, **_kwargs: {
            "provider": "lrclib", "lyrics": " ", "source_payload": {},
        },
    )
    assert result["providers"]["lrclib"]["reason"] == "invalid_lyrics_contract"
