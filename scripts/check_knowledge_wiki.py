"""Offline structural validation of the Git-managed research wiki."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "docs/knowledge/wiki"
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIRED = {"index.md", "log.md", "prior-work-ledger.md", "research-landscape.md", "experiment-registry.md"}


def validate() -> list[str]:
    errors: list[str] = []
    pages = sorted(WIKI.glob("*.md"))
    names = {p.name for p in pages}
    for missing in sorted(REQUIRED - names):
        errors.append(f"missing wiki page: {missing}")
    index = WIKI / "index.md"
    index_text = index.read_text(encoding="utf-8") if index.exists() else ""
    for page in pages:
        content = page.read_text(encoding="utf-8")
        if not content.startswith("# "):
            errors.append(f"{page.relative_to(ROOT)}: missing H1")
        if page.name not in {"index.md", "log.md"}:
            if "Status:" not in content or "Last reviewed:" not in content:
                errors.append(f"{page.relative_to(ROOT)}: missing status/review date")
            if page.name not in index_text:
                errors.append(f"{page.relative_to(ROOT)}: not indexed")
        for target in LINK.findall(content):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (page.parent / target.split("#", 1)[0]).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f"{page.relative_to(ROOT)}: broken link {target}")
    return errors


if __name__ == "__main__":
    problems = validate()
    for problem in problems:
        print(problem)
    print(f"Wiki validation: {len(problems)} error(s)")
    raise SystemExit(bool(problems))
