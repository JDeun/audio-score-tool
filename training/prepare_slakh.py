from __future__ import annotations

import argparse
import json
from pathlib import Path

ALLOWED_LICENSES = {"CC-BY-4.0", "CC0-1.0", "MIT", "Apache-2.0", "project-owned"}


def infer_split(path: Path) -> str:
    names = {part.lower() for part in path.parts}
    if {"validation", "valid", "val"} & names:
        return "validation"
    if "test" in names:
        return "test"
    return "train"


def build_manifest(root: Path, output: Path) -> int:
    root = root.expanduser().resolve()
    rows: list[dict[str, str]] = []
    for mix in sorted(root.rglob("mix.flac")):
        midi = mix.parent / "all_src.mid"
        metadata = mix.parent / "metadata.yaml"
        if not midi.is_file():
            continue
        rows.append(
            {
                "audio": str(mix),
                "midi": str(midi),
                "metadata": str(metadata) if metadata.is_file() else "",
                "split": infer_split(mix.relative_to(root)),
                "dataset": "Slakh2100",
                "license": "CC-BY-4.0",
                "source": "https://zenodo.org/records/4599666",
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an AudioScore Native manifest from Slakh2100.")
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("training/data/slakh2100.jsonl"))
    args = parser.parse_args()
    count = build_manifest(args.root, args.output)
    print(f"wrote {count} Slakh2100 tracks to {args.output}")


if __name__ == "__main__":
    main()
