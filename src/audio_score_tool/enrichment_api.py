from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .enrichment import (
    EnrichmentError,
    LyricsProvider,
    choose_high_confidence,
    fetch_lyrics,
    search_musicbrainz,
    search_musicbrainz_by_isrc,
)
from .lyrics import attach_lyrics_to_musicxml
from .musicxml_editor import set_score_title
from .publication_layout import apply_publication_layout
from .publication_store_v2 import PublicationStoreV2
from .reference_lyrics import align_reference_lyrics
from .runtime_settings import runtime_settings
from .song_store_v2 import SongStoreV2
from .source_identification import identify_source

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


class IdentifySourceRequest(BaseModel):
    refresh: bool = False
    apply_high_confidence_metadata: bool = True
    musicbrainz_commercial_entitlement: bool = False
    acoustid_commercial_entitlement: bool = False
    acoustid_client_key_env: str = "ACOUSTID_CLIENT_KEY"
    fpcalc_cmd: str = "fpcalc"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_metadata(song_id: str, song: dict, selected: dict, fallback_title: str, fallback_artist: str | None) -> bool:
    next_title = str(selected.get("title") or fallback_title).strip() or "제목 없는 곡"
    next_artist = str(selected.get("artist") or fallback_artist or "").strip() or None
    title_changed = next_title != song.get("title")
    revision: int | None = None
    if title_changed:
        revision = _store.snapshot_revision(song_id, _publication.read(song_id))
        path = _store.checkout_current(song_id)
        try:
            set_score_title(path, next_title)
            apply_publication_layout(path, title=next_title, settings=_publication.read(song_id))
            _store.commit_edit_from_path(song_id, path)
        except Exception:
            if revision is not None:
                _store.discard_snapshot(song_id, revision)
            return False
    try:
        updated = _store.update_metadata(song_id, title=next_title, artist=next_artist)
    except Exception:
        # Keep canonical score metadata and the MusicXML title atomic from the user's
        # perspective. If the DB metadata write fails after the score edit, restore the
        # snapshot instead of leaving two conflicting titles behind.
        if revision is not None:
            _store.restore_revision(song_id, revision)
        return False
    if updated is None and revision is not None:
        _store.restore_revision(song_id, revision)
    return updated is not None


def _source_audio(song_id: str) -> Path | None:
    root = _store.asset_root / song_id
    if not root.exists():
        return None
    matches = sorted(root.glob("original-audio.*"))
    return matches[0] if matches else None


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


