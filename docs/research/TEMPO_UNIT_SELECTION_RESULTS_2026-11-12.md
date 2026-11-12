# #259 / #261 — completed no-reference pulse-unit selection study

## Decision

Unit-aware representation remains valid. The tested automatic notation-prior selector did **not** improve overall agreement with the catalog's quarter-note convention. On the same12 admitted audio sources, one original alias was resolved and one previously matching convention was changed incorrectly:9/12 remained9/12. Do not enable this selector as a production auto-corrector.

An incorrect catalog-unit choice here is NOT necessarily a wrong physical rhythm. All original pulse/onset timestamps are preserved; the candidate quarter coordinates scale with the unit. We measured reproduction of the reference QPM convention, not whether every alternative notation is musically invalid. This study does not invalidate the earlier half/double time-preservation result.

## Execution and provenance

- Draft PR https://github.com/JDeun/audio-score-tool/pull/261; parent #260 at58ab50cf6be509e476913c7be460bdf43047c30f.
- Successful CPU Actions https://github.com/JDeun/audio-score-tool/actions/runs/43132930816 ; job130901234726. Pinned dependency install/pip check, Ruff, compile and **51 tests passed**, as observed in the log (25new plus26 tests collected from the inherited suite). The PR's initial expected27 inherited tests is superseded by this observed count; no inference rule or test parameter was changed after results.
- Execution head d131aa3582d746e63d3a7e39639645db5b71d2c3; actual PR merge checkout5eb32c413940c874f75db66893d2d93f66f987cb. No main merge occurred.
- Artifact13906366081 ZIP SHA256 c2969fe9b471b6eaef52d20c0e8d03783707b61c87a382fa15831e9268bb7e75.
- report.json SHA256 b2c5ef429d2e41e60ad6dc6dcd90bb5a54f13905a9d11a4f45a8d2175650623e.
- Original predictions: #258 Actions43122028203/artifact13900383659. ZIP SHA256d62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d; JSON SHA25636f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82. Learned model inference was NOT repeated.
- Original16 IDs accounted for:12 paired sources completed,4 previously model-unadmitted sources remain unavailable. No replacements or hidden denominator changes.12 sources x2observation representations x5selectors =120 evaluations, not120 independent recordings.
- Independently checked ZIP checksum against Actions, original receipt checksums, all pulse/source/sample hashes and durations, median pulse rates, all candidate unit/QPM arithmetic, cost rankings and abstention thresholds,120 outcome classifications, all summary counts and paired gains/losses. Three new local source/test files match executed hashes. This is receipt provenance/arithmetic auditing, not independent raw-waveform re-inference.
- Actual WAV DSP onset extraction WAS rerun on the exact original decoded first24s.1057 audio-detected onsets and1103 paired known-role MIDI onsets across12 sources. No raw WAV/MIDI/onset arrays published.
- 69,800,510 bytes in38 strictHTTP206 requests; no full5.11GB archive download. Metadata-only ZIP SHA, identical info.csv and source/sample SHA checked. Full audio ZIP SHA was NOT verified. Evaluation elapsed12.58s excluding environment setup, on one CPU runner.
- Research Evidence Contracts also passed on the experiment head. This is NOT full product CI, GUI, MusicXML/PDF rendering or human editing QA.

## What was actually selected

Predictors receive observed pulse timestamps and onset times/roles only. No nominal BPM, meter, file name, reference score, source label or downbeat. Units0.5/1/2 produce three QPM candidates. Quantization is performed once on a common1/12-pulse grid so every unit has identical second-domain fitting error.

A dynamic program computes minimum spelling cost for inter-onset spans, split exactly at candidate3/4 or4/4 barlines and phase hypotheses. These are **spans between attacks of the same role**, NOT measured sustain durations or ground-truth rests. Meter/phase are nuisance search variables; no correct-meter/downbeat claim. All three units can satisfy bar partitioning, so compactness is a preference, not a unique sum constraint.

Hand-set fixed spelling costs, broad120QPM preference and margin threshold were committed before actual evaluation. No threshold retuning, new checkpoints or per-recording winning-method selection.

## Primary result — audio-derived onsets, same12 sources

Nominal agreement means selected quarter-note BPM within4% of catalog. Values below do NOT measure complete score or physical-rhythm correctness.

