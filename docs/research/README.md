# Research reports

Use [research template](RESEARCH_TEMPLATE.md) for reproducible investigations. Index each report here and link source records in [knowledge wiki](../knowledge/README.md). Existing performance and benchmark documents remain authoritative until explicitly superseded.

## Research inventory

- [AMT provider landscape](AMT_PROVIDER_LANDSCAPE_2026.md) — published vs reproduced evidence, license constraints
- [Experiment/failure audit ledger](EXPERIMENT_LEDGER_2026.md) — workstream status and missing evidence

- [Audited implementation PR/CI timeline](IMPLEMENTATION_EVIDENCE_2026.json) — pinned source PRs, merge commits and successful workflow IDs (code evidence only); [scope and unknowns](EXPERIMENT_LEDGER_2026.md). Verify offline via `python scripts/audit_research_history.py`.

- [CocoChorales MR-MT3 real sample baseline](COCOCHORALES_MRMT3_REAL_SAMPLE_2026-11-08.md) — independently scored author WAV/reference MIDI, exact model/source hashes, low instrument/onset F1 and explicit non-generalization limits; actual CI run #42489135513.

- [Four-ensemble real CocoChorales MR-MT3 benchmark](COCOCHORALES_MRMT3_FOUR_ENSEMBLE_2026-11-08.md) — original source/score SHA evidence, GM program/part-collapse diagnosis, per-ensemble F1, explicit train-split limitations; Actions run #42490888388.

- [MR-MT3 program-preserving MIDI before/after evidence](COCOCHORALES_MRMT3_PROGRAM_PRESERVING_2026-11-09.md) — real four-ensemble onset, offset and instrument F1 improvement, exact run/checkpoint/source provenance and remaining over-segmentation.

- [MR-MT3 vs YourMT3+ real same-source A/B](COCOCHORALES_MRMT3_YOURMT3_HEAD_TO_HEAD_2026-11-09.md) — four identical author WAV/MIDI pairs, exact checkpoint SHA, onset/offset versus instrument F1 tradeoffs; paired Actions run #42535843289.

- [혼합 음원 vs 분리 stem 채보 비교](MIX_VS_STEMS_ABLATION_2026-11-09.md) — 동일 모델·원본·정답을 고정한 직접 채보와 Demucs 6개 stem 채보 비교, 전체 음표 보존 및 실패 포함 평가; Actions run #42584934707.

- [CASD 공개 원본 주석 가져오기 검사](CASD_ANNOTATION_IMPORT_2026-11-09.json) — pinned 원본 JAMS 3개, 전문가 12그룹·6,704구간의 실제 import/시간 구간 검사; 음원 매칭과 모델 정확도는 미측정.
