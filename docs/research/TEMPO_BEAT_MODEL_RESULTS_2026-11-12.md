# Completed BPM-only Beat This! vs fixed DSP comparison

Issue #252 / draft PR #258, stacked on #256. No main merge, production/default
changes, automatic score edits, other-session changes, user songs, external
metadata API calls, credentials, GPU or training. Downbeats/meter were NOT scored.

## Execution and audit

- Successful CPU Actions: https://github.com/JDeun/audio-score-tool/actions/runs/43122028203
- Job130864610770, head e34f2ba6dcace8e1a0d84815528b3eb03e8ae7c7;
  actual PR merge checkout 7fe43f663e37636bcfbe4a7fb70ad5d01d087eff.
- Pinned CPU install and pip check, Ruff, compile, all43 tests (22new+21existing)
  and actual inference passed on the first remote study attempt. A pre-PR import
  grouping correction did not change any inference rule.
- Artifact13900383659 ZIP SHA256
  d62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d;
  report.json SHA256
  36f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82.
- Downloaded ZIP digest matched Actions metadata. Independently recomputed every
  BPM classification, 12 model median inter-beat conversions, grouped counts,
  correction/loss comparisons and all planned denominators. All64 reused DSP
  predictions (16sources x4methods), source WAV SHA/duration and both envelope
  hashes match the previous #256 receipt EXACTLY, including candidate scores.
- Five local new-code/test/protocol/input hashes match the executed receipt.
  This is independent receipt verification, not a second raw-audio model rerun.
- All16 sources fetched, all16 fixed DSP evaluations completed.12 sources were
  admitted to learned-model evaluation; all12 actually ran successfully.4 were
  excluded because no exact annotation-fold entry exists, not inference failure.
- Waveforms:78,189,118 bytes in42 strictHTTP206 requests, no full5.11GB download.
  Original metadata ZIP checksum, matching info.csv and member CRC/SHA checked;
  full audio ZIP SHA256 was NOT verified. No WAV/MIDI/weights artifacts published.

## Training overlap addressed before evaluation

Official upstream final0/small0 includes Groove MIDI training data, so neither
was used. Read original v1.0 groove_midi/8-folds.split (Git blob
0ff7d0954194060597b027c29c2332f894b32aca) and select exactly the corresponding
foldN model. Checked each public checkpoint's `datamodule_hyper_parameters.fold`
and explicit `no_val=False`. Upstream dataset.py excludes that fold from gradient
training. All7 required checkpoints passed this gate; no metadata defaults or
fallback to final0 were accepted.

This proves the **published file-level validation assignment**, not no possible
near-duplicate/composition/performer overlap. Validation can be used for model
selection. These recordings also informed earlier DSP development. NOT an
untouched generalization benchmark and not a fair estimate of mixed-song quality.

Four nonadmitted IDs: drummer7/session2/2, drummer7/session3/87,
drummer7/session3/86, drummer7/session3/73. They stay in all-planned coverage and
are never silently replaced or declared unseen merely because absent from split.

## Frozen same-input methods

Same mono16k float32 WAV excerpts, first up-to24seconds, exact source hashes and
lengths from #256. Unchanged DSP mean8/prior120 and multi-scale consensus/prior120
on detected-hit timing and continuous spectral flux; no selective-confidence
policy, no per-file best-of choice. Beat This source
b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c, CPU float32, Audio2Beats dbn=False.
Only beat outputs used: BPM=60/median(diff(beats)), at least4beats. No reference
BPM/meter/downbeat, manual alias folding or metadata reranking in predictors.
Reference catalog nominal BPM used after all predictions. Nominal success=±4%.

## Primary comparison: SAME12 admitted recordings

| Method | Correct /12 | Half/double /12 | Other wrong /12 |
|---|---:|---:|---:|
| DSP detected hits mean8 |7 (58.33%)|3|2|
| DSP detected hits consensus |7 (58.33%)|3|2|
| DSP continuous flux mean8 |8 (66.67%)|3|1|
| DSP continuous flux consensus |8 (66.67%)|3|1|
| Beat This matched validation fold |9 (75.00%)|2|1|

