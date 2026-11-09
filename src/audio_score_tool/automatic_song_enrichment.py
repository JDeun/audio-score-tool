"""Opt-in post-transcription source metadata enrichment.

This runs only for a completed Song whose filename has a clear artist/track
pair. It reuses the same revision-aware enrichment API as the manual editor.
Failure must never invalidate a successful transcription.
"""
from __future__ import annotations

from typing import Any

from .enrichment_api import EnrichRequest, enrich_song
from .song_store_v2 import SongStoreV2
from .source_metadata_hints import title_artist_hints


def enrich_completed_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "done" or job.get("source_kind") not in {"youtube", "local"}:
        return {"status": "not_applicable"}
    if job.get("auto_enrich") is not True:
        return {"status": "disabled"}
    hint = title_artist_hints(job.get("filename"))
    if hint is None:
        return {"status": "no_trusted_title_artist_hint"}
    title, artist = hint
    song_id = str(job["job_id"])
    store = SongStoreV2()
    store.sync_completed_jobs([job])
    if not store.get(song_id):
        return {"status": "song_not_created"}

    # Original audio and generated notation are never uploaded to MusicBrainz.
    # API lyrics were already attempted before WhisperX in the actual pipeline.
    result = enrich_song(
        song_id,
        EnrichRequest(
            title=title, artist=artist,
            apply_high_confidence_metadata=True,
            apply_reference_lyrics=False,
            auto_lyrics=False,
        ),
    )
    metadata = result.get("metadata") or {}
    report = {
        "status": "applied" if metadata.get("applied") else "no_confirmed_match",
        "provider": "musicbrainz",
        "matched": metadata.get("selected") is not None,
        "title_artist_hint_used": True,
        "lyrics_lookup_in_this_stage": False,
        "content_uploaded": False,
        "error": metadata.get("error") or metadata.get("work_credits_error"),
    }
    store.set_analysis(song_id, "automatic_enrichment", report)
    return report
