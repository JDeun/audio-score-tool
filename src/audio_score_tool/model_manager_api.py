from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from huggingface_hub import HfApi, snapshot_download
from pydantic import BaseModel, Field

from .config import component_dir, packaged_runtime
from .hf_session import active_token, authenticated, clear_session, identity, set_session
from .runtime_settings import runtime_settings

router = APIRouter(tags=["model-manager"])

MUSCRIPTOR_MODELS = {
    "small": {
        "repo_id": "MuScriptor/muscriptor-small",
        "parameters": "103M",
        "weight_bytes": 422_000_000,
        "label": "Small",
        "description": "CPU와 저사양 환경용. 가장 빠르지만 정확도는 낮습니다.",
    },
    "medium": {
        "repo_id": "MuScriptor/muscriptor-medium",
        "parameters": "307M",
        "weight_bytes": 1_230_000_000,
        "label": "Medium",
        "description": "속도와 정확도의 균형형 모델입니다.",
    },
    "large": {
        "repo_id": "MuScriptor/muscriptor-large",
        "parameters": "1.4B",
        "weight_bytes": 5_470_000_000,
        "label": "Large",
        "description": "정확도 우선 기본 모델. GPU/Apple Silicon 사용을 권장합니다.",
    },
}

_MAX_JOB_HISTORY = 64
_TERMINAL = {"done", "failed", "cancelled"}
_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


class RemoveRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


class HfTokenRequest(BaseModel):
    token: str = Field(min_length=8, max_length=4096)


def _now_ts() -> float:
    return time.time()


def _prune_locked(store: dict[str, dict]) -> None:
    if len(store) <= _MAX_JOB_HISTORY:
        return
    terminal = sorted(
        ((key, value) for key, value in store.items() if value.get("status") in _TERMINAL),
        key=lambda item: float(item[1].get("updated_at") or item[1].get("created_at") or 0.0),
    )
    for key, _ in terminal:
        if len(store) <= _MAX_JOB_HISTORY:
            break
        store.pop(key, None)


def _update_job(store: dict[str, dict], key: str, **changes) -> None:
    if key in store:
        store[key].update(changes, updated_at=_now_ts())


def _hf_home() -> Path:
    if packaged_runtime():
        return component_dir() / "models" / "huggingface"
    raw = os.getenv("HF_HOME")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "huggingface"


def _hub_root() -> Path:
    return _hf_home() / "hub"


def _repo_cache_dir(repo_id: str) -> Path:
    return _hub_root() / f"models--{repo_id.replace('/', '--')}"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def _model_cached(repo_id: str) -> tuple[bool, int]:
    root = _repo_cache_dir(repo_id)
    size = _directory_size(root)
    snapshots = root / "snapshots"
    has_weights = False
    if snapshots.exists():
        try:
            for snapshot in snapshots.iterdir():
                if snapshot.is_dir() and any(snapshot.rglob("*.safetensors")):
                    has_weights = True
                    break
        except OSError:
            has_weights = False
    return has_weights, size


def _model_payload(variant: str, settings) -> dict:
    spec = MUSCRIPTOR_MODELS[variant]
    ready, cached_bytes = _model_cached(str(spec["repo_id"]))
    selected = settings.transcription_engine == "muscriptor" and settings.muscriptor_model == variant
    allowed = settings.usage_mode != "commercial"
    return {
        "family": "muscriptor",
        "variant": variant,
        "label": spec["label"],
        "repo_id": spec["repo_id"],
        "parameters": spec["parameters"],
        "weight_bytes": spec["weight_bytes"],
        "cached_bytes": cached_bytes,
        "ready": ready,
        "selected": selected,
        "allowed_for_usage_mode": allowed,
        "license": "CC BY-NC 4.0",
        "commercial_allowed": False,
        "description": spec["description"],
        "requires_hf_auth": True,
    }