Vs either hit-based baseline:2 recordings corrected,0 previously correct lost.
Vs either continuous-flux baseline:1 corrected,0 previously correct lost.
Small n, no statistical significance or universal winner claim. This is at most
one extra success over the strongest DSP baseline on this specific admitted set.

### Keep the original16 denominator visible

| Method | Correct /16 planned | Evaluated /16 | Model-unavailable |
|---|---:|---:|---:|
| detected mean8 |8|16|0|
| detected consensus |9|16|0|
| continuous mean8 |9|16|0|
| continuous consensus |10|16|0|
| Beat This fold-matched |9|12|4|

Do NOT compare75% on12 to62.5% on16 as a paired gain.9/16 describes a correct
result on56.25% of planned cases at75% model-admission coverage, not a model's
accuracy on the four untested sources. All4 DSP predictions remain available.

## Which errors changed, which did not

- Nominal138 drummer5/eval_session/1: continuous-flux DSP selected the wrong
  half/double rate; Beat This136.36 is within4%. Hit DSP already got it correct.
- Nominal92 drummer3/session2/25: hit DSP selected half/double; Beat This90.91
  correct. Continuous-flux DSP already got this correct.
- Nominal95 drummer1/session1/145: hit DSP ordinary error; Beat This93.75 correct.
  Continuous-flux DSP already got it correct.
- Remaining model errors:75 ->150;184 ->92.31;157 ->103.45. The first two are
  half/double, the last is an ordinary nominal error under frozen scoring.
  All three also fail every DSP arm, so cross-method agreement is NOT reliable
  evidence that a selected BPM is correct. No posthoc redefinition of2/3x as
  a nominal success or metadata-based correction was performed.
- Existing cohort admitted8: Beat This6/8; new-to-#256 validation cohort4:
  Beat This3/4. These are reused recordings now, not newly held-out compositions.

## CPU practicality and checkpoint provenance

Each admitted source had a24second excerpt. Measured CPU inference calls:
0.903–0.943s, median0.914s, total11.023s for12 calls. This excludes checkpoint
loading/download and is ONE runner execution, not a replicated latency benchmark.
Overall study69.27s excluding environment installation.7 checkpoints downloaded,
567,382,130 bytes total (81,054,590 each), hashes observed before deserialization:

| Fold | SHA256 |
|---|---|
|0|f5c6b6726179e20710e4be6a0fba4018f6cbc89f32f9c0dfd15072cb047578ad|
|1|617b5b9641cefa585c975c97ac4e7fb9c00165ec9827303e8a88fdbd5ff3b71f|
|2|cece4323bccc50738e415c91c204c93ca7021e42ab3a24da6a84dccaa7cc0d4c|
|3|849de186a21ed1cd41d0ac78dc412c61f5283dcafffa9dd32f390674c50792cf|
|4|0a17b1691edbae73a7fac35f6d26d5f8f9aa483b0e3aff5d891c74140f836c52|
|5|ea651e7a0d1a1b243ad3ff268969c8c3d4b7e6d06b1bfb451b020d40526275c2|
|7|f26bed3c18c8f338a39b5a9524ffea7dce654e847ccf3d006e147fa7bf71d43f|

No independent published vendor hashes were available; these identify actual
observed official bytes, not a preexisting authenticity signature. Metadata,
source pin and strict model loading verified; weights never distributed here.

## Decision

Beat This is a practical CPU BPM candidate and modestly better than these DSP
baselines on the same admitted recordings, but not a remedy for all beat-level
aliases. Do not tune the prior repeatedly or accept agreement as calibrated
confidence. Keep DSP as a transparent comparison/fallback; next substantive gate
is licensed real MIXED recordings and corresponding separated drums, with
independent reference BPM and verified model-training disjointness. Compare
without giving reference tempo to either model. Metadata-assisted reranking,
meter/downbeat, original note F1, notation and human editing cost are separate,
unperformed validations. Do not enable automatic score changes.

Keep #258 draft and #252/#249/#34 open. Source/weight MIT statements and their
training-rights caveat are upstream claims, not commercial-release approval.
