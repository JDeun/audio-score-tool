from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .enrichment import EnrichmentError, LyricsProvider, choose_high_confidence, fetch_lyrics, search_musicbrainz
from .lyrics import attach_lyrics_to_musicxml
from .publication_store_v2 import PublicationStoreV2
from .reference_lyrics import align_reference_lyrics
from .runtime_settings import runtime_settings
from .song_store_v2 import SongStoreV2

router = APIRouter(prefix="/api/songs", tags=["enrichment"])
_store = SongStoreV2()
_publication = PublicationStoreV2()


class EnrichRequest(BaseModel):
    title: str | None = None
    artist: str | None = None
    apply_high_confidence_metadata: bool = True
    metadata_threshold: int = Field(default=92, ge=70, le=100)
    musicbrainz_commercial_entitlement: bool = False
    lyrics_provider_name: str | None = None
    lyrics_url_template: str | None = None
    lyrics_api_key_env: str | None = None
    apply_reference_lyrics: bool = False


def _apply_external_lyrics(song_id: str, text: str) -> dict:
    transcript = _store.analysis(song_id, "lyrics_transcript")
    alignment = _store.analysis(song_id, "lyric_alignment") or {}
    language = alignment.get("language") if isinstance(alignment, dict) else None
    timed, stats = align_reference_lyrics(transcript, text, language=language)
    if not timed:
        return {"applied": False, "reason": "WhisperX word timing이 없어 외부 가사를 안전하게 정렬할 수 없습니다.", "stats": stats}

    song = _store.get(song_id)
    if not song:
        return {"applied": False, "reason": "Song not found", "stats": stats}
    revision = _store.snapshot_revision(song_id, _publication.read(song_id))
    source = _store.checkout_current(song_id)
    destination = _store.cache_song_dir(song_id) / "score.reference-lyrics.musicxml"
    try:
        part_id, attached = attach_lyrics_to_musicxml(source, destination, timed)
        _store.commit_edit_from_path(song_id, destination)
    except Exception as exc:  # noqa: BLE001 - preserve current score on reference mismatch
        _store.discard_snapshot(song_id, revision)
        return {"applied": False, "reason": str(exc), "stats": stats}
    return {"applied": True, "part_id": part_id, "attached_tokens": attached, "stats": stats}


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
    lyric_application = None
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
            if lyrics and payload.apply_reference_lyrics:
                lyric_application = _apply_external_lyrics(song_id, lyrics["lyrics"])
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
        "lyric_application": lyric_application,
        "lyrics_policy": {
            "arbitrary_web_scraping": False,
            "configured_provider_only": True,
            "text_source": "configured external provider when available",
            "timing_source": "WhisperX/acoustic evidence",
            "fallback": "WhisperX transcription/alignment remains authoritative when no licensed provider is configured",
        },
    }
    _store.set_analysis(song_id, "external_enrichment", report)
    if lyrics:
        _store.set_analysis(song_id, "external_lyrics", lyrics)
    if lyric_application:
        _store.set_analysis(song_id, "reference_lyrics_alignment", lyric_application)
    return report