def model_manager_status() -> dict:
    settings = runtime_settings()
    home = _hf_home()
    home.mkdir(parents=True, exist_ok=True)
    disk_anchor = home.parent if home.parent.exists() else Path.home()
    disk = shutil.disk_usage(disk_anchor)
    return {
        "usage_mode": settings.usage_mode,
        "selected_engine": settings.transcription_engine,
        "selected_muscriptor_model": settings.muscriptor_model,
        "hf_authenticated": authenticated(),
        "hf_identity": identity(),
        "hf_home": str(home),
        "hf_cli_ready": False,
        "disk_free_bytes": disk.free,
        "models": [_model_payload(variant, settings) for variant in ("large", "medium", "small")],
        "policy": {
            "automatic_download": False,
            "explicit_user_action_required": True,
            "commercial_mode_blocks_muscriptor": True,
            "model_license_acceptance_required": True,
            "auth_token_stored_by_app": False,
            "auth_token_scope": "process-memory-only",
            "download_transport": "huggingface_hub-python-api",
            "selected_or_active_model_removal_blocked": True,
            "background_jobs_cancellable": "best-effort-after-current-transfer",
            "background_job_history_limit": _MAX_JOB_HISTORY,
        },
    }


def _run_download(job_id: str, variant: str) -> None:
    spec = MUSCRIPTOR_MODELS[variant]
    repo_id = str(spec["repo_id"])
    token = active_token()
    if not token:
        with _jobs_lock:
            _update_job(_jobs, job_id, status="failed", error="Hugging Face 인증이 필요합니다.")
        return

    with _jobs_lock:
        if _jobs.get(job_id, {}).get("cancel_requested"):
            _update_job(_jobs, job_id, status="cancelled")
            return
        _update_job(_jobs, job_id, status="running", transport="huggingface_hub")

    try:
        _hub_root().mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=repo_id,
            cache_dir=str(_hub_root()),
            token=token,
            local_files_only=False,
        )
        ready, size = _model_cached(repo_id)
        with _jobs_lock:
            if _jobs.get(job_id, {}).get("cancel_requested"):
                _update_job(
                    _jobs,
                    job_id,
                    status="cancelled",
                    cached_bytes=size,
                    progress=100 if ready else 0,
                    error=None,
                )
            elif ready:
                _update_job(
                    _jobs,
                    job_id,
                    status="done",
                    progress=100,
                    cached_bytes=size,
                    error=None,
                )
            else:
                _update_job(
                    _jobs,
                    job_id,
                    status="failed",
                    cached_bytes=size,
                    error="다운로드는 끝났지만 model weights를 확인하지 못했습니다.",
                )
            _prune_locked(_jobs)
    except Exception as exc:
        with _jobs_lock:
            status = "cancelled" if _jobs.get(job_id, {}).get("cancel_requested") else "failed"
            _update_job(
                _jobs,
                job_id,
                status=status,
                error=None if status == "cancelled" else str(exc),
            )
            _prune_locked(_jobs)


@router.get("/api/models")
def get_models() -> dict:
    return model_manager_status()


@router.post("/api/models/hf-auth/token")
def set_hf_auth_token(payload: HfTokenRequest) -> dict:
    token = payload.token.strip()
    try:
        account = HfApi(token=token).whoami(token=token)
    except Exception as exc:
        raise HTTPException(422, "Hugging Face token을 검증하지 못했습니다.") from exc

    name = str(account.get("name") or account.get("fullname") or "authenticated-user")
    set_session(token, name)
    return {
        "authenticated": True,
        "identity": name,
        "persisted": False,
        "storage": "process-memory-only",
    }


@router.delete("/api/models/hf-auth/token")
def clear_hf_auth_token() -> dict:
    clear_session()
    return {"authenticated": authenticated(), "cleared": True}


@router.post("/api/models/hf-auth/start")
def legacy_hf_auth_start() -> dict:
    if authenticated():
        return {"already_authenticated": True}
    raise HTTPException(
        410,
        (
            "외부 hf/uvx CLI 기반 로그인은 제거되었습니다. 모델 페이지에서 라이선스를 수락한 뒤 "
            "read 권한 Hugging Face token을 세션 인증에 입력하세요. token은 DB나 설정 파일에 저장되지 않습니다."
        ),
    )


