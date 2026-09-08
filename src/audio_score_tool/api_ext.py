from __future__ import annotations

from collections.abc import Callable

import uvicorn

from . import api as base_api
from .api_token import ApiTokenMiddleware
from .engine_api import router as engine_router
from .enrichment_api import router as enrichment_router
from .export_api_v2 import router as export_router
from .job_artifact_api_v2 import download_job_artifact_v2
from .job_artifact_api_v2 import router as job_artifact_router
from .job_lifecycle_api_v2 import (
    create_youtube_job_v2,
    delete_job_v2,
    retry_job_v2,
)
from .job_lifecycle_api_v2 import router as job_lifecycle_router
from .model_manager_api import router as model_manager_router
from .notation_api import router as notation_router
from .notation_export_api import build_exports
from .notation_export_api import router as notation_export_router
from .omr_api import router as omr_router
from .pipeline_v2 import transcribe as transcribe_v2
from .preflight_v2 import preflight as preflight_v2
from .publication_api_v2 import router as publication_router
from .publication_api_v2 import update_publication_v2
from .request_limits import RequestSizeLimitMiddleware
from .revision_api_v2 import router as revision_router
from .revision_api_v2 import undo_song_v2
from .runtime_settings import runtime_settings
from .setup_center_api import router as setup_center_router
from .song_api_v2 import router as song_router
from .song_delete_api import delete_song_v2
from .song_delete_api import router as song_delete_router
from .song_metadata_api import router as song_metadata_router
from .song_metadata_api import update_song_metadata_v2
from .song_mutation_lock import SongMutationSerializationMiddleware
from .sqlite_runtime import configure_sqlite
from .startup_recovery import recover_startup_state
from .storage_api_v2 import cleanup_storage_v2
from .storage_api_v2 import router as storage_router
from .upload_api_v2 import create_benchmark_v2, create_job_v2
from .upload_api_v2 import router as upload_router
from .validation_api import router as validation_router

# v0.8 keeps the proven workers/read APIs while switching product-facing mutation
# persistence and lifecycle handling to hardened v0.8 routes.
base_api._runtime_settings = runtime_settings
base_api.transcribe = transcribe_v2
base_api.preflight = preflight_v2
configure_sqlite()
app = base_api.app
app.version = "0.8.0"
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SongMutationSerializationMiddleware)
app.add_middleware(ApiTokenMiddleware)

# Remove legacy handlers that now have v0.8 owners. This avoids request-order shadowing
# and keeps OpenAPI aligned with the endpoint users actually reach.
song_router.routes[:] = [
    route
    for route in song_router.routes
    if not (
        getattr(route, "path", None) == "/api/songs/{song_id}/export"
        and "POST" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/songs/{song_id}"
        and "DELETE" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/songs/{song_id}"
        and "PATCH" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/songs/{song_id}/undo"
        and "POST" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/songs/{song_id}/publication"
        and "PATCH" in (getattr(route, "methods", None) or set())
    )
]
base_api.app.routes[:] = [
    route
    for route in base_api.app.routes
    if not (
        getattr(route, "path", None) in {"/api/jobs", "/api/benchmarks"}
        and "POST" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) in {"/api/jobs/youtube", "/api/jobs/{job_id}/retry"}
        and "POST" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/jobs/{job_id}"
        and "DELETE" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/jobs/{job_id}/files/{kind}"
        and "GET" in (getattr(route, "methods", None) or set())
    )
    and not (
        getattr(route, "path", None) == "/api/storage/cleanup"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]

app.include_router(upload_router)
app.include_router(job_lifecycle_router)
app.include_router(job_artifact_router)
app.include_router(storage_router)
app.include_router(notation_export_router)
app.include_router(song_delete_router)
app.include_router(song_metadata_router)
app.include_router(revision_router)
app.include_router(publication_router)
app.include_router(song_router)
app.include_router(export_router)
app.include_router(engine_router)
app.include_router(validation_router)
app.include_router(omr_router)
app.include_router(notation_router)
app.include_router(setup_center_router)
app.include_router(model_manager_router)
app.include_router(enrichment_router)


def _ensure_route(path: str, method: str, endpoint: Callable, *, tag: str) -> None:
    """Guarantee one public owner for v0.8 routes after legacy router composition.

    FastAPI copies APIRouter routes at include time. This app still composes a legacy
    base router with v0.8 replacements, so make the public contract explicit rather
    than depending on import/include ordering while that migration remains in place.
    """
    matches = [
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]
    if not matches:
        app.add_api_route(path, endpoint, methods=[method], tags=[tag])
    elif len(matches) > 1:
        raise RuntimeError(f"Duplicate public route owner: {method} {path}")


# Song mutation/publication owners.
_ensure_route("/api/songs/{song_id}/export", "POST", build_exports, tag="notation-export")
_ensure_route("/api/songs/{song_id}/undo", "POST", undo_song_v2, tag="revision-v2")
_ensure_route(
    "/api/songs/{song_id}/publication",
    "PATCH",
    update_publication_v2,
    tag="publication-v2",
)
_ensure_route("/api/songs/{song_id}", "PATCH", update_song_metadata_v2, tag="song-metadata-v2")
_ensure_route("/api/songs/{song_id}", "DELETE", delete_song_v2, tag="song-delete-v2")

# Job/storage owners. These are also removed from the legacy app above, so they need
# the same invariant rather than relying on router-copy ordering.
_ensure_route("/api/jobs", "POST", create_job_v2, tag="uploads-v2")
_ensure_route("/api/benchmarks", "POST", create_benchmark_v2, tag="uploads-v2")
_ensure_route("/api/jobs/youtube", "POST", create_youtube_job_v2, tag="jobs-v2")
_ensure_route("/api/jobs/{job_id}/retry", "POST", retry_job_v2, tag="jobs-v2")
_ensure_route("/api/jobs/{job_id}", "DELETE", delete_job_v2, tag="jobs-v2")
_ensure_route(
    "/api/jobs/{job_id}/files/{kind}",
    "GET",
    download_job_artifact_v2,
    tag="job-artifacts-v2",
)
_ensure_route("/api/storage/cleanup", "POST", cleanup_storage_v2, tag="storage-v2")


def run() -> None:
    # Filesystem recovery removes partial uploads/work buffers and can restore an export
    # backup. Keep that side effect out of module import so pytest/OpenAPI inspection is
    # non-destructive; execute it only when the actual sidecar/server is launched.
    recover_startup_state(job_store=base_api._store)
    uvicorn.run("audio_score_tool.api_ext:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()
