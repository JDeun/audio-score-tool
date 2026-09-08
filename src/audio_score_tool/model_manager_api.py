from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import Settings
from .runner import resolve_executable, split_command, terminate_process_tree
from .runtime_settings import runtime_settings
from .system_status import huggingface_authenticated

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
_job_processes: dict[str, subprocess.Popen[str]] = {}
_auth_lock = threading.Lock()
_auth_jobs: dict[str, dict] = {}
_auth_processes: dict[str, subprocess.Popen[str]] = {}


class DownloadRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


class RemoveRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


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


def _popen_group_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _hf_home() -> Path:
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


def _uvx_path_from_settings() -> str | None:
    settings = Settings()
    for value in (settings.muscriptor_cmd, settings.whisperx_cmd, settings.mt3_infer_cmd):
        parts = split_command(value)
        if parts and Path(parts[0]).name.lower().startswith("uvx") and Path(parts[0]).exists():
            return parts[0]
    return None


def _hf_command() -> list[str] | None:
    hf = resolve_executable("hf")
    if hf:
        return [hf]
    uvx = resolve_executable("uvx") or _uvx_path_from_settings()
    if uvx:
        return [uvx, "hf"]
    return None


def _hf_auth_command() -> list[str] | None:
    uvx = resolve_executable("uvx") or _uvx_path_from_settings()
    if uvx:
        return [uvx, "hf"]
    return _hf_command()


def _model_payload(variant: str, settings: Settings) -> dict:
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
    disk_anchor = _hf_home().parent if _hf_home().parent.exists() else Path.home()
    disk = shutil.disk_usage(disk_anchor)
    return {
        "usage_mode": settings.usage_mode,
        "selected_engine": settings.transcription_engine,
        "selected_muscriptor_model": settings.muscriptor_model,
        "hf_authenticated": huggingface_authenticated(),
        "hf_home": str(_hf_home()),
        "hf_cli_ready": _hf_command() is not None,
        "disk_free_bytes": disk.free,
        "models": [_model_payload(variant, settings) for variant in ("large", "medium", "small")],
        "policy": {
            "automatic_download": False,
            "explicit_user_action_required": True,
            "commercial_mode_blocks_muscriptor": True,
            "model_license_acceptance_required": True,
            "auth_token_stored_by_app": False,
            "selected_or_active_model_removal_blocked": True,
            "background_jobs_cancellable": True,
            "background_job_history_limit": _MAX_JOB_HISTORY,
        },
    }


def _run_download(job_id: str, variant: str) -> None:
    spec = MUSCRIPTOR_MODELS[variant]
    repo_id = str(spec["repo_id"])
    target_bytes = int(spec["weight_bytes"])
    command = _hf_command()
    if command is None:
        with _jobs_lock:
            _update_job(_jobs, job_id, status="failed", error="Hugging Face CLI를 실행할 수 없습니다. 먼저 uv/uvx를 준비하세요.")
        return

    with _jobs_lock:
        if _jobs.get(job_id, {}).get("cancel_requested"):
            _update_job(_jobs, job_id, status="cancelled")
            return
        _update_job(_jobs, job_id, status="running", command=" ".join([*command, "download", repo_id]))

    argv = [*command, "download", repo_id]
    log_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=False) as log:
            log_path = log.name
            proc = subprocess.Popen(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy(),
                **_popen_group_kwargs(),
            )
            with _jobs_lock:
                _job_processes[job_id] = proc
                cancelled = bool(_jobs.get(job_id, {}).get("cancel_requested"))
            if cancelled:
                terminate_process_tree(proc)
            while proc.poll() is None:
                size = _directory_size(_repo_cache_dir(repo_id))
                progress = min(99, int(size / max(target_bytes, 1) * 100))
                with _jobs_lock:
                    if _jobs.get(job_id, {}).get("cancel_requested"):
                        cancelled = True
                    _update_job(_jobs, job_id, cached_bytes=size, progress=progress)
                if cancelled:
                    terminate_process_tree(proc)
                    break
                time.sleep(0.7)
            returncode = proc.wait()

        log_text = Path(log_path).read_text(encoding="utf-8", errors="replace") if log_path else ""
        ready, size = _model_cached(repo_id)
        with _jobs_lock:
            if _jobs.get(job_id, {}).get("cancel_requested"):
                _update_job(_jobs, job_id, status="cancelled", cached_bytes=size, error=None)
            elif returncode == 0 and ready:
                _update_job(
                    _jobs,
                    job_id,
                    status="done",
                    progress=100,
                    cached_bytes=size,
                    log="\n".join(log_text.splitlines()[-30:]),
                )
            else:
                _update_job(
                    _jobs,
                    job_id,
                    status="failed",
                    cached_bytes=size,
                    error=("\n".join(log_text.splitlines()[-8:]) or f"hf download 종료 코드 {returncode}"),
                )
            _prune_locked(_jobs)
    except Exception as exc:
        with _jobs_lock:
            status = "cancelled" if _jobs.get(job_id, {}).get("cancel_requested") else "failed"
            _update_job(_jobs, job_id, status=status, error=None if status == "cancelled" else str(exc))
            _prune_locked(_jobs)
    finally:
        with _jobs_lock:
            _job_processes.pop(job_id, None)
        if log_path:
            try:
                Path(log_path).unlink(missing_ok=True)
            except OSError:
                pass