@router.post("/{song_id}/identify-source")
def identify_song_source(song_id: str, payload: IdentifySourceRequest) -> dict:
    song = _store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")

    cached = _store.analysis(song_id, "source_identification")
    if cached and not payload.refresh:
        return cached

    audio = _source_audio(song_id)
    if audio is None:
        report = {
            "song_id": song_id,
            "selected": None,
            "applied": False,
            "skipped": "managed original audio asset is unavailable",
        }
        _store.set_analysis(song_id, "source_identification", report)
        return report

    settings = runtime_settings()
    mb_entitled = payload.musicbrainz_commercial_entitlement or _env_flag("AST_MUSICBRAINZ_COMMERCIAL_ENTITLED")
    acoustid_entitled = payload.acoustid_commercial_entitlement or _env_flag("AST_ACOUSTID_COMMERCIAL_ENTITLED")
    report = identify_source(
        audio,
        usage_mode=settings.usage_mode,
        fpcalc_cmd=payload.fpcalc_cmd,
        acoustid_client_key_env=payload.acoustid_client_key_env,
        acoustid_commercial_entitled=acoustid_entitled,
    )

    tags = report.get("embedded_tags") or {}
    selected = report.get("selected")
    musicbrainz_candidates: list[dict] = []
    fuzzy_candidates: list[dict] = []
    mb_error = None
    mb_allowed = settings.usage_mode != "commercial" or mb_entitled

    # ISRC is a cleaner identifier than fuzzy title search and should win when present.
    if tags.get("isrc"):
        if not mb_allowed:
            mb_error = "commercial MusicBrainz Web Service entitlement not confirmed"
        else:
            try:
                musicbrainz_candidates = search_musicbrainz_by_isrc(str(tags["isrc"]))
            except EnrichmentError as exc:
                mb_error = str(exc)
            if musicbrainz_candidates:
                selected = {
                    **musicbrainz_candidates[0],
                    "confidence": 0.99,
                    "reason": "ISRC → MusicBrainz exact identifier path",
                }

    confidence = float((selected or {}).get("confidence") or 0.0)
    if selected and "score" in selected:
        confidence = max(confidence, float(selected.get("score") or 0) / 100.0)

    # The policy has always promised a MusicBrainz fuzzy fallback. Actually execute it
    # when tags/ISRC/AcoustID did not produce an auto-applicable identity. This matters
    # most for YouTube imports whose downloaded audio usually has no useful embedded tags.
    if confidence < 0.92 and mb_allowed:
        query_title = str(tags.get("title") or song.get("title") or "").strip()
        query_artist = str(tags.get("artist") or song.get("artist") or "").strip() or None
        if query_title and query_title not in {"YouTube import", "제목 없는 곡"}:
            try:
                fuzzy_candidates = search_musicbrainz(query_title, query_artist, limit=5)
            except EnrichmentError as exc:
                mb_error = mb_error or str(exc)
            fuzzy = choose_high_confidence(fuzzy_candidates, threshold=92)
            if fuzzy:
                fuzzy_confidence = float(fuzzy.get("score") or 0) / 100.0
                if fuzzy_confidence > confidence:
                    selected = {
                        **fuzzy,
                        "confidence": fuzzy_confidence,
                        "reason": "high-confidence MusicBrainz fuzzy title/artist match",
                    }
                    confidence = fuzzy_confidence
    elif confidence < 0.92 and not mb_allowed and mb_error is None:
        mb_error = "commercial MusicBrainz Web Service entitlement not confirmed"

    applied = False
    if selected and confidence >= 0.92 and payload.apply_high_confidence_metadata:
        applied = _apply_metadata(
            song_id,
            song,
            selected,
            str(song.get("title") or "제목 없는 곡"),
            song.get("artist"),
        )

    final = {
        **report,
        "song_id": song_id,
        "selected": selected,
        "selected_confidence": round(confidence, 4),
        "musicbrainz_isrc_candidates": musicbrainz_candidates,
        "musicbrainz_fuzzy_candidates": fuzzy_candidates,
        "musicbrainz_error": mb_error,
        "applied": applied,
        "policy": {
            **(report.get("policy") or {}),
            "auto_apply_threshold": 0.92,
            "priority": ["embedded tags", "ISRC", "AcoustID fingerprint", "MusicBrainz fuzzy", "model fallback"],
            "acoustid_client_key_embedded": False,
            "commercial_services_require_entitlement": True,
            "musicbrainz_commercial_entitlement": mb_entitled,
            "acoustid_commercial_entitlement": acoustid_entitled,
        },
    }
    _store.set_analysis(song_id, "source_identification", final)
    return final


@router.post("/{song_id}/enrich")
def enrich_song(song_id: str, payload: EnrichRequest) -> dict:
    song = _store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")

    settings = runtime_settings()
    mb_entitled = payload.musicbrainz_commercial_entitlement or _env_flag("AST_MUSICBRAINZ_COMMERCIAL_ENTITLED")
    if settings.usage_mode == "commercial" and not mb_entitled:
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
        applied = _apply_metadata(song_id, song, selected, title, artist)

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
            "policy": "auto-apply only above configured confidence threshold; title is synchronized with MusicXML/layout",
            "commercial_entitlement_confirmed": mb_entitled,
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