| Method | Correct convention /12 | Wrong selected /12 | Unselected /12 | Original wrong fixed | Former correct corrupted |
|---|---:|---:|---:|---:|---:|
| Keep one quarter per detected pulse |9|3|0|0|0|
| Broad120QPM preference only |9|3|0|0|0|
| Minimum notation proxy cost |9|3|0|1|1|
| Notation plus weak tempo prior |9|3|0|1|1|
| Notation with >0.10 cost-margin guard |4|0|8|0|0|

The margin guard selects4/12 and matches all4, but withholds5 formerly matching outputs and8 total. Conditional4/4 precision is NOT100% whole-input accuracy; correct/all12 is33.33%, and correct/all16 planned is25%. This reused tiny set does not validate safety on other recordings.

### Concrete paired outcomes

- drummer4/session1/5, reference quarter=184: source92.307692 pulse/min. Both notation methods choose unit2 ->184.615385 QPM, now within tolerance. This is one successful automatic reinterpretation without reference input.
- drummer3/session2/25, reference quarter=92: source90.909091 pulse/min was already within tolerance. Both audio notation methods choose unit2 ->181.818182 QPM, now a catalog-unit mismatch. Observed seconds were NOT shifted; this is a convention-selection regression.
- drummer7/session2/93, reference quarter=75: source150 pulse/min stays unit1 under both notation methods. The earlier unit0.5 interpretation is temporally valid, but this selector does not discover it automatically from these observed attacks.
- Reference157 source103.448276 remains outside the fixed0.5/1/2 family. Do not introduce an extra ratio post hoc to score it correct.

All12 original pulse clocks and their family coverage are unchanged: evaluation-only family ceiling remains11/12. Candidate availability is not the same as selecting the original convention. Four earlier unadmitted sources remain visible in the all16 cohort, not counted as known wrong guesses.

## Separate privileged known-role MIDI diagnostic

Same original pulse clocks, but use human MIDI attack times/roles instead of acoustic detection. This is NOT an automatic audio-only path.

| Method | Correct /12 | Wrong selected /12 | Unselected /12 | Fixed original wrong | Corrupted original correct | Withheld original correct |
|---|---:|---:|---:|---:|---:|---:|
| Keep unit1 |9|3|0|0|0|0|
| Tempo preference only |9|3|0|0|0|0|
| Notation only |8|3|1|1|1|1|
| Notation plus tempo preference |9|2|1|1|0|1|
| Notation margin guard |2|0|10|1|0|8|

One source drummer3/session1/15 contains only5 eligible kick/backbeat MIDI attacks in the interval and cannot satisfy the predeclared minimum8. It remains in the denominator. The audio detector has85 outputs there, a reminder that detected attacks may include other percussion/role errors rather than true eligible hits.

The known-role notation-only method changes a correctly matched102-QPM recording to a doubled convention; adding the weak tempo preference preserves that case. More accurate role/timing observations alone do not make the tested notation prior universally correct.

## Identifiability control and interpretation

Constructed identical physical pulse/onset arrays admit quarter=75/eighth=150 or quarter=150 conventions. Every selector returns the same result for the same arrays regardless of which notation the evaluator names as reference. Our notation rule picks75 in this control, thus matches one convention and misses the other. This demonstrates a limit of these observations, not that all musical-unit inference is impossible: further evidence or user intent can disambiguate many practical cases.

The earlier user insight stands: do not discard a correct double/half pulse clock as useless. However, short attack-gap spelling and measure-sum constraints do not by themselves establish the original note-value convention. This experiment uses a narrow drum timing proxy, not a complete melodic/harmonic rhythm-transcription model.

## Product decision and next substantive gate

Keep measured pulse times plus explicit0.5/1/2 unit candidates; retain original timing. Do not silently apply this new selector or its margin guard. No main/product/default/model/automatic-score/other-session changes were made. PR#261 stays draft; #259/#252/#249 stay open.

Further assessment should target real score-performance pairs with actual written note/rest labels and additional context, or an authorized exact-recording metadata/user-specified beat-unit path. Do not keep tuning these12 recordings and call them independent tests. A user/metadata-provided unit and an automatically inferred unit must remain distinct evidence classes. Actual mixed music, inferred stems, note F1, readable notation and editing effort are still separate unperformed validations.