@router.post("/api/models/download")
def download_model(payload: DownloadRequest) -> dict:
    if payload.family != "muscriptor" or payload.variant not in MUSCRIPTOR_MODELS:
        raise HTTPException(404, "지원하지 않는 모델입니다.")
    settings = runtime_settings()
    if settings.usage_mode == "commercial":
        raise HTTPException(422, "MuScriptor 공개 weights는 CC BY-NC이므로 상용 모드에서 다운로드할 수 없습니다.")
    if not authenticated():
        raise HTTPException(422, "Hugging Face 인증과 모델 라이선스 수락이 먼저 필요합니다.")

    spec = MUSCRIPTOR_MODELS[payload.variant]
    home = _hf_home()
    home.mkdir(parents=True, exist_ok=True)
    disk_anchor = home.parent if home.parent.exists() else Path.home()
    if shutil.disk_usage(disk_anchor).free < int(spec["weight_bytes"]) * 1.15:
        raise HTTPException(422, "모델을 안전하게 다운로드하기 위한 디스크 여유 공간이 부족합니다.")

    ready, size = _model_cached(str(spec["repo_id"]))
    if ready:
        return {"already_ready": True, "variant": payload.variant, "cached_bytes": size}

    with _jobs_lock:
        active = next(
            (
                job
                for job in _jobs.values()
                if job.get("family") == "muscriptor"
                and job.get("variant") == payload.variant
                and job.get("status") in {"queued", "running", "cancelling"}
            ),
            None,
        )
        if active:
            return {"job_id": active["job_id"], "status": active["status"], "reused": True}
        _prune_locked(_jobs)
        job_id = uuid.uuid4().hex
        now = _now_ts()
        _jobs[job_id] = {
            "job_id": job_id,
            "family": "muscriptor",
            "variant": payload.variant,
            "status": "queued",
            "progress": 0,
            "cached_bytes": size,
            "target_bytes": spec["weight_bytes"],
            "error": None,
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
        }
    threading.Thread(target=_run_download, args=(job_id, payload.variant), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/api/models/jobs/{job_id}")
def model_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "모델 다운로드 작업을 찾을 수 없습니다.")
        result = dict(job)
    if result.get("status") == "running":
        repo_id = str(MUSCRIPTOR_MODELS[result["variant"]]["repo_id"])
        size = _directory_size(_repo_cache_dir(repo_id))
        target = max(int(result.get("target_bytes") or 1), 1)
        result["cached_bytes"] = size
        result["progress"] = min(99, int(size / target * 100))
        with _jobs_lock:
            _jobs[job_id].update(
                cached_bytes=result["cached_bytes"],
                progress=result["progress"],
                updated_at=_now_ts(),
            )
    return result


@router.post("/api/models/jobs/{job_id}/cancel")
def cancel_model_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "모델 다운로드 작업을 찾을 수 없습니다.")
        if job.get("status") in _TERMINAL:
            return dict(job)
        _update_job(_jobs, job_id, cancel_requested=True, status="cancelling")
    return {
        "job_id": job_id,
        "status": "cancelling",
        "note": "현재 HTTP transfer가 끝난 뒤 취소 상태가 적용됩니다.",
    }


@router.post("/api/models/remove")
def remove_model(payload: RemoveRequest) -> dict:
    if payload.family != "muscriptor" or payload.variant not in MUSCRIPTOR_MODELS:
        raise HTTPException(404, "지원하지 않는 모델입니다.")

    settings = runtime_settings()
    if settings.transcription_engine == "muscriptor" and settings.muscriptor_model == payload.variant:
        raise HTTPException(409, "현재 선택된 MuScriptor 모델은 삭제할 수 없습니다. 다른 모델 또는 채보 엔진을 먼저 선택하세요.")
    with _jobs_lock:
        active = any(
            job.get("family") == "muscriptor"
            and job.get("variant") == payload.variant
            and job.get("status") in {"queued", "running", "cancelling"}
            for job in _jobs.values()
        )
    if active:
        raise HTTPException(409, "다운로드 중인 모델은 삭제할 수 없습니다. 작업이 끝난 뒤 다시 시도하세요.")

    repo_id = str(MUSCRIPTOR_MODELS[payload.variant]["repo_id"])
    target = _repo_cache_dir(repo_id)
    try:
        if target.exists():
            shutil.rmtree(target)
    except OSError as exc:
        raise HTTPException(500, f"모델 cache를 삭제하지 못했습니다: {exc}") from exc
    return {"removed": True, "variant": payload.variant, "status": model_manager_status()}
