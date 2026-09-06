from __future__ import annotations

import uvicorn

from . import api as base_api
from .advanced_song_api import router as advanced_song_router
from .engine_api import router as engine_router
from .runtime_settings import runtime_settings
from .song_api import router as song_router

# The base API keeps backwards-compatible function calls, while all runtime workers
# resolve the persisted v0.7 engine settings through the shared resolver.
base_api._runtime_settings = runtime_settings
app = base_api.app
app.version = "0.7.0"
app.include_router(song_router)
app.include_router(advanced_song_router)
app.include_router(engine_router)


def run() -> None:
    uvicorn.run("audio_score_tool.api_ext:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()
