"""Opt-in post-transcription source metadata enrichment.

Local files: embedded title/artist tags take precedence over a consistent
original filename. YouTube: only the video title is a query hint. Neither
channel/uploader nor the filename is accepted as an authoritative author.
When MusicBrainz has no verified match, persist explicit Unknown score
metadata without replacing a later user edit; WhisperX lyrics stay intact.
"""
from __future__ import annotations

from typing import Any

from .enrichment_api import EnrichRequest, _apply_metadata, enrich_song
from .song_store_v2 import SongStoreV2
from .source_metadata_hints import SourceLookupHints, resolve_source_lookup_hints


def _write_unknown_if_unchanged(
    store: SongStoreV2,
    job: dict[str, Any],
) -> bool:
    """Never overwrite a user-edited Song while the external lookup is running."""
    song_id = str(job["job_id"])
    current = store.get(song_id)
    if (
        current is None
        or current.get("revision") != 1
        or not current.get("title")
        or current.get("title") != store._title_from_filename(job.get("filename"))
        or current.get("artist") not in (None, "")
    ):
        return False
    return _apply_metadata(
        song_id,
        current,
        {"provider": "unresolved", "title": "Unknown", "artist": "Unknown"},
        str(current["title"]),
        current.get("artist"),
    )


def enrich_completed_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "done" or job.get("source_kind") not in {"youtube", "local"}:
        return {"status": "not_applicable"}
    if job.get("auto_enrich") is not True:
        return {"status": "disabled"}
    song_id = str(job["job_id"])
    store = SongStoreV2()
    store.sync_completed_jobs([job])
    if not store.get(song_id):
        return {"status": "song_not_created"}

    # This field is attached in memory by the worker. Direct manual/replay
    # entrypoints without it can use a conservative filename fallback.
    hints = job.get("_source_lookup_hints")
    if "_source_lookup_hints" not in job:
        hints = resolve_source_lookup_hints(
            job.get("source_kind"), job.get("filename"),
        )
    if hints is not None and not isinstance(hints, SourceLookupHints):
        hints = None

    metadata: dict[str, Any] = {}
    if hints is not None:
        # Do not send audio or stems; only query terms. An exact title/artist
        # pair plus >=92% MusicBrainz confidence is required before publishing
        # external metadata as confirmed song credits.
        result = enrich_song(
            song_id,
            EnrichRequest(
                title=hints.title,
                artist=hints.artist,
                apply_high_confidence_metadata=True,
                apply_reference_lyrics=False,
                auto_lyrics=False,
                require_exact_match=True,
            ),
        )
        metadata = result.get("metadata") or {}

    selected = metadata.get("selected")
    applied = bool(metadata.get("applied"))
    if applied:
        status = "applied"
    elif selected:
        # A verified candidate could not be committed (e.g. Song revision
        # changed while waiting for network). Never replace that edit.
        status = "verified_not_applied"
    else:
        status = "unknown" if _write_unknown_if_unchanged(store, job) else "unknown_not_applied"

    report = {
        "status": status,
        "provider": "musicbrainz" if hints is not None else None,
        "source_hint": hints.provenance if hints is not None else "missing",
        "matched": selected is not None,
        "query_issued": hints is not None,
        "unknown_fields": (
            ["title", "artist", "album", "performer", "release_date", "composer", "lyricist"]
            if status == "unknown" else []
        ),
        "lyrics_lookup_in_this_stage": False,
        "content_uploaded": False,
        "error": metadata.get("error") or metadata.get("work_credits_error"),
    }
    store.set_analysis(song_id, "automatic_enrichment", report)
    return report
