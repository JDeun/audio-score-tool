"""Real YouTube product release-acceptance contracts with synthetic API replies only.

No source is downloaded, no YouTube URL is opened, and no weights, media, or
third-party executables are included in this test suite.
"""
from __future__ import annotations

import json
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from audio_score_tool.job_store import JobStore
from audio_score_tool.song_store_v2 import SongStoreV2
from scripts import smoke_packaged_sidecar as smoke
from scripts import verify_packaged_managed_features as packaged
from scripts import verify_packaged_youtube_ingest as youtube

_BASE = "http://127.0.0.1:4567"
_TOKEN = "synthetic-local-qa-token"
_VIDEO_ID = "AbC_dEfGh12"
_URL = f"https://www.youtube.com/watch?v={_VIDEO_ID}"
_JOB = "a" * 32


def _review() -> dict:
    return {
        "schema": 1,
        "purpose": "owned-youtube-automated-release-qa-v1",
        "source_url": _URL,
        "video_id": _VIDEO_ID,
        "rights_basis": "original-owned",
        "authorized_for_automated_download_and_transcription": True,
        "may_publish_source_media_as_ci_artifact": False,
        "redistribution_status": "pending",
        "reviewer": "release-QA-person",
        "rights_evidence_reference": "internal-release-review-2026-001",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "max_duration_seconds": 60,
    }


def _approved() -> dict:
    return youtube.reviewed_youtube_source(json.dumps(_review()))


def _midi() -> bytes:
    track = b"\x00\x90\x3c\x64\x81\x40\x80\x3c\x00\x00\xff\x2f\x00"
    return (
        b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480)
        + b"MTrk" + struct.pack(">I", len(track)) + track
    )


def _xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<score-partwise><part-list><score-part id="P1"><part-name>Piano</part-name>'
        b'</score-part></part-list><part id="P1"><measure number="1">'
        b'<note><pitch><step>C</step><octave>4</octave></pitch>'
        b'<duration>1</duration></note></measure></part></score-partwise>'
    )


def test_reviewed_short_owned_video_is_explicit_and_never_an_approval():
    checked = _approved()
    assert checked["video_id"] == _VIDEO_ID
    assert checked["source_url"] == _URL
    assert checked["duration_limit_seconds"] == 60
    assert len(checked["rights_receipt_sha256"]) == 64
    assert checked["authorization_is_operator_claim_not_independent_legal_proof"] is True
    assert set(checked) == {
        "video_id", "source_url", "duration_limit_seconds",
        "rights_receipt_sha256",
        "authorization_is_operator_claim_not_independent_legal_proof",
    }


@pytest.mark.parametrize("mutation", (
    {"video_id": "N0tSameIdX"},
    {"source_url": "https://example.com/watch?v=AbC_dEfGh12"},
    {"source_url": "http://www.youtube.com/watch?v=AbC_dEfGh12"},
    {"source_url": "https://www.youtube.com/watch?v=AbC_dEfGh12&list=playlist"},
    {"source_url": "https://www.youtube.com/watch?v=AbC_dEfGh12#fragment"},
    {"rights_basis": "unknown"},
    {"authorized_for_automated_download_and_transcription": False},
    {"may_publish_source_media_as_ci_artifact": True},
    {"redistribution_status": "approved"},
    {"rights_evidence_reference": "tbd"},
    {"max_duration_seconds": 1800},
    {"max_duration_seconds": True},
    {"reviewed_at": "2024-01-01T00:00:00Z"},
    {"reviewed_at": "not-a-date"},
    {"reviewed_at": "2026-11-08T10:00:00"},  # no offset
))
def test_unauthorized_unbounded_or_unverifiable_youtube_sources_rejected(mutation):
    reviewed = _review()
    reviewed.update(mutation)
    with pytest.raises(packaged.PackagedFeatureAcceptanceError):
        youtube.reviewed_youtube_source(json.dumps(reviewed))


def test_qa_source_must_be_supplied_before_any_install_or_external_call(monkeypatch):
    monkeypatch.delenv("AST_YOUTUBE_QA_RECEIPT_JSON", raising=False)
    monkeypatch.setattr(
        smoke, "_sidecar",
        lambda: (_ for _ in ()).throw(AssertionError("No sidecar may start")),
    )
    monkeypatch.setattr(sys, "argv", ["smoke_packaged_sidecar.py", "--require-managed-delivery"])
    with pytest.raises(
        packaged.PackagedFeatureAcceptanceError, match="explicit owned/licensed",
    ):
        smoke.main()


