# Research reports

Start with the [current research status and next experiment](RESEARCH_STATUS_2026-11-12.md). It distinguishes completed execution, code integrated into main, and scientific or product acceptance. Historical reports retain their original snapshots, including earlier `pending`, `keep draft`, and `main unchanged` wording.

Use the [research template](RESEARCH_TEMPLATE.md) for reproducible investigations and link source records in the [knowledge wiki](../knowledge/README.md). Existing performance and benchmark documents remain authoritative until explicitly superseded.

## Current navigation

- [Completed note-state factor diagnosis](NOTE_STATE_FACTORS_RESULTS_2026-11-13.md), [frozen protocol](NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md), and [Tony source audit](TONY_NOTE_HMM_SOURCE_AUDIT_2026-11-13.md): [#291](https://github.com/JDeun/audio-score-tool/issues/291) / [#292](https://github.com/JDeun/audio-score-tool/pull/292) completed 245 authored contours and 40 recordings × ten arms × two annotators. Gaussian exponent 1 improves offset-inclusive F1 from the old HMM 3.528561% to 24.270837% (all 40 improved), and runs 22.149227% to 24.270837% (20 improved / 20 worsened). Offset matches fall 980→807 while onset matches rise 1,636→1,929; six no-gap semitone controls remain merged. Historical 200-prediction/240-array parity, 42,867 private checks and 125,891 postrun assertions passed. Product unchanged; [#293](https://github.com/JDeun/audio-score-tool/issues/293) diagnoses the remaining boundary losses.
- [Melodyne, Flex Pitch and Tony design review](MELODYNE_FLEX_PITCH_DESIGN_REVIEW_2026-11-13.md), [frozen note-state protocol](NOTE_STATE_HMM_PROTOCOL_2026-11-13.md) and [completed results](NOTE_STATE_HMM_RESULTS_2026-11-13.md): [#288](https://github.com/JDeun/audio-score-tool/issues/288) records the public-source distinctions; [#289](https://github.com/JDeun/audio-score-tool/issues/289) / [#290](https://github.com/JDeun/audio-score-tool/pull/290) completed all 40 recordings × five arms × two annotators. Primary HMM/RMS reduces pitch/onset/offset F1 from 22.149227% to 5.290052%, with 1 recording improved and 39 worsened. Exact historical baseline parity and 13,538 private-file audit checks passed. Keep this Tony-inspired adaptation out of the product; [#291](https://github.com/JDeun/audio-score-tool/issues/291) tracks its conservative state-model diagnosis. Written-score recovery remains separate.
- [Completed repeat-context results](REPEAT_CONTEXT_RESULTS_2026-11-13.md), [frozen protocol](REPEAT_CONTEXT_PROTOCOL_2026-11-13.md) and [report-only recovery](REPEAT_CONTEXT_RECOVERY_2026-11-13.md): [#286](https://github.com/JDeun/audio-score-tool/issues/286) / [#287](https://github.com/JDeun/audio-score-tool/pull/287) completed all 1,520 cases with original/recovery prediction hash parity. Primary repeat adds nine correct reused authored scores, but new factorial scores change from local 79/12/933 to 83/20/921 correct/wrong/abstained and lose 26 true joint candidates. 435/748 factorial links join different rhythms. Actual repeat coverage is zero for all eight performances, with no target improvement. Both exact artifacts, the original size-guard failure and independent audits remain recorded; #281 stays open.
- [Same-XML local expression results](SAME_SCORE_EXPRESSION_RESULTS_2026-11-12.md) and [protocol](SAME_SCORE_EXPRESSION_PROTOCOL_2026-11-12.md): [#284](https://github.com/JDeun/audio-score-tool/issues/284) / [#285](https://github.com/JDeun/audio-score-tool/pull/285) completed all 488 cases. Primary local improves reused synthetic full-score results from global 201/84/195 to 210/15/255 correct/wrong/abstained, but actual same-score ordinary accuracy falls from 751/782 to 720/782, with 31 correct-to-abstained changes and no gained correct note. Both-correct same-score reference pairs fall 364/391→350/391. Exact source, model and arithmetic audits passed. Inventory-confounded strict signatures, supplied clocks/alignment and development reuse remain explicit; #281 stays open.
- [Same-score expression invariance results](PERFORMED_RHYTHM_INVARIANCE_RESULTS_2026-11-12.md) and [protocol](PERFORMED_RHYTHM_INVARIANCE_PROTOCOL_2026-11-12.md): [#282](https://github.com/JDeun/audio-score-tool/issues/282) / [#283](https://github.com/JDeun/audio-score-tool/pull/283) completed all 524 cases. In 384 stationary authored cases, phase-aware makes 201 correct / 0 wrong / 183 abstentions, but the 96 changing/out-of-vocabulary cases give 84 wrong decisions. Actual GMD same-groove retrieval falls from straight 34/40 to phase-aware 31/40; only 1/40 full canonical decisions is available, without notation truth. Identical-observation controls, stable-wrong collapse, exact receipts and independent audits remain distinct. [#281](https://github.com/JDeun/audio-score-tool/issues/281) stays open for common-score recovery.
- [Original-waveform boundary/rest results](KRAISLER_BOUNDARY_RESULTS_2026-11-12.md) and [protocol](KRAISLER_BOUNDARY_PROTOCOL_2026-11-12.md): [#279](https://github.com/JDeun/audio-score-tool/issues/279) / [#280](https://github.com/JDeun/audio-score-tool/pull/280) completed all six original WAVs and exact historical gate/source replays. All 947 onsets/offsets/midpoints remain in scope; only 49 offsets have isolated annotation context. Supported rest cores total 3.403845s, of which the old gate marks 1.016089s quiet. Four selected old gate changes have distinct spectral contexts. No new inference, release truth or improved F1 is claimed.
- [Local timing and note/rest range results](KRAISLER_EXPRESSIVE_RESULTS_2026-11-12.md) and [protocol](KRAISLER_EXPRESSIVE_PROTOCOL_2026-11-12.md): [#277](https://github.com/JDeun/audio-score-tool/issues/277) / [#278](https://github.com/JDeun/audio-score-tool/pull/278) completed all six recordings, with 373/607 supported beat cells. Local fixed100 resolves 412/947 references; tempo20 resolves 394/947, with 295 stable across tempo10/20/30. Duration and rest boundaries are descriptive ranges; all previous gate gains/losses remain unresolved. Exact receipt and two independent audits passed. No acoustic dynamics, real swing detection or improved model F1 is claimed.
- [KRAISLER score correspondence results](KRAISLER_ALIGNMENT_RESULTS_2026-11-12.md) and [protocol](KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md): #275/#276 completed. The fixed source-consistency method admits 1/6 recordings and 225/947 references at 100ms (137 stable across windows). All prior gate match transitions remain unresolved in the primary/stable scopes. Exact receipts and independent audits are retained; no new inference or written-rest accuracy claim.
- [Research consolidation scope](RESEARCH_INTEGRATION_2026-11-12.md) and [pinned source manifest](RESEARCH_MERGE_MANIFEST_2026-11-12.json): research evidence integrated through [PR #266](https://github.com/JDeun/audio-score-tool/pull/266); this did not activate corrections in the product.
- [Actual waveform gate results](AUDIO_GATE_REST_RESULTS_2026-11-12.md) and [edit attribution](AUDIO_GATE_ATTRIBUTION_RESULTS_2026-11-12.md): completed and integrated through [PR #270](https://github.com/JDeun/audio-score-tool/pull/270) and [PR #272](https://github.com/JDeun/audio-score-tool/pull/272). Performed-note gaps remain distinct from written rests.
- [PR integration and cleanup](PR_CLEANUP_2026-11-12.md): #272 merged, 14 already-integrated research PRs closed, and the substantive reasons #236 remains separate.
- [KRAISLER frozen-gate results](KRAISLER_GATE_RESULTS_2026-11-12.md) and [protocol](KRAISLER_GATE_PROTOCOL_2026-11-12.md): #273/#274; all six new violin recordings completed. Tail-only's vocal gain did not transfer; full/non-tail F1 gains retain note-time damage and are strongly affected by prediction count. Written-rest alignment remains unestablished.
- [Experiment/failure audit ledger](EXPERIMENT_LEDGER_2026.md), [provider landscape](AMT_PROVIDER_LANDSCAPE_2026.md), and [implementation PR/CI evidence](IMPLEMENTATION_EVIDENCE_2026.json). Verify historical implementation evidence with `python scripts/audit_research_history.py`.

## CPU vocal decoding and acoustic evidence

| Study | Protocol | Recorded results |
|---|---|---|
| Public vocadito provider comparison | [CPU specialist scope](CPU_SPECIALIST_PROTOCOL_2026-11-10.md) | [Specialist results](CPU_SPECIALIST_RESULTS_2026-11-10.md); [public vocadito results](CPU_PUBLIC_VOCADITO_RESULTS_2026-11-10.md) |
| Basic Pitch decoding and YourMT3 recovery | [Protocol](CPU_VOCAL_RECOVERY_PROTOCOL_2026-11-11.md) | [Basic Pitch snapshot](CPU_VOCAL_RECOVERY_RESULTS_2026-11-11.md); [PR #239 execution record](https://github.com/JDeun/audio-score-tool/pull/239) |
| DSP note baseline | [Protocol](DSP_NOTE_BASELINE_PROTOCOL_2026-11-11.md) | [Results](DSP_NOTE_BASELINE_RESULTS_2026-11-11.md) |
| Same-pYIN note-state HMM and RMS boundary deletion | [Protocol](NOTE_STATE_HMM_PROTOCOL_2026-11-13.md) | [Completed negative result](NOTE_STATE_HMM_RESULTS_2026-11-13.md); [design review](MELODYNE_FLEX_PITCH_DESIGN_REVIEW_2026-11-13.md) |
| Same-pYIN one-factor HMM diagnosis | [Protocol](NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md) | [Completed results](NOTE_STATE_FACTORS_RESULTS_2026-11-13.md); [source audit](TONY_NOTE_HMM_SOURCE_AUDIT_2026-11-13.md) |
| DSP octave corroboration | [Protocol](DSP_OCTAVE_HYBRID_PROTOCOL_2026-11-11.md) | [Results](DSP_OCTAVE_HYBRID_RESULTS_2026-11-11.md) |
| Offset-tail evidence and supplied-clock controls | [Protocol](OFFSET_TAIL_METER_PROTOCOL_2026-11-11.md) | [Basic Pitch snapshot](OFFSET_TAIL_METER_RESULTS_2026-11-11.md); [PR #248 execution record](https://github.com/JDeun/audio-score-tool/pull/248) |
| Actual RMS gate, hard versus soft edits | [Protocol](AUDIO_GATE_REST_PROTOCOL_2026-11-12.md) | [Results](AUDIO_GATE_REST_RESULTS_2026-11-12.md) |
| Selected waveform-gate edits, tail versus non-tail | [Protocol](AUDIO_GATE_ATTRIBUTION_PROTOCOL_2026-11-12.md) | [Results](AUDIO_GATE_ATTRIBUTION_RESULTS_2026-11-12.md) |
| Frozen gate on new KRAISLER violin recordings | [Protocol](KRAISLER_GATE_PROTOCOL_2026-11-12.md) | [Completed results](KRAISLER_GATE_RESULTS_2026-11-12.md); [run 43184102838](https://github.com/JDeun/audio-score-tool/actions/runs/43184102838) |
| KRAISLER score correspondence and conditional attribution | [Protocol](KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md) | [Completed results](KRAISLER_ALIGNMENT_RESULTS_2026-11-12.md); [run 43201534121](https://github.com/JDeun/audio-score-tool/actions/runs/43201534121) |
| Local source support and tempo-relative note/rest ranges | [Protocol](KRAISLER_EXPRESSIVE_PROTOCOL_2026-11-12.md) | [Completed results](KRAISLER_EXPRESSIVE_RESULTS_2026-11-12.md); [run 43210425240](https://github.com/JDeun/audio-score-tool/actions/runs/43210425240) |
| Original-waveform boundary and supported-rest context | [Protocol](KRAISLER_BOUNDARY_PROTOCOL_2026-11-12.md) | [Completed results](KRAISLER_BOUNDARY_RESULTS_2026-11-12.md); [run 43222529760](https://github.com/JDeun/audio-score-tool/actions/runs/43222529760) |

The vocal corpus is repeatedly used development data. Performed-note F1 and non-note occupancy are not written-rest or full-score accuracy. Reports labelled partial snapshots do not establish the current status of other jobs; consult the [current status](RESEARCH_STATUS_2026-11-12.md) and linked execution records.

## Symbolic selection and candidate headroom

| Study | Protocol | Recorded results |
|---|---|---|
| Rule, Markov, Qwen, LSTM and MelodyT5 admission | [Stage 0 protocol](SYMBOLIC_POSTCORRECTION_STAGE0_2026-11-11.md) | [Stage 0 results](SYMBOLIC_POSTCORRECTION_STAGE0_RESULTS_2026-11-11.md); [mono runtime repair #242](https://github.com/JDeun/audio-score-tool/pull/242) |
| Crossed candidate order/labels and learned mono prior | [Protocol](SYMBOLIC_CHOICE_FOLLOWUP_PROTOCOL_2026-11-11.md) | [Results](SYMBOLIC_CHOICE_FOLLOWUP_RESULTS_2026-11-11.md) |
| Actual vocal error and candidate headroom | [Protocol](ERROR_HEADROOM_INTERFACE_PROTOCOL_2026-11-11.md) | [Basic Pitch snapshot](ERROR_HEADROOM_INTERFACE_RESULTS_2026-11-11.md); [PR #244 execution record](https://github.com/JDeun/audio-score-tool/pull/244) |

Runtime admission, valid JSON and reference-selected candidate ceilings are separate from achieved correction. The Qwen instruction-gate failures and lack of demonstrated LSTM gain remain part of the evidence.

## Rhythm, drum observations and tempo units

| Study | Protocol | Recorded results |
|---|---|---|
| Measure-sum joint rhythm on authored phrases | [Protocol](BAR_SUM_RHYTHM_PROTOCOL_2026-11-11.md) | [Results](BAR_SUM_RHYTHM_RESULTS_2026-11-11.md) |
| Sounding/written duration and synthesized accent evidence | [Protocol](BAR_SUM_ARTICULATION_PROTOCOL_2026-11-11.md) | [Results](BAR_SUM_ARTICULATION_RESULTS_2026-11-11.md) |
| Human-played GMD MIDI and supplied recording metadata | [Protocol](DRUM_METER_METADATA_PROTOCOL_2026-11-11.md) | [PR #253 record](https://github.com/JDeun/audio-score-tool/pull/253); [successful run](https://github.com/JDeun/audio-score-tool/actions/runs/43032170166) |
| Bounded real GMD WAV access and onset extraction | [Protocol](GMD_AUDIO_RANGE_PROTOCOL_2026-11-11.md) | [Results](GMD_AUDIO_RANGE_RESULTS_2026-11-11.md) |
| BPM from rhythm patterns | [Protocol](TEMPO_PATTERN_PROTOCOL_2026-11-11.md) | [Results](TEMPO_PATTERN_RESULTS_2026-11-11.md) |
| Multiwindow consensus and alias abstention | [Protocol](TEMPO_CONSENSUS_PROTOCOL_2026-11-12.md) | [Results](TEMPO_CONSENSUS_RESULTS_2026-11-12.md) |
| DSP versus file-held-out Beat This checkpoints | [Protocol](TEMPO_BEAT_MODEL_PROTOCOL_2026-11-12.md) | [Results](TEMPO_BEAT_MODEL_RESULTS_2026-11-12.md); [frozen inputs](TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json) |
| Half/double pulse units and playback invariance | [Protocol](TEMPO_UNIT_PROTOCOL_2026-11-12.md) | [Results](TEMPO_UNIT_RESULTS_2026-11-12.md) |
| Automatic pulse-unit choice from notation priors | [Protocol](TEMPO_UNIT_SELECTION_PROTOCOL_2026-11-12.md) | [Results](TEMPO_UNIT_SELECTION_RESULTS_2026-11-12.md) |

Nominal BPM, tempo-family membership, beat sequence, meter and downbeat are different outcomes. Supplied units and authored MusicXML playback controls do not establish automatically inferred notation quality.

## Real score/performance duration and rest interpretation

| Study | Protocol | Recorded results |
|---|---|---|
| nASAP duration and pulse-unit pilot | [Protocol](NASAP_DURATION_PROTOCOL_2026-11-12.md) | [Results](NASAP_DURATION_RESULTS_2026-11-12.md) |
| Paired key release versus sustain endpoints | [Protocol](NASAP_KEYOFF_PAIRED_PROTOCOL_2026-11-12.md) | [Results](NASAP_KEYOFF_PAIRED_RESULTS_2026-11-12.md) |
| Joint voice/rest/measure decoding | [Protocol](NASAP_JOINT_RHYTHM_PROTOCOL_2026-11-12.md) | [Results](NASAP_JOINT_RHYTHM_RESULTS_2026-11-12.md) |
| Frozen decoder on composition-disjoint works | [Protocol](NASAP_JOINT_HOLDOUT_PROTOCOL_2026-11-12.md) | [Results](NASAP_JOINT_HOLDOUT_RESULTS_2026-11-12.md) |
| Development-only symbolic quiet-core evidence | [Protocol](NASAP_REST_EVIDENCE_PROTOCOL_2026-11-12.md) | [Results](NASAP_REST_EVIDENCE_RESULTS_2026-11-12.md) |

These experiments supply clock/unit/bar/voice/chord context and aligned note inventory. Preserve their admission denominators and note-damage/rest-erasure measures. The #265 validation works must not become tuning data while retaining an untouched-validation claim. Data-license conditions remain in the source reports.

## Earlier baseline inventory

- [실제 보컬 40개 MR-MT3 / YourMT3+ 평가](VOCADITO_VOCAL_BASELINES_2026-11-09.md) — 원본 체크섬·두 독립 주석자·곡별 실제 F1; 두 모델 각 40/40 완료, 최종 모델 미승인. [Metadata-only 원본 결과](VOCADITO_VOCAL_BASELINES_2026-11-09.json).

- [CocoChorales MR-MT3 real sample baseline](COCOCHORALES_MRMT3_REAL_SAMPLE_2026-11-08.md) — independently scored author WAV/reference MIDI, exact model/source hashes, low instrument/onset F1 and explicit non-generalization limits; actual CI run #42489135513.

- [Four-ensemble real CocoChorales MR-MT3 benchmark](COCOCHORALES_MRMT3_FOUR_ENSEMBLE_2026-11-08.md) — original source/score SHA evidence, GM program/part-collapse diagnosis, per-ensemble F1, explicit train-split limitations; Actions run #42490888388.

- [MR-MT3 program-preserving MIDI before/after evidence](COCOCHORALES_MRMT3_PROGRAM_PRESERVING_2026-11-09.md) — real four-ensemble onset, offset and instrument F1 improvement, exact run/checkpoint/source provenance and remaining over-segmentation.

- [MR-MT3 vs YourMT3+ real same-source A/B](COCOCHORALES_MRMT3_YOURMT3_HEAD_TO_HEAD_2026-11-09.md) — four identical author WAV/MIDI pairs, exact checkpoint SHA, onset/offset versus instrument F1 tradeoffs; paired Actions run #42535843289.

- [혼합 음원 vs 분리 stem 채보 비교](MIX_VS_STEMS_ABLATION_2026-11-09.md) — 동일 모델·원본·정답을 고정한 직접 채보와 Demucs 6개 stem 채보 비교, 전체 음표 보존 및 실패 포함 평가; Actions run #42584934707.

- [CASD 공개 원본 주석 가져오기 검사](CASD_ANNOTATION_IMPORT_2026-11-09.json) — pinned 원본 JAMS 3개, 전문가 12그룹·6,704구간의 실제 import/시간 구간 검사; 음원 매칭과 모델 정확도는 미측정.

## Current continuation

- [Waveform-gate edit attribution protocol](AUDIO_GATE_ATTRIBUTION_PROTOCOL_2026-11-12.md) — issue #271; fixed full/tail-only/complementary interventions on the reused development corpus. Completed: [results](AUDIO_GATE_ATTRIBUTION_RESULTS_2026-11-12.md), [one-case recovery](AUDIO_GATE_ATTRIBUTION_RECOVERY_2026-11-12.md).
- [Durable waveform-gate receipts](receipts/README.md) — exact historical metadata ZIPs and offline integrity/arithmetic checks.
- [KRAISLER transfer result](KRAISLER_GATE_RESULTS_2026-11-12.md) — new-recording comparison completed, including the negative tail-only result, matching/count explanation and unaligned score audit.
- [KRAISLER source correspondence](KRAISLER_ALIGNMENT_RESULTS_2026-11-12.md) — metadata-only follow-up completed with 1/6 clock admission, explicit unresolved denominators, conditional ledgers and limited supported rest context.
- [KRAISLER local timing and duration/rest ranges](KRAISLER_EXPRESSIVE_RESULTS_2026-11-12.md) — completed local-support follow-up with tempo-relative bands, articulation-aware interpretation limits, synthetic swing controls and independent arithmetic/source audits.
- [KRAISLER original-waveform boundary and rest context](KRAISLER_BOUNDARY_RESULTS_2026-11-12.md) — completed all-note onset/offset/midpoint descriptors, exact gate replay and source-defined rest coverage, retaining the distinct selected-watchlist observations and unchanged prior model metrics.
