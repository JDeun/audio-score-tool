# Knowledge governance schema v1

- `raw/`: append-only provenance records (source URL, access date, revision/hash if known, rights, linked issue, evidence status). Correct errors with new linked records.
- `wiki/`: mutable agent-assisted synthesis with citations, index and append-only change log. Evidence status: `external-reported`, `reproduced`, `hypothesis`, `unverified`. Do not turn third-party benchmark claims into local measurements.
- `docs/research/`: canonical research reports and experiment protocols. Record corpus rights/fingerprint, model revision, hardware, metrics, commands, failures, and results.
- `docs/decisions/`: proposed/accepted/superseded ADRs; accepted status requires human-reviewed PR.

Every wiki page must have an H1, Status, Last reviewed (YYYY-MM-DD), primary-source links, open validation gaps, and an index entry. All relative links must resolve. New records are reviewed in PRs. Wiki edits do not change commercial model policy, engine defaults, or release gates.

## Offline consistency audit (issue #48)

Run `python scripts/audit_knowledge_evidence.py` before merging research changes. The checker requires complete fields and honest evidence status for every immutable `raw/*.md` record, source backlinks from `wiki/`, one structured claim per raw source in `wiki/source-register.md`, and consistent status between claim and source. It validates date syntax, future dates, issue links and review metadata. Records without exact version pins and wiki reviews older than 90 days are emitted as **warnings**, not fabricated facts or automatic edits. CI fails on missing provenance/claims/orphans; manual reviews may opt in to `--fail-on-stale` to enforce freshness. All checks are offline and leave accepted decisions and model defaults unchanged.
