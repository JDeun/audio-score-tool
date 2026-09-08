from __future__ import annotations

import os
from threading import Lock

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import runtime_services as runtime
from .api_token import ApiTokenMiddleware
from .request_limits import RequestSizeLimitMiddleware
from .song_mutation_lock import SongMutationSerializationMiddleware
from .sqlite_runtime import configure_sqlite
from .startup_recovery import recover_startup_state


# Compatibility bridge for the hardened routers that share runtime worker/state helpers.
# The public FastAPI app itself is owned only by this module.
def __getattr__(name: str):
    return getattr(runtime, name)


def _reconcile_completed_job_batch() -> None:
    from .job_ingestion import reconcile_completed_jobs
    from .song_routes import _song_store, _tombstones

    reconcile_completed_jobs(
        job_store=runtime._store,
        song_store=_song_store,
        tombstones=_tombstones,
        batch_size=200,
        max_batches=1,
    )


def _worker(*args, **kwargs) -> None:
    runtime._worker(*args, **kwargs)
    _reconcile_completed_job_batch()


def _youtube_worker(*args, **kwargs) -> None:
    runtime._youtube_worker(*args, **kwargs)
    _reconcile_completed_job_batch()


# Routers are imported only after the runtime bridge is established. Several of them
# intentionally import `audio_score_tool.api` for the shared JobStore/worker helpers.
from .engine_api import router as engine_router  # noqa: E402
from .enrichment_api import router as enrichment_router  # noqa: E402
from .export_api_v2 import router as export_router  # noqa: E402
from .job_artifact_api_v2 import router as job_artifact_router  # noqa: E402
from .job_lifecycle_api_v2 import router as job_lifecycle_router  # noqa: E402
from .model_manager_api import router as model_manager_router  # noqa: E402
from .notation_api import router as notation_router  # noqa: E402
from .notation_export_api import export_song  # noqa: E402
from .omr_api import router as omr_router  # noqa: E402
from .publication_api_v2 import router as publication_router  # noqa: E402
from .revision_api_v2 import router as revision_router  # noqa: E402
from .setup_center_api import router as setup_center_router  # noqa: E402
from .song_api import router as song_router  # noqa: E402
from .song_delete_api import router as song_delete_router  # noqa: E402
from .song_metadata_api import router as song_metadata_router  # noqa: E402
from .storage_api_v2 import router as storage_router  # noqa: E402
from .upload_api_v2 import router as upload_router  # noqa: E402
from .validation_api import router as validation_router  # noqa: E402

configure_sqlite()
app = FastAPI(title="AudioScoreTool", version="0.8.0")
_ALLOWED_ORIGINS = set(runtime._ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SongMutationSerializationMiddleware)
app.add_middleware(ApiTokenMiddleware)


@app.middleware("http")
async def protect_local_mutations(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin is not None and origin not in _ALLOWED_ORIGINS:
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
    return await call_next(request)


# Stable runtime/read endpoints retained from the original service implementation.
app.add_api_route("/api/health", runtime.health, methods=["GET"], tags=["system"])
app.add_api_route("/api/setup", runtime.setup, methods=["GET"], tags=["system"])
app.add_api_route("/api/settings", runtime.get_settings, methods=["GET"], tags=["settings"])
app.add_api_route("/api/storage", runtime.get_storage, methods=["GET"], tags=["storage"])
app.add_api_route(
    "/api/settings/tool-paths", runtime.update_tool_paths, methods=["PUT"], tags=["settings"]
)
app.add_api_route("/api/presets", runtime.presets, methods=["GET"], tags=["presets"])
app.add_api_route(
    "/api/sources/youtube/status", runtime.youtube_status, methods=["GET"], tags=["youtube"]
)
app.add_api_route(
    "/api/sources/youtube/inspect",
    runtime.inspect_youtube_source,
    methods=["POST"],
    tags=["youtube"],
)
app.add_api_route("/api/jobs", runtime.list_jobs, methods=["GET"], tags=["jobs"])
app.add_api_route("/api/jobs/{job_id}", runtime.get_job, methods=["GET"], tags=["jobs"])
app.add_api_route(
    "/api/jobs/{job_id}/cancel", runtime.cancel_job, methods=["POST"], status_code=202, tags=["jobs"]
)
app.add_api_route(
    "/api/jobs/{job_id}/reveal", runtime.reveal_job, methods=["POST"], tags=["jobs"]
)

# This critical product route is registered directly by the canonical application so
# its ownership cannot be altered by compatibility router composition.
app.add_api_route(
    "/api/songs/{song_id}/export",
    export_song,
    methods=["POST"],
    tags=["notation-export"],
    response_model=None,
)

# Product-facing mutation/read routers. Each public method/path has one owner; no route
# arrays are mutated and no `_ensure_route` fallback is required.
for router in (
    upload_router,
    job_lifecycle_router,
    job_artifact_router,
    storage_router,
    song_delete_router,
    song_metadata_router,
    revision_router,
    publication_router,
    song_router,
    export_router,
    engine_router,
    validation_router,
    omr_router,
    notation_router,
    setup_center_router,
    model_manager_router,
    enrichment_router,
):
    app.include_router(router)

_startup_lock = Lock()
_startup_diagnostics: dict = {"recovery_completed": False, "recovery": None}


@app.get("/api/startup-diagnostics", tags=["system"])
def startup_diagnostics() -> dict:
    with _startup_lock:
        return {
            "app_version": app.version,
            "recovery_completed": bool(_startup_diagnostics["recovery_completed"]),
            "recovery": _startup_diagnostics["recovery"],
        }


def _server_port() -> int:
    raw = os.getenv("AST_API_PORT", "8080").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("AST_API_PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("AST_API_PORT must be an integer between 1 and 65535")
    return port


def run() -> None:
    from .job_ingestion import full_reconcile_completed_jobs
    from .song_routes import _song_store, _tombstones

    recovery = recover_startup_state(job_store=runtime._store)
    recovery["job_ingestion"] = full_reconcile_completed_jobs(
        job_store=runtime._store,
        song_store=_song_store,
        tombstones=_tombstones,
    )
    with _startup_lock:
        _startup_diagnostics["recovery_completed"] = True
        _startup_diagnostics["recovery"] = recovery
    uvicorn.run(
        "audio_score_tool.api:app",
        host="127.0.0.1",
        port=_server_port(),
        reload=False,
    )


if __name__ == "__main__":
    run()
