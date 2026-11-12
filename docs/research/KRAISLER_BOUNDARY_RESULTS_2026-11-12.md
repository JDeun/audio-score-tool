# #279 / #280 — original-waveform note boundaries and supported-rest context

## Decision

**The six-recording waveform diagnostic completed. The studied gate's quiet
label alone is not a verified note release or written rest.** Most annotated
offsets have another annotated note near the observation window; selected old
gate changes exhibit different acoustic contexts. The supported score-rest
cores also contain substantial time when the unchanged gate remains open.

Keep the exact symbolic rhythm, performed timing, annotation context and acoustic
observations separate. The new descriptor is conditioned on reference pitches;
it is not a deployed pitch-aware gate, independent release truth or improved
transcription accuracy. No annotation, old threshold, correspondence, prediction
mask or product correction was changed.

The [pre-execution protocol](KRAISLER_BOUNDARY_PROTOCOL_2026-11-12.md) was frozen
before the new waveform descriptors. This is the same six previously observed
KRAISLER performances, with four explicitly outcome-selected watchlist notes.
The all-note controls limit selective reporting but do not turn the study into
held-out validation.

## Actual execution and preserved baselines

[CPU run **43222529760**](https://github.com/JDeun/audio-score-tool/actions/runs/43222529760),
attempt **1**, completed successfully at **2026-11-12 21:57:34 Asia/Seoul**.
All **six audio decodes, six analyses, six historical-baseline checks and six
watchlist attachments** completed. The scientific runner took **49.8367s**,
including **44.1034s** preparation and **5.2675s** waveform/source analysis.

| Identity | Value |
| --- | --- |
| Prior actual main | `84fade231ebc89fefcb3f6a60f284b1e5a6cd575` |
| Frozen study head | `116a68599c9358dc0dc9d8590edbfb1f696307b4` |
| Actual PR checkout | `9a812a6262b4be398ab245af207890af6cf7f60c` |
| Identical head / checkout tree | `a36f8b3ba364da6d9a7b3c31604a44f4cc516446` |
| Runtime | CPython3.12.16; NumPy1.26.4; pytest8.4.2; Ruff0.16.6 |

The checkout's parents are the prior main and frozen study head. Its workspace
was clean. All **37 inherited file hashes** and **11 new measured-file hashes**
were recorded. The result-only commit does not alter those files.

The actual cold acquisition used **14 HTTP206 ranges / 29,116,178 bytes**, zero
cache hits, verifying **36 unique source members**. Two unchanged loaders
intentionally fetched the shared metadata suffix separately. The original six
mono PCM16/44.1kHz WAVs total **403.2338095238s**. There was no crop, normalization,
resampling, model download, model inference, training or external credential use.
Whole-archive MD5 verification is not claimed.

Every replayed gate threshold scalar, frame/quiet count and mask SHA256 exactly
matched #274. Every full expressive diagnostic exactly matched #278. New source
analyses were saved before those prior outcomes were first opened by the runner.
The historical saved-mask transitions were attached only after all six baseline
checks passed. This supplies context for the old outcomes without recalculating
or improving their F1.

## Observation support and annotation context

The same fixed windows were used everywhere: **[-100,-20]ms** before and
**[+20,+100]ms** after each onset, offset and within-note midpoint. Only complete
2048-sample Hann frames inside the requested window were used. There is no
endpoint search, added padding, adjusted window or post-outcome threshold.

| Position | Planned | Both side windows available | Before only | Exact-zero transitions in available pairs |
| --- | ---: | ---: | ---: | ---: |
| Onset | 947 | 947 | 0 | 0 |
| Offset | 947 | 946 | 1 | 0 |
| Midpoint control | 947 | 947 | 0 | 0 |

The unavailable offset is recording02 reference72, its final reference. Only
15.0095ms of audio remain after the annotated offset, so its requested post
window is unsupported. It stays in the denominator; it was not padded or clipped.

All available pairs had positive target and total band power on both sides.
This means no selected window was exactly digital zero under the descriptor;
it does **not** mean every window contains an audible played note. Noise,
residual vibration and unrelated sound can all give positive spectral power.

Annotation strata are mutually exclusive, with priority same-pitch neighbour,
other-pitch neighbour, own-note short window, then isolated annotation context.
Neighbours are counted anywhere in the +/-100ms hull, including the guard;
they need not sound simultaneously at the exact boundary. Isolation refers
only to the available annotations.

| Annotation context | Onsets | Offsets | Midpoints |
| --- | ---: | ---: | ---: |
| Same-pitch neighbour | 153 | **155** | 68 |
| Other-pitch neighbour | 729 | **734** | 403 |
| Own note too short for its expected side(s) | 12 | 9 | 45 |
| Isolated annotation context | 53 | **49** | 431 |
| **Total** | **947** | **947** | **947** |

Only **49/947 offsets (5.17%)** satisfy the declared isolated-context rule;
48 of those have both waveform windows. **889/947 (93.88%)** have same-pitch or
other-pitch neighbours. These are context counts, not counts of incorrect
annotations or intrinsically unrecognizable boundaries. They explain why a
global energy drop cannot be interpreted uniformly across this repertoire.

## What the spectral changes describe

Target power is the union of fixed bands around the first eight harmonics of
the **annotated** pitch, within 80–8000Hz. Total power is the entire analysis
band. Window powers are averaged linearly before dB conversion. Concentration
is summed target power / summed total power, not pitch confidence.

The following are pooled means of **per-boundary after-minus-before dB values**.
They are not dB of the cohort's pooled waveform power, not six-recording macro
means, and not estimates with independent-sample confidence intervals.

| Population | Defined pairs | Mean target change, dB | Mean total-band change, dB |
| --- | ---: | ---: | ---: |
| All onsets | 947 | +12.0366 | +1.7966 |
| All offsets | 946 | -5.7895 | -0.2749 |
| All midpoints | 947 | +2.8637 | +1.3565 |
| Isolated-context onsets | 53 | +20.6698 | +11.6763 |
| Isolated-context offsets | 48 | -5.4146 | -3.4735 |
| Isolated-context midpoints | 431 | +1.5659 | +1.5097 |

The onset/offset differences are consistent with useful pitch-conditioned
context, while midpoints show that level changes also occur inside annotated
notes. These populations and side supports differ: the table is not a paired
classifier evaluation and cannot establish separation accuracy or a cutoff.
Midpoint means need not be zero in expressive or changing-intensity passages.

For offsets, the same-pitch-neighbour group has mean target change **+0.7626dB**
(155 pairs), whereas the other-pitch-neighbour group has **-7.4178dB** (734).
The short-own-note group has **+12.1659dB** (nine). This heterogeneity argues
against applying one direction-of-energy-change rule to all three contexts.

Per-recording quantiles and counts are preserved in the receipt. Cohort means
were calculated from count/sum; recording medians were not averaged into a
fictitious cohort median.

## Four prior gate-change references: separate observations

These cases were selected from the previous results. The table uses the
historically changed boundary type; extra onset/offset/midpoint diagnostics are
retained in the receipt. Gate-quiet fraction is the fraction of each fixed 80ms
side window classified quiet by the unchanged gate.

| Reference / relevant boundary | Historical saved-mask change | Target dBFS, before → after | Concentration, before → after | Gate quiet fraction, before → after |
| --- | --- | ---: | ---: | ---: |
| 02 / 14 onset | Full/non-tail onset loss, both decoders | -75.943 → -46.920 | 0.0564 → **0.9639** | **1.000 → 1.000** |
| 19 / 294 offset | Full/tail-only offset gain, both decoders | -43.271 → -44.441 | 0.9763 → 0.8878 | 0.000 → 0.000 |
| 12 / 16 offset | Full/tail-only offset loss, onset065 | -73.324 → -33.728 | 0.2731 → 0.9848 | 1.000 → 0.03125 |
| 06 / 159 offset | Full/tail-only offset loss, default | -92.643 → -97.243 | 0.2423 → 0.1206 | 1.000 → 1.000 |

**02/14:** The annotation-isolated onset has a **+29.0229dB** target-band change
and a large concentration increase, yet the gate remains closed throughout
both side windows. This is concrete evidence that gate-quiet can coexist with
increasing energy near the annotated pitch's harmonics. It motivates checking
quiet attacks before editing them. The new spectral descriptor and old RMS gate
use different windows/frequency coverage; their dB values must not be directly
substituted into one another's thresholds. Old prediction intervals are absent,
so this does not reconstruct the exact onset edit or prove its mechanism.

**19/294:** The final reference retains substantial target-band concentration
in the post window, with only **-1.1696dB** target change; the gate is open on
both sides. The old matching gain therefore cannot be rephrased as verified
silence exactly at this annotation boundary. This observation does not prove
that the annotation is wrong or locate a later physical release.

**12/16:** The next annotation of the same pitch begins at the current offset.
The post window belongs to that next note. Target energy rises **+39.5959dB**
and the gate mostly opens again. Treating this increase as continuing evidence
for the first note would conflate two annotated notes. Conversely, the quiet
pre-window is not proof of a written rest. This is an annotation-defined
same-pitch transition context, distinct from a final-note tail example.

**06/159:** Before its annotated final offset, total-band power is already
**-86.4865dBFS**, falling to **-88.0574dBFS** after. Both windows are gate-quiet.
This weak-energy context differs from19's final note. It motivates independent
endpoint/source review without claiming human inaudibility, a corrected offset
or a causal explanation of the saved matching loss.

All historical reference-mask changes remain exactly as previously reported.
No new prediction-event matching, range-aware F1 or causal edit attribution is
available from these observations.

## Written-rest ranges contain different gate and annotation states

The source projection is unchanged: **36 intervals = 18 projected + 18
unprojectable**, with zero collapsed cores. Only 19, 08 and 12 contribute supported
rest cores. The 18 unprojectable intervals are retained, not relabelled correct
or excluded from the score-rest denominator.

| Region union | Duration, s | Frozen gate quiet, s | Frozen gate active, s | Quiet fraction |
| --- | ---: | ---: | ---: | ---: |
| Envelope | 10.963546 | 2.220000 | 8.743546 | 20.25% |
| Core | **3.403845** | **1.016089** | **2.387756** | **29.85%** |
| Boundary-uncertain | 7.559701 | 1.203911 | 6.355789 | 15.93% |

Continuous time obeys core+uncertain=envelope and quiet+active=duration. In the
core, the **0.042037s** of annotated-note overlap are all gate-active. Even the
**3.361808s** without a note annotation contain **2.345719s** of gate-active time;
their quiet fraction is 30.22%. Annotation-uncovered and gate-quiet are different
sets. Neither is asserted to be acoustic silence or written-rest correctness.

| Recording | Projected / total rests | Core duration, s | Gate quiet, s | Gate active, s | Core spectral frames | Core pooled total dBFS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 19 | 9 / 10 | 1.618424 | 0.871389 | 0.747035 | 121 | -39.9058 |
| 08 | 8 / 14 | 1.051023 | 0.144700 | 0.906323 | 68 | -29.6721 |
| 12 | 1 / 4 | 0.734398 | 0 | 0.734398 | 69 | -31.2731 |
| 02 | 0 / 4 | 0 | 0 | 0 | 0 | unavailable |
| 05 | 0 / 3 | 0 | 0 | 0 | 0 | unavailable |
| 06 | 0 / 1 | 0 | 0 | 0 | 0 | unavailable |

The full core has 258 complete spectral frames and pooled total-band power
**0.0005316508**, or **-32.7437dBFS** after pooling linear power. All 258 are
nonzero. Different durations/levels and frame support affect this pooled value;
it is not calibrated acoustic loudness or a claim that every core is equally loud.

The envelope has 1012 full frames, core 258 and uncertain 587. The remaining
**167 envelope frames cross a core/uncertain boundary**, so spectral frame
counts must not be forced to obey the continuous-duration partition. Likewise,
the two tiny annotated-note overlaps inside the core have positive duration
but zero full spectral frames. They are not zero-energy measurements.

## Exact artifact and independent audits

Artifact **13944769055** is preserved without recompression as the exact eighth
ZIP: [kraisler-boundaries-43222529760.zip](receipts/kraisler-boundaries-43222529760.zip).

- ZIP: **111,438 bytes**, SHA256
  `ead70a5ea7d5826d24d3ac470b9e5d154004c332ffea678dbc9b82c8a9ff42fd`.
- Sole `report.json`: **813,260 bytes**, SHA256
  `9177964bff5d848610a6ae93f2a509f0cb4a3608ca86df9ff53f35760668feba`.
- Original waveforms, source event/interval arrays, spectrograms and predictions
  are not republished. Earlier exact receipts remain unchanged.

Both independent post-run audits **passed**, with no measured-file changes:

- [Metadata arithmetic/provenance audit](receipts/kraisler-boundaries-audit-43222529760.json):
  24,723 assertions; 2,841 independently reconstructed annotation-context
  memberships and 18 complete partitions; 90 case/context groups with 1,080
  statistic blocks and 180 cohort pooled blocks; 54 continuous and 54 spectral
  rest rows; 64 historical watchlist transition rows; 36 source SHA256/CRC and
  PCM headers; 48 code/protocol hashes, both prior ZIPs, all six gate/expressive
  identities, actual checkout/tree and artifact. It uses standard-library
  arithmetic and original annotation context, not a waveform reanalysis.
- [Independent original-source/FFT audit](receipts/kraisler-boundaries-source-audit-43222529760.json):
  16,731 assertions; all 2,841 probes / 5,682 side windows, 72 membership masks,
  12,185 direct single-frame FFTs, six exact gate masks / 40,324 cells, 54 rest
  interval hashes and 54 spectral frame-mask hashes. All four watchlist notes
  were checked at onset/offset/midpoint. It imports none of the new acoustic,
  clock or boundary helpers; only frozen XML/Match parsing, eligibility and
  symbolic normalization are reused.

The second audit computes Hann directly from its cosine formula and evaluates
fieldwise values, rather than claiming every floating probe hash is bit-identical.
Observed maximum differences were **3.638e-12 dB**, **2.220e-16 power**, and
**1.137e-13** for other float fields, below its declared absolute tolerances
(1e-9 dB, 1e-14 power, 1e-12 other). Gate scalars and masks, source interval hashes
and spectral support masks match exactly. Arithmetic regrouping of large dB
sums differed by at most 1.819e-12; continuous-time conservation retained 1e-12.
Neither audit supplies independent human/acoustic ground truth or reconstructed
prediction endpoints.

## Validation and integration

**105 new contracts** passed locally and in the actual study workflow. The
[initial-head CI 43222529003](https://github.com/JDeun/audio-score-tool/actions/runs/43222529003)
passed **2,119 product tests / nine optional skips; 1,167 research tests / one
existing upstream warning; 69 frontend tests**. Inventory: 200 product / 46
research files, zero omissions. Required verify passed with conditional PR
Tauri skipped (`required=false`).
[Evidence Contracts 43222529276](https://github.com/JDeun/audio-score-tool/actions/runs/43222529276)
passed 34 tests. The result/receipt-only commit requires its own CI; final-head,
merge and actual-main evidence is recorded on [PR #280](https://github.com/JDeun/audio-score-tool/pull/280).

## Next research decision

Prioritize a diagnostic that separates quiet attacks, same-pitch rearticulation
and final-note releases before considering a new gate policy. The present
harmonic descriptor uses reference pitch; a deployable proposal would have to
use prediction-side candidates, preserve their event arrays privately, freeze
the rule before validation, and measure gains as well as note-time damage.
It cannot be promoted by replacing reference pitch with a convenient assumed
truth or by tuning on these four selected examples.

Independent listening/source annotation and a separately declared validation
population remain necessary for endpoint or notation-quality claims. The
current study neither estimates real swing nor learns articulation-duration
rules. Preserve the previous negative transfer result and all unresolved
correspondences as comparison baselines.
