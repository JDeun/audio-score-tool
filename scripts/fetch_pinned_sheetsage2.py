"""Prepare the reviewed official SheetSage2 and its exact MERT parent privately."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PINS = json.loads((Path(__file__).resolve().parents[1] /
                   "benchmarks/tier2/sheetsage2-pins.json").read_text())


def verify_files(root: Path, files: dict[str, str]) -> None:
    if root.is_symlink():
        raise ValueError("Model snapshot cannot be a symlink")
    for name, expected in files.items():
        path = root / name
        if Path(name).name != name or path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unsafe pinned model file: {name}")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(8 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError(f"Pinned model file SHA-256 differs: {name}")


def prepare(root: Path) -> None:
    from huggingface_hub import snapshot_download

    project = Path(__file__).resolve().parents[1]
    if root.resolve().is_relative_to(project) or root.is_symlink():
        raise ValueError("Model bytes must remain outside the Git repository")
    for kind in ("model", "mert"):
        pin = PINS[kind]
        snapshot_download(pin["repository"], revision=pin["revision"],
                          local_dir=root / kind, allow_patterns=list(pin["files"]))
        verify_files(root / kind, pin["files"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    prepare(args.root)
    print("Official SheetSage2 and MERT source/config/weight SHA-256 verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
