# Drum event lanes: completed four-arm experiment, candidate rejected

Tracking: [#305](https://github.com/JDeun/audio-score-tool/issues/305),
[PR #306](https://github.com/JDeun/audio-score-tool/pull/306), under #303/#36.
[Frozen protocol](DRUM_EVENT_LANES_PROTOCOL_2026-11-14.md) ·
[Structured results](DRUM_EVENT_LANES_RESULTS_2026-11-14.json) ·
[Original Actions artifact](receipts/drum-event-lanes-43601526575-attempt-1.zip).

## Decision

**Reject the preregistered `independent10` candidate.** On the six newly evaluated
GMD waveforms, supported-class onset F1 fell from **65.142857% to 40.705128%**
(-24.437729 percentage points). Every one of the six clips worsened. The
candidate recovered 13 more correct events but introduced 261 more false
positives; its all-kit correction proxy increased from 324 to 557 operations.

The independent lanes do preserve simultaneous events and some close repeats on
authored signals. That mechanical benefit did not provide acceptable precision
on the actual sound-module recordings. The original baseline and all production
defaults remain unchanged. Passing the scientific workflow means the experiment
and its independent audit completed, not that the candidate passed acceptance.

## Execution and provenance

The protocol, candidate, controls, scorer and independent auditor were published
before opening the PR that triggered this first scientific execution.

| Evidence | Recorded value |
| --- | --- |
| Original run / attempt | [43601526575](https://github.com/JDeun/audio-score-tool/actions/runs/43601526575) / **1** |
| Scientific job | 132467097860 |
| Frozen PR head | `68e7a65fe7ff7a92b5e8806faa74cd51cf66ac7f` |
| Actual PR merge checkout | `367154c38fa15ca41898a7b33768dd3e6350cd91` |
| Frozen source inventory | **87 files**, including the unchanged original 66 scientific sources |
| Source manifest SHA256 | `1f67931f1f2433b801697957522d3a25a8006c05b064a1ec7f845662dbda6673` |
| Scientific runtime | Python **3.11.18**, NumPy **1.26.4**, Intel Xeon **6975P-C** |
| CPU override | `NPY_DISABLE_CPU_FEATURES` **unset** |
| Numerical prerequisite | **461** input arrays, **216** independent reconstructions and **20** analytic rows, all exact |
| Contract tests before inference | **124 passed** |
| Planned / scored cases | **110 / 110**, all four arms: **440** arm-level prediction results |

There was no scientific rerun, replacement case, post-result parameter change or
scorer repair. The original runner audit reopened and verified all **110** saved
input arrays. A second run of the unchanged auditor passed against the extracted
public event receipts; it did not have the private input arrays and explicitly
reports that distinction. Neither audit re-infers the audio or independently
annotates the original MIDI.

The source reader fetched **44,634,686 bytes in 26 strict HTTP 206 requests**.
Whole-member CRC/SHA and original metadata binding passed. The full archive is
5,111,599,714 bytes; it was not downloaded and its full publisher SHA was not
verified. The original ten WAV excerpts total **97.796893 seconds**, of which
**58.635601 seconds** belong to the new-waveform cohort.

## Primary result: six newly evaluated waveforms

All arms receive identical decoded audio and share the historical features and
threshold. Only global versus independent lanes and 85 versus 10 ms refractory
interval vary. `global85` calls the unchanged historical detector.

The reference denominator below is **172 kick/backbeat events**. Matching is
one-to-one, class-conditioned and within 50 ms. An incorrect class stays an
error even if a different drum sounds nearby.

| Arm | Predictions | Correct | False positives | Missed | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| global85 — original | 178 | 114 | 64 | 58 | 64.04% | 66.28% | **65.14%** |
| global10 — shorter interval | 302 | 120 | 182 | 52 | 39.74% | 69.77% | **50.63%** |
| independent85 — separate lanes | 299 | 123 | 176 | 49 | 41.14% | 71.51% | **52.23%** |
| independent10 — fixed candidate | 452 | 127 | 325 | 45 | 28.10% | 73.84% | **40.71%** |

Both isolated changes already lower real-waveform F1. The combined candidate
adds **13** correct matches and **261** false positives. Higher recall alone
does not justify the intervention. No alternative arm was promoted after
examining these results.

### Class-specific damage

| Class | Truth | Baseline correct / predicted | Candidate correct / predicted | Baseline F1 | Candidate F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Kick | 39 | 37 / 69 | 37 / 215 | 68.52% | 29.13% |
| Backbeat | 133 | 77 / 109 | 90 / 237 | 63.64% | 48.65% |

All 13 additional correct events are backbeats. Correct kick detections remain
37, while false kicks increase **32 → 178**. Backbeat false positives increase
**32 → 147**. This is direct event-count evidence for poor selectivity. The
stored confusion diagnostics contain timing ambiguities at simultaneous hits,
so they do not independently identify the acoustic cause of every false event.

### Stricter timing, all-kit denominator and correction proxy

The all-kit denominator is **350 events**, retaining all 178 unsupported hat,
tom and crash events. This detector still emits only kick/backbeat labels.
Unsupported classes do not disappear from the accuracy denominator.

| Arm | Supported F1, 10 ms | All-kit F1, 50 ms | Edit operations | Operations / all-kit reference |
| --- | ---: | ---: | ---: | ---: |
| global85 | 60.00% | 43.18% | 324 | 0.925714 |
| global10 | 44.73% | 36.81% | 435 | 1.242857 |
| independent85 | 46.71% | 37.90% | 412 | 1.177143 |
| independent10 | 35.90% | 31.67% | 557 | 1.591429 |

The minimum operation-count proxy increases **71.91%** for the candidate. It
counts bounded insert/delete/reclassify/move operations and is not measured
human editing time. Its fixed association window remains 50 ms; the stricter
F1 does not silently redefine the edit objective.

### Every selected new excerpt

| Original ID | Metadata style / kind | Seconds | global85 | global10 | independent85 | independent10 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| drummer3/session1/14 | rock / beat | 12.00 | 24.24% | 21.43% | 20.51% | 17.91% |
| drummer5/eval_session/7 | pop/groove7 / beat | 12.00 | 64.29% | 52.17% | 58.00% | 44.60% |
| drummer7/eval_session/7 | pop/groove7 / beat | 12.00 | 83.08% | 65.88% | 69.66% | 50.82% |
| drummer3/session1/32 | jazz / beat | 9.50 | 62.37% | 48.33% | 44.44% | 37.04% |
| drummer7/session2/122 | jazz/fusion / fill | 5.00 | 66.67% | 48.15% | 48.15% | 37.68% |
| drummer7/session2/18 | rock / fill | 8.14 | 77.78% | 63.64% | 59.26% | 49.23% |

These are the metadata-ordered selections, not clips chosen after their scores.
The two `pop/groove7` recordings also make the lack of composition independence
visible. No recording-level significance or external-generalization claim is made.
All official test MIDI had already been processed in earlier project research;
"new" refers only to waveform evaluation, not untouched labels or compositions.
During this run, reference decoding remained behind the frozen-prediction barrier.

## Authored controls: mechanism improves, transfer does not

The 100 controls use fixed integer PCM construction rather than sampled drums.
Their exact input hashes matched the frozen pre-inference manifest.

| Diagnostic | global85 | global10 | independent85 | independent10 |
| --- | ---: | ---: | ---: | ---: |
| Strict same-class pair recovery | 6 / 48 | 16 / 48 | 12 / 48 | **36 / 48** |
| Strict simultaneous supported-group recovery | 0 / 12 | 0 / 12 | **12 / 12** | **12 / 12** |

The simultaneous denominator contains kick+backbeat groups with and without an
additional unsupported hat. Its recovery condition covers the supported events;
it does not certify recovery of that hat.

| Authored inter-hit gap | global85 | global10 | independent85 | independent10 |
| --- | ---: | ---: | ---: | ---: |
| 15 ms | 0 / 12 | 0 / 12 | 0 / 12 | **0 / 12** |
| 30 ms | 0 / 12 | 4 / 12 | 0 / 12 | **12 / 12** |
| 60 ms | 0 / 12 | 6 / 12 | 0 / 12 | **12 / 12** |
| 90 ms | 6 / 12 | 6 / 12 | 12 / 12 | **12 / 12** |

The candidate's supported-singleton false positives increase **6 → 12**.
The controls therefore show both expanded event representation and added
cross-talk. None of the arms resolves the 15 ms controls under the fixed strict
criterion. Shortening a refractory parameter does not remove the shared 10 ms
hop and 64 ms window limits.

On the **new real waveforms**, strict close-pair recovery remains **0 / 8 for
every arm**; simultaneous-group recovery changes **0 / 2 → 1 / 2** for the
independent arms. These small, source-dependent diagnostics are separate from
the much clearer false-positive increase in the primary metric.
Here a real-audio "flam" diagnostic means an adjacent same-role pair within
90 ms in the MIDI reference; it is not an independently annotated musical rudiment.

## Historical development replay

The four previous waveforms are replayed separately. Their baseline has 116
supported reference events, 139 predictions and 93 class-correct matches:
**72.941176%** supported F1. The three interventions score **65.100671%**,
**57.988166%** and **52.741514%**, respectively.

The previous report's **75.29%** pooled number was class-agnostic: 96 timing
matches among the same 116 references and 139 predictions. Do not compare that
number to the new class-conditioned 93-match result as a baseline regression.
Both original per-class match totals, kick 40 and backbeat 53, are preserved.

## Fixed acceptance gates and interpretation

The complete population gate passes. The primary +3 pp condition, both-class
non-regression, all-kit non-regression, four-of-six clip condition, correction
proxy and singleton false-positive conditions all fail. Authored pair and
simultaneous recovery conditions pass. Their improvement cannot override the
failed real-waveform and false-positive gates.

The supported conclusion is narrow: **independent low/high spectral novelty
lanes with the same simple threshold are insufficient for acceptable drum
classification**, and shortening suppression amplifies their false detections.
This does not disprove class-independent event outputs in a trained or more
discriminative detector, and it does not measure PRISM's proprietary algorithm.

The next justified comparison should retain the event representation and raw
evaluation contract while adding evidence that distinguishes drum classes
before relaxing suppression. A separately frozen drum-aware model or calibrated
class-evidence baseline is a candidate for that follow-up. Its runtime, model
license, source exposure and selection must be specified before another trial.
Do not tune another frequency threshold on these six clips and call it an
independent validation result.

Acoustic kits, additional sound modules, separated stems, full mixes, nine-class
recognition, velocity estimation, custom MIDI maps, variable-tempo export and
measured human editing remain open in #303/#299/#300. This study neither changes
the rejected vocal #298 result nor resolves #302's every-CPU portability question.

## Durable evidence and reuse

The exact original artifact is **543,266 bytes**, artifact **14116835699**, SHA256
`a6ab844ed5cfb6cd4ac74ddf5dc7002fc8409ba738c8f84765d9c590aba79a45`, matching
GitHub Actions metadata. Its report SHA256 is
`f2c04248861968d1e12a9b2dca733dac5bbeb6625be193e6bb15888b739762e4`.
All six member hashes and sizes are in the structured results and receipts index.
The ZIP is preserved without recompression.

The artifact contains source/decoded-input identities, all raw predicted and
reference event ledgers, exact matches and edit operations, runtime qualification,
and the original private-input audit. It contains no raw WAV/MIDI files or model
weights. GMD-derived reference events retain **Google LLC / Groove MIDI Dataset /
CC BY 4.0** attribution; see the [official dataset](https://magenta.tensorflow.org/datasets/groove)
and Gillick et al., *Learning to Groove with Inverse Sequence Transformations*,
ICML 2019. Authored controls are project-created schematic signals.

The unchanged auditor can verify an extracted copy without rerunning inference:

```bash
python -m scripts.audit_drum_event_lanes \
  --reports /path/to/extracted-original-artifact \
  --output /path/to/new-public-event-audit.json
```

Omitting `--work` explicitly means that private input arrays are not reopened.
The original `audit.json` must remain unchanged. The separately preserved
[public-event audit](receipts/drum-event-lanes-public-audit-43601526575.json)
passes the same event/source/arithmetic checks with that limitation.

Final-head and actual-main integration results are recorded separately on
[PR #306](https://github.com/JDeun/audio-score-tool/pull/306); they do not turn
this rejected candidate into a quality-approved product change.

## Separate integration observation: #302 on an incompatible native host

The scientific execution above passed its input gate and independent audit.
The initial source-head [general CI 43601526551, attempt 1](https://github.com/JDeun/audio-score-tool/actions/runs/43601526551)
failed the existing frozen parent-guard regeneration test on a different host.
Both jobs checked out the same `367154c...` merge tree.

| Observation | Scientific run | General source-head CI |
| --- | --- | --- |
| Native CPU | Intel Xeon 6975P-C | AMD EPYC 7763 |
| AVX512F | Available | Unavailable |
| Python | 3.11.18 | 3.11.16 |
| NumPy | 1.26.4 | 1.26.4 |
| NumPy extension bytes | Same SHA256 | Same SHA256 |
| CPU override | Unset | Unset |
| Legacy / stress / independent input mismatches | 0 / 0 / 0 | **18 / 207 / 207** |
| Analytic field differences | 0 | **10** |
| Original 66 sources and receipt | Unchanged | Unchanged |

Source-head product tests passed **2,127** with **9** existing optional skips;
frontend passed **69**. Research ran all unchanged tests and reported **2,571
passed, 1 failed, 1 existing warning**. The failed test is
`test_both_input_only_manifests_bind_original245_and_new216_without_inference`,
with `independent_stress_input_regeneration: boolean mismatch`. The positive
environment gate correctly prevented the seven mutation checks from being
misrepresented as independently validated paths on that incompatible host.

The new observation is consistent with the earlier controlled CPU-dispatch
diagnosis, and now includes the actual failing runner's CPU/build/input identities.
The two remote runs also differ in Python patch and other runtime conditions,
so this pair alone is not exclusive causal proof for CPU dispatch. It does not
invalidate the completed drum trial on its recorded compatible host or establish
universal portability. #302 remains open.

The failed CI was not retried, and no CPU flags, test selection, frozen inputs
or tolerances were changed. Preserve its [original qualification ZIP](receipts/research-numeric-qualification-43601526551-attempt-1.zip)
(73,860 bytes, artifact 14116881438, SHA256
`50d5dec4617571f57d4ddc4ccfc71290d29de24f22de211be0c6cc1500d5b631`)
and [derived host observation](RESEARCH_NUMERIC_CI_V2_HOST_OBSERVATION_2026-11-14.json).
The necessary final results/receipt commit receives its normal CI separately;
its outcome and actual-main status belong to PR #306's integration record.
