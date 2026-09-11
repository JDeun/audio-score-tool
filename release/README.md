# v1 release evidence

This directory contains **metadata only** for release approval. Do not commit copyrighted Tier 2 audio or private reference assets here.

## Required before any `v1*` tag

The release gate requires `release/v1-quality-approval.json`. The file is intentionally absent until the real Tier 2 campaign in issue #34 is complete.

The receipt must use `schema_version: "1"` and contain:

- `status: "approved"`
- `issue: 34`
- exact `corpus_version`
- reviewer identity and timezone-aware ISO-8601 `reviewed_at`
- selected commercial engine id
- exact model revision
- exact runtime revision
- 64-hex engine artifact SHA-256
- repository-relative Tier 2 comparison report path
- SHA-256 of that comparison report
- at least two source Tier 2 report paths with their SHA-256 values

The comparison report and source reports contain benchmark metadata and metrics only. Private audio remains outside the repository.

## Validation semantics

`python scripts/check_v1_release_readiness.py --tag v1.0.0-rc.1` fails closed unless all of the following are true:

1. Python/npm/Cargo/Tauri/README versions match the tag.
2. The quality approval receipt exists and references issue #34.
3. The approved engine is commercial/default eligible under the engine release policy.
4. At least two immutable source Tier 2 reports exist, match their SHA-256 values, parse as Tier 2 schema v1, and use the approved corpus version.
5. The gate recomputes the Tier 2 comparison from those source reports; the stored comparison must be exactly equal to the recomputed result and match its receipt SHA-256.
6. The approved engine must be that recomputed comparison's qualified `recommended_engine`, with identical model/runtime/artifact revisions.
7. Required Windows x86_64 and macOS arm64 managed runtime artifacts are published with valid URL, checksum, tools, license, and provenance metadata.

The desktop sidecar packaging path independently executes the same unified checker for `v1*` tags. A separate preflight workflow therefore cannot be bypassed by running the desktop release workflow alone.

## Evidence immutability

If a source benchmark report or comparison changes, its SHA-256 changes and the approval receipt becomes invalid. Update the receipt only after a new explicit #34 review. Do not hand-edit metrics after approval without regenerating the comparison and re-reviewing the result.
