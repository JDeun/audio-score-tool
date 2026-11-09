from __future__ import annotations

import os
import unicodedata
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .enrichment import (
    EnrichmentError,
    LyricsProvider,
    choose_high_confidence,
    fetch_lrclib_lyrics,
    fetch_lyrics,
    lookup_musicbrainz_work_credits,
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
    apply_reference_lyrics: bool = True
    auto_lyrics: bool = True
    require_exact_match: bool = False


class IdentifySourceRequest(BaseModel):
    refresh: bool = False
    apply_high_confidence_metadata: bool = True
    musicbrainz_commercial_entitlement: bool = False
    acoustid_commercial_entitlement: bool = False
    acoustid_client_key_env: str = "ACOUSTID_CLIENT_KEY"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_metadata(
    song_id: str,
    song: dict,
    selected: dict,
    fallback_title: str,
    fallback_artist: str | None,
) -> bool:
    """Save a trusted identification as one atomic, undoable Song mutation.

    The previous two-step XML edit followed by metadata UPDATE caused partial
    title/artist changes, and artist-only changes had no Undo revision.
    Compute score layout first; commit only if the original song revision is
    still current, so late network results cannot overwrite a later user edit.
    """
    next_title = str(selected.get("title") or fallback_title).strip() or "제목 없는 곡"
    next_artist = str(selected.get("artist") or fallback_artist or "").strip() or None
    try:
        current_publication = _publication.read(song_id)
        updated_publication = dict(current_publication)
        auto_unknown = (
            (_store.analysis(song_id, "automatic_enrichment") or {}).get("status")
            == "unknown"
        )

        def fillable(field: str) -> bool:
            current = str(updated_publication.get(field) or "").strip()
            return not current or (auto_unknown and current == "Unknown")

        # Unknown is an explicit unresolved marker, not an artist/author
        # guess. Missing credits can later be filled by verified API matches;
        # user-entered credits are never overwritten by automatic lookup.
        if selected.get("provider") == "unresolved":
            for field in ("album", "performer", "release_date", "composer", "lyricist"):
                if not str(updated_publication.get(field) or "").strip():
                    updated_publication[field] = "Unknown"
        elif selected.get("provider") == "musicbrainz":
            # Title/artist can agree across multiple recordings while album,
            # recording version and songwriter Work differ. Mark only those
            # *unresolved* details Unknown instead of choosing a first result.
            if selected.get("match_scope") == "song_identity_only_ambiguous_recording":
                for field in ("album", "release_date", "composer", "lyricist"):
                    if not str(updated_publication.get(field) or "").strip():
                        updated_publication[field] = "Unknown"
            for field, suggested in (
                ("album", selected.get("album")),
                ("performer", next_artist),
                ("release_date", selected.get("first_release_date")),
            ):
                if suggested and fillable(field):
                    updated_publication[field] = str(suggested).strip()[:300]
            if selected.get("songwriters_verified") is True:
                for field in ("composer", "lyricist"):
                    value = selected.get(field)
                    if value and fillable(field):
                        updated_publication[field] = str(value).strip()[:200]
        expected_revision = int(song["revision"])
        credits_changed = updated_publication != current_publication
        if next_title != song.get("title") or credits_changed:
            score = _store.checkout_current(song_id)
            if next_title != song.get("title"):
                set_score_title(score, next_title)
            apply_publication_layout(
                score, title=next_title, settings=updated_publication
            )
            xml_text = score.read_text(encoding="utf-8")
        else:
            xml_text = _store.score_xml(song_id)
        _store.commit_identified_metadata(
            song_id,
            title=next_title,
            artist=next_artist,
            score_xml=xml_text,
            publication=current_publication,
            next_publication=updated_publication if credits_changed else None,
            expected_revision=expected_revision,
        )
        return True
    except Exception:
        # Fail closed without changing the canonical Song, exporting an
        # incomplete revision, or reapplying stale source-identification data.
        return False


def _same_song_identity(left: object, right: object) -> bool:
    """Conservative exact identity after Unicode/case/space normalization."""
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    return (
        bool(left.strip()) and bool(right.strip())
        and " ".join(unicodedata.normalize("NFKC", left).casefold().split())
        == " ".join(unicodedata.normalize("NFKC", right).casefold().split())
    )


def _with_work_credits(selected: dict) -> tuple[dict, str | None]:
    """Attach independently verified creator relations; never guess from performer."""
    mbid = selected.get("recording_mbid")
    if not mbid or selected.get("provider") != "musicbrainz":
        return selected, None
    try:
        credits = lookup_musicbrainz_work_credits(str(mbid))
    except EnrichmentError as exc:
        return selected, str(exc)
    return {
        **selected,
        "composer": credits.get("composer"),
        "lyricist": credits.get("lyricist"),
        "work_mbid": credits.get("work_mbid"),
        "songwriters_verified": credits.get("status") == "verified_work_relations",
    }, None


def _source_audio(song_id: str) -> Path | None:
    root = _store.asset_root / song_id
    if root.is_dir() and not root.is_symlink():
        matches = sorted(
            item for item in root.glob("original-audio.*")
            if item.is_file() and not item.is_symlink()
        )
        if len(matches) == 1:
            return matches[0]
    # Songs ingested before #106 never copied the original audio out of the
    # temporary Job workspace. A manual user-initiated lookup may recover it,
    # if storage cleanup has not already deleted the Job input.
    song = _store.get(song_id)
    if song and song.get("source_kind") in {"local", "youtube"}:
        try:
            return _store._preserve_original_audio(song_id)
        except OSError:
            return None
    return None


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
    destination = source.with_name(f"{source.stem}.reference-lyrics.musicxml")
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
            "status": "no_audio",
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

    work_credits_error = None
    if selected and confidence >= 0.92:
        selected, work_credits_error = _with_work_credits(selected)

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
        "status": "identified" if confidence >= 0.92 else "unresolved",
        "musicbrainz_isrc_candidates": musicbrainz_candidates,
        "musicbrainz_fuzzy_candidates": fuzzy_candidates,
        "musicbrainz_error": mb_error,
        "work_credits_error": work_credits_error,
        "applied": applied,
        "policy": {
            **(report.get("policy") or {}),
            "auto_apply_threshold": 0.92,
            "priority": ["embedded tags", "ISRC", "AcoustID fingerprint", "MusicBrainz fuzzy", "model fallback"],
            "fpcalc_executable": "fixed application dependency; not caller-controlled",
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
    mb_allowed = settings.usage_mode != "commercial" or mb_entitled

    title = (payload.title or song.get("title") or "").strip()
    artist = (payload.artist if payload.artist is not None else song.get("artist")) or None
    if mb_allowed:
        try:
            candidates = search_musicbrainz(title, artist)
        except EnrichmentError as exc:
            candidates = []
            metadata_error = str(exc)
        else:
            metadata_error = None
    else:
        candidates = []
        metadata_error = "MusicBrainz commercial API entitlement not confirmed"

    if payload.require_exact_match:
        candidates = [
            item for item in candidates
            if _same_song_identity(item.get("title"), title)
            and _same_song_identity(item.get("artist"), artist)
        ]
    selected = choose_high_confidence(candidates, threshold=payload.metadata_threshold)
    if payload.require_exact_match and selected is not None:
        eligible = [
            item for item in candidates
            if int(item.get("score") or 0) >= payload.metadata_threshold
        ]
        recording_ids = {
            str(item.get("recording_mbid") or f"missing-{index}")
            for index, item in enumerate(eligible)
        }
        if len(recording_ids) > 1:
            # The same song-level identity occurs on different recordings.
            # Both name fields may be confirmed, but selecting one recording
            # would assign a possibly unrelated album/Work writer to the user.
            selected = {
                "provider": "musicbrainz",
                "title": title,
                "artist": artist,
                "score": int(selected.get("score") or 0),
                "recording_mbid": None,
                "album": None,
                "first_release_date": None,
                "match_scope": "song_identity_only_ambiguous_recording",
                "ambiguous_recording_count": len(recording_ids),
            }
    work_credits_error = None
    if selected:
        selected, work_credits_error = _with_work_credits(selected)
    applied = False
    if selected and payload.apply_high_confidence_metadata:
        applied = _apply_metadata(song_id, song, selected, title, artist)

    lyrics = None
    lyrics_error = None
    lyric_application = None
    lyrics_title = str((selected or {}).get("title") or title)
    lyrics_artist = (selected or {}).get("artist") or artist
    # Explicit user-configured provider is preferred. Personal-use LRCLIB
    # requires no API key; never silently query it from a commercial session.
    try:
        if payload.lyrics_url_template:
            lyrics = fetch_lyrics(
                LyricsProvider(
                    name=payload.lyrics_provider_name or "configured_provider",
                    url_template=payload.lyrics_url_template,
                    api_key_env=payload.lyrics_api_key_env,
                ),
                title=lyrics_title, artist=lyrics_artist,
            )
        elif payload.auto_lyrics and settings.usage_mode == "personal":
            lyrics = fetch_lrclib_lyrics(
                lyrics_title, lyrics_artist,
                album=(selected or {}).get("album"),
            )
    except EnrichmentError as exc:
        lyrics_error = str(exc)
    if lyrics and payload.apply_reference_lyrics:
        lyric_application = _apply_external_lyrics(song_id, lyrics["lyrics"])

    # WhisperX was executed during transcription when the user enabled
    # lyrics. If the external API has no entry or is unreachable, preserve
    # that acoustic transcript and its already-attached score lyrics.
    fallback = "external_api" if lyrics else (
        "whisperx" if _store.analysis(song_id, "lyrics_transcript") else "unavailable"
    )

    report = {
        "song_id": song_id,
        "query": {"title": title, "artist": artist},
        "metadata": {
            "provider": "musicbrainz",
            "candidates": candidates,
            "selected": selected,
            "applied": applied,
            "error": metadata_error,
            "work_credits_error": work_credits_error,
            "policy": "auto-apply only above configured confidence threshold; title is synchronized with MusicXML/layout",
            "commercial_entitlement_confirmed": mb_entitled,
        },
        "lyrics": lyrics,
        "lyrics_error": lyrics_error,
        "lyric_application": lyric_application,
        "lyrics_source": fallback,
        "lyrics_policy": {
            "arbitrary_web_scraping": False,
            "provider_priority": ["configured_licensed_api", "lrclib_personal", "whisperx"],
            "configured_provider_only": settings.usage_mode == "commercial",
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
