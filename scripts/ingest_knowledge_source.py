"""Register append-only, source-specific research metadata (schema v2).

No remote fetch, no model or LLM invocation, no automatic wiki/ADR edits.
Accessed dates use UTC so cross-timezone CI never flags future records.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "docs/knowledge/raw"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ISSUE = re.compile(r"^#\d+$|^https://github\.com/[^/]+/[^/]+/issues/\d+$")
RUN = re.compile(r"^https://github\.com/[^/]+/[^/]+/actions/runs/\d+$")
EVIDENCE = frozenset({"external-reported", "reproduced", "hypothesis", "unverified"})
COMPARABILITY = frozenset({"unknown", "not-comparable", "pending-same-corpus"})


def _line(value: str, name: str) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > 240
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be one nonempty single line up to 240 characters")
    return value.strip()


def register(
    slug: str, url: str, revision: str, rights: str, issue: str, *,
    scope: str = "metadata-only",
    comparability: str = "unknown",
    evidence: str = "external-reported",
    run: str | None = None,
) -> Path:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError("slug must be lowercase kebab-case")
    source_url = _line(url, "URL")
    parsed = urlsplit(source_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.port == 0):
        raise ValueError("source must be an uncredentialed HTTPS URL without fragment")
    revision = _line(revision, "revision/hash")
    rights = _line(rights, "rights/license")
    issue = _line(issue, "issue")
    scope = _line(scope, "scope")
    if not ISSUE.fullmatch(issue):
        raise ValueError("issue must be a #number or canonical GitHub issues URL")
    if comparability not in COMPARABILITY:
        raise ValueError("benchmark comparability cannot be treated as verified")
    if evidence not in EVIDENCE:
        raise ValueError("evidence must have an explicit supported classification")
    if evidence == "reproduced":
        if not isinstance(run, str) or not RUN.fullmatch(run):
            raise ValueError("reproduced evidence needs an actual GitHub Actions Run URL")
    elif run is not None:
        raise ValueError("Run reference is only supported for reproduced evidence")

    path = RAW / f"{slug}.md"
    content = (
        f"# Source: {slug}\n\nRecord schema: 2\n"
        f"Accessed: {datetime.now(timezone.utc).date().isoformat()}\n"
        f"URL: {source_url}\nRevision/hash: {revision}\nRights/license: {rights}\n"
        f"Scope: {scope}\nBenchmark comparability: {comparability}\n"
        f"Issue: {issue}\nEvidence: {evidence}\n"
        + (f"Run: {run}\n" if run is not None else "")
        + "\nNotes: metadata only; independent scientific accuracy and license validation are not implied.\n"
    )
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Append-only curated research source metadata")
    parser.add_argument("slug")
    parser.add_argument("--url", required=True)
    parser.add_argument("--revision", default="unknown")
    parser.add_argument("--rights", default="unverified")
    parser.add_argument("--issue", required=True)
    parser.add_argument("--scope", default="metadata-only")
    parser.add_argument("--comparability", choices=sorted(COMPARABILITY), default="unknown")
    parser.add_argument("--evidence", choices=sorted(EVIDENCE), default="external-reported")
    parser.add_argument("--run")
    args = parser.parse_args()
    print(register(
        args.slug, args.url, args.revision, args.rights, args.issue,
        scope=args.scope, comparability=args.comparability,
        evidence=args.evidence, run=args.run,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
