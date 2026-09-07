from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from threading import Thread

from fastapi import APIRouter, HTTPException

from . import api as base_api
from .paths import jobs_dir, song_assets_dir
from .runtime_settings import runtime_settings
from .song_store_v2 import SongStoreV2
from .youtube import YouTubeSourceError, validate_youtube_url

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
    if not payload.authorized:
        raise HTTPException(422, "이 콘텐츠를 처리할 권한이 있음을 확인해야 합니다.")
    try:
        url = validate_youtube_url(payload.url)
        selected = base_api.resolve_preset(payload.preset)
    except (YouTubeSourceError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    resolved_muscriptor = payload.muscriptor_model or selected.muscriptor_model
    resolved_whisperx = payload.whisperx_model or selected.whisperx_model
    job_id = uuid.uuid4().hex
    job_dir = jobs_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    try:
        base_api._store.create(
            job_id,
            status="queued",
            stage="queued",
            progress=0,
            filename="YouTube import",
            language=payload.language,
            skip_lyrics=payload.skip_lyrics,
            preset=payload.preset,
            muscriptor_model=resolved_muscriptor,
            whisperx_model=resolved_whisperx,
        )
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
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


@router.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job_v2(job_id: str) -> dict:
    source = base_api._store.get(job_id)
    if not source:
        raise HTTPException(404, "Job not found")
    if source["status"] in {"queued", "running", "cancelling"}:
        raise HTTPException(409, "Running jobs cannot be retried.")

    source_dir = jobs_dir() / job_id
    audio_candidates = sorted(source_dir.glob("input.*"))
    if not audio_candidates:
        raise HTTPException(404, "Original input audio is missing.")

    settings = runtime_settings()
    new_id = uuid.uuid4().hex
    target_dir = jobs_dir() / new_id
    target_dir.mkdir(parents=True, exist_ok=False)
    audio = target_dir / audio_candidates[0].name
    try:
        _copy_retry_input(audio_candidates[0], audio)

        if source.get("kind") == "benchmark":
            reference_source = source_dir / "reference.mid"
            reference_target = target_dir / "reference.mid" if reference_source.exists() else None
            if reference_target is not None:
                _copy_retry_input(reference_source, reference_target)
            profile = source.get("preset") or "all"
            base_api._store.create(
                new_id,
                kind="benchmark",
                status="queued",
                stage="queued",
                progress=0,
                filename=source.get("filename"),
                language=source.get("language"),
                preset=profile,
            )
            thread = Thread(
                target=base_api._benchmark_worker,
                args=(new_id, audio, reference_target, source.get("language"), profile),
                daemon=True,
            )
        else:
            muscriptor_model = source.get("muscriptor_model") or settings.muscriptor_model
            whisperx_model = source.get("whisperx_model") or settings.whisperx_model
            base_api._store.create(
                new_id,
                kind="transcription",
                status="queued",
                stage="queued",
                progress=0,
                filename=source.get("filename"),
                language=source.get("language"),
                skip_lyrics=source.get("skip_lyrics", False),
                preset=source.get("preset") or "auto",
                muscriptor_model=muscriptor_model,
                whisperx_model=whisperx_model,
            )
            thread = Thread(
                target=base_api._worker,
                args=(
                    new_id,
                    audio,
                    source.get("language"),
                    source.get("skip_lyrics", False),
                    muscriptor_model,
                    whisperx_model,
                ),
                daemon=True,
            )
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise

    _start_or_mark_failed(new_id, thread)
    return {"job_id": new_id, "status": "queued", "retried_from": job_id}


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
