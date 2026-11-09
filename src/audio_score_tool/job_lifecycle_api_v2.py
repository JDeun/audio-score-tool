from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, HTTPException

from . import api as base_api
from .job_admission import JobCapacityError, reserve_job
from .job_transcription_settings import (
    restore_transcription_job_settings,
    transcription_job_selection,
)
from .paths import jobs_dir, song_assets_dir
from .preflight_v2 import preflight
from .presets import resolve_job_models
from .runner import command_exists
from .runtime_settings import runtime_settings
from .score_requests import needs_stem_separation, validate_score_mode
from .song_store_v2 import SongStoreV2
from .youtube import YouTubeSourceError, validate_youtube_url, youtube_tool_status

router = APIRouter(tags=["jobs-v2"])
_songs = SongStoreV2()


def _start_or_mark_failed(job_id: str, thread: Thread) -> None:
    try:
        thread.start()
    except Exception as exc:
        base_api._store.update(
            job_id,
            status="failed",
            stage="failed",
            error=f"Background worker could not start: {exc}",
        )
        raise HTTPException(
            500,
            "백그라운드 작업을 시작하지 못했습니다. 원본 입력은 재시도를 위해 보존했습니다.",
        ) from exc


def _reserve_or_429(job_id: str, **values) -> None:
    try:
        reserve_job(base_api._store, job_id, **values)
    except JobCapacityError as exc:
        raise HTTPException(429, str(exc)) from exc


