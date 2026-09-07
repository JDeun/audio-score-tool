from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .enrichment import EnrichmentError, LyricsProvider, choose_high_confidence, fetch_lyrics, search_musicbrainz
from .runtime_settings import runtime_settings
from .song_store_v2 import SongStoreV2

router = APIRouter(prefix="/api/songs", tags=["enrichment"])
_store = SongStoreV2()


class EnrichRequest(BaseModel):
    title: str | None = None
    artist: str | None = None
    apply_high_confidence_metadata: bool = True
    metadata_threshold: int = Field(default=92, ge=70, le=100)
    musicbrainz_commercial_entitlement: bool = False
    lyrics_provider_name: str | None = None
    lyrics_url_template: str | None = None
    lyrics_api_key_env: str | None = None


@router.post("/{song_id}/enrich")
def enrich_song(song_id: str, payload: EnrichRequest) -> dict:
    song = _store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")

    settings = runtime_settings()
    if settings.usage_mode == "commercial" and not payload.musicbrainz_commercial_entitlement:
        raise HTTPException(
            422,
            "상용 모드에서는 MusicBrainz 공개 Web Service의 상용 이용 자격/계약을 확인한 뒤 사용하세요.",
        )

    title = (payload.title or song.get("title") or "").strip()
    artist = (payload.artist if payload.artist is not None else song.get("artist")) or None
    try:
        candidates = search_musicbrainz(title, artist)
    except EnrichmentError as exc:
        candidates = []
        metadata_error = str(exc)
    else:
        metadata_error = None

    selected = choose_high_confidence(candidates, threshold=payload.metadata_threshold)
    applied = False
    if selected and payload.apply_high_confidence_metadata:
        _store.update_metadata(
            song_id,
            title=str(selected.get("title") or title),
            artist=str(selected.get("artist") or artist or "") or None,
        )
        applied = True

    lyrics = None
    lyrics_error = None
    if payload.lyrics_url_template:
        try:
            lyrics = fetch_lyrics(
                LyricsProvider(
                    name=payload.lyrics_provider_name or "configured_provider",
                    url_template=payload.lyrics_url_template,
                    api_key_env=payload.lyrics_api_key_env,
                ),
                title=str((selected or {}).get("title") or title),
                artist=(selected or {}).get("artist") or artist,
            )
        except EnrichmentError as exc:
            lyrics_error = str(exc)

    report = {
        "song_id": song_id,
        "query": {"title": title, "artist": artist},
        "metadata": {
            "provider": "musicbrainz",
            "candidates": candidates,
            "selected": selected,
            "applied": applied,
            "error": metadata_error,
            "policy": "auto-apply only above configured confidence threshold",
            "commercial_entitlement_confirmed": payload.musicbrainz_commercial_entitlement,
        },
        "lyrics": lyrics,
        "lyrics_error": lyrics_error,
        "lyrics_policy": {
            "arbitrary_web_scraping": False,
            "configured_provider_only": True,
            "fallback": "WhisperX transcription/alignment remains authoritative when no licensed provider is configured",
        },
    }
    _store.set_analysis(song_id, "external_enrichment", report)
    if lyrics:
        _store.set_analysis(song_id, "external_lyrics", lyrics)
    return report
