"""Frozen MR-MT3 review executable. Never download checkpoints at runtime.

This entrypoint is intended to be frozen with Python/PyTorch by PyInstaller
on the matching native OS. It is not an approved redistributable release.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen_main(argv: list[str] | None = None) -> int:
    """Refuse implicit/explicit downloads before importing the model runtime."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"--help", "-h", "--version"}:
        from mt3_infer.cli import main

        return main(args)

    if args[0] != "transcribe":
        print("Frozen MT3 runtime: only offline transcription is allowed.", file=sys.stderr)
        return 64
    if "--no-download" not in args:
        print("Frozen MT3 runtime: --no-download is required.", file=sys.stderr)
        return 64

    selected: str | None = None
    for index, token in enumerate(args):
        if token in {"-m", "--model"} and index + 1 < len(args):
            selected = args[index + 1]
        elif token.startswith("--model="):
            selected = token.partition("=")[2]
    # This review build contains only the pinned MR-MT3 adapter and weights;
    # the commercial default cannot silently select another model.
    if selected != "mr_mt3":
        print("Frozen MT3 review runtime: only pinned mr_mt3 is supported.", file=sys.stderr)
        return 64

    raw_root = os.environ.get("MT3_CHECKPOINT_DIR", "")
    checkpoint = Path(raw_root).expanduser() / "mr_mt3" / "mt3.pth"
    if (
        not raw_root
        or not Path(raw_root).is_absolute()
        or checkpoint.is_symlink()
        or not checkpoint.is_file()
        or checkpoint.stat().st_size == 0
    ):
        print(
            "Frozen MT3 runtime: a preinstalled, verified MR-MT3 checkpoint is required.",
            file=sys.stderr,
        )
        return 64

    # Defense in depth: the app's managed installer verifies every byte and
    # supplies the checkpoint root. Upstream's built-in auto-download is
    # forbidden in this review executable as well.
    os.environ.update({
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    })
    from mt3_infer.cli import main

    return main(args)


if __name__ == "__main__":
    raise SystemExit(frozen_main())