def _run_auth(auth_id: str) -> None:
    command = _hf_auth_command()
    if command is None:
        with _auth_lock:
            _update_job(_auth_jobs, auth_id, status="failed", error="Hugging Face CLI를 실행할 수 없습니다.")
        return
    with _auth_lock:
        if _auth_jobs.get(auth_id, {}).get("cancel_requested"):
            _update_job(_auth_jobs, auth_id, status="cancelled")
            return
        _update_job(_auth_jobs, auth_id, status="running")

    argv = [*command, "auth", "login", "--format", "agent"]
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
            **_popen_group_kwargs(),
        )
        with _auth_lock:
            _auth_processes[auth_id] = proc
        lines: list[str] = []
        if proc.stdout is not None:
            for raw in proc.stdout:
                line = raw.rstrip()
                lines.append(line)
                joined = "\n".join(lines[-12:])
                url_match = re.search(r"https://huggingface\.co/oauth/device", joined)
                code_match = re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", joined)
                with _auth_lock:
                    cancel_requested = bool(_auth_jobs.get(auth_id, {}).get("cancel_requested"))
                    _update_job(
                        _auth_jobs,
                        auth_id,
                        status="waiting_for_user" if url_match else "running",
                        verification_url=url_match.group(0) if url_match else _auth_jobs[auth_id].get("verification_url"),
                        user_code=code_match.group(0) if code_match else _auth_jobs[auth_id].get("user_code"),
                        message=line[-500:],
                    )
                if cancel_requested:
                    terminate_process_tree(proc)
                    break
        returncode = proc.wait()
        with _auth_lock:
            if _auth_jobs.get(auth_id, {}).get("cancel_requested"):
                _update_job(_auth_jobs, auth_id, status="cancelled", error=None)
            elif returncode == 0 and huggingface_authenticated():
                _update_job(_auth_jobs, auth_id, status="done", authenticated=True, message="Hugging Face 로그인 완료")
            else:
                _update_job(
                    _auth_jobs,
                    auth_id,
                    status="failed",
                    error="\n".join(lines[-8:]) or f"hf auth login 종료 코드 {returncode}",
                )
            _prune_locked(_auth_jobs)
    except Exception as exc:
        with _auth_lock:
            status = "cancelled" if _auth_jobs.get(auth_id, {}).get("cancel_requested") else "failed"
            _update_job(_auth_jobs, auth_id, status=status, error=None if status == "cancelled" else str(exc))
            _prune_locked(_auth_jobs)
    finally:
        with _auth_lock:
            _auth_processes.pop(auth_id, None)


@router.get("/api/models")
def get_models() -> dict:
    return model_manager_status()


