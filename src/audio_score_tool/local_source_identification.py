"""Registration-time *local-only* embedded tag identification.

Only invoked when the user enables the persisted preference. Never calls
AcoustID, MusicBrainz, fpcalc, or any network service. Failed optional tag
processing must never fail a completed music transcription/ingestion.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .musicxml_editor import set_score_title
from .publication_layout import apply_publication_layout
from .publication_store_v2 import PublicationStoreV2
from .source_identification import read_embedded_tags

if TYPE_CHECKING:
    from .song_store_v2 import SongStoreV2


def identify_local_on_import(store: SongStoreV2, song_id: str, audio: Path) -> dict:
    current = store.get(song_id)
    result: dict = {
        "song_id": song_id,
        "mode": "local_only_on_import",
        "source_asset": audio.name,
        "network_attempted": False,
        "fingerprint_attempted": False,
        "selected": None,
        "applied": False,
        "status": "no_tags",
    }
    if current is None or current.get("source_kind") not in {"local", "youtube"}:
        result["status"] = "not_audio_song"
        return result
    try:
        tags = read_embedded_tags(audio)
        result["embedded_tags"] = tags
        title = str(tags.get("title") or "").strip()
        artist = str(tags.get("artist") or "").strip()
        if not title or not artist:
            result["status"] = "insufficient_local_tags"
        else:
            result["selected"] = {
                "title": title,
                "artist": artist,
                "provider": "embedded_tags",
                "confidence": 1.0,
            }
            # New import has revision 1. Never overwrite a later user edit or
            # a concurrent enrichment; atomic CAS protects a race after reading.
            if int(current.get("revision") or 0) != 1:
                result["status"] = "changed_after_import"
            else:
                publication = PublicationStoreV2(path=store.path).read(song_id)
                score = store.checkout_current(song_id)
                if title != current.get("title"):
                    set_score_title(score, title)
                    apply_publication_layout(score, title=title, settings=publication)
                store.commit_identified_metadata(
                    song_id,
                    title=title,
                    artist=artist,
                    score_xml=score.read_text(encoding="utf-8"),
                    publication=publication,
                    expected_revision=1,
                )
                result["applied"] = True
                result["status"] = "identified"
    except Exception as exc:
        # Never turn a valid completed transcription into a failed import.
        result["status"] = "local_identification_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"

    # This analysis is independent of the explicit /identify-source cache, so
    # a later user request can choose whether to consult licensed providers.
    store.set_analysis(song_id, "local_tag_identification", result)
    return result