def test_real_product_youtube_job_to_midi_musicxml_and_canonical_song(monkeypatch):
    calls = []
    status_payload = {
        "ready": True, "js_runtime_ready": True,
        "ffmpeg_ready": True, "ffprobe_ready": True,
    }

    def api(base, token, method, route, **kwargs):
        assert (base, token) == (_BASE, _TOKEN)
        calls.append((method, route))
        if route == "/api/sources/youtube/status":
            return 200, json.dumps(status_payload).encode()
        if route == "/api/sources/youtube/inspect":
            body = json.loads(kwargs["data"])
            assert body == {"url": _URL}
            assert kwargs["content_type"] == "application/json"
            assert kwargs["timeout"] <= 150
            return 200, json.dumps({
                "webpage_url": _URL, "title": "Original owned.mp3",
                "duration": 16.5, "uploader": "Test owner",
            }).encode()
        if route == "/api/jobs/youtube":
            assert json.loads(kwargs["data"]) == {
                "url": _URL, "authorized": True,
                "skip_lyrics": True, "preset": "auto",
            }
            return 202, json.dumps({
                "job_id": _JOB, "source": "youtube", "status": "queued",
            }).encode()
        if route == f"/api/jobs/{_JOB}/files/midi":
            return 200, _midi()
        if route == f"/api/jobs/{_JOB}/files/musicxml":
            return 200, _xml()
        if route == "/api/songs":
            return 200, json.dumps({"songs": [
                {"job_id": _JOB, "source_kind": "youtube", "song_id": _JOB},
            ]}).encode()
        raise AssertionError(f"Unapproved route {route}")

    monkeypatch.setattr(packaged, "_http", api)
    monkeypatch.setattr(packaged, "_await_job", lambda base, token, job_id, **kw: {
        "status": "done", "job_id": job_id, "kind": "transcription",
        "source_kind": "youtube", "result": {"midi": "owned", "musicxml": "owned"},
    })
    proof = youtube.verify_packaged_youtube_ingest(_BASE, _TOKEN, reviewed=_approved())
    assert proof["real_managed_youtube_job_completed"] is True
    assert proof["youtube_song_source_kind_persisted"] is True
    assert proof["youtube_midi_note_ons"] == 1
    assert proof["youtube_musicxml_pitched_notes"] == 1
    assert proof["youtube_musicxml_parts"] == 1
    assert proof["youtube_source_media_uploaded_to_ci"] is False
    assert proof["authorization_independently_verified"] is False
    assert proof["redistribution_status"] == "pending"
    assert calls == [
        ("GET", "/api/sources/youtube/status"),
        ("POST", "/api/sources/youtube/inspect"),
        ("POST", "/api/jobs/youtube"),
        ("GET", f"/api/jobs/{_JOB}/files/midi"),
        ("GET", f"/api/jobs/{_JOB}/files/musicxml"),
        ("GET", "/api/songs"),
    ]


@pytest.mark.parametrize(("failure", "match"), [
    ("status", "fully app-managed"),
    ("different_video", "different YouTube video"),
    ("duration", "exceeds the reviewed"),
    ("no_duration", "duration is unverified"),
    ("wrong_source", "expected Job"),
    ("wrong_job", "durable source provenance"),
    ("missing_midi", "no downloadable MIDI"),
    ("empty_musicxml", "pitched notes"),
    ("missing_song", "exactly one canonical"),
])
def test_unverified_youtube_media_tools_or_song_cannot_pass_release(
    monkeypatch, failure, match,
):
    def api(_base, _token, method, route, **_kwargs):
        if route == "/api/sources/youtube/status":
            return 200, json.dumps({
                "ready": failure != "status", "js_runtime_ready": True,
                "ffmpeg_ready": True, "ffprobe_ready": True,
            }).encode()
        if route == "/api/sources/youtube/inspect":
            return 200, json.dumps({
                "webpage_url": (
                    "https://www.youtube.com/watch?v=QweRTYUio09"
                    if failure == "different_video" else _URL
                ),
                "duration": (
                    None if failure == "no_duration"
                    else 600 if failure == "duration" else 16,
                ),
            }).encode()
        if route == "/api/jobs/youtube":
            return 202, json.dumps({
                "job_id": _JOB, "status": "queued",
                "source": "transcription" if failure == "wrong_source" else "youtube",
            }).encode()
        if route == f"/api/jobs/{_JOB}/files/midi":
            return (404, b"none") if failure == "missing_midi" else (200, _midi())
        if route == f"/api/jobs/{_JOB}/files/musicxml":
            if failure == "empty_musicxml":
                return 200, b'<score-partwise></score-partwise>' * 15
            return 200, _xml()
        if route == "/api/songs":
            return 200, json.dumps({
                "songs": [] if failure == "missing_song" else [
                    {"song_id": _JOB, "source_kind": "youtube", "job_id": _JOB}
                ],
            }).encode()
        raise AssertionError("Unexpected synthetic route")

    monkeypatch.setattr(packaged, "_http", api)
    monkeypatch.setattr(packaged, "_await_job", lambda *_a, **_kw: {
        "kind": "transcription",
        "source_kind": "local" if failure == "wrong_job" else "youtube",
    })
    with pytest.raises(packaged.PackagedFeatureAcceptanceError, match=match):
        youtube.verify_packaged_youtube_ingest(_BASE, _TOKEN, reviewed=_approved())


