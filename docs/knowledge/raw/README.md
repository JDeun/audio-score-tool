# Immutable source records

Append-only metadata records, one per curated source/revision. Include URL, accessed date, source revision/hash (or `unknown`), license/rights (or `unverified`), issue, and evidence status. Never copy entire copyrighted papers or private recordings. Existing records are not rewritten; corrections are new records linking predecessors.

## Source v2 registration and legacy compatibility

New raw records must specify `Record schema: 2`, `Scope` and `Benchmark comparability`. The registry tool now validates HTTPS URLs, revision, issue link and structured evidence classification before atomically creating the file; it never mutates or downloads old records.

```bash
python scripts/ingest_knowledge_source.py example-paper \
  --url https://example.org/paper \
  --revision unknown --rights unverified --issue '#44' \
  --scope published-literature-only \
  --comparability not-comparable \
  --evidence external-reported
```

Allowed comparability: `unknown`, `not-comparable`, `pending-same-corpus`. No category implies verified model accuracy. A locally reproduced claim requires `--evidence reproduced --run https://github.com/OWNER/REPO/actions/runs/RUN_ID`; this is an asserted provenance link, not an independent accuracy finding. Newly written timestamps use **UTC**; legacy raw records remain read-only under the previous schema.
