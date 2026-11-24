from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .chord_editor import ChordEditError, set_chord_at_note
from .chord_listing import list_chords
from .job_store import JobStore
from .musicxml_editor import MusicXMLEditError, score_summary, set_score_title, update_note
from .musicxml_parts import list_score_parts
from .note_evidence import (
    baseline,
    baseline_fingerprint,
    clock_signature,
    linked_source_ids,
    resolve_lineage,
    rhythm_lineage,
    score_hash,
    written_notes,
)
from .publication_layout import apply_publication_layout, initial_publication_settings
from .publication_store_v2 import PublicationStoreV2
from .score_structure import (
    delete_measure,
    delete_note,
    insert_measure,
    insert_note,
    rhythm_edit,
    set_measure_signature,
    structure_summary,
    update_note_structure,
)
from .song_store_v2 import ConcurrentEditError, SongStoreV2
from .song_tombstones import SongTombstoneStore

router = APIRouter(prefix="/api/songs", tags=["songs-v2"])
_song_store = SongStoreV2()
_job_store = JobStore()
_publication_store = PublicationStoreV2()
_tombstones = SongTombstoneStore()


class SongMetadataPatch(BaseModel):
    title: str | None = None
    artist: str | None = None


class NotePatch(BaseModel):
    step: str | None = None
    alter: int | None = None
    octave: int | None = None
    lyric: str | None = None


