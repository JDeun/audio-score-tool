from __future__ import annotations

import uvicorn

from . import api as base_api
from .engine_api import router as engine_router
from .export_api_v2 import router as export_router
from .pipeline_v2 import transcribe as transcribe_v2
from .runtime_settings import runtime_settings
from .song_api_v2 import router as song_router
from .validation_api import router as validation_router

# v0.8 keeps the proven job/benchmark APIs while switching the product workflow to
# SQLite-canonical score storage, deferred exports, and advisory score validation.
base_api._runtime_settings = runtime_settings
base_api.transcribe = transcribe_v2
app = base_api.app
app.version = "0.8.0"
app.include_router(song_router)
app.include_router(export_router)
app.include_router(engine_router)
app.include_router(validation_router)


def run() -> None:
    uvicorn.run("audio_score_tool.api_ext:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()
