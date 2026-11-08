"""Release-only, real packaged YouTube→managed yt-dlp→AMT→Song acceptance.

There is deliberately no public default test video. A release operator must
supply recent metadata describing a video they own or are licensed to process.
The metadata is a human authorization *claim*, not independent legal proof.

The original URL is passed only to the already-running frozen sidecar's
authenticated product API. This checker never downloads source bytes, follows
external URLs, invokes host yt-dlp/Python models, or uploads media as CI artifacts.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from audio_score_tool.youtube import YouTubeSourceError, validate_youtube_url
from scripts import verify_packaged_managed_features as packaged

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_SCHEMA = "owned-youtube-automated-release-qa-v1"
_MAX_RECEIPT_BYTES = 8192
_MAX_DURATION_SECONDS = 180
_MAX_REVIEW_AGE_DAYS = 180


def _fail(reason: str) -> None:
    raise packaged.PackagedFeatureAcceptanceError(reason)


def _canonical_video_id(url: str) -> str:
    """Require an exact canonical video URL, not a playlist/redirect/short."""
    try:
        validated = validate_youtube_url(url)
    except (YouTubeSourceError, ValueError) as exc:
        raise packaged.PackagedFeatureAcceptanceError("YouTube QA source URL is invalid") from exc
    parsed = urlparse(validated)
    values = parse_qs(parsed.query, keep_blank_values=True)
    ids = values.get("v", [])
    if (
        parsed.scheme != "https" or parsed.netloc != "www.youtube.com"
        or parsed.path != "/watch" or parsed.fragment or len(ids) != 1
        or set(values) != {"v"} or not _VIDEO_ID.fullmatch(ids[0])
        or validated != f"https://www.youtube.com/watch?v={ids[0]}"
    ):
        _fail("YouTube QA source must be a canonical single-video HTTPS watch URL")
    return ids[0]


def reviewed_youtube_source(raw: str | None) -> dict[str, Any]:
    """Validate a tightly scoped operator-provided rights receipt.

    A matching JSON receipt proves only that the operator opted in and that
    the source is bounded. It does not verify media ownership/YouTube ToS.
    """
    if not isinstance(raw, str) or not 2 <= len(raw.encode("utf-8")) <= _MAX_RECEIPT_BYTES:
        _fail("YouTube release acceptance requires an explicit owned/licensed source review receipt")
    try:
        item = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise packaged.PackagedFeatureAcceptanceError("YouTube QA rights receipt is invalid JSON") from exc
    if not isinstance(item, dict) or item.get("schema") != 1 or item.get("purpose") != _SCHEMA:
        _fail("YouTube QA rights receipt has an unsupported schema")
    url, video_id = item.get("source_url"), item.get("video_id")
    if not isinstance(url, str) or not isinstance(video_id, str):
        _fail("YouTube QA rights receipt lacks source URL or video ID")
    if _canonical_video_id(url) != video_id:
        _fail("YouTube QA source URL does not match the reviewed video ID")
    if (
        item.get("rights_basis") not in {"original-owned", "separately-licensed-for-qa"}
        or item.get("authorized_for_automated_download_and_transcription") is not True
        or item.get("may_publish_source_media_as_ci_artifact") is not False
        or item.get("redistribution_status") != "pending"
    ):
        _fail("YouTube QA source was not explicitly authorized for private processing")
    for field in ("reviewer", "rights_evidence_reference"):
        label = item.get(field)
        if (
            not isinstance(label, str) or not 6 <= len(label.strip()) <= 300
            or label.strip().lower() in {"unknown", "none", "tbd", "placeholder"}
        ):
            _fail(f"YouTube QA source has no accountable {field}")
    limit = item.get("max_duration_seconds")
    if type(limit) is not int or not 5 <= limit <= _MAX_DURATION_SECONDS:
        _fail("YouTube QA source maximum runtime must be between 5 and 180 seconds")
    reviewed_at = item.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        _fail("YouTube QA rights receipt has no review date")
    try:
        reviewed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise packaged.PackagedFeatureAcceptanceError("YouTube QA review date is invalid") from exc
    if reviewed.tzinfo is None or reviewed.utcoffset() is None:
        _fail("YouTube QA review date must specify a timezone")
    now = datetime.now(timezone.utc)
    if reviewed > now + timedelta(minutes=5) or now - reviewed > timedelta(days=_MAX_REVIEW_AGE_DAYS):
        _fail("YouTube QA source rights review is stale or future-dated")
    # Hash metadata, not the third-party media. Do not log any URL or its title.
    return {
        "video_id": video_id,
        "source_url": url,
        "duration_limit_seconds": limit,
        "rights_receipt_sha256": hashlib.sha256(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "authorization_is_operator_claim_not_independent_legal_proof": True,
    }


def verify_packaged_youtube_ingest(
    base: str, token: str, *,
    reviewed: dict[str, Any],
    job_timeout_seconds: float = 1200,
) -> dict[str, Any]:
    """Real approved managed yt-dlp/Deno/FFmpeg→audio→MT3→Song via frozen API."""
    if not isinstance(reviewed, dict) or not isinstance(reviewed.get("source_url"), str):
        _fail("YouTube QA rights receipt was not validated before starting")
    source_url = reviewed["source_url"]
    video_id = reviewed.get("video_id")
    if video_id != _canonical_video_id(source_url):
        _fail("YouTube QA URL/video ID changed after rights preflight")

    status, raw = packaged._http(base, token, "GET", "/api/sources/youtube/status")
    tools = packaged._json_ok(status, raw, name="packaged YouTube toolchain")
    if any(tools.get(key) is not True for key in (
        "ready", "js_runtime_ready", "ffmpeg_ready", "ffprobe_ready",
    )):
        _fail("Packaged YouTube toolchain is not fully app-managed and ready")
    status, raw = packaged._http(
        base, token, "POST", "/api/sources/youtube/inspect",
        data=json.dumps({"url": source_url}).encode(),
        content_type="application/json", timeout=150,
    )
    metadata = packaged._json_ok(status, raw, name="packaged reviewed YouTube inspection")
    webpage = metadata.get("webpage_url")
    if not isinstance(webpage, str) or _canonical_video_id(webpage) != video_id:
        _fail("yt-dlp resolved a different YouTube video from the reviewed QA source")
    duration = metadata.get("duration")
    if (
        isinstance(duration, bool) or not isinstance(duration, (int, float))
        or not math.isfinite(duration) or not 0 < duration <= reviewed["duration_limit_seconds"]
    ):
        _fail("YouTube QA media duration is unverified or exceeds the reviewed bound")
    # Require explicit user/content permission confirmation on the *real* API,
    # but never claim it is an independent legal signoff.
    job_data = json.dumps({
        "url": source_url, "authorized": True, "skip_lyrics": True, "preset": "auto",
    }).encode()
    status, raw = packaged._http(
        base, token, "POST", "/api/jobs/youtube",
        data=job_data, content_type="application/json", timeout=60,
    )
    created = packaged._json_ok(status, raw, name="packaged YouTube Job", expected=202)
    job_id = created.get("job_id")
    if (
        not isinstance(job_id, str) or packaged._JOB_ID.fullmatch(job_id) is None
        or created.get("status") != "queued" or created.get("source") != "youtube"
    ):
        _fail("Packaged YouTube ingress did not queue the expected Job")
    completed = packaged._await_job(
        base, token, job_id, timeout_seconds=job_timeout_seconds,
    )
    if completed.get("kind") != "transcription" or completed.get("source_kind") != "youtube":
        _fail("Completed YouTube Job lost its durable source provenance")
    status, midi = packaged._http(base, token, "GET", f"/api/jobs/{job_id}/files/midi")
    if status != 200:
        _fail(f"Packaged YouTube→AMT Job produced no downloadable MIDI (HTTP {status})")
    midi_note_count = packaged._midi_note_count(midi)
    status, xml = packaged._http(base, token, "GET", f"/api/jobs/{job_id}/files/musicxml")
    if status != 200:
        _fail(f"Packaged YouTube→AMT Job produced no MusicXML (HTTP {status})")
    musicxml_notes, musicxml_parts = packaged._musicxml_note_count(xml)

    status, raw = packaged._http(base, token, "GET", "/api/songs")
    songs = packaged._json_ok(status, raw, name="packaged YouTube canonical Song list")
    candidates = songs.get("songs")
    if not isinstance(candidates, list):
        _fail("YouTube Job was not ingested into the Song library")
    rows = [
        entry for entry in candidates
        if isinstance(entry, dict) and entry.get("job_id") == job_id
        and entry.get("source_kind") == "youtube"
    ]
    if len(rows) != 1 or rows[0].get("song_id") != job_id:
        _fail("YouTube Job was not persisted as exactly one canonical YouTube Song")

    return {
        "schema_version": "1",
        "reviewed_video_id": video_id,
        "rights_receipt_sha256": reviewed["rights_receipt_sha256"],
        "authorized_youtube_metadata_inspection_verified": True,
        "youtube_video_identity_and_duration_verified": True,
        "real_managed_youtube_job_completed": True,
        "youtube_midi_note_ons": midi_note_count,
        "youtube_musicxml_pitched_notes": musicxml_notes,
        "youtube_musicxml_parts": musicxml_parts,
        "youtube_song_source_kind_persisted": True,
        "youtube_source_media_uploaded_to_ci": False,
        "authorization_independently_verified": False,
        "redistribution_status": "pending",
    }
