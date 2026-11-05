"""Local, offline keyword search of knowledge and research Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / "docs/knowledge", ROOT / "docs/research", ROOT / "docs/decisions")


def search(query: str) -> list[tuple[str, int, str]]:
    matches: list[tuple[str, int, str]] = []
    for folder in SOURCES:
        for path in sorted(folder.rglob("*.md")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append((str(path.relative_to(ROOT)), number, line.strip()[:240]))
    return matches


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    for path, number, excerpt in search(args.query):
        print(f"{path}:{number}: {excerpt}")
