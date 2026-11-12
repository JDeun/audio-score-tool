# #269 / #270 — actual waveform amplitude gate: completed CPU pilot

## Decision

The user's amplitude-gate hypothesis has measurable utility on these actual solo-vocal recordings. All four frozen gate treatments improve the average onset+offset F1 over their same-input Basic Pitch control. However, a hard absolute threshold damages previously matched notes and is sensitive to overall gain. Relative-level evidence with an edit cost changes fewer notes and has smaller measured damage, but **is not proven safe or production approved**. This is performed-note/gap evaluation, not published-score rest recognition.

No parameters were changed after evaluation. Research code, tests, protocol and these results can be integrated; no product source, model default, runtime dependency lock or automatic correction is changed.

## Inputs and fair comparison

All40 original vocadito recordings completed, two human annotators A1/A2, two Basic Pitch decoders(default and onset0.65), five arms. These are40 reused DEVELOPMENT recordings, not400/800 independent recordings or a new holdout. Original audio/annotation hashes match the earlier corpus. Predictions were regenerated ONNX CPU once per recording; both decoders share those arrays. All80 raw event fingerprints and320 individual baseline F1 values exactly replay the historical result. No reference labels, lyrics, F0 or beat grid enter the gate/edits; annotations are read after all candidate predictions.

Gate measures native-rate20ms RMS on10ms cells, with60ms low hold and6dB hysteresis. Absolute closing threshold-45dBFS; relative closing threshold95th-percentile frame RMS minus30dB. Both settings were committed before measurement. Hard mode intersects note spans with gate-open intervals; soft mode compares raw/cut with the frozen change-cost objective. Hard/soft are separate methods, not a reference-guided winner per file. Original audio is not altered.

## Note results — recording/annotator-equal mean F1

| Method | Default onset F1 | Default onset+offset F1 | onset0.65 onset F1 | onset0.65 onset+offset F1 |
|---|---:|---:|---:|---:|
| Raw |49.1021%|31.5831%|54.1923%|37.2572%|
| Absolute / hard |49.4663%|33.0708%|54.4211%|38.7662%|
| Absolute / soft |49.3407%|32.7103%|54.4480%|38.5510%|
| Relative / hard |49.2751%|32.3766%|54.3788%|38.0934%|
| Relative / soft |49.2404%|31.9991%|54.3454%|37.6995%|

The largest measured onset0.65 improvement is absolute-hard +1.5090 percentage points. Relative-soft gains +0.4423pp. Both individual annotator means improve under each treatment. Neither metric is end-to-end sheet-music accuracy. Pitch is not corrected; note onsets, offsets and count CAN change, unlike an offset-only test.

### Improvement versus damage, onset0.65

| Method | Reference onset+offset matches gained / lost | Recordings better / worse / equal (A1+A2 mean) | Changed source notes |
|---|---:|---:|---:|
| Absolute / hard |81 /25|15 /1 /24|263|
| Absolute / soft |62 /14|13 /1 /26|86|
| Relative / hard |40 /9|11 /2 /27|119|
| Relative / soft |14 /0|9 /0 /31|20|

Gain/loss counts sum separate A1/A2 matching outcomes; they are NOT necessarily distinct physical notes. Relative-soft does not lose an already matched reference under this tolerance, but **zero matched-reference losses is not zero damage**. Its20 edited source events include9 deletions and2 splits (7 fewer output notes:1783->1776). Some gain comes from removing false estimates and reducing the precision denominator, not from recovering14 distinct new notes.

Important counterexample retained: vocadito_7 under relative-soft changes A1 onset+offset F1 from0.35955056 to0.35555556, while A2 improves0.38095238->0.40000000. A1's score falls due to an extra predicted fragment despite unchanged matched-reference count. Hence the9/0/31 table is a two-annotator-averaged result, not a claim that every individual annotation evaluation improves.

## Time occupancy: non-note gaps versus quiet real notes

Evaluate only between the first and last reference note of each recording, avoiding easy leading/trailing silence. Reference crop is evaluation-only. Values below are sums over40 recordings, A1/A2 totals averaged, in SECONDS (not quarter-note units). Average reference scope contains547.0624s annotated note time and212.3500s non-note time.

| onset0.65 method | Reference non-note time wrongly covered by notes | Annotated note time wrongly unoccupied |
|---|---:|---:|
| Raw |32.175s|101.7024s|
| Absolute / hard |23.265s|106.9824s|
| Absolute / soft |26.245s|105.1824s|
| Relative / hard |28.505s|102.6724s|
| Relative / soft |30.480s|101.9874s|

