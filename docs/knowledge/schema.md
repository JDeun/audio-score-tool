# Knowledge governance schema v1

- `raw/`: append-only provenance records (source URL, access date, revision/hash if known, rights, linked issue, evidence status). Correct errors with new linked records.
- `wiki/`: mutable agent-assisted synthesis with citations, index and append-only change log. Evidence status: `external-reported`, `reproduced`, `hypothesis`, `unverified`. Do not turn third-party benchmark claims into local measurements.
- `docs/research/`: canonical research reports and experiment protocols. Record corpus rights/fingerprint, model revision, hardware, metrics, commands, failures, and results.
- `docs/decisions/`: proposed/accepted/superseded ADRs; accepted status requires human-reviewed PR.

Every wiki page must have an H1, Status, Last reviewed (YYYY-MM-DD), primary-source links, open validation gaps, and an index entry. All relative links must resolve. New records are reviewed in PRs. Wiki edits do not change commercial model policy, engine defaults, or release gates.