def _cleanup_failed_reservation(job_id: str, path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    base_api._store.delete(job_id)


def _copy_retry_input(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".copying")
    try:
        shutil.copy2(source, temp)
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _stage_job_workspace_for_delete(job_id: str) -> tuple[Path | None, Path | None]:
    """Atomically hide a Job workspace before deleting its DB row.

    If the DB delete fails, the caller can move the staged directory back. If the
    process dies after the DB row is deleted but before rmtree completes, startup
    recovery removes the hidden `.deleting-*` directory.
    """
    original = jobs_dir() / job_id
    if not original.exists():
        return None, None
    staged = jobs_dir() / f".deleting-{job_id}-{uuid.uuid4().hex}"
    try:
        original.replace(staged)
    except OSError as exc:
        raise HTTPException(500, f"Job 작업 폴더를 삭제 준비하지 못했습니다: {exc}") from exc
    return original, staged


def _restore_staged_workspace(original: Path | None, staged: Path | None) -> None:
    if original is None or staged is None or not staged.exists() or original.exists():
        return
    try:
        staged.replace(original)
    except OSError:
        # Keep the staged directory intact for startup recovery rather than deleting
        # potentially valuable retry/debug artifacts after a DB failure.
        pass


@router.post("/api/jobs/youtube", status_code=202)
def create_youtube_job_v2(payload: base_api.YouTubeJobRequest) -> dict:
    try:
        url = validate_youtube_url(payload.url)
        defaults = runtime_settings()
        score_mode = validate_score_mode(payload.score_mode)
        # The desktop default is private, noncommercial practice; do not ask
        # users to affirm ownership of every streamed public-video analysis.
        # Commercial jobs still require explicit user confirmation. This does
        # not override YouTube service restrictions or independently verify rights.
        if getattr(defaults, "usage_mode", None) != "personal" and not payload.authorized:
            raise HTTPException(422, "이 콘텐츠를 처리할 권한이 있음을 확인해야 합니다.")
        resolved_muscriptor, resolved_whisperx = resolve_job_models(
            payload.preset,
            selected_muscriptor_model=defaults.muscriptor_model,
            selected_whisperx_model=defaults.whisperx_model,
            muscriptor_override=payload.muscriptor_model,
            whisperx_override=payload.whisperx_model,
        )
        selected = replace(
            defaults, muscriptor_model=resolved_muscriptor,
            whisperx_model=resolved_whisperx,
        )
        selection = transcription_job_selection(selected)
    except (YouTubeSourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    readiness = preflight(selected, require_lyrics=False)
    if not readiness["ok"]:
        raise HTTPException(
            503,
            "채보 필수 실행환경이 준비되지 않았습니다: " + ", ".join(readiness["missing"]),
        )
    if not youtube_tool_status(defaults)["ready"]:
        raise HTTPException(503, "YouTube 가져오기 구성요소가 준비되지 않았습니다.")

    if needs_stem_separation(score_mode) and not command_exists(defaults.demucs_cmd):
        raise HTTPException(503, "선택 악기 채보에는 Demucs가 필요합니다. 구성요소 상태에서 설치하세요.")

    job_id = uuid.uuid4().hex
    _reserve_or_429(
        job_id,
        status="queued",
        stage="queued",
        progress=0,
        filename="YouTube import",
        source_kind="youtube",
        language=payload.language,
        skip_lyrics=payload.skip_lyrics,
        preset=payload.preset,
        score_mode=score_mode,
        auto_enrich=payload.auto_enrich,
        **selection,
    )
    job_dir = jobs_dir() / job_id
    try:
        job_dir.mkdir(parents=True, exist_ok=False)
    except Exception:
        _cleanup_failed_reservation(job_id, job_dir)
        raise

    thread = Thread(
        target=base_api._youtube_worker,
        args=(
            job_id,
            url,
            payload.language,
            payload.skip_lyrics,
            resolved_muscriptor,
            resolved_whisperx,
        ),
        daemon=True,
    )
    _start_or_mark_failed(job_id, thread)
    return {"job_id": job_id, "status": "queued", "source": "youtube"}


def _retry_input_source(job_id: str, kind: str) -> Path:
    """Select the original source for this Job type, not just input.* audio files."""
    if kind in {"transcription", "benchmark"}:
        pattern, allowed = "input.*", base_api._AUDIO_EXTENSIONS
    elif kind == "omr":
        from .omr_api import _ALLOWED as allowed

        pattern = "source-score.*"
    elif kind == "notation-import":
        from .direct_score_import_api import _ALLOWED as allowed

        pattern = "source.*"
    else:
        raise HTTPException(409, f"Retry is unsupported for job kind: {kind}")

    candidates = sorted(
        path
        for path in (jobs_dir() / job_id).glob(pattern)
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in allowed
    )
    if not candidates:
        raise HTTPException(404, f"Original {kind} input is missing.")
    if len(candidates) != 1:
        raise HTTPException(409, f"Multiple original {kind} inputs found; cannot retry safely.")
    return candidates[0]


@router.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job_v2(job_id: str) -> dict:
    source = base_api._store.get(job_id)
    if not source:
        raise HTTPException(404, "Job not found")
    if source["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Running jobs cannot be retried.")

    kind = str(source.get("kind") or "transcription")
    original = _retry_input_source(job_id, kind)
    settings = runtime_settings()
    if kind == "omr":
        from .omr import audiveris_status

        if not audiveris_status(settings.audiveris_cmd)["ready"]:
            raise HTTPException(503, "OMR component is unavailable; check Setup Center before retry.")

    new_id = uuid.uuid4().hex
    default_presets = {
        "transcription": "auto",
        "benchmark": "all",
        "omr": "omr-audiveris",
        "notation-import": "direct-notation-import",
    }
    values = {
        "kind": kind,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "filename": source.get("filename"),
        "source_kind": source.get("source_kind"),
        "language": source.get("language"),
        "preset": source.get("preset") or default_presets[kind],
        "score_mode": source.get("score_mode") or "full",
        "auto_enrich": source.get("auto_enrich", False),
        "skip_lyrics": source.get("skip_lyrics", False) if kind == "transcription" else kind != "benchmark",
    }
    if kind == "transcription":
        validate_score_mode(values["score_mode"])
        try:
            selected = restore_transcription_job_settings(settings, source)
            selection = transcription_job_selection(selected)
            if (
                source.get("native_checkpoint_sha256") is not None
                and selection["native_checkpoint_sha256"] != source["native_checkpoint_sha256"]
            ):
                raise ValueError("The job's Native checkpoint changed while preparing the retry")
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        readiness = preflight(selected, require_lyrics=False)
        if not readiness["ok"]:
            raise HTTPException(
                503,
                "이 작업에 저장된 채보 모델이 준비되지 않았습니다: " + ", ".join(readiness["missing"]),
            )
        if needs_stem_separation(values["score_mode"]) and not command_exists(settings.demucs_cmd):
            raise HTTPException(503, "재실행할 선택 악기 분리 도구가 준비되지 않았습니다.")
        values.update(selection)

    _reserve_or_429(new_id, **values)
    target_dir = jobs_dir() / new_id
    copied = target_dir / original.name
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        _copy_retry_input(original, copied)

        if kind == "benchmark":
            reference_source = original.parent / "reference.mid"
            reference_target = (
                target_dir / "reference.mid"
                if reference_source.is_file() and not reference_source.is_symlink()
                else None
            )
            if reference_target is not None:
                _copy_retry_input(reference_source, reference_target)
            thread = Thread(
                target=base_api._benchmark_worker,
                args=(new_id, copied, reference_target, source.get("language"), values["preset"]),
                daemon=True,
            )
        elif kind == "omr":
            from .omr_api import _worker as omr_worker

            thread = Thread(target=omr_worker, args=(new_id, copied, settings), daemon=True)
        elif kind == "notation-import":
            from .direct_score_import_api import _worker as notation_worker

            thread = Thread(
                target=notation_worker,
                args=(new_id, copied, copied.suffix.lower()),
                daemon=True,
            )
        else:
            thread = Thread(
                target=base_api._worker,
                args=(
                    new_id,
                    copied,
                    source.get("language"),
                    source.get("skip_lyrics", False),
                    values["muscriptor_model"],
                    values["whisperx_model"],
                ),
                daemon=True,
            )
    except Exception:
        _cleanup_failed_reservation(new_id, target_dir)
        raise

    _start_or_mark_failed(new_id, thread)
    return {"job_id": new_id, "status": "queued", "kind": kind, "retried_from": job_id}


@router.delete("/api/jobs/{job_id}")
def delete_job_v2(job_id: str) -> dict:
    job = base_api._store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Cancel the running job before deleting it.")

    # A completed score job is disposable only after its canonical Song row exists.
    if job.get("status") == "done" and job.get("kind") != "benchmark":
        if _songs.get_by_job(job_id) is None:
            _songs.sync_completed_jobs([job])
        if _songs.get_by_job(job_id) is None:
            raise HTTPException(
                409,
                "완료된 악보가 아직 곡 라이브러리에 안전하게 저장되지 않았습니다. 작업을 삭제하지 않았습니다.",
            )

    original, staged = _stage_job_workspace_for_delete(job_id)
    try:
        deleted = base_api._store.delete(job_id)
    except Exception as exc:
        _restore_staged_workspace(original, staged)
        raise HTTPException(500, f"Job 기록을 삭제하지 못했습니다: {exc}") from exc
    if not deleted:
        _restore_staged_workspace(original, staged)
        raise HTTPException(404, "Job not found")

    if staged is not None:
        shutil.rmtree(staged, ignore_errors=True)

    # Failed/cancelled jobs may have preserved source audio before the pipeline failed.
    # Canonical songs own their managed assets; only remove truly orphaned job assets.
    if _songs.get_by_job(job_id) is None:
        shutil.rmtree(song_assets_dir() / job_id, ignore_errors=True)

    return {"job_id": job_id, "deleted": True}