class EditPreconditions(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    expected_score_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_generation: int | None = Field(default=None, ge=0)

    def preconditions(self) -> dict:
        return self.model_dump(include={"expected_revision", "expected_score_sha256", "expected_generation"})


class ChordPatch(EditPreconditions):
    symbol: str | None = None


class PublicationPatch(BaseModel):
    page_size: Literal["A4", "LETTER"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    bars_per_system: int | None = Field(default=None, ge=1, le=12)
    systems_per_page: int | None = Field(default=None, ge=1, le=12)
    system_distance_mm: float | None = Field(default=None, ge=3, le=40)
    first_page_title_space_mm: float | None = Field(default=None, ge=15, le=90)
    top_margin_mm: float | None = Field(default=None, ge=5, le=40)
    bottom_margin_mm: float | None = Field(default=None, ge=5, le=40)
    left_margin_mm: float | None = Field(default=None, ge=5, le=40)
    right_margin_mm: float | None = Field(default=None, ge=5, le=40)
    title_font_size: float | None = Field(default=None, ge=14, le=48)
    subtitle_font_size: float | None = Field(default=None, ge=8, le=28)
    credit_font_size: float | None = Field(default=None, ge=7, le=18)
    subtitle: str | None = Field(default=None, max_length=200)
    album: str | None = Field(default=None, max_length=300)
    performer: str | None = Field(default=None, max_length=300)
    release_date: str | None = Field(default=None, max_length=50)
    composer: str | None = Field(default=None, max_length=200)
    lyricist: str | None = Field(default=None, max_length=200)
    arranger: str | None = Field(default=None, max_length=200)
    rights: str | None = Field(default=None, max_length=500)


NoteType = Literal["whole", "half", "quarter", "eighth", "16th", "32nd", "64th"]
NoteLocator = Annotated[str, StringConstraints(pattern=r"^p(0|[1-9][0-9]*)-m(0|[1-9][0-9]*)-n(0|[1-9][0-9]*)$", max_length=40)]


class RhythmEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["split", "merge", "boundary", "delete"]
    note_ids: list[NoteLocator] = Field(min_length=1, max_length=2)
    left_note_type: NoteType | None = None
    left_dots: int = Field(default=0, ge=0, le=2)
    expected_revision: int = Field(ge=1)
    expected_score_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_generation: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_action(self):
        count = 2 if self.action in {"merge", "boundary"} else 1
        if len(self.note_ids) != count or len(set(self.note_ids)) != count:
            raise ValueError("Supply the distinct note locators required by the operation.")
        if self.action in {"split", "boundary"}:
            if self.left_note_type is None:
                raise ValueError("Specify the new left note type.")
        elif self.left_note_type is not None or self.left_dots:
            raise ValueError("Left note type and dots only apply to split or boundary.")
        return self


class NoteStructurePatch(EditPreconditions):
    step: Literal["A", "B", "C", "D", "E", "F", "G"] | None = None
    alter: int | None = Field(default=None, ge=-2, le=2)
    octave: int | None = Field(default=None, ge=0, le=9)
    lyric: str | None = Field(default=None, max_length=200)
    type: NoteType | None = None
    dots: int | None = Field(default=None, ge=0, le=2)
    rest: bool | None = None
    articulations: list[Literal["staccato", "tenuto", "accent", "strong-accent"]] | None = None
    ties: list[Literal["start", "stop"]] | None = None
    slurs: list[Literal["start", "stop"]] | None = None
    beam: Literal["begin", "continue", "end", "forward hook", "backward hook"] | None = None


class InsertNotePayload(EditPreconditions):
    position: Literal["before", "after"] = "after"
    rest: bool = False
    step: Literal["A", "B", "C", "D", "E", "F", "G"] = "C"
    alter: int = Field(default=0, ge=-2, le=2)
    octave: int = Field(default=4, ge=0, le=9)
    type: NoteType = "quarter"
    dots: int = Field(default=0, ge=0, le=2)
    lyric: str = Field(default="", max_length=200)


class SignaturePatch(EditPreconditions):
    key_fifths: int | None = Field(default=None, ge=-7, le=7)
    key_mode: Literal["major", "minor"] | None = None
    beats: int | None = Field(default=None, ge=1, le=32)
    beat_type: Literal[1, 2, 4, 8, 16, 32] | None = None


def _sync() -> None:
    jobs = [
        job
        for job in _job_store.list(limit=5000)
        if not _tombstones.contains(job.get("job_id"))
    ]
    _song_store.sync_completed_jobs(jobs)
    _initialize_publications()


def _initialize_publications() -> None:
    for song in _song_store.list():
        song_id = song["song_id"]
        if _publication_store.exists(song_id):
            continue
        try:
            snapshot = _song_store.export_snapshot(song_id)
            with tempfile.TemporaryDirectory(prefix="ast-publication-") as folder:
                path = Path(folder) / "score.musicxml"
                path.write_text(snapshot.current_score_xml, encoding="utf-8")
                settings = initial_publication_settings(path)
                apply_publication_layout(path, title=snapshot.title, settings=settings)
                if not _publication_store.exists(song_id):
                    _song_store.initialize_publication(snapshot, settings, path.read_text(encoding="utf-8"))
        except Exception:
            continue


def _part_exports(song: dict, *, parts: list[dict] | None = None) -> list[dict]:
    if parts is None:
        try:
            parts = list_score_parts(_song_store.checkout_current(song["song_id"]))
        except Exception:
            return []
    export_dir = _song_store.export_root / song["song_id"] / "parts"
    return [
        {
            **part,
            "pdf": (export_dir / f"{part['slug']}.pdf").exists(),
            "musicxml": (export_dir / f"{part['slug']}.musicxml").exists(),
        }
        for part in parts
    ]


def _public(song: dict, *, parts: list[dict] | None = None) -> dict:
    exports = song.get("exports") or {}
    return {
        "song_id": song["song_id"],
        "job_id": song.get("job_id"),
        "title": song["title"],
        "artist": song.get("artist"),
        "source_kind": song.get("source_kind", "transcription"),
        "revision": song.get("revision", 1),
        "created_at": song.get("created_at"),
        "updated_at": song.get("updated_at"),
        "exports": {
            "pdf": bool(exports.get("pdf")),
            "midi": bool(exports.get("midi")),
            "musicxml": bool(exports.get("musicxml")),
        },
        "parts": _part_exports(song) if parts is None else parts,
    }


def _require_song(song_id: str) -> dict:
    _sync()
    song = _song_store.get(song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    return song


def _snapshot_before_edit(song: dict) -> int:
    return _song_store.snapshot_revision(
        song["song_id"],
        _publication_store.read(song["song_id"]),
    )


def _discard_snapshot(song_id: str, revision: int) -> None:
    _song_store.discard_snapshot(song_id, revision)
    try:
        _song_store.checkout_current(song_id)
    except KeyError:
        pass


def _commit_score_change(song_id: str, path: Path) -> dict:
    updated = _song_store.commit_edit_from_path(song_id, path)
    if not updated:
        raise HTTPException(404, "Song not found")
    return updated


def _refresh_layout(song: dict, path: Path | None = None) -> Path:
    target = path or _song_store.checkout_current(song["song_id"])
    apply_publication_layout(
        target,
        title=song["title"],
        settings=_publication_store.read(song["song_id"]),
    )
    return target


def _evidence_links(song_id: str, revision: int, xml: str, state: dict | None, *, with_manifest=False):
    if (not state or not state["active"] or state["revision"] != revision
            or state["score_sha256"] != score_hash(xml)):
        raise ValueError("lineage_unavailable")
    links, original, clock, manifest_hash = baseline(_song_store.asset_root, song_id)
    fingerprint = baseline_fingerprint(links, original, clock, manifest_hash)
    if state["baseline_sha256"] != fingerprint:
        raise ValueError("lineage_unavailable")
    if clock_signature(xml) != clock:
        raise ValueError("current_structure_changed")
    if state["lineage_json"] is not None:
        try:
            lineage = json.loads(state["lineage_json"])
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid_lineage") from exc
        links = resolve_lineage(lineage, links, xml)
    return (links, fingerprint, manifest_hash) if with_manifest else (links, fingerprint)


def _rhythm_patch(payload: RhythmEditRequest, result: dict, before_xml: str, after_xml: str,
                  links: dict, fingerprint: str | None) -> tuple[dict, dict | None]:
    before = {row["note_id"]: row for row in written_notes(before_xml)}
    after = {row["note_id"]: row for row in written_notes(after_xml)}
    if clock_signature(before_xml, require_explicit=False) != clock_signature(after_xml, require_explicit=False):
        raise MusicXMLEditError("The rhythm edit would change the score clock.")
    successor = rhythm_lineage(before, after, links, result["mapping"])
    targets = set(payload.note_ids)
    for locator, row in before.items():
        if locator in targets:
            continue
        mapped = result["mapping"][locator]
        if len(mapped) != 1:
            raise MusicXMLEditError("The rhythm edit would change a note outside the selected region.")
        next_row = after[mapped[0]]
        if (any(abs(next_row[key] - row[key]) > 1e-8 for key in ("start", "end"))
                or {key: value for key, value in next_row.items() if key not in {"start", "end"}}
                != {key: value for key, value in dict(row, note_id=mapped[0]).items()
                    if key not in {"start", "end"}}):
            raise MusicXMLEditError("The rhythm edit would change a note outside the selected region.")
    if fingerprint is not None:
        resolve_lineage(successor, links, after_xml)

    def entries(note_ids, rows, sources):
        return [{"locator": locator, "source_ids": sources.get(locator, []), "pitch": rows[locator]["pitch"],
                 "written_quarters": {"start": rows[locator]["start"], "end": rows[locator]["end"]}}
                for locator in note_ids]

    origin_ids = {locator: linked_source_ids(link) for locator, link in links.items()}
    patch = {"schema_version": 2, "operation": payload.action, "reason": "manual_rhythm_edit",
             "generation": payload.expected_generation, "baseline_sha256": fingerprint,
             "inputs": entries(payload.note_ids, before, origin_ids),
             "outputs": entries(result["result_note_ids"], after, successor["locators"]),
             **result}
    return patch, successor if fingerprint is not None else None


def _mutate(song_id: str, operation, *, expected_revision: int | None = None,
            expected_score_sha256: str | None = None, expected_generation: int | None = None,
            evidence_note_id: str | None = None, rhythm: RhythmEditRequest | None = None) -> dict:
    song = _require_song(song_id)
    try:
        snapshot_revision = _song_store.snapshot_revision(
            song_id, _publication_store.read(song_id), expected_revision=expected_revision,
            expected_score_sha256=expected_score_sha256, expected_generation=expected_generation)
    except ConcurrentEditError as exc:
        raise HTTPException(409, str(exc)) from exc
    path = _song_store.checkout_current(song_id)
    try:
        before_xml = path.read_text(encoding="utf-8")
        evidence = None
        if rhythm:
            snapshot, state = _song_store.evidence_snapshot(song_id)
            if (not state or state["generation"] != expected_generation or snapshot.revision != snapshot_revision
                    or snapshot.current_score_xml != before_xml or score_hash(before_xml) != expected_score_sha256):
                raise ConcurrentEditError("Song changed. Reload and retry.")
            rhythm_links, rhythm_fingerprint = (
                _evidence_links(song_id, snapshot_revision, before_xml, state) if state["active"] else ({}, None)
            )
        if (evidence_note_id and expected_revision is not None and expected_score_sha256 is not None
                and score_hash(before_xml) == expected_score_sha256):
            try:
                snapshot, state = _song_store.evidence_snapshot(song_id)
                if snapshot.revision != snapshot_revision or snapshot.current_score_xml != before_xml:
                    raise ValueError("lineage_unavailable")
                links, fingerprint = _evidence_links(song_id, snapshot_revision, before_xml, state)
                row = next(row for row in written_notes(before_xml) if row["note_id"] == evidence_note_id)
                link = links.get(evidence_note_id)
                if link and len(link["locators"]) == 1 and not row["ties"]:
                    evidence = (links, fingerprint, row, state["generation"])
            except Exception:
                pass
        result = operation(song, path)
        if result is None:
            _discard_snapshot(song_id, snapshot_revision)
            return {"song": _public(song), "result": None}
        _refresh_layout(song, path)
        evidence_patch = None
        evidence_lineage = None
        if rhythm:
            after_xml = path.read_text(encoding="utf-8")
            evidence_patch, evidence_lineage = _rhythm_patch(
                rhythm, result, before_xml, after_xml, rhythm_links, rhythm_fingerprint)
            result["edit"] = {key: value for key, value in evidence_patch.items()
                              if key not in {"baseline_sha256", "generation", "mapping", "result_note_ids"}}
        if evidence:
            links, fingerprint, before, generation = evidence
            try:
                before_rows, after_rows = written_notes(before_xml), written_notes(path.read_text(encoding="utf-8"))
                after = next((row for row in after_rows if row["note_id"] == evidence_note_id), None)
                if after and after["pitch"] is not None and after != before:
                    comparable = [dict(row, pitch=before["pitch"], spelling=before["spelling"]) if row["note_id"] == evidence_note_id else row
                                  for row in after_rows]
                    if comparable == before_rows and clock_signature(before_xml) == clock_signature(path.read_text(encoding="utf-8")):
                        evidence_patch = {"baseline_sha256": fingerprint, "locator": evidence_note_id,
                                          "generation": generation,
                                          "source_id": links[evidence_note_id]["source_id"],
                                          "source_ids": linked_source_ids(links[evidence_note_id]),
                                          "before_pitch": before["pitch"], "after_pitch": after["pitch"],
                                          "before_spelling": before["spelling"], "after_spelling": after["spelling"],
                                          "reason": "manual_pitch_edit"}
            except ValueError:
                pass
        updated = _song_store.commit_edit_from_path(song_id, path, expected_revision=snapshot_revision,
                                                    expected_score_sha256=expected_score_sha256,
                                                    expected_generation=expected_generation,
                                                    evidence_patch=evidence_patch, evidence_lineage=evidence_lineage,
                                                    save_undo_snapshot=True)
        if not updated:
            raise HTTPException(404, "Song not found")
    except ConcurrentEditError as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(409, str(exc)) from exc
    except (MusicXMLEditError, ChordEditError) as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"악보를 수정하지 못했습니다: {exc}") from exc
    return {"song": _public(updated), "result": result}


@router.get("")
def list_songs() -> dict:
    _sync()
    return {"songs": [_public(song) for song in _song_store.list()]}


@router.get("/{song_id}")
def get_song(song_id: str) -> dict:
    return _public(_require_song(song_id))


@router.delete("/{song_id}")
def delete_song(song_id: str) -> dict:
    song = _require_song(song_id)
    _tombstones.add(song.get("job_id"))
    _publication_store.delete(song_id)
    if not _song_store.delete(song_id):
        raise HTTPException(404, "Song not found")
    return {"song_id": song_id, "deleted": True}


@router.get("/{song_id}/score")
def get_score(song_id: str) -> Response:
    _require_song(song_id)
    try:
        content = _song_store.score_xml(song_id)
    except KeyError as exc:
        raise HTTPException(404, "Current MusicXML is missing") from exc
    return Response(content=content, media_type="application/vnd.recordare.musicxml+xml",
                    headers={"ETag": f'"{score_hash(content)}"', "Access-Control-Expose-Headers": "ETag"})


@router.get("/{song_id}/notes")
def get_notes(song_id: str) -> dict:
    song = _require_song(song_id)
    snapshot, state = _song_store.evidence_snapshot(song_id)
    try:
        with tempfile.TemporaryDirectory(prefix="ast-notes-") as folder:
            path = Path(folder) / "score.musicxml"
            path.write_text(snapshot.current_score_xml, encoding="utf-8")
            summary = score_summary(path)
            chords = list_chords(path)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse MusicXML: {exc}") from exc
    song.update(title=snapshot.title, artist=snapshot.artist, revision=snapshot.revision,
                updated_at=snapshot.updated_at)
    return {"song": _public(song), **summary, "chords": chords,
            "score_sha256": hashlib.sha256(snapshot.current_score_xml.encode()).hexdigest(),
            "evidence_generation": state["generation"] if state else None}


@router.get("/{song_id}/notes/{note_id}/evidence")
def get_note_evidence(song_id: str, note_id: str,
                      expected_revision: int = Query(ge=1),
                      expected_score_sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
                      expected_generation: int = Query(ge=0),
                      include_pitch_observations: bool = False) -> dict:
    try:
        snapshot, state = _song_store.evidence_snapshot(song_id)
    except KeyError as exc:
        raise HTTPException(404, "Song not found") from exc
    if (snapshot.revision != expected_revision or score_hash(snapshot.current_score_xml) != expected_score_sha256
            or not state or state["generation"] != expected_generation):
        raise HTTPException(409, "Song changed. Reload and retry.")
    result = {"schema_version": 2 if state["active"] and state["lineage_json"] is not None else 1,
              "revision": snapshot.revision,
              "evidence_generation": state["generation"],
              "score_sha256": score_hash(snapshot.current_score_xml), "note_id": note_id,
              "status": "unavailable", "evidence": None,
              "limits": ["Selected performed vocal layer; not independent musical ground truth.",
                         "Source audio seek uses the interpreted grid, not a measured acoustic onset."]}
    if include_pitch_observations:
        from .pitch_observation_window import unavailable
        result['pitch_observations'] = unavailable('no_source')
    try:
        links, _, manifest_hash = _evidence_links(song_id, snapshot.revision, snapshot.current_score_xml, state,
                                                  with_manifest=True)
        if note_id in links:
            result.update(status="linked", evidence=links[note_id], reason=None)
            # Prefix observations are independently versioned and do not enter lineage fingerprints.
            from .vocal_hypotheses import read_archived
            root = _song_store.asset_root / song_id / 'model-evidence'
            try:
                prefix, recipe = read_archived(root, manifest_hash)
                if prefix is not None:
                    by_id = {row['selected_id']: row for row in prefix['mappings']}
                    candidates = {row['id']: row for row in prefix['candidates']}
                    source_ids = linked_source_ids(links[note_id])
                    result['vocal_hypotheses'] = {
                        'schema_version': 1, 'frame_clock': 'stem_local',
                        'model_segment_clock': 'model_input', 'advisory': True,
                        'kind': 'decoder_model_segments_and_cotemporal_tiny_frames',
                        'join_basis': 'unique_exact_performed_event_equivalence',
                        'frame_interval_seconds': .01,
                        'pitch_sha256': prefix['pitch_sha256'], 'frame_count': prefix['frame_count'],
                        'sources': [{**by_id[source], 'model_segments': [candidates[candidate]
                                    for candidate in by_id[source]['candidate_ids']]}
                                    for source in source_ids],
                    }
                    if include_pitch_observations:
                        from .pitch_observation_window import pitch_observation_window
                        result['pitch_observations'] = pitch_observation_window(root, prefix, source_ids)
                else:
                    declaration = recipe.get('vocal_hypotheses') or {}
                    result['vocal_hypotheses'] = {'schema_version': 1, 'status': 'unavailable',
                                                  'reason': declaration.get('reason', 'legacy')}
                    if include_pitch_observations:
                        result['pitch_observations'] = unavailable('unavailable')
            except Exception as exc:
                reason = 'unsupported' if str(exc) == 'Unsupported vocal hypothesis declaration' else 'invalid'
                result['vocal_hypotheses'] = {'schema_version': 1, 'status': 'unavailable', 'reason': reason}
                if include_pitch_observations:
                    result['pitch_observations'] = unavailable(reason)
        else:
            result["reason"] = "no_represented_source_event"
    except Exception as exc:
        reasons = {"model_evidence_missing", "not_fixed_vocal_recipe", "incomplete_evidence",
                   "unsupported_recipe", "unsupported_interpretation", "invalid_interpretation",
                   "current_structure_changed", "ambiguous_mapping", "mapping_not_found",
                   "repeated_source_run", "unsupported_score", "unsupported_polyphony",
                   "unsupported_note", "invalid_divisions", "invalid_duration", "invalid_pitch",
                   "invalid_tie", "broken_tie", "unsupported_clock", "unsupported_positions",
                   "evidence_limit_exceeded", "lineage_unavailable", "invalid_lineage", "unsupported_lineage"}
        reason = str(exc) if str(exc) in reasons else "invalid_evidence"
        result.update(status="ambiguous" if reason == "ambiguous_mapping" else "unavailable", reason=reason)
        if include_pitch_observations:
            result['pitch_observations'] = unavailable('no_source')
    patches = _song_store.evidence_patches(song_id, snapshot.revision, result["score_sha256"])
    result["patch"] = next((patch for patch in reversed(patches)
                            if patch.get("after_generation") == state["generation"]
                            and (patch.get("locator") == note_id or note_id in patch.get("result_note_ids", []))), None)
    return result


@router.patch("/{song_id}")
def update_song(song_id: str, payload: SongMetadataPatch) -> dict:
    song = _require_song(song_id)
    title_changed = (
        payload.title is not None
        and (payload.title.strip() or "제목 없는 곡") != song["title"]
    )
    if title_changed:
        snapshot_revision = _snapshot_before_edit(song)
        path = _song_store.checkout_current(song_id)
        title = payload.title.strip() or "제목 없는 곡"
        try:
            set_score_title(path, title)
            apply_publication_layout(
                path,
                title=title,
                settings=_publication_store.read(song_id),
            )
            _commit_score_change(song_id, path)
        except Exception as exc:
            _discard_snapshot(song_id, snapshot_revision)
            raise HTTPException(422, f"제목을 악보에 반영하지 못했습니다: {exc}") from exc

    updated = _song_store.update_metadata(
        song_id,
        title=payload.title,
        artist=payload.artist,
    )
    if not updated:
        raise HTTPException(404, "Song not found")
    return _public(updated)


@router.patch("/{song_id}/notes/{note_id}")
def patch_note(song_id: str, note_id: str, payload: NotePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(_require_song(song_id)), "note_id": note_id}

    def operation(_song: dict, path: Path) -> dict:
        update_note(path, note_id, patch)
        return {"note_id": note_id}

    return _mutate(song_id, operation)


@router.patch("/{song_id}/notes/{note_id}/chord")
def patch_chord(song_id: str, note_id: str, payload: ChordPatch, request: Request) -> dict:
    def operation(_song: dict, path: Path) -> dict | None:
        if not set_chord_at_note(path, note_id, payload.symbol):
            return None
        return {"note_id": note_id, "symbol": payload.symbol or ""}

    response = _mutate(song_id, operation, **payload.preconditions())
    if response["result"] is None:
        request.state.song_edit_unchanged = True
    return {
        "song": response["song"],
        "note_id": note_id,
        "symbol": payload.symbol or "",
    }


@router.get("/{song_id}/publication")
def get_publication(song_id: str) -> dict:
    _require_song(song_id)
    return {"settings": _publication_store.read(song_id)}


@router.patch("/{song_id}/publication")
def update_publication(song_id: str, payload: PublicationPatch) -> dict:
    song = _require_song(song_id)
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        return {"song": _public(song), "settings": _publication_store.read(song_id)}

    current = _publication_store.read(song_id)
    next_settings = dict(current)
    next_settings.update(patch)
    snapshot_revision = _snapshot_before_edit(song)
    path = _song_store.checkout_current(song_id)
    try:
        apply_publication_layout(path, title=song["title"], settings=next_settings)
        saved = _publication_store.write(song_id, next_settings)
        updated = _commit_score_change(song_id, path)
    except Exception as exc:
        _publication_store.write(song_id, current)
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"악보 조판 설정을 적용하지 못했습니다: {exc}") from exc
    return {"song": _public(updated), "settings": saved}


@router.post("/{song_id}/undo")
def undo_song(song_id: str) -> dict:
    song = _require_song(song_id)
    current_revision = int(song.get("revision", 1))
    if current_revision <= 1:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    restored_publication = _song_store.restore_revision(song_id, current_revision - 1)
    if restored_publication is None:
        raise HTTPException(409, "되돌릴 수정 이력이 없습니다.")
    _publication_store.write(song_id, restored_publication)
    updated = _song_store.get(song_id)
    return _public(updated or song)


@router.post("/{song_id}/restore")
def restore_original(song_id: str) -> dict:
    song = _require_song(song_id)
    snapshot_revision = _snapshot_before_edit(song)
    current = _song_store.checkout_current(song_id)
    original = _song_store.checkout_original(song_id)
    try:
        shutil.copy2(original, current)
        apply_publication_layout(
            current,
            title=song["title"],
            settings=_publication_store.read(song_id),
        )
        updated = _commit_score_change(song_id, current)
    except Exception as exc:
        _discard_snapshot(song_id, snapshot_revision)
        raise HTTPException(422, f"원본 악보를 복원하지 못했습니다: {exc}") from exc
    return _public(updated)


@router.get("/{song_id}/structure")
def get_structure(song_id: str) -> dict:
    song = _require_song(song_id)
    snapshot, _ = _song_store.evidence_snapshot(song_id)
    with tempfile.TemporaryDirectory(prefix="ast-structure-") as folder:
        path = Path(folder) / "score.musicxml"
        path.write_text(snapshot.current_score_xml, encoding="utf-8")
        summary = structure_summary(path)
    song.update(title=snapshot.title, artist=snapshot.artist, revision=snapshot.revision,
                updated_at=snapshot.updated_at)
    return {"song": _public(song), **summary, "score_sha256": score_hash(snapshot.current_score_xml)}


@router.patch("/{song_id}/notes/{note_id}/structure")
def patch_note_structure(song_id: str, note_id: str, payload: NoteStructurePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True)
    expected_revision = patch.pop("expected_revision", None)
    expected_score_sha256 = patch.pop("expected_score_sha256", None)
    expected_generation = patch.pop("expected_generation", None)
    if not patch:
        song = _require_song(song_id)
        snapshot, state = _song_store.evidence_snapshot(song_id)
        if ((expected_revision is not None and expected_revision != snapshot.revision)
                or (expected_score_sha256 is not None and expected_score_sha256 != score_hash(snapshot.current_score_xml))):
            raise HTTPException(409, "Song changed. Reload and retry.")
        if expected_generation is not None and (not state or state["generation"] != expected_generation):
            raise HTTPException(409, "Song changed. Reload and retry.")
        return {"song": _public(song), "note_id": note_id}

    def operation(_song: dict, path: Path) -> dict:
        structure_fields = {
            key: value
            for key, value in patch.items()
            if key in {"type", "dots", "rest", "articulations", "ties", "slurs", "beam"}
        }
        if structure_fields:
            update_note_structure(path, note_id, structure_fields)
        basic_fields = {
            key: value
            for key, value in patch.items()
            if key in {"step", "alter", "octave", "lyric"}
        }
        if basic_fields:
            if patch.get("rest") is True:
                basic_fields = {key: value for key, value in basic_fields.items() if key == "lyric"}
            if basic_fields:
                update_note(path, note_id, basic_fields)
        return {"note_id": note_id}

    return _mutate(song_id, operation, expected_revision=expected_revision,
                   expected_score_sha256=expected_score_sha256,
                   expected_generation=expected_generation,
                   evidence_note_id=note_id if set(patch) <= {"step", "alter", "octave"} else None)


@router.post("/{song_id}/notes/rhythm-edit")
def edit_note_rhythm(song_id: str, payload: RhythmEditRequest) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        return rhythm_edit(path, payload.action, payload.note_ids,
                           left_note_type=payload.left_note_type, left_dots=payload.left_dots)

    return _mutate(song_id, operation, expected_revision=payload.expected_revision,
                   expected_score_sha256=payload.expected_score_sha256,
                   expected_generation=payload.expected_generation, rhythm=payload)


@router.post("/{song_id}/notes/{note_id}/insert")
def insert_score_note(song_id: str, note_id: str, payload: InsertNotePayload) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        new_id = insert_note(
            path,
            note_id,
            position=payload.position,
            rest=payload.rest,
            step=payload.step,
            alter=payload.alter,
            octave=payload.octave,
            note_type=payload.type,
            dots=payload.dots,
            lyric=payload.lyric,
        )
        return {"note_id": new_id}

    return _mutate(song_id, operation, **payload.preconditions())


@router.delete("/{song_id}/notes/{note_id}")
def delete_score_note(song_id: str, note_id: str,
                      expected_revision: int | None = Query(default=None, ge=1),
                      expected_score_sha256: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
                      expected_generation: int | None = Query(default=None, ge=0)) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        delete_note(path, note_id)
        return {"deleted_note_id": note_id}

    return _mutate(song_id, operation, expected_revision=expected_revision,
                   expected_score_sha256=expected_score_sha256, expected_generation=expected_generation)


@router.post("/{song_id}/measures/{measure_index}/insert-after")
def insert_score_measure(song_id: str, measure_index: int,
                         expected_revision: int | None = Query(default=None, ge=1),
                         expected_score_sha256: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
                         expected_generation: int | None = Query(default=None, ge=0)) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        return {"measure_index": insert_measure(path, measure_index)}

    return _mutate(song_id, operation, expected_revision=expected_revision,
                   expected_score_sha256=expected_score_sha256, expected_generation=expected_generation)


@router.delete("/{song_id}/measures/{measure_index}")
def delete_score_measure(song_id: str, measure_index: int,
                         expected_revision: int | None = Query(default=None, ge=1),
                         expected_score_sha256: str | None = Query(default=None, pattern=r"^[0-9a-f]{64}$"),
                         expected_generation: int | None = Query(default=None, ge=0)) -> dict:
    def operation(_song: dict, path: Path) -> dict:
        delete_measure(path, measure_index)
        return {"deleted_measure_index": measure_index}

    return _mutate(song_id, operation, expected_revision=expected_revision,
                   expected_score_sha256=expected_score_sha256, expected_generation=expected_generation)


@router.patch("/{song_id}/measures/{measure_index}/signature")
def patch_measure_signature(song_id: str, measure_index: int, payload: SignaturePatch) -> dict:
    patch = payload.model_dump(exclude_unset=True, exclude=set(payload.preconditions()))
    if not patch:
        result = _mutate(song_id, lambda _song, _path: None, **payload.preconditions())
        return {"song": result["song"], "measure_index": measure_index}

    def operation(_song: dict, path: Path) -> dict:
        set_measure_signature(
            path,
            measure_index,
            fifths=patch.get("key_fifths"),
            mode=patch.get("key_mode"),
            beats=patch.get("beats"),
            beat_type=patch.get("beat_type"),
        )
        return {"measure_index": measure_index}

    return _mutate(song_id, operation, **payload.preconditions())


@router.get("/{song_id}/files/parts/{slug}/{kind}")
def download_part_file(song_id: str, slug: str, kind: str) -> FileResponse:
    _require_song(song_id)
    current = _song_store.checkout_current(song_id)
    allowed = {str(part["slug"]) for part in list_score_parts(current)}
    if slug not in allowed:
        raise HTTPException(404, "Unknown score part")
    if kind == "pdf":
        path = _song_store.export_root / song_id / "parts" / f"{slug}.pdf"
        media_type = "application/pdf"
    elif kind == "musicxml":
        path = _song_store.export_root / song_id / "parts" / f"{slug}.musicxml"
        media_type = "application/vnd.recordare.musicxml+xml"
    else:
        raise HTTPException(404, "Unknown part artifact")
    if not path.exists():
        raise HTTPException(404, "Part export is not available. Run final export first.")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{song_id}/files/{kind}")
def download_song_file(song_id: str, kind: str):
    song = _require_song(song_id)
    export_dir = _song_store.export_root / song_id
    if kind == "musicxml":
        exported = export_dir / "score.musicxml"
        if exported.exists():
            return FileResponse(
                exported,
                media_type="application/vnd.recordare.musicxml+xml",
                filename=f"{song['title']}.musicxml",
            )
        return Response(
            content=_song_store.score_xml(song_id),
            media_type="application/vnd.recordare.musicxml+xml",
            headers={"Content-Disposition": 'attachment; filename="score.musicxml"'},
        )
    if kind == "pdf":
        path = export_dir / "score.pdf"
        media_type = "application/pdf"
        filename = f"{song['title']}.pdf"
    elif kind == "midi":
        path = export_dir / "score.mid"
        media_type = "audio/midi"
        filename = f"{song['title']}.mid"
    else:
        raise HTTPException(404, "Unknown song artifact")
    if not path.exists():
        raise HTTPException(404, "Export file is not available. Run final export first.")
    return FileResponse(path, media_type=media_type, filename=filename)
