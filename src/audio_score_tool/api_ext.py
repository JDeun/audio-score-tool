"""Compatibility import for pre-v0.9 callers.

The canonical FastAPI application and desktop sidecar entrypoint live in
`audio_score_tool.api`. This module intentionally contains no application
composition or route mutation.
"""

from .api import (
    _server_port,
    _startup_diagnostics,
    _startup_lock,
    app,
    run,
    startup_diagnostics,
)

__all__ = [
    "app",
    "run",
    "startup_diagnostics",
    "_server_port",
    "_startup_diagnostics",
    "_startup_lock",
]