Absolute-hard restores8.910s of non-note time but additionally removes5.280s of annotated note time. Relative-soft restores1.695s while removing an additional0.285s of annotated note time. Those removed portions may be unmatched notes or boundary portions still within note-matching tolerance. Do not conceal them behind the0 matched-note-loss figure. Reference non-note time can include articulation/annotation choices; it is not an explicit engraved rest.

### Gate alone, before applying any model edits

Time-weighted precision of closed-gate predictions against the performed-note complement, and recall of that complement:

| Gate | A1 precision / recall | A2 precision / recall |
|---|---:|---:|
| Absolute |90.17% /50.32%|92.15% /48.73%|
| Relative |95.95% /39.57%|97.62% /38.17%|

Thus low-amplitude intervals are useful high-precision gap EVIDENCE in this sample, but they miss most annotated non-note time and sometimes overlap real annotated notes. These percentages are neither general rest-classification accuracy nor final-score quality.

## Overall gain control

Same40 WAVs rescaled as unclipped float arrays, no clipping/compression and no new model inference. Total81,72710ms cells per gain condition:
- -12dB: absolute gate changes19,479 cells; relative gate changes0.
- +12dB: absolute gate changes7,585 cells; relative gate changes0.

This supports the normalization property of the tested relative threshold, not robustness to compression, reverb, noise or source-separation artifacts. The source-dependent relative closing levels span approximately-63.65 to-35.21dBFS. It is not simply a uniformly stricter version of the absolute threshold.

## What this does and does not establish

This is actual acoustic RMS evidence, unlike #267's symbolic endpoint-gap evidence. It improves a frozen AMT output in the reused vocal pilot. It does NOT test the nASAP joint metrical decoder, recover explicit rests/staccato from an original published score, evaluate separated mixed-song stems, fix pitch or demonstrate better PDF readability/editing time. The source has performed-note annotations only. The full score/rest hypothesis therefore remains open.

The next scientific gate is fixed relative-level evidence on independent score-aligned mono stems, with true written rest versus short articulation labels, and then mixed/separated audio. Keep hard-vs-soft and absent-gate controls. Do not keep tuning this40-recording sample while reporting it as a holdout. Do not activate either correction automatically from this result alone.

## Execution / provenance / receipt audit

First CPU run **43172631193** succeeded, job131029296062. Executed branch head451f4dc616dabb60499298a0d733c351be405a2a; actual PR merge checkoutd6bd1d761d5edc993d1166c5630bcca1c80ef5bb. New-code lint, compile and26 offline contract tests passed. All40 real-source cases and both decoders/five arms completed. Evaluation time34.0785s on this runner excludes setup/download; no generalized performance claim.

Artifact13922463947 / waveform-gate-rest-43172631193:
- ZIP SHA256 `ce7fb57fa4da65ee320f5c5e14e58d61d6a19bbccedd303143540de239a56325` (matches Actions metadata).
- report.json SHA256 `e807cee43b21425738ae1fea206f61c86eeb4cbbfd4cfd113c4bb226cdf2461d`.
- Baseline artifact13825524844/run42954128502 ZIP SHA256 `6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0` and report SHA256 `dff293dc36a6642141cd235d8d958770e01d4bcd90f6f67c2ae0f82ae465309c` checked before inference comparison.

Independent receipt audit rechecked40 unique IDs/statuses, all80 old event fingerprints/counts,320 baseline metric values,1,600 note-metric/mask identities, all gains/damage, pooled/macro/annotator arithmetic, occupancy conservation and monotonicity, hard-vs-soft containment, gain-control totals and new-source byte hashes. This is receipt arithmetic/provenance validation, NOT an independent second audio/model inference.

The inference-head full repository CI43172631169 and Research Evidence Contracts43172631086 passed. Final documentation-head CI and normal main integration are tracked in PR #270; old-head success does not replace new-head checks. No source audio, MIDI, lyrics, full predicted events or model weights are in the artifact or repository. Archived artifact retention is14days; protocols/hashes and these derived results remain in Git. Replaying the checksum-guarded historical-baseline step requires the corresponding archived metadata ZIP to be retained.

Official vocadito attribution: Bittner, Pasalo, Bosch, Meseguer Brocal, Rubinstein(2021), https://zenodo.org/records/5578807. Model/source licenses remain distinct from this research merge. #269/#249/#259 remain open for independent/full-notation validation.
