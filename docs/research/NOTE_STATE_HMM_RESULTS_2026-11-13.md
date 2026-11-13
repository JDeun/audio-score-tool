# Note-state HMM comparison — completed negative result, 2026-11-13

Execution [#289](https://github.com/JDeun/audio-score-tool/issues/289),
research [PR #290](https://github.com/JDeun/audio-score-tool/pull/290),
design [#288](https://github.com/JDeun/audio-score-tool/issues/288),
follow-up [#291](https://github.com/JDeun/audio-score-tool/issues/291).
Read the [frozen protocol](NOTE_STATE_HMM_PROTOCOL_2026-11-13.md) and
[primary-source design review](MELODYNE_FLEX_PITCH_DESIGN_REVIEW_2026-11-13.md).

## Decision

**Do not adopt either new decoder.** The preregistered primary comparison,
HMM/RMS versus the existing pitch runs, reduced pitch+onset+offset F1 from
**22.149227% to 5.290052%**, a **16.859175 percentage-point loss**. One recording
improved and 39 worsened. Onset F1 also declined. The protocol's condition for
positive follow-up evidence was not met.

Execution, historical reproduction and independent saved-note auditing succeeded.
This is a completed negative scientific result, not a preparation failure. Keep
the original settings and failure visible; no post-outcome retuning or favorable
per-recording arm selection occurred. Product code, defaults and dependencies
remain unchanged, and `quality_approved=false`.

The tested method is the explicit **Tony-inspired adaptation** in the protocol.
It is not the Tony application or an implementation of Melodyne/Flex Pitch.
This result does not establish a limit for HMMs, DSP, or those products. It also
does not resolve #281's expressive-performance-to-written-rhythm question.

## Execution and immutable provenance

[CPU run 43336542480](https://github.com/JDeun/audio-score-tool/actions/runs/43336542480),
[job 131594039626](https://github.com/JDeun/audio-score-tool/actions/runs/43336542480/job/131594039626)
completed successfully on its first attempt. The fixed-runtime dependency check,
Ruff, **115 tests with zero skips**, corpus inference/scoring, private-file audit
and artifact upload all passed. All 40 recordings, five arms and both A1/A2
annotators were scored; there were no failed recordings or empty arm outputs.

- Frozen remote PR head: `bad2eb20a7124395699cd4fe7eaa320334ebda35`.
- Actual Actions merge checkout: `e08cc06e9f7f0838887dd6442248fabf05449773`.
- Base main: `441ff85f2383cf3e0b501f10ba0d1f1399acbffa`.
- Frozen tree: `bd993c002cf447d89ebc75b00398778a55975566`, identical to the locally
  reviewed pre-publication commit `3ce97432df7c92892698c1a0c67a7c7d22aa3185`.
- Artifact13996459905: **73,141 bytes**, preserved unchanged as
  [note-state-hmm-43336542480.zip](receipts/note-state-hmm-43336542480.zip).
- ZIP SHA256: `46ea77a90750172a905750599db3b419f09d70d165ef0be221e0004b8cd61b26`.

| Exact ZIP member | Bytes | SHA256 |
|---|---:|---|
| `vocadito.json` | 709,930 | `18a623ab0d8e62ff2a0be84d980cad21a0bdec5a8f2d05c66aaa353b450136e5` |
| `audit.json` | 15,062 | `552804d253a3b33fae46f63da88921a20592890416f27823ed173056522b1c4b` |

Only metadata is in the archive: hashes, settings, scalar metrics, diagnostic
counts and indexed matching outcomes. It contains no WAV, annotation contents,
full predicted notes, F0 arrays, state paths or private logs.

## All five fixed arms

The same fresh pYIN observations feed all arms. The original extractor and three
baseline segmenters are unchanged. Scores use original reference Hz, pitch
tolerance 50 cents with octave errors counted as errors, onset tolerance 50 ms,
and optional offset tolerance max(50 ms, 20% of reference duration). Each recording
and annotator has equal macro weight. The two annotators contain 2,237 and 1,876
reference notes respectively; their judgments remain separate.

| Fixed method | Pitch+onset F1 | Pitch+onset+offset F1 | Predicted events | Onset precision | Onset recall |
|---|---:|---:|---:|---:|---:|
| Original pitch runs | 36.353202% | 22.149227% | 2,497 | 33.789840% | 40.481840% |
| Original pitch hysteresis | 35.124455% | 13.906851% | 2,757 | 31.173840% | 41.278632% |
| Original hysteresis + reattack | 35.346152% | 14.170140% | 2,785 | 31.216474% | 41.783116% |
| Note-state HMM | 12.832055% | 3.528561% | 292 | 49.119307% | 7.607332% |
| Note-state HMM + RMS | 14.215365% | 5.290052% | 332 | 49.218807% | 8.599437% |

The new arms have higher onset precision but drastically lower recall. The
larger precision alone is not an improvement in note transcription. No neural
AMT model (YourMT3 or Basic Pitch) was rerun. Historical model context remains in
the [earlier DSP report](DSP_NOTE_BASELINE_RESULTS_2026-11-11.md); it is not a new
controlled timing or model comparison in this run.

Both annotators show the same broad regression:

| Method | A1 onset F1 | A2 onset F1 | A1 onset+offset F1 | A2 onset+offset F1 |
|---|---:|---:|---:|---:|
| Pitch runs | 37.230026% | 35.476379% | 22.637677% | 21.660778% |
| HMM | 12.121203% | 13.542906% | 3.087562% | 3.969560% |
| HMM + RMS | 13.283082% | 15.147648% | 4.661422% | 5.918683% |

The primary HMM/RMS arm's onset F1 delta is −22.137837 points (1 recording
improved / 39 worsened). HMM alone loses −23.521148 onset points (0 / 40) and
−18.620666 offset-inclusive points (1 / 39). A1/A2 means and every recording's
full metrics are preserved in the original receipt.

## RMS ablation and matched-reference losses

The additional RMS rule improves the weak HMM baseline, but remains far below
pitch runs. This distinction is retained rather than calling RMS a successful
replacement for the original pipeline.

| RMS versus HMM alone | Macro F1 delta | Recordings improved / worse / tied |
|---|---:|---:|
| Pitch+onset | +1.383310 points | 13 / 9 / 18 |
| Pitch+onset+offset | +1.761492 points | 14 / 4 / 22 |

Matched-reference changes relative to the original pitch runs are:

| Candidate | Onset gained / lost | Onset+offset gained / lost |
|---|---:|---:|
| HMM | 149 / 1,492 | 62 / 957 |
| HMM + RMS | 165 / 1,472 | 91 / 947 |

There are 1,636 onset and 980 offset-inclusive matched reference judgments for
pitch runs, versus 293/85 for HMM and 329/124 for HMM/RMS. Count conservation holds:
baseline matched + gained − lost equals candidate matched. Counts combine the
two annotators' judgments, not unique physical notes.

Relative to HMM alone, RMS changes onset-matched references by 40 gained / 4 lost,
and offset-inclusive matches by 39 gained / 0 lost. The full recording macro can
still worsen on a file when extra false predictions reduce precision. These
sets arise from deterministic maximum matching; ambiguous matchings prevent
interpreting every changed ID as a human-confirmed causal correction or damage.

## What the diagnostics actually show

Across 81,734 analysis frames, the raw track contains 64,502 voiced frames. The
HMM marks **31,575 of those frames Silent (48.951970%)**, retaining 32,927 decoded
voiced frames. Neither candidate bridges any raw-unvoiced frame in this run,
although the declared finite emission floor permits that behavior in principle.

HMM has **292 segments before filtering and 292 emitted notes**: zero segments
are removed by the 80 ms filter, zero lack raw voiced support, and none are
attack-only. Its much smaller output cannot be attributed to that final pruning
step. The observation supports a conservative state path and too little note
coverage; it does not by itself identify which transition or emission assumption
caused each missed or merged event. No manual note-error taxonomy was collected.

RMS finds 3,632 amplitude-rise candidates. Of these, 3,297 already fall on Silent
frames and 335 change voiced support to Silent. That removes 3.35 seconds of
predicted support. The modified path contains 388 segments before pruning;
56 short fragments totaling 1.62 seconds are discarded, leaving 332 events.
Total emitted note duration falls from 329.24325 to 324.27325 seconds, a 4.97-second
reduction equal to 3.35 + 1.62. These are changes to predicted support, not a claim
that 4.97 seconds of true reference notes were deleted.

The adaptation uses a different extractor window/rate and declared pitch range
from the paper. It also makes explicit choices for the jump kernel, emission
normalization, unvoiced handling, hop conversion and integer output, without
claiming equivalence with Tony on under-specified details. In particular, allocating
voiced likelihood jointly across Attack/Stable states and a highly persistent
Silent state are hypotheses to inspect. Their individual causal contributions
have **not** been measured by this experiment. #291 requires analytical and
owned-contour checks plus separately frozen one-factor comparisons; no parameter
has been changed in response to these results.

## Historical parity and independent checks

The unchanged historical DSP archive is preserved as
[dsp-note-baseline-42989661618.zip](receipts/dsp-note-baseline-42989661618.zip),
SHA256 `6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541`.
Archive, extractor, note scorer and F0 scorer identities match. All **120 legacy
prediction-file hashes and counts**, 40 WAV hashes, 80 note-reference hashes,
40 F0-reference hashes and their scores match the old run. The historical parity
ledger contains no difference. Old raw F0 arrays were unavailable; this verifies
matching baseline outputs and metrics, not historical F0 byte identity.

The Actions auditor directly read the private saved notes and original-Hz
annotations, independently parsed them and called mir_eval without the runner's
scoring/aggregation helpers. It passed **13,538 checks**, including 200 complete
prediction files, 240 observation-array identities, 80 note references, 40 F0
reference hashes and all 12 frozen source identities. Maximum numerical
difference was 1.1102230246251565e−16. Prediction manifests before and after
evaluation match. The two-pass access order is established by the frozen runner
and its contract tests; a post-hoc file check alone cannot prove historic access.

A separate downloaded-artifact audit passed **11,263 assertions**, independently
checking archive/member hashes, the 12-file freeze, historical baseline parity,
macro/paired arithmetic and diagnostic conservation. Its record is
[note-state-postrun-audit-43336542480.json](receipts/note-state-postrun-audit-43336542480.json).
This later audit used metadata, not private raw audio or pitch arrays.
Neither audit is an independent rerun of pYIN or the full real-audio HMM. Before
corpus access, an independent protocol-derived dense decoder agreed on 180 owned
synthetic contours; the committed tests also include exhaustive small-path checks.

## Resources and integration validation

Actual runtime: Python3.11.18, NumPy1.26.4, SciPy1.13.1, librosa0.10.2.post1,
numba0.60.0, soundfile0.13.1, resampy0.4.2, soxr1.1.0, mir_eval0.8.2;
all actual transitives are recorded. CPU only, two threads, no learned-weight
download, training, paid API or model credentials.

The corpus runner reports **117.38 seconds** and **717,476 KiB peak self RSS**;
the independent private-file audit reports 0.38 seconds. These exclude package
installation, the earlier tests and artifact handling. They are one execution,
not a hardware-normalized speed comparison, real-time guarantee or product SLA.

On the original frozen head's synthetic merge, [CI43336542454](https://github.com/JDeun/audio-score-tool/actions/runs/43336542454)
passed: product **2,119 tests / 9 optional skips**, research **1,751 tests** with
one existing librosa deprecation warning, and frontend **69 tests**. Required
`verify` passed. [Evidence Contracts43336542451](https://github.com/JDeun/audio-score-tool/actions/runs/43336542451)
passed 34 tests, with zero provenance errors and five existing unpinned-source
warnings. The research integration audit was skipped by its branch filter.
Tauri and separate repeated stress/soak checks are not executed by this PR event;
report actual-main results separately after integration. Documentation/receipt
follow-up commits must leave all 12 scientific hashes unchanged and pass their
own final-head integration checks; the PR records that final status.

## Remaining work

Close #289 as a completed measured experiment when its research PR is integrated.
Keep #288 open for the versioned continuous-evidence/note/score design. Track the
specific state-model diagnosis in #291, with the failed arm retained as a control.
Do not replace the existing AMT path or enable automatic pitch/length correction.

The corpus is repeatedly used development material. No independent recordings,
polyphonic mixture, resynthesis listening study, human edit cost, MusicXML/PDF
quality, written-rest recovery or expressive common-score success is established.
Those acceptance gates remain separate from this completed negative comparison.
