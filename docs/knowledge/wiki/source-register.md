# Evidence and source register

Status: reviewed source inventory; Last reviewed: 2026-11-09

This table records **only what a primary/public source record reports or what remains unresolved**. These are *not* verified local benchmark results. The metadata and rights of each source should be reviewed again before a model is distributed.

| Claim | Evidence status | Source record | Validation gap |
| --- | --- | --- | --- |
| Vocadito v3 provides 40 solo vocal recordings with two independent note annotations under CC BY 4.0 | external-reported | [Vocadito v3 metadata](../raw/vocadito-v3-2026-11-09.md) | Pretraining overlap unknown; no mixed-pop, beat/chord or editing-time acceptance implied |
| YourMT3+ has published research and an implementation, not a verified AudioScoreTool real-music benchmark | external-reported | [YourMT3+ paper](../raw/yourmt3-public-evaluation-2026.md) | Exact code/weights revision, checkpoint rights, instrument-specific metrics |
| MR-MT3 has a public research record; reported licenses require artifact-level verification | external-reported | [MR-MT3 paper](../raw/mr-mt3-public-evaluation-2026.md) | Pin checkpoint hash and reproduce on the same corpus and hardware |
| MuScriptor has published evaluation claims that are not reproduced locally | external-reported | [MuScriptor research](../raw/muscriptor-public-evaluation-2026.md) | Model access, CC BY-NC rights, hardware and real-music comparison |
| SheetSage2 is an optional lead-sheet provider, not a demonstrated replacement for multi-instrument transcription | external-reported | [SheetSage2 model card](../raw/sheetsage2-model-card-2026.md) | Pin MERT/model revisions, secure rights and evaluate independent chord/beat references |
| The repository has a Tier 2 protocol, but protocol existence does not establish successful real-audio evaluation | unverified | [Tier 2 local protocol](../raw/tier2-protocol-2026.md) | Licensed corpus, exact run records, verified note metrics and human edits |

Unresolved observations remain explicitly classified. See [experiment registry](experiment-registry.md), [research landscape](research-landscape.md), and [experiment ledger](../../research/EXPERIMENT_LEDGER_2026.md). No commercial engine policy is approved by this register.

Audit with `python scripts/audit_knowledge_evidence.py`. Every raw source must be represented by a claim with status and validation gap. The audit checks consistency; it does not validate scientific accuracy or scrape remote pages.
