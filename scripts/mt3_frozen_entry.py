"""Frozen MT3-Infer CLI entry point for app-managed runtime QA.

Production commands always use this frozen binary as a managed executable.
Checkpoint retrieval stays disabled by the caller's --no-download contract.
"""
from __future__ import annotations

from mt3_infer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
