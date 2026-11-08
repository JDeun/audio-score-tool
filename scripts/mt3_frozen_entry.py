"""Frozen MT3-Infer CLI entry point for app-managed runtime QA.

Production commands always use this frozen binary as a managed executable.
Checkpoint retrieval stays disabled by the caller's --no-download contract.
"""
from __future__ import annotations

import sys

from audio_score_tool.mt3_program_midi import main


def _configure_utf8_output() -> None:
    """Keep Unicode CLI status markers representable on Windows log streams.

    When PyInstaller's bootloader freezes the interpreter, it may ignore
    PYTHONIOENCODING because isolated Python startup ignores environment
    settings. Explicit stream reconfiguration is required on legacy Windows
    code pages when stdout/stderr are redirected to product log files.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _configure_utf8_output()
    raise SystemExit(main())
