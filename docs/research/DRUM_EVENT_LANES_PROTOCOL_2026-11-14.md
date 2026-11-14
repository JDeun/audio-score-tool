# Independent drum lanes and refractory interval — frozen experiment

Tracking: [#305](https://github.com/JDeun/audio-score-tool/issues/305), under
[#303](https://github.com/JDeun/audio-score-tool/issues/303) and
[#36](https://github.com/JDeun/audio-score-tool/issues/36).
Base: `b60545fb2024cd37cf74a78fe68700daa8dde622` (PR #304).
Status at authoring: protocol/code fixed before cohort inference or reference scoring.

## Question and fixed intervention

Does removing global competition between low/high onset lanes improve the
existing coarse kick/backbeat detector, and what changes when its refractory
interval is shortened? This is an untrained DSP mechanism experiment. It does
not evaluate PRISM, train a nine-class model or change a production backend.

| Arm | Peak representation | Refractory interval |
| --- | --- | --- |
| `global85` | Unchanged historical `detect_audio_roles()` | Global 85 ms |
| `global10` | Same global peaks and exclusive role rule | Global 10 ms |
| `independent85` | Low/high peaks independently emit kick/backbeat | Per lane 85 ms |
| `independent10` | Low/high peaks independently emit kick/backbeat | Per lane 10 ms |

The sole nominated candidate is **independent10**; the other interventions are
ablations, not alternatives selected after looking at scores. Keep the original
function unchanged. All arms use its 16 kHz input, 1024-point Hann FFT, 160-sample
hop, positive spectral change, 45–210 / 400–6000 Hz bands, per-band 99th percentile
normalization and clipping. The shared threshold remains
`max(.14, median(max(low,high)) + .45*(p85(max(low,high))-median(max(low,high))))`.
Global arms retain the exclusive low >= 1.25*high kick rule. Independent arms
apply the same threshold to separate local peaks without cross-lane suppression.
Ties and peak times preserve the old convention.

A 10 ms refractory setting does not imply 10 ms resolving power. Strict local
maxima at a 10 ms hop need at least two frames between same-lane peaks, and the
64 ms FFT window further smears close transients. A failure at 15 ms is a useful
observation, not grounds to change the settings after execution.

## Sources, exposure and admission

Use the original Groove MIDI Dataset v1.0.0 recordings. GMD contains human
performances captured from a Roland TD-11 sound module, with aligned MIDI; this
is distinct from a microphone-recorded acoustic kit or a full-band mix. Google
LLC distributes GMD under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Source: [official dataset](https://magenta.tensorflow.org/datasets/groove), checked
2026-11-14. Cite Gillick et al., *Learning to Groove with Inverse Sequence
Transformations*, ICML 2019. Derived event ledgers retain that attribution.

The primary **new_waveform** cohort is six recordings selected only from the
original, checksum-verified `info.csv`: four test-split 4/4 beats of duration
4–28 seconds and two test-split 4/4 fills of duration 4–15 seconds. In each group,
order IDs by SHA256 and select the first required count, after excluding all 16
waveforms in `TEMPO_BEAT_MODEL_INPUTS_2026-11-12.json`. Its exact hash and IDs are
recorded. No replacement follows unavailable audio or detector failure.

The **development_replay** cohort is the four original WAV-study IDs:
`drummer7/session2/93`, `drummer7/session2/2`, `drummer7/session3/87`,
`drummer1/session2/1`. Their original whole-member SHA256 values must match.
Analyze the first 12 seconds, or the complete shorter WAV, with the unchanged
historical decoder. Report the cohorts separately.

All official test MIDI was already processed in earlier project research. The
new-waveform label therefore means newly evaluated WAVs within this project;
it does not mean untouched labels, performer independence, composition
independence or an external validation dataset. Some GMD test performances share
the same grooves. Do not infer a generalization confidence interval from six
selected excerpts.

The MIDI-only archive SHA256 is
`651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e`.
Original metadata SHA256 is
`3e17eef2f18012c0160c183ad5b106964eb429876cceb1eee1b746def4e6b11b`.
Use the existing strict HTTP 206 reader for the roughly 5.1 GB full ZIP, with
10 MiB/request, 140 MiB/experiment and 55 MiB/member limits. Inspect the whole
selected member inventory and conservative compressed-byte estimate before
reading WAV payloads. The reader still enforces the actual cumulative budget.
Validate selected member CRC and record full-member SHA256. **The full ZIP is
not downloaded and its publisher checksum is not verified.** Never substitute
locally synthesized MIDI for missing original WAVs.

## Authored controls

The separate **authored_controls** cohort contains 100 fixed, schematic
integer-PCM inputs. All are deterministic integer oscillators/noise/envelopes
followed by exact power-of-two float32 scaling, avoiding transcendental input
generation differences. These are signal controls, not sampled real drums.
Their canonical input-only hashes are frozen in
`DRUM_EVENT_LANES_CONTROL_INPUTS_2026-11-14.json`; the runtime must reproduce
every array exactly before inference.

| Category | Cases |
| --- | ---: |
| Supported single kick/backbeat | 12 |
| Same-class pair at 15/30/60/90 ms | 48 |
| Simultaneous kick+backbeat | 6 |
| Supported hits with unsupported hat | 18 |
| Unsupported hat/tom singletons | 12 |
| Silence | 4 |

Two construction levels and three deterministic seeds vary non-silent inputs;
leading silence is retained. Construction amplitude is not claimed to be MIDI
velocity or physical force. Predicted novelty strength is likewise not a
velocity estimator. Controls expose extra-class cross-talk, duplicated hits,
missing pairs and temporal resolution. Do not pool them with real WAV accuracy.

## Input and prediction barriers

1. Check the frozen source inventory and run PR #304's input-only numerical
   qualification **in the actual scientific process/runtime**, without CPU
   feature overrides. Preserve the original 66 sources and scientific receipt.
2. Select all ten real inputs from metadata, acquire them, and construct all
   100 control inputs. Save canonical little-endian float32 arrays privately.
   Freeze every planned ID, source SHA, decoded input SHA, shape and status in
   `preflight.json`. No detector or reference parser has run yet.
3. Run all four arms on those exact arrays. Record every raw predicted event,
   including zero detections and failures, in `predictions.json`; save/hash the
   complete population and make the file read-only.
4. Only then parse MIDI references and access authored reference events. Save
   `references.json` bound to the prediction artifact hash. Recheck predictions
   after reference access. Source archive byte hashing and CSV access before
   this barrier are allowed; MIDI event decoding is not.
5. Score the saved event ledgers. A separate auditor, which does not import the
   detector/scorer, verifies matching cardinalities, arithmetic, population,
   source/byte bindings, edit objectives and the fixed decision. Private-input
   SHA verification is performed in the original runner before artifact upload.

The source freeze and protocol are committed remotely before opening the PR
that triggers this single scientific run. Unit tests may use tiny constructed
signals or symbolic events to verify code contracts; no cohort inference,
scores, threshold search or parameter fitting occurs before that freeze.

## References and metrics

Keep original source seconds. Convert MIDI ticks through its own tempo messages;
do not shift references, align detected events to MIDI, infer or supply BPM to
the detector, or quantize performance timing.

The primary supported classes are kick (35/36) and backbeat (37/38/39/40),
preserving the original study's coarse semantic families. All-kit evaluation
also retains closed/open hats, low/mid/high toms, crash and ride using the
official Roland-to-paper mapping. Unknown pitches remain distinct
`unsupported_pitch_N` classes. Unsupported notes are never dropped from the
all-kit denominator; a hat misclassified as backbeat remains a false positive
and an unmatched hat. This is not a nine-class-capable detector.

The primary outcome is **new-waveform micro onset+class F1 at ±50 ms**. Also
report per-clip/per-class counts, precision, recall, FP/FN, all-kit F1, and all
of those at ±10 ms. Matching is one-to-one within each class, maximizing matched
count then minimizing absolute timing error. Unlabeled timing/confusion
diagnostics are separate and cannot replace class-conditioned accuracy.
Temporal endpoint comparisons use a fixed 1e-12-second allowance for floating
representation of inclusive boundaries, including the 90 ms control boundary.

Pair recovery uses class-conditioned ±10 ms matching. Simultaneous reference
groups use a 5 ms span; recovered timing must remain within a 10 ms gap error.
Adjacent same-class reference pairs up to 90 ms require two distinct matched
predictions, a positive predicted gap and at most 10 ms gap error. Report
15/30/60/90 ms authored bins rather than treating ±50 ms F1 as flam recovery.

The correction proxy assigns unit cost to inserting a missing note, deleting an
extra note, reclassifying a note or moving it by more than 5 ms. A separate
minimum-cost assignment permits association only within 50 ms and allows
cross-class reordering. This bounded edit proxy always uses a 50 ms association
window, including reports accompanying the stricter F1. It is not measured human
time and does not cover interface actions, velocity or notation editing.

## Frozen candidate decision

Do not choose the best-scoring arm after execution. `independent10` advances to
broader research only when **all** of the following hold:

- All 110 planned cases are scored with all four arms.
- New-waveform supported micro F1 improves at least **3 percentage points**
  versus `global85` at 50 ms.
- Neither supported class loses more than **2 percentage points** in F1.
- All-kit micro F1 does not decrease, and at least four of the six new excerpts
  have nondecreasing supported F1.
- New-waveform all-kit edit operations per reference event do not increase.
- Authored supported-singleton false positives do not increase.
- Authored strict flam and simultaneous-group recovery counts do not decrease.

These are engineering screening thresholds, not statistical significance.
Complete failures yield `reject_candidate`. Missing inputs/predictions/references
yield `inconclusive_incomplete`, with conditional scored-case summaries and all
failure identities retained. A research pass still does not approve a product
default or a release. Record all ablations even if the nominated candidate fails.

No tuning, data replacement, CPU override, scorer change or successful-run
selection follows musical results. Infrastructure/code failures before inference
may be corrected with a new explicit source revision, preserving prior evidence.
Any change after cohort results requires a separate experiment.

## Evidence and remaining scope

The scientific job uses Python 3.11 with NumPy 1.26.4, SciPy 1.13.1,
mido 1.3.3, threadpoolctl 3.6.0 and PyYAML 6.0.3; contract checks use
pytest 8.4.2 and Ruff 0.16.6. Record the resolved Python patch/build and loaded
NumPy extension, CPU dispatch and BLAS runtime in the actual process.

Preserve original Actions artifact ZIP/digest, actual checkout and PR head, run
attempt, source inventory, imported numerical runtime, qualification, inputs,
all raw event ledgers, matching/aggregate report and independent audit. Publish
derived JSON and source attribution; raw WAV/MIDI files are not uploaded.
Original historical sources/reports/receipts are not rewritten.

Acoustic kits, different sound modules, estimated stems, full mixes, nine-class
recognition, velocity estimation, custom-map/variable-tempo export and measured
human correction time remain separate #303/#299/#300 work.
