# Research status — 2026-11-12

This is the continuation snapshot taken with main at `7dd5c6ce0b18fda023403d92fba981867a1f0202`, after #266 and #270. It is navigation and task state, not a replacement for frozen protocols, result reports or execution receipts. New work below is in progress; no result is claimed for it.

## Repository state at the snapshot

- [Open issues](https://github.com/JDeun/audio-score-tool/issues): **32**. [Open PRs](https://github.com/JDeun/audio-score-tool/pulls): **15**, all draft. These counts precede this continuation's new PRs or issues.
- **14 open research drafts already have their code/evidence integrated through [#266](https://github.com/JDeun/audio-score-tool/pull/266):** #242, #243, #251, #253, #254, #255, #256, #258, #260, #261, #262, #263, #264 and #265. See the [source manifest](RESEARCH_MERGE_MANIFEST_2026-11-12.json). An open draft does not imply an experiment is still running; the stack does not need another merge.
- #266 merged as `2f9e9bd637dd66ed07544230c01ea6e9951a6190`. Its earlier nested-Ruff import-classification/CI problem was repaired. [#268](https://github.com/JDeun/audio-score-tool/pull/268) was closed as a duplicate, without merging.
- [#270](https://github.com/JDeun/audio-score-tool/pull/270), the actual waveform gate pilot for [#269](https://github.com/JDeun/audio-score-tool/issues/269), completed and merged as the snapshot's main commit. It adds research evidence, not automatic product correction.
- The inspected current main and research-head checks have no outstanding execution failure. No active, queued or waiting experiment was identified. Historical failed/cancelled attempts remain part of the record and are not relabelled successful.
- **[Product PR #236](https://github.com/JDeun/audio-score-tool/pull/236) belongs to separate ongoing work and is excluded from this continuation.** Its private-song inputs and branch are not part of this research task.

### Verified baseline CI, not verification of a future head

[Main CI 43174128315](https://github.com/JDeun/audio-score-tool/actions/runs/43174128315) passed on `7dd5c6ce0b18fda023403d92fba981867a1f0202`, including changes, Python, frontend, Tauri and required `verify`. [Python job 131034149693](https://github.com/JDeun/audio-score-tool/actions/runs/43174128315/job/131034149693) checked out that exact commit and reported **2,119 product tests passed, 9 optional skips; 484 research tests passed, 1 upstream warning**. Its inventory covered 200 product and 25 research test files, with zero omitted files. Boundary stress passed 57 checks on each of three passes; the concurrency soak passed two checks. [Compatibility/security 43174128310](https://github.com/JDeun/audio-score-tool/actions/runs/43174128310) and [dependency security 43174128269](https://github.com/JDeun/audio-score-tool/actions/runs/43174128269) also passed.

These are observed results for the existing main baseline. They do not verify new changes, installer release readiness or musical accuracy.

## Scientific workstreams

| Workstream | Actual evidence | Remaining limitation | Next useful task |
|---|---|---|---|
| Vocal decoding and endpoint recovery | [Basic Pitch decoding](CPU_VOCAL_RECOVERY_RESULTS_2026-11-11.md): onset threshold 0.65 changes onset+offset F1 from 31.5831% to 37.2572% on 40 recordings. [Offset evidence](OFFSET_TAIL_METER_RESULTS_2026-11-11.md) adds smaller gains with some damage. | Repeated development corpus; performed-note matching; older reports can be partial execution snapshots. | Attribute edits and damage under identical inputs; reserve separate data for subsequent generalization. |
| Symbolic model selection | [#243 results](SYMBOLIC_CHOICE_FOLLOWUP_RESULTS_2026-11-11.md): Qwen 1.7B/4B fail the 12/12 instruction gate; music choices 14/32 and 16/32. The mono prior adds no demonstrated gain on its supported probes. | Tiny authored examples, presentation sensitivity and unsupported rhythms; no measured real-score correction gain. | Establish reliable reference-free candidate selection before product integration. |
| Drum tempo and unit interpretation | [Beat This comparison](TEMPO_BEAT_MODEL_RESULTS_2026-11-12.md): 9/12 nominal matches versus strongest DSP 8/12 on identical admitted sources; four of 16 planned sources lack model admission. [Unit selection](TEMPO_UNIT_SELECTION_RESULTS_2026-11-12.md) remains 9/12, with one fix and one regression. | Drum-only data; file-level validation is not independent composition generalization. Correct tempo family is not correct automatic unit choice. | Preserve explicit pulse-unit hypotheses and supplied-context labels; do not silently force a convention. |
| Joint written rhythm | [Frozen #265 validation](NASAP_JOINT_HOLDOUT_RESULTS_2026-11-12.md): sustain input exact onset+duration rises 117/385 to 289/385 with joint/rest cost. | Only 7/24 planned works admitted; supplied clock, unit, bars, reference voices/chords and note inventory. Seven formerly correct note pairs are damaged, and true rest time is erased. | Fix coverage separately; distinguish intended rests from articulation, then remove supplied context one factor at a time. |
| Symbolic quiet-core preservation | [#267 development results](NASAP_REST_EVIDENCE_RESULTS_2026-11-12.md): sustain soft evidence reduces erased true-rest length 14.6875 to 7.9792 quarter units, while note pairs correct fall 381 to 379 and false-rest time grows. | Endpoint gaps are not waveform silence; most quiet-core time overlaps written notes. #265 validation was not evaluated by this follow-up. | Obtain evidence that separates short articulation gaps from written rests before a new rest-rich validation. |
| Actual waveform gate | [#270 results](AUDIO_GATE_REST_RESULTS_2026-11-12.md), [run 43172631193](https://github.com/JDeun/audio-score-tool/actions/runs/43172631193): relative-soft onset0.65 F1 37.2572% to 37.6995%; 14 matched outcomes gained/0 lost. | Matching losses conceal occupancy damage: +0.285 seconds of wrongly unoccupied annotated-note time; 20 source edits include deletions/splits. One individual annotation F1 worsens. These are performed gaps, not written rests. | Run the fixed edit-attribution ablation below; later validate written rest/articulation on independently reserved score-aligned sources. |

F1 values and nASAP exact written-note correctness use different targets and denominators; they must not be combined into one accuracy ranking. Full audio-to-score quality, inferred voices, rendered readability and editing-time benefit remain open. [#249](https://github.com/JDeun/audio-score-tool/issues/249), [#259](https://github.com/JDeun/audio-score-tool/issues/259) and [#269](https://github.com/JDeun/audio-score-tool/issues/269) therefore remain research questions.

## Current continuation: in progress

**Question:** How much of the frozen relative-soft gate's measured improvement and damage comes from tail edits, and how much comes from the complementary non-tail edits?

- Compare raw output, the full frozen relative-soft treatment, tail-only edits and complementary non-tail edits on the **same 40 development recordings**, with the existing two Basic Pitch decoders and both human annotations. This is an attribution ablation, not an independent holdout or a newly tuned winning method.
- Freeze edit classification and evaluation before measurement. Keep note matching, per-annotator/per-recording outcomes, occupancy damage, deletion/split counts and unchanged-input replay visible. Do not select a different arm using each recording's reference result.
- Fix the zero-width final RMS-cell boundary case with a focused regression check; retain the original pilot's execution identity and report the effect of the correction explicitly.
- Preserve checksum-verified **metadata receipts** in versioned research evidence so the historical-baseline check does not depend solely on a 14-day Actions artifact. The existing reports identify the original ZIP/report hashes. Do not add source WAV/MIDI, lyrics, full prediction events or weights to the repository.
- Execute on bounded CPU resources and record the new exact head, run, artifact/report identity and all planned-case outcomes before drawing a conclusion. Existing main CI numbers above are not this execution's validation.

This continuation does not yet resolve the central rest-versus-articulation question. It first tests whether the earlier apparent safety is explained by the edit mix. The separate nASAP decoder still receives privileged context, and the already-observed #265 validation works must not be reused for tuning under an untouched-test claim.

## Evidence handling

Use the [research index](README.md) for all current protocols and reports. Preserve historical results and negative findings. Their earlier `keep draft`, `pending` or `main unchanged` language describes their authoring snapshot; the later integration is documented by [#266](https://github.com/JDeun/audio-score-tool/pull/266), [#270](https://github.com/JDeun/audio-score-tool/pull/270) and the [integration scope](RESEARCH_INTEGRATION_2026-11-12.md). Code inclusion and successful CI do not authorize experimental product activation. Raw dataset/model licensing remains separate from the repository's code and derived receipts.
