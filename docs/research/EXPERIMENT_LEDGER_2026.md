# Research: Experiment and failure audit ledger

Status: implementation CI history audited; limited source-paired AMT measurements exist; release-quality acceptance remains pending
Last reviewed: 2026-11-09

| Workstream | Evidence | Status | Missing proof |
| --- | --- | --- | --- |
| Deterministic music adversarial tests | [protocol](../MUSIC_ADVERSARIAL_BENCHMARK.ko.md) | repository implementation documented | execution artifacts and field transfer |
| Real-music Tier 2 | [#34](https://github.com/JDeun/audio-score-tool/issues/34) | pending | licensed corpus, references, metrics, time-to-publish |
| SheetSage2 integration | [#43](https://github.com/JDeun/audio-score-tool/issues/43) | pending | runnable environment, output conversion, hybrid A/B |
| Native model training | [native design](../NATIVE_MODEL.ko.md) | scaffold documented | trained production checkpoint, quality baseline |
| Managed runtime release | [#29](https://github.com/JDeun/audio-score-tool/issues/29) | pending | clean-machine artifact acceptance |
| Paired original-source AMT | [MR-MT3 vs YourMT3+](COCOCHORALES_MRMT3_YOURMT3_HEAD_TO_HEAD_2026-11-09.md) | four author train examples measured | held-out, real-vocal/pop corpus and editing-time acceptance |
| Direct mix vs estimated stems | [complete same-model comparison](MIX_VS_STEMS_ABLATION_2026-11-09.md) | both models completed 4/4 pairs; all three macro F1 lower after 6-stem AMT | held-out/real-vocal corpus, ground-truth-stem control, evaluated prediction filtering |
| Chordify/CASD chord evaluation | [#53](https://github.com/JDeun/audio-score-tool/issues/53), [#58](https://github.com/JDeun/audio-score-tool/issues/58), [three original annotation imports](CASD_ANNOTATION_IMPORT_2026-11-09.json) | original annotation import/coverage checks passed; real-song evaluation pending | same-recording audio and independent multi-annotator chord metrics |

**Important:** This inventory does not assert that historical failed experiments occurred. Each actual failure must be registered with a command, input fingerprint, environment, log/artifact, root-cause hypothesis and retest status. Never fabricate missing results.

## Implementation evidence backfill — 2026-11-06

The [historical PR/CI ledger](IMPLEMENTATION_EVIDENCE_2026.json) records eight **already merged** implementation PRs (#65, #66, #67, #68, #69, #70, #71, #73). Each entry has its actual merge SHA/date, successful GitHub Actions CI run ID/head SHA and immutable PR/run links. These were checked through the GitHub API at authoring; the offline audit checks **shape and consistency**, not live remote state.

| Workstream | Sources | Observed evidence | Unresolved |
| --- | --- | --- | --- |
| Tier 2 candidate provenance and ensemble | [#65](https://github.com/JDeun/audio-score-tool/pull/65), [#66](https://github.com/JDeun/audio-score-tool/pull/66) | implementation CI success | licensed real-music note/instrument F1 and timing |
| Research claim/source integrity | [#67](https://github.com/JDeun/audio-score-tool/pull/67) | offline source-metadata checks pass | independent scientific claim verification |
| Timed chord comparison and reference import | [#68](https://github.com/JDeun/audio-score-tool/pull/68), [#73](https://github.com/JDeun/audio-score-tool/pull/73) | synthetic annotated-contract tests pass | recording alignment, original license and real-song metrics |
| Repository governance audit | [#69](https://github.com/JDeun/audio-score-tool/pull/69) | read-only policy-check code CI success | actual admin ruleset activation/live push refusal |
| Minimal HF data ingestion | [#70](https://github.com/JDeun/audio-score-tool/pull/70) | synthetic and offline shard tests pass | genuine source-specific rights, provenance and licensed files |
| Tier 2 execution/retest lineage | [#71](https://github.com/JDeun/audio-score-tool/pull/71) | receipt and tamper tests pass | private hardware measurements, actual failing logs and retest evidence |

Run `python scripts/audit_research_history.py` to reject noncanonical PR/run URLs, bad hashes, timestamps, duplicate entries and any promotion of CI evidence into model-quality or commercial-release approval.

**Unknown/not recovered:** older local shell commands, full model/checkpoint hashes, private audio and annotations, independent reference alignment, real measured GPU timing, human editing/publish sessions and accepted architecture decisions. No historical run is invented or inferred from passing tests. This ledger does **not** satisfy the real-music benchmark gate in #34.
