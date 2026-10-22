"""Register one curated source metadata record, without downloading its content."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs/knowledge/raw"


def register(slug: str, url: str, revision: str, rights: str, issue: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("slug must be lowercase kebab-case")
    if not url.startswith(("https://", "http://")):
        raise ValueError("source must have an HTTP(S) URL")
    path = RAW / f"{slug}.md"
    content = (
        f"# Source: {slug}\n\nAccessed: {date.today().isoformat()}\n"
        f"URL: {url}\nRevision/hash: {revision}\nRights/license: {rights}\n"
        f"Issue: {issue}\nEvidence: external-reported\n\n"
        "Notes: metadata only; no local reproduction implied.\n"
    )
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--url", required=True)
    parser.add_argument("--revision", default="unknown")
    parser.add_argument("--rights", default="unverified")
    parser.add_argument("--issue", default="unlinked")
    args = parser.parse_args()
    print(register(args.slug, args.url, args.revision, args.rights, args.issue))