def test_job_store_persists_explicit_youtube_source_avoids_title_extension_bug(tmp_path: Path):
    store = JobStore(tmp_path / "app.sqlite3")
    store.create(
        _JOB, kind="transcription", status="queued",
        filename="Original recording.mp3", source_kind="youtube",
    )
    job = store.get(_JOB)
    assert job is not None and job["source_kind"] == "youtube"
    assert SongStoreV2._source_kind(job) == "youtube"
    store.update(_JOB, filename="Concert. Recorded 2026.mp3", source_kind="youtube")
    job = store.get(_JOB)
    assert job is not None and SongStoreV2._source_kind(job) == "youtube"
    for unsafe in ("external-http", "https://youtube.com", "", "licenced"):
        with pytest.raises(ValueError, match="source_kind"):
            store.update(_JOB, source_kind=unsafe)


def test_explicit_local_marker_stops_dotted_title_guess_and_legacy_records_remain_unknown(tmp_path):
    store = JobStore(tmp_path / "app.sqlite3")
    store.create(
        "b" * 32, kind="transcription",
        filename="No extension local audio", source_kind="local",
    )
    job = store.get("b" * 32)
    assert job is not None and SongStoreV2._source_kind(job) == "local"
    store.create("c" * 32, kind="transcription", filename="Legacy title.m4a")
    legacy = store.get("c" * 32)
    assert legacy is not None and legacy["source_kind"] is None
    assert SongStoreV2._source_kind(legacy) == "local"
    assert SongStoreV2._source_kind({
        "kind": "omr", "source_kind": "youtube",
    }) == "omr"
    assert SongStoreV2._source_kind({
        "kind": "notation-import", "source_kind": "youtube",
    }) == "notation"


def test_workflow_only_passes_rights_receipt_on_opt_in_native_package_gate():
    text = (
        Path(__file__).resolve().parents[1] / ".github/workflows/desktop-packages.yml"
    ).read_text(encoding="utf-8")
    assert "YOUTUBE_QA_SOURCE_REVIEW_JSON" in text
    assert "AST_YOUTUBE_QA_RECEIPT_JSON:" in text
    assert "require_managed_delivery" in text
    assert "startsWith(github.ref, 'refs/tags/v1')" in text


def test_youtube_job_api_persists_source_kind_before_any_worker_starts(
    monkeypatch, tmp_path: Path,
):
    from audio_score_tool import job_lifecycle_api_v2 as jobs
    from audio_score_tool.runtime_services import YouTubeJobRequest

    reservations = []
    monkeypatch.setattr(jobs, "runtime_settings", lambda: object())
    monkeypatch.setattr(
        jobs, "resolve_job_models", lambda *_a, **_kw: ("small", "small"),
    )
    monkeypatch.setattr(jobs, "preflight", lambda *_a, **_kw: {"ok": True})
    monkeypatch.setattr(jobs, "youtube_tool_status", lambda *_a, **_kw: {"ready": True})
    monkeypatch.setattr(jobs, "jobs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        jobs, "_reserve_or_429",
        lambda job_id, **values: reservations.append((job_id, values)),
    )
    monkeypatch.setattr(jobs, "_start_or_mark_failed", lambda *_a: None)
    payload = YouTubeJobRequest(
        url=_URL, authorized=True, skip_lyrics=True, preset="auto",
    )
    response = jobs.create_youtube_job_v2(payload)
    assert response["source"] == "youtube"
    assert response["status"] == "queued"
    assert len(reservations) == 1
    assert reservations[0][0] == response["job_id"]
    assert reservations[0][1]["source_kind"] == "youtube"
    assert reservations[0][1]["filename"] == "YouTube import"
    assert (tmp_path / response["job_id"]).is_dir()

