"""Read-only, offline provenance and claim-evidence audit of the research wiki.

This audits metadata and link *consistency*, not whether third-party claims are
true. No network, LLM, downloads, mutation, or experimental result generation.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
VALID_EVIDENCE = frozenset({"external-reported", "reproduced", "hypothesis", "unverified"})
FIELDS = ("Accessed", "URL", "Revision/hash", "Rights/license", "Issue", "Evidence")
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REVIEW = re.compile(r"(?m)^Status: ([^\n;]+); Last reviewed: (\d{4}-\d{2}-\d{2})\s*$")
LINE = re.compile(r"^([A-Za-z][A-Za-z /-]*):\s*(.*?)\s*$")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    detail: str


def _file(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _local_links(page: Path, text: str, root: Path):
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        location = target.split("#", 1)[0].split("?", 1)[0]
        if not location:
            continue
        dest = (page.parent / location).resolve()
        if dest.is_relative_to(root):
            yield dest


def _raw_fields(content: str) -> dict[str, str]:
    pairs = {}
    for line in content.splitlines():
        found = LINE.fullmatch(line.strip())
        if found:
            pairs[found.group(1)] = found.group(2).strip()
    return pairs


def audit(
    root: Path = ROOT,
    *,
    as_of: date | None = None,
    max_review_age_days: int = 90,
) -> list[Finding]:
    """Return stable, machine-readable errors/warnings; never alter the repo."""
    root = root.resolve()
    as_of = as_of or date.today()
    if max_review_age_days < 0:
        raise ValueError("max_review_age_days must be nonnegative")
    raw = root / "docs/knowledge/raw"
    wiki = root / "docs/knowledge/wiki"
    results: list[Finding] = []

    def add(severity: str, code: str, path: Path, detail: str) -> None:
        results.append(Finding(severity, code, _file(root, path), detail))

    raw_records: dict[Path, dict[str, str]] = {}
    for path in sorted(raw.glob("*.md")):
        if path.name == "README.md":
            continue
        fields = _raw_fields(path.read_text(encoding="utf-8"))
        raw_records[path.resolve()] = fields
        for field in FIELDS:
            if not fields.get(field):
                add("error", "missing-raw-field", path, field)
        if not fields.get("URL"):
            continue
        uri = urlsplit(fields["URL"])
        if uri.scheme not in {"https", "http"} or not uri.hostname or uri.username:
            add("error", "invalid-source-url", path, fields["URL"])
        access = _date(fields.get("Accessed", ""))
        if access is None:
            add("error", "invalid-accessed-date", path, fields.get("Accessed", ""))
        elif access > as_of:
            add("error", "future-accessed-date", path, access.isoformat())
        if not re.fullmatch(r"#\d+|https://github\.com/[^/]+/[^/]+/issues/\d+", fields.get("Issue", "")):
            add("error", "missing-issue-link", path, fields.get("Issue", ""))
        if fields.get("Evidence") not in VALID_EVIDENCE:
            add("error", "invalid-evidence-status", path, fields.get("Evidence", ""))
        if fields.get("Revision/hash", "").startswith(("unknown", "not pinned")):
            add("warning", "unpinned-source-revision", path, "exact revision is not confirmed")
        if fields.get("Evidence") == "reproduced" and not fields.get("Run"):
            add("error", "missing-reproduction-run", path, "reproduced requires Run: reference")

    linked: set[Path] = set()
    index = wiki / "index.md"
    registry = wiki / "source-register.md"
    if not index.exists() or not registry.exists():
        add("error", "missing-evidence-register", wiki, "wiki index and source-register.md required")

    for path in sorted(wiki.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if path.name != "log.md":
            match = REVIEW.search(content)
            if not match:
                add("error", "missing-review-metadata", path, "Status and Last reviewed required")
            else:
                stamp = _date(match.group(2))
                if stamp is None:
                    add("error", "invalid-review-date", path, match.group(2))
                elif stamp > as_of:
                    add("error", "future-review-date", path, stamp.isoformat())
                elif (as_of - stamp).days > max_review_age_days:
                    add("warning", "stale-review", path, f"last reviewed {stamp}; threshold {max_review_age_days}d")
        for dest in _local_links(path, content, root):
            if dest in raw_records:
                linked.add(dest)
        if path.name != "index.md" and path.name != "log.md" and index.exists():
            if path.name not in index.read_text(encoding="utf-8"):
                add("error", "unindexed-wiki-page", path, "add index entry")

    for record in sorted(set(raw_records) - linked):
        add("error", "orphan-raw-record", record, "no wiki claim links to this source")

    if registry.is_file():
        content = registry.read_text(encoding="utf-8")
        header = "| Claim | Evidence status | Source record | Validation gap |"
        if header not in content:
            add("error", "missing-claims-table", registry, "structured evidence claims table required")
        else:
            rows = 0
            claimed_sources: set[Path] = set()
            for row in content.splitlines()[content.splitlines().index(header) + 1:]:
                if not row.startswith("|"):
                    if rows:
                        break
                    continue
                cols = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if len(cols) != 4 or all(set(cell) <= set("-: ") for cell in cols):
                    continue
                rows += 1
                claim, evidence, source_cell, gap = cols
                links = list(_local_links(registry, source_cell, root))
                if not claim or not gap or evidence not in VALID_EVIDENCE or len(links) != 1:
                    add("error", "claim-evidence-missing", registry, f"row {rows}: claim/status/source/gap required")
                    continue
                source = links[0]
                if source not in raw_records:
                    add("error", "claim-source-not-raw", registry, f"row {rows}: source must link to raw record")
                    continue
                claimed_sources.add(source)
                if raw_records[source].get("Evidence") != evidence:
                    add("error", "claim-evidence-conflict", registry, f"row {rows}: source status differs")
            if rows == 0:
                add("error", "empty-claims-table", registry, "register needs at least one sourced claim")
            for path in sorted(set(raw_records) - claimed_sources):
                add("error", "unregistered-source", path, "raw record has no claim in source-register.md")

    return sorted(results, key=lambda x: (x.severity != "error", x.path, x.code, x.detail))


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline research wiki provenance audit")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--max-review-age-days", type=int, default=90)
    parser.add_argument("--fail-on-stale", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    findings = audit(args.root, as_of=args.today, max_review_age_days=args.max_review_age_days)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for item in findings:
            print(f"{item.severity}: {item.code}: {item.path}: {item.detail}")
        print(f"Knowledge evidence: {sum(f.severity == 'error' for f in findings)} errors, "
              f"{sum(f.severity == 'warning' for f in findings)} warnings")
    return int(any(f.severity == "error" or (args.fail_on_stale and f.code == "stale-review")
                   for f in findings))


if __name__ == "__main__":
    raise SystemExit(main())
