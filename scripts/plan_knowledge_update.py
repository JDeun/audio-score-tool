"""Create a read-only research source impact/review plan, never apply edits."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs/knowledge/raw"
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
META = re.compile(r"(?m)^([A-Za-z][A-Za-z /-]*):\s*(.*?)\s*$")
TOKENS = frozenset({"source", "model", "card", "paper", "public", "evaluation", "record", "research", "the", "and"})


def _label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _references(page: Path, record: Path) -> bool:
    for link in LINK.findall(page.read_text(encoding="utf-8")):
        if link.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target = (page.parent / link.split("#", 1)[0]).resolve()
        if target == record:
            return True
    return False


def impact(source: Path) -> dict:
    """Offline relationship analysis with explicitly non-authoritative hints."""
    resolved = source.resolve()
    if not resolved.is_relative_to(RAW.resolve()) or not resolved.is_file() or resolved.suffix != ".md":
        raise ValueError("source must be an existing raw record")
    content = resolved.read_text(encoding="utf-8")
    fields = dict(META.findall(content))
    tokens = set(re.findall(r"[a-z0-9]+", resolved.stem.casefold())) - TOKENS
    issue = fields.get("Issue", "").strip()
    wiki = ROOT / "docs/knowledge/wiki"
    referenced = sorted(
        (_label(page) for page in wiki.glob("*.md") if _references(page, resolved))
    ) if wiki.exists() else []

    # Candidate pages are recommendations to *review*, not assertions of
    # technical or scientific impact. Keep all changes human-authorized.
    candidates = []
    for folder in (ROOT / "docs/research", wiki, ROOT / "docs/decisions"):
        if not folder.exists():
            continue
        for page in sorted(folder.rglob("*.md")):
            if page.resolve() == resolved:
                continue
            lower = page.read_text(encoding="utf-8").casefold()
            named = sum(token in lower for token in tokens if len(token) > 3)
            issue_match = bool(issue and issue in lower)
            if (named >= 2 or issue_match) and _label(page) not in referenced:
                candidates.append(_label(page))

    raw_neighbours = []
    url = urlsplit(fields.get("URL", ""))
    if RAW.exists():
        for other in sorted(RAW.glob("*.md")):
            if other.resolve() == resolved or other.name == "README.md":
                continue
            neighbour = other.read_text(encoding="utf-8")
            other_fields = dict(META.findall(neighbour))
            other_url = urlsplit(other_fields.get("URL", ""))
            if (
                url.hostname and url.hostname == other_url.hostname
                or issue and issue == other_fields.get("Issue", "").strip()
            ):
                raw_neighbours.append(_label(other))

    return {
        "source": _label(resolved),
        "url": fields.get("URL", ""),
        "revision": fields.get("Revision/hash", ""),
        "rights": fields.get("Rights/license", ""),
        "issue": issue,
        "evidence": fields.get("Evidence", ""),
        "referencing_wiki_pages": referenced,
        "candidate_review_pages": sorted(set(candidates)),
        "related_raw_records": raw_neighbours,
        "requires_claim_registration": not any(page.endswith("/source-register.md")
                                               for page in referenced),
        "automatic_changes": False,
        "review_steps": [
            "Verify original URL, exact revision/hash, license and issue status",
            "Compare this record with existing evidence; label reported vs reproduced separately",
            "Review source-register claim and explicitly record unknowns or contradictions",
            "Review candidate wiki/research pages and append-only change log through PR",
            "Never auto-modify accepted ADRs, commercial model defaults, or v1 release gates",
        ],
    }


def plan(source: Path) -> str:
    data = impact(source)
    lines = [
        f"Review plan for {data['source']}",
        f"Source URL: {data['url'] or '(missing)'}",
        f"Revision: {data['revision'] or '(missing)'}",
        f"Rights: {data['rights'] or '(missing)'}",
        f"Tracking issue: {data['issue'] or '(missing)'}",
        f"Evidence status: {data['evidence'] or '(missing)'}",
        f"Claim needs registration: {data['requires_claim_registration']}",
        "",
        "Existing wiki references:",
        *(f"- {item}" for item in data["referencing_wiki_pages"]),
        "Possible research/wiki impact (human review only):",
        *(f"- {item}" for item in data["candidate_review_pages"]),
        "Related source records:",
        *(f"- {item}" for item in data["related_raw_records"]),
        "Review checklist:",
        *(f"- {item}" for item in data["review_steps"]),
        "",
        "No edits were made. Re-run the offline evidence audit before review.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only source review impact plan")
    parser.add_argument("source", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data = impact(args.source) if args.json else None
    print(json.dumps(data, indent=2, ensure_ascii=False) if data is not None else plan(args.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
