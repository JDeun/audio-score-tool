# Research: AMT provider landscape (initial evidence inventory)

Status: evidence inventory; no local comparative experiment
Last reviewed: 2026-10-23
Issues: [#34](https://github.com/JDeun/audio-score-tool/issues/34), [#43](https://github.com/JDeun/audio-score-tool/issues/43)

## Scope

Compare MuScriptor, YourMT3+, MR-MT3 and SheetSage2 for AudioScoreTool's editable multi-instrument MusicXML workflow. This is a traceability inventory, not an adoption recommendation.

| Candidate | Task scope | Provenance | Evidence classification |
| --- | --- | --- | --- |
| MuScriptor | Multi-instrument AMT | [raw source](../knowledge/raw/muscriptor-public-evaluation-2026.md) | external-reported |
| YourMT3+ | Multi-instrument AMT | [raw source](../knowledge/raw/yourmt3-public-evaluation-2026.md) | external-reported |
| MR-MT3 | Multi-instrument AMT / fallback | [raw source](../knowledge/raw/mr-mt3-public-evaluation-2026.md) | external-reported |
| SheetSage2 | Lead-sheet melody/chords/structure | [raw source](../knowledge/raw/sheetsage2-model-card-2026.md) | external-reported |

## Existing implementation policy

See [engine performance](../ENGINE_PERFORMANCE.ko.md) and [third-party licensing](../THIRD_PARTY_LICENSES.ko.md). Model-specific published F1 figures cannot be directly compared across different datasets and task definitions. Noncommercial model weights must not be enabled in commercial mode.

## Validation plan

Use [Tier 2 protocol](../knowledge/raw/tier2-protocol-2026.md) with legally cleared audio and references. Pin model revisions and environment; measure note/part/chord/beat accuracy, memory/latency and human edit count/time-to-publish. Compare SheetSage2 only on supported tasks and optionally as an auxiliary analysis provider.

## Open gaps

No reproducible same-corpus experiment result or licensed Golden Set is attached here. No failed run log has been independently audited. No default-engine change is authorized.
