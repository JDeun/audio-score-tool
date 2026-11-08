"""Frozen MT3-Infer CLI entry point for app-managed runtime QA.

Production commands always use this frozen binary as a managed executable.
Checkpoint retrieval stays disabled by the caller's --no-download contract.
"""
from __future__ import annotations

import sys


def _configure_frozen_windows_stdio() -> None:
    """The isolated PyInstaller interpreter ignores PYTHONIOENCODING/UTF8.

    The upstream MT3 CLI emits Unicode status characters while the product
    captures output in a file; force a deterministic encoding at the entrypoint.
    No developer/source Python interpreter behavior is changed.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


_configure_frozen_windows_stdio()

from mt3_infer.cli import main  # noqa: E402  -- configure streams first

if __name__ == "__main__":
    raise SystemExit(main())
