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
    assert result["providers"]["musicbrainz"]["http_status"] == 429
    assert result["providers"]["lrclib"]["http_status"] == 429
    assert "external redacted" not in json.dumps(result)


def test_live_probe_rejects_empty_lyrics_contract():
    result = check_live_providers(
        recording_search=lambda *_args, **_kwargs: [],
        lyrics_fetch=lambda *_args, **_kwargs: {
            "provider": "lrclib", "lyrics": " ", "source_payload": {},
        },
    )
    assert result["providers"]["lrclib"]["reason"] == "invalid_lyrics_contract"



def test_live_probe_checks_selected_recording_release_identity_without_response_payload():
    calls = []
    recording = "00000000-0000-0000-0000-000000000001"
    release = "11111111-1111-1111-1111-111111111111"

    def search(title, artist, *, limit):
        return [{
            "title": title, "artist": artist, "score": 100,
            "recording_mbid": recording, "release_mbid": release,
        }]

    def choice(mbid, *, release_mbid):
        calls.append((mbid, release_mbid))
        return {
            "title": "American Idiot", "artist": "Green Day",
            "recording_mbid": mbid, "release_mbid": release_mbid,
            "album": "Sensitive album title stays out of public metadata",
        }

    def writer(_mbid):
        return {"status": "ambiguous_or_missing_work", "composer": None, "lyricist": None}

    def lyric(_title, _artist, **_kwargs):
        return {
            "provider": "lrclib", "lyrics": "private lyric content remains local",
            "source_payload": {}, "synced": True,
        }

    result = check_live_providers(
        recording_search=search, work_lookup=writer,
        recording_choice_lookup=choice, lyrics_fetch=lyric,
    )
    assert calls == [(recording, release)]
    assert result["both_provider_contracts_live"] is True
    assert result["providers"]["musicbrainz"]["recording_choice_binding_verified"] is True
    assert "Sensitive album" not in json.dumps(result)
    assert "private lyric" not in json.dumps(result)


def test_live_probe_does_not_call_untrusted_recording_choice_on_mismatched_search_result():
    def bad_search(*_args, **_kwargs):
        return [{
            "title": "Wrong Song", "artist": "Different Artist",
            "score": 100, "recording_mbid": "00000000-0000-0000-0000-000000000001",
        }]

    def fail(*_args, **_kwargs):
        raise AssertionError("Must not fetch an unrelated recording")

    result = check_live_providers(
        recording_search=bad_search,
        work_lookup=fail,
        recording_choice_lookup=fail,
        lyrics_fetch=lambda *_args, **_kwargs: None,
    )
    assert result["providers"]["musicbrainz"]["high_confidence_selected"] is False
    assert "recording_choice_binding_verified" not in result["providers"]["musicbrainz"]