@router.post("/api/models/hf-auth/start")
def start_hf_auth() -> dict:
    if huggingface_authenticated():
        return {"already_authenticated": True}
    if _hf_auth_command() is None:
        raise HTTPException(422, "Hugging Face CLI를 실행할 수 없습니다. Setup Center에서 uv/uvx를 먼저 준비하세요.")
    with _auth_lock:
        active = next(
            (job for job in _auth_jobs.values() if job.get("status") in {"queued", "running", "waiting_for_user"}),
            None,
        )
        if active:
            return {"auth_id": active["auth_id"], "status": active["status"], "reused": True}
        _prune_locked(_auth_jobs)
        auth_id = uuid.uuid4().hex
        now = _now_ts()
        _auth_jobs[auth_id] = {
            "auth_id": auth_id,
            "status": "queued",
            "authenticated": False,
            "verification_url": None,
            "user_code": None,
            "message": None,
            "error": None,
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
        }
    threading.Thread(target=_run_auth, args=(auth_id,), daemon=True).start()
    return {"auth_id": auth_id, "status": "queued"}


@router.get("/api/models/hf-auth/{auth_id}")
def get_hf_auth(auth_id: str) -> dict:
    with _auth_lock:
        state = _auth_jobs.get(auth_id)
        if state is None:
            raise HTTPException(404, "Hugging Face 인증 작업을 찾을 수 없습니다.")
        result = dict(state)
    if huggingface_authenticated() and result["status"] not in {"failed", "done", "cancelled"}:
        result.update(status="done", authenticated=True, message="Hugging Face 로그인 완료", updated_at=_now_ts())
        with _auth_lock:
            _auth_jobs[auth_id].update(result)
    return result


@router.post("/api/models/hf-auth/{auth_id}/cancel")
def cancel_hf_auth(auth_id: str) -> dict:
    with _auth_lock:
        state = _auth_jobs.get(auth_id)
        if state is None:
            raise HTTPException(404, "Hugging Face 인증 작업을 찾을 수 없습니다.")
        if state.get("status") in _TERMINAL:
            return dict(state)
        _update_job(_auth_jobs, auth_id, cancel_requested=True, status="cancelling")
        proc = _auth_processes.get(auth_id)
    if proc is not None:
        terminate_process_tree(proc)
    return {"auth_id": auth_id, "status": "cancelling"}


@router.post("/api/models/download")
def download_model(payload: DownloadRequest) -> dict:
    if payload.family != "muscriptor" or payload.variant not in MUSCRIPTOR_MODELS:
        raise HTTPException(404, "지원하지 않는 모델입니다.")
    settings = runtime_settings()
    if settings.usage_mode == "commercial":
        raise HTTPException(422, "MuScriptor 공개 weights는 CC BY-NC이므로 상용 모드에서 다운로드할 수 없습니다.")
    if not huggingface_authenticated():
        raise HTTPException(422, "Hugging Face 인증과 모델 라이선스 수락이 먼저 필요합니다.")
    spec = MUSCRIPTOR_MODELS[payload.variant]
    disk_anchor = _hf_home().parent if _hf_home().parent.exists() else Path.home()
    if shutil.disk_usage(disk_anchor).free < int(spec["weight_bytes"]) * 1.15:
        raise HTTPException(422, "모델을 안전하게 다운로드하기 위한 디스크 여유 공간이 부족합니다.")
    if _hf_command() is None:
        raise HTTPException(422, "Hugging Face CLI를 실행할 수 없습니다. Setup Center에서 uv/uvx를 먼저 준비하세요.")

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
        return dict(job)


@router.post("/api/models/jobs/{job_id}/cancel")
def cancel_model_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "모델 다운로드 작업을 찾을 수 없습니다.")
        if job.get("status") in _TERMINAL:
            return dict(job)
        _update_job(_jobs, job_id, cancel_requested=True, status="cancelling")
        proc = _job_processes.get(job_id)
    if proc is not None:
        terminate_process_tree(proc)
    return {"job_id": job_id, "status": "cancelling"}


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
