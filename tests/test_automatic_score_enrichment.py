"""No-network tests for API-first lyrics, job metadata and conservative hints."""
from __future__ import annotations

from threading import Event
from types import SimpleNamespace

import pytest

from audio_score_tool import automatic_song_enrichment, runtime_services
from audio_score_tool.job_store import JobStore
from audio_score_tool.source_metadata_hints import title_artist_hints


@pytest.mark.parametrize(("raw", "expected"), [
    ("Green Day - American Idiot [Official Music Video]",
     ("American Idiot", "Green Day")),
    ("Artist – Song Name (Official Audio)", ("Song Name", "Artist")),
    ("Band — Single.wav", ("Single", "Band")),
    ("Group - Song Title (Live)", ("Song Title (Live)", "Group")),
    ("American Idiot", None),
    ("YouTube import", None),
    ("Artist - Official Video", None),
    ("", None),
])
def test_only_explicit_track_artist_title_can_trigger_remote_lookup(raw, expected):
    assert title_artist_hints(raw) == expected


def test_sqlite_job_flag_is_user_opt_in_and_old_rows_are_off(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("legacy", status="done")
    assert store.get("legacy")["auto_enrich"] is False
    store.create(
        "requested", status="done", auto_enrich=True,
        filename="Artist - Track.mp3", source_kind="local",
    )
    assert store.get("requested")["auto_enrich"] is True
    store.update("requested", auto_enrich=False)
    assert store.get("requested")["auto_enrich"] is False


def test_auto_enrichment_reuses_existing_revision_safe_enrich_api(monkeypatch):
    complete = {
        "job_id": "job-1", "status": "done", "source_kind": "youtube",
        "filename": "Green Day - American Idiot (Official Music Video)",
        "auto_enrich": True, "result": {"musicxml": "/private/nonexistent"},
    }
    calls = []
    class FakeStore:
        def sync_completed_jobs(self, jobs):
            calls.append(("sync", jobs[0]["job_id"]))
            return 1

        def get(self, song_id):
            return {"song_id": song_id, "revision": 1}

        def set_analysis(self, song_id, key, data):
            calls.append(("analysis", song_id, key, data["status"]))

    monkeypatch.setattr(automatic_song_enrichment, "SongStoreV2", FakeStore)
    def fake_enrich(song_id, request):
        calls.append(("enrich", song_id, request.title, request.artist,
                      request.auto_lyrics, request.apply_reference_lyrics))
        return {"metadata": {"applied": True, "selected": {"title": request.title}}}

    monkeypatch.setattr(automatic_song_enrichment, "enrich_song", fake_enrich)
    receipt = automatic_song_enrichment.enrich_completed_job(complete)
    assert receipt["status"] == "applied"
    assert calls == [
        ("sync", "job-1"),
        ("enrich", "job-1", "American Idiot", "Green Day", False, False),
        ("analysis", "job-1", "automatic_enrichment", "applied"),
    ]
    complete["filename"] = "Unknown title"
    # A partial mock Song has no valid original title; preserve it rather
    # than asserting that the Unknown placeholder could be committed.
    assert automatic_song_enrichment.enrich_completed_job(complete)["status"] == (
        "unknown_not_applied"
    )
    complete["auto_enrich"] = False
    assert automatic_song_enrichment.enrich_completed_job(complete)["status"] == "disabled"


def test_api_first_lyric_reference_precedes_transcription_and_post_song_lookup(
    tmp_path, monkeypatch,
):
    from audio_score_tool import automatic_song_enrichment as auto
    from audio_score_tool import enrichment

    stored = {
        "job_id": "queued-1", "filename": "Band - Song (Official Audio)",
        "source_kind": "local", "score_mode": "full",
        "auto_enrich": True, "status": "queued",
    }
    calls = []
    class FakeStore:
        def get(self, key):
            assert key == "queued-1"
            return dict(stored)
        def update(self, key, **kwargs):
            stored.update(kwargs)
            calls.append(("store", kwargs["status"])) if "status" in kwargs else None

    class FakeResult:
        warnings: list[str] = []
        def as_dict(self):
            return {"musicxml": str(tmp_path / "score.musicxml"),
                    "warnings": list(self.warnings)}

    def mocked_api(title, artist, **_kwargs):
        calls.append(("api", title, artist))
        return {"provider": "lrclib", "lyrics": "first line", "synced": False}

    def mocked_transcribe(_audio, _root, **kwargs):
        calls.append(("transcribe", kwargs["reference_lyrics"]["provider"]))
        return FakeResult()

    def mocked_postprocess(job):
        calls.append(("after_done", job["status"]))
        return {"status": "applied"}

    monkeypatch.setattr(runtime_services, "_store", FakeStore())
    monkeypatch.setattr(runtime_services, "_acquire_inference_slot", lambda *_: True)
    monkeypatch.setattr(runtime_services, "_inference_lock", SimpleNamespace(
        release=lambda: calls.append(("release",)),
    ))
    monkeypatch.setattr(runtime_services, "_runtime_settings", lambda **_k: SimpleNamespace(
        usage_mode="personal",
    ))
    monkeypatch.setattr(enrichment, "fetch_lrclib_lyrics", mocked_api)
    monkeypatch.setattr(runtime_services, "transcribe", mocked_transcribe)
    monkeypatch.setattr(auto, "enrich_completed_job", mocked_postprocess)
    runtime_services._execute_transcription(
        "queued-1", tmp_path / "audio.wav", "en", False,
        "small", "small", Event(),
    )
    assert calls.index(("api", "Song", "Band")) < calls.index(("transcribe", "lrclib"))
    assert calls[-2:] == [("release",), ("after_done", "done")]
    assert stored["status"] == "done"


def test_external_lyrics_api_error_does_not_fail_song_and_falls_back_to_asr(
    tmp_path, monkeypatch,
):
    from audio_score_tool import automatic_song_enrichment as auto
    from audio_score_tool import enrichment

    stored = {
        "job_id": "q", "filename": "Band - Song", "source_kind": "local",
        "auto_enrich": True, "score_mode": "full", "status": "queued",
    }
    class FakeStore:
        def get(self, _): return dict(stored)
        def update(self, _id, **kwargs): stored.update(kwargs)

    class FakeResult:
        def __init__(self):
            self.warnings = []
        def as_dict(self):
            return {"musicxml": "private://", "warnings": self.warnings}

    calls = []
    def fail_api(*_args, **_kwargs):
        raise enrichment.EnrichmentError("HTTP Error 429: Too Many Requests")
    def transcribe(*_args, **kwargs):
        calls.append(kwargs.get("reference_lyrics"))
        return FakeResult()
    monkeypatch.setattr(runtime_services, "_store", FakeStore())
    monkeypatch.setattr(runtime_services, "_acquire_inference_slot", lambda *_: True)
    monkeypatch.setattr(runtime_services, "_inference_lock", SimpleNamespace(release=lambda: None))
    monkeypatch.setattr(runtime_services, "_runtime_settings",
                        lambda **_kwargs: SimpleNamespace(usage_mode="personal"))
    monkeypatch.setattr(enrichment, "fetch_lrclib_lyrics", fail_api)
    monkeypatch.setattr(runtime_services, "transcribe", transcribe)
    monkeypatch.setattr(auto, "enrich_completed_job", lambda *_args: {"status": "ok"})
    runtime_services._execute_transcription(
        "q", tmp_path / "audio.wav", "en", False, "small", "small", Event(),
    )
    assert calls == [None]
    assert stored["status"] == "done"
    assert "WhisperX" in stored["result"]["warnings"][0]



def test_local_file_tags_drive_api_first_lyrics_and_post_job_musicbrainz(
    tmp_path, monkeypatch,
):
    from audio_score_tool import automatic_song_enrichment as auto
    from audio_score_tool import enrichment, source_identification

    stored = {
        "job_id": "tagged-1",
        "filename": "unnamed_009.mp3",
        "source_kind": "local",
        "score_mode": "full",
        "auto_enrich": True,
        "status": "queued",
    }
    media = tmp_path / "input.mp3"
    media.write_bytes(b"original-test-bytes")
    calls = []

    class FakeStore:
        def get(self, _id):
            return dict(stored)

        def update(self, _id, **update):
            stored.update(update)

    class FakeResult:
        def __init__(self):
            self.warnings = []

        def as_dict(self):
            return {"musicxml": "private://fixture.musicxml", "warnings": self.warnings}

    def tags(_media):
        calls.append(("tags",))
        return {
            "title": "American Idiot",
            "artist": "Green Day",
            "album": "American Idiot",
        }

    def lyrics_api(title, artist, *, album=None):
        calls.append(("lyrics_api", title, artist, album))
        return {"provider": "lrclib", "lyrics": "private-test", "synced": False}

    def transcribe(*_args, **kwargs):
        calls.append(("transcribe", kwargs["reference_lyrics"]["provider"]))
        return FakeResult()

    def postprocess(job):
        hint = job["_source_lookup_hints"]
        calls.append(("musicbrainz_after_done", hint.provenance, hint.title, hint.artist))

    monkeypatch.setattr(runtime_services, "_store", FakeStore())
    monkeypatch.setattr(runtime_services, "_acquire_inference_slot", lambda *_: True)
    monkeypatch.setattr(runtime_services, "_inference_lock", SimpleNamespace(
        release=lambda: calls.append(("release",)),
    ))
    monkeypatch.setattr(runtime_services, "_runtime_settings",
                        lambda **_kw: SimpleNamespace(usage_mode="personal"))
    monkeypatch.setattr(source_identification, "read_embedded_tags", tags)
    monkeypatch.setattr(enrichment, "fetch_lrclib_lyrics", lyrics_api)
    monkeypatch.setattr(runtime_services, "transcribe", transcribe)
    monkeypatch.setattr(auto, "enrich_completed_job", postprocess)

    runtime_services._execute_transcription(
        "tagged-1", media, "en", False, "small", "small", Event(),
    )
    assert calls == [
        ("tags",),
        ("lyrics_api", "American Idiot", "Green Day", "American Idiot"),
        ("transcribe", "lrclib"),
        ("release",),
        ("musicbrainz_after_done", "embedded_tags", "American Idiot", "Green Day"),
    ]
    assert stored["status"] == "done"


def test_unknown_local_filename_without_tags_skips_lyric_api_but_still_runs_asr(
    tmp_path, monkeypatch,
):
    from audio_score_tool import automatic_song_enrichment as auto
    from audio_score_tool import enrichment, source_identification

    stored = {
        "job_id": "unknown-1",
        "filename": "filename_not_song_727299.mp3",
        "source_kind": "local",
        "score_mode": "full",
        "auto_enrich": True,
        "status": "queued",
    }
    media = tmp_path / "input.mp3"
    media.write_bytes(b"local-synthetic")
    observations = []

    class FakeStore:
        def get(self, _id):
            return dict(stored)

        def update(self, _id, **update):
            stored.update(update)

    class FakeResult:
        def __init__(self):
            self.warnings = []

        def as_dict(self):
            return {"musicxml": "fixture", "warnings": self.warnings}

    def no_api(*_args, **_kwargs):
        pytest.fail("No artist/title query: must not call LRCLIB")

    def transcribe(*_args, **kwargs):
        observations.append(("transcribe", kwargs.get("reference_lyrics")))
        assert kwargs["skip_lyrics"] is False
        return FakeResult()

    monkeypatch.setattr(runtime_services, "_store", FakeStore())
    monkeypatch.setattr(runtime_services, "_acquire_inference_slot", lambda *_: True)
    monkeypatch.setattr(runtime_services, "_inference_lock",
                        SimpleNamespace(release=lambda: observations.append(("release",))))
    monkeypatch.setattr(runtime_services, "_runtime_settings",
                        lambda **_kw: SimpleNamespace(usage_mode="personal"))
    monkeypatch.setattr(source_identification, "read_embedded_tags", lambda _: {})
    monkeypatch.setattr(enrichment, "fetch_lrclib_lyrics", no_api)
    monkeypatch.setattr(runtime_services, "transcribe", transcribe)
    monkeypatch.setattr(
        auto, "enrich_completed_job",
        lambda job: observations.append(("unknown_after_done", job["_source_lookup_hints"])),
    )

    runtime_services._execute_transcription(
        "unknown-1", media, "en", False, "small", "small", Event(),
    )
    assert observations == [
        ("transcribe", None),
        ("release",),
        ("unknown_after_done", None),
    ]
    assert stored["status"] == "done"
