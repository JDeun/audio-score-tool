from __future__ import annotations

import uvicorn

from . import api as base_api
from .engine_api import router as engine_router
from .enrichment_api import router as enrichment_router
from .export_api_v2 import router as export_router
from .model_manager_api import router as model_manager_router
from .notation_api import router as notation_router
from .notation_export_api import router as notation_export_router
from .omr_api import router as omr_router
from .pipeline_v2 import transcribe as transcribe_v2
from .preflight_v2 import preflight as preflight_v2
from .request_limits import RequestSizeLimitMiddleware
from .runtime_settings import runtime_settings
from .setup_center_api import router as setup_center_router
from .song_api_v2 import router as song_router
from .song_mutation_lock import SongMutationSerializationMiddleware
from .upload_api_v2 import router as upload_router
from .validation_api import router as validation_router

# v0.8 keeps the proven job/benchmark workers while switching product-facing state and
# upload persistence to the hardened v0.8 routes.
base_api._runtime_settings = runtime_settings
base_api.transcribe = transcribe_v2
base_api.preflight = preflight_v2
app = base_api.app
app.version = "0.8.0"
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(SongMutationSerializationMiddleware)

# Remove legacy handlers that now have v0.8 owners. This avoids request-order shadowing
# and keeps OpenAPI aligned with the endpoint users actually reach.
song_router.routes[:] = [
    route
    for route in song_router.routes
    if not (
        getattr(route, "path", None) == "/api/songs/{song_id}/export"
        and "POST" in (getattr(route, "methods", None) or set())
    )
]
base_api.app.routes[:] = [
    route
    for route in base_api.app.routes
    if not (
        getattr(route, "path", None) in {"/api/jobs", "/api/benchmarks"}
        and "POST" in (getattr(route, "methods", None) or set())
    )
]

app.include_router(upload_router)
app.include_router(notation_export_router)
app.include_router(song_router)
app.include_router(export_router)
app.include_router(engine_router)
app.include_router(validation_router)
app.include_router(omr_router)
app.include_router(notation_router)
app.include_router(setup_center_router)
app.include_router(model_manager_router)
app.include_router(enrichment_router)


def run() -> None:
    uvicorn.run("audio_score_tool.api_ext:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()
