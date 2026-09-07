from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import Settings
from .runner import command_exists, split_command
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

_jobs_lock = threading.Lock()
_jobs: dict[str, dict] = {}


class DownloadRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


class RemoveRequest(BaseModel):
    family: str = "muscriptor"
    variant: str


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
            has_weights = any(snapshot.rglob("*.safetensors") for snapshot in snapshots.iterdir() if snapshot.is_dir())
        except OSError:
            has_weights = False
    # Hugging Face's cache may use symlinks whose bytes live in blobs/. The presence of
    # a snapshot safetensors entry is therefore the authoritative ready signal.
    return has_weights, size


def _hf_command() -> list[str] | None:
    # Prefer an already installed hf CLI. Otherwise uvx lets packaged desktop users
    # invoke the official CLI without managing a Python environment themselves.
    if command_exists("hf"):
        return [*split_command("hf")]
    settings = Settings()
    for candidate in ("uvx", "uv"):
        if command_exists(candidate):
            if candidate == "uvx":
                return [*split_command(candidate), "hf"]
            return [*split_command(candidate), "tool", "run", "hf"]
    # Settings command paths may point to an absolute uvx resolved outside GUI PATH.
    for value in (settings.muscriptor_cmd, settings.whisperx_cmd):
        parts = split_command(value)
        if parts and Path(parts[0]).name.startswith("uvx"):
            return [parts[0], "hf"]
    return None


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
    disk = shutil.disk_usage(_hub_root().parent if _hub_root().parent.exists() else Path.home())
    command = _hf_command()
    return {
        "usage_mode": settings.usage_mode,
        "selected_engine": settings.transcription_engine,
        "selected_muscriptor_model": settings.muscriptor_model,
        "hf_authenticated": huggingface_authenticated(),
        "hf_home": str(_hf_home()),
        "hf_cli_ready": command is not None,
        "disk_free_bytes": disk.free,
        "models": [_model_payload(variant, settings) for variant in ("large", "medium", "small")],
        "policy": {
            "automatic_download": False,
            "explicit_user_action_required": True,
            "commercial_mode_blocks_muscriptor": True,
            "model_license_acceptance_required": True,
        },
    }


def _run_download(job_id: str, variant: str) -> None:
    spec = MUSCRIPTOR_MODELS[variant]
    repo_id = str(spec["repo_id"])
    target_bytes = int(spec["weight_bytes"])
    command = _hf_command()
    if command is None:
        with _jobs_lock:
            _jobs[job_id].update(status="failed", error="Hugging Face CLI를 실행할 수 없습니다. 먼저 uv/uvx를 준비하세요.")
        return

    argv = [*command, "download", repo_id]
    with _jobs_lock:
        _jobs[job_id].update(status="running", command=" ".join(argv))

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        lines: list[str] = []
        while proc.poll() is None:
            size = _directory_size(_repo_cache_dir(repo_id))
            progress = min(99, int(size / max(target_bytes, 1) * 100))
            with _jobs_lock:
                _jobs[job_id]["cached_bytes"] = size
                _jobs[job_id]["progress"] = progress
            if proc.stdout is not None:
                # Avoid blocking on readline while download progress is emitted on the
                # same stream. Cache byte growth is the progress source of truth.
                pass
            time.sleep(0.6)
        stdout, _ = proc.communicate(timeout=5)
        if stdout:
            lines.extend(stdout.splitlines()[-30:])
        ready, size = _model_cached(repo_id)
        if proc.returncode == 0 and ready:
            with _jobs_lock:
                _jobs[job_id].update(status="done", progress=100, cached_bytes=size, log="\n".join(lines))
        else:
            with _jobs_lock:
                _jobs[job_id].update(
                    status="failed",
                    cached_bytes=size,
                    error=("\n".join(lines[-8:]) or f"hf download 종료 코드 {proc.returncode}"),
                )
    except Exception as exc:  # noqa: BLE001 - background job must surface any failure
        with _jobs_lock:
            _jobs[job_id].update(status="failed", error=str(exc))


@router.get("/api/models")
def get_models() -> dict:
    return model_manager_status()


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
    if shutil.disk_usage(_hf_home().parent if _hf_home().parent.exists() else Path.home()).free < int(spec["weight_bytes"]) * 1.15:
        raise HTTPException(422, "모델을 안전하게 다운로드하기 위한 디스크 여유 공간이 부족합니다.")
    if _hf_command() is None:
        raise HTTPException(422, "Hugging Face CLI를 실행할 수 없습니다. Setup Center에서 uv/uvx를 먼저 준비하세요.")

    ready, size = _model_cached(str(spec["repo_id"]))
    if ready:
        return {"already_ready": True, "variant": payload.variant, "cached_bytes": size}

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "family": "muscriptor",
            "variant": payload.variant,
            "status": "queued",
            "progress": 0,
            "cached_bytes": size,
            "target_bytes": spec["weight_bytes"],
            "error": None,
        }
    thread = threading.Thread(target=_run_download, args=(job_id, payload.variant), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued"}


@router.get("/api/models/jobs/{job_id}")
def model_job(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "모델 다운로드 작업을 찾을 수 없습니다.")
        return dict(job)


@router.post("/api/models/remove")
def remove_model(payload: RemoveRequest) -> dict:
    if payload.family != "muscriptor" or payload.variant not in MUSCRIPTOR_MODELS:
        raise HTTPException(404, "지원하지 않는 모델입니다.")
    repo_id = str(MUSCRIPTOR_MODELS[payload.variant]["repo_id"])
    target = _repo_cache_dir(repo_id)
    if target.exists():
        shutil.rmtree(target)
    return {"removed": True, "variant": payload.variant, "status": model_manager_status()}
