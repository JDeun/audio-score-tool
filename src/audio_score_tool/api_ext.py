from __future__ import annotations

import uvicorn

from .api import app
from .song_api import router as song_router

app.include_router(song_router)


def run() -> None:
    uvicorn.run("audio_score_tool.api_ext:app", host="127.0.0.1", port=8080, reload=False)


if __name__ == "__main__":
    run()
