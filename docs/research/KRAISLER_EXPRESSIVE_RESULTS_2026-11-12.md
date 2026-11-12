# #277 / #278 — local timing and expressive ranges

## Decision

The declared local procedure finds supported intervals in **five of six
recordings**, admitting **394/947 reference correspondences (41.6051%)** in
the primary tempo20 condition. The frozen global result reproduces exactly:
**225/947 primary, 137/947 stable, one whole-recording clock admitted**.

This larger source-correspondence coverage does not establish improved
transcription accuracy. The new local fixed100 comparator admits **412/947**,
more than tempo20's 394. A tempo-relative policy is not uniformly wider or
better: it tightens fast-pulse timing and can create ambiguity or cross support
boundaries at slow pulses. All previous gate matching gains/losses remain in
the unresolved class under every new scope. The earlier negative tail-transfer
result is unchanged.

The duration observations support separating symbolic slots from sounding
duration. Among the selected primary subset, 37 staccato-family notes have
mean annotated/projected duration ratios of **0.5341 / 0.5367** under the beat /
piano clocks; 321 fully supported unmarked notes have means **0.9694 / 0.9774**.
These are descriptive source ratios, not general articulation correction
factors. **33/37 staccato observations come from recording 19**, and the violin
offset annotations themselves have limited reliability.

## Why ranges need musical context

The user's suggestion identifies a real distinction. Exact rational score
positions specify musical structure; local tempo and interpretation determine
their performed times. The unchanged model scorer already tolerates onset
errors of 50ms and offset errors of max(50ms, 20% of performed-reference
duration). Score identity, performed release and the musical acceptability of
a notation are separate questions.

The [frozen protocol](KRAISLER_EXPRESSIVE_PROTOCOL_2026-11-12.md) therefore keeps
timing support separate from note windows, fixes identity from onset/pitch
before inspecting offsets, and treats length bands as compatibility diagnostics.
Neither a 20% band nor a sample quantile is a measured human tolerance or a
calibrated confidence interval. Staccato detachment is not automatically a new
written rest. A swing pattern changes subdivision phase; symmetric tolerance
alone does not estimate that pattern.

The shared beat timeline was derived and manually refined using the piano
alignment. Agreement between these related source clocks is therefore not two
independent annotations or independent acoustic ground truth.

## Actual execution and fixed evidence

[CPU run 43210425240](https://github.com/JDeun/audio-score-tool/actions/runs/43210425240)
/ [job 131156298397](https://github.com/JDeun/audio-score-tool/actions/runs/43210425240/job/131156298397)
succeeded on **attempt 1**, completing on 2026-11-12 at **11:35:31 UTC /
20:35:31 Asia/Seoul**. All six source analyses, exact historical baseline checks
and conditional attributions completed.

- Frozen head: `18e358645fcec5c5314bb69f2725d9bc3be984f7`.
- Actual PR checkout: `4a9f603d983eb0a576795bffd8e9f4fdb2254a77`, parents
  main `12c9aa5477c63b8a1770a2dcae692dadf930414e` and that frozen head.
- Both checkout/head trees: `7d16179315f8c62ef18f527db2c38fe942d550e1`, checked
  against GitHub commit objects.
- **30 original metadata members, seven HTTP 206 ranges, 776,325 bytes, zero
  cache hits.** No full-archive MD5 verification is claimed.
- **Zero audio loads, model inference or training.** The runtime was CPython
  3.12.16 with standard-library analysis; contracts used pytest 8.4.2 and
  Ruff 0.16.6.
- **27 inherited sources** remained byte-identical; **11 new measured files**
  were fingerprinted, including the intentionally extended research inventory.
- All six analyses and their hashes were preserved before the runner opened
  the previous alignment/gate receipts. Each previous source analysis then
  reproduced exactly, and attribution could not mutate new source analysis.
- Observed runner time: **6.26s** (4.20s preparation, 1.31s analysis, 0.61s
  attribution). This single metadata run excludes setup/install time and is
  not a controlled runtime benchmark.

## Local support coverage

No original median anchor was moved or deleted. Non-increasing edges, their
endpoint anchors and incident edges remained unsupported. Complete beat cells
also had to satisfy the original 4-quarter/3-second gaps and <=100ms source
clock disagreement at every piano breakpoint, not just beat endpoints.

| ID | Reference notes | Supported / observed beat cells | Connected support components | Primary tempo20 pairs |
| --- | ---: | ---: | ---: | ---: |
| 02 | 73 | 0 / 58 | 0 | 0 |
| 19 | 295 | 170 / 190 | 8 | 183 |
| 08 | 203 | 56 / 112 | 12 | 67 |
| 12 | 65 | 24 / 42 | 14 | 20 |
| 05 | 151 | 25 / 79 | 7 | 24 |
| 06 | 160 | 98 / 126 | 14 | 100 |
| **Total** | **947** | **373 / 607** | **55** | **394** |

The 373 cells cover 426 symbolic quarter-note units within the admitted
observed beat spans. This is not whole-piece duration coverage: 02 has no
admitted symbolic mapping and unobserved beginning/ending score positions are
not extrapolated. All 947 references remain in the correspondence denominator.

02 retains the prior grace/tie representation limitation. The other five each
have one purely structural beat-sequence candidate and some supported cells;
that does not mean their entire recordings have verified clocks. In 19, 20
cells fail pointwise clock agreement despite the previous global admission.
In 08/12/06, the original reversals are preserved while healthy regions become
usable. In 05, support gaps and local disagreement continue to remove regions.
These method exclusions do not establish the musical cause of a source mismatch.

## Onset windows: increased coverage is not monotone

The tempo conditions use observed annotated pulse length, including compound
meter pulses, with a 50–200ms clamp. At a beat boundary, the shorter adjacent
period is used. The full tolerance band must stay inside supported components
under both clocks. Unsupported beat competitors remain in the candidate graph.

| Condition | Correspondences | Of all 947 | Unresolved |
| --- | ---: | ---: | ---: |
| Frozen previous global 100ms | 225 | 23.7592% | 722 |
| Local fixed100 comparator | 412 | 43.5058% | 535 |
| Local tempo10 sensitivity | 303 | 31.9958% | 644 |
| **Local tempo20 primary** | **394** | **41.6051%** | **553** |
| Local tempo30 sensitivity | 440 | 46.4625% | 507 |
| Same pair at tempo10/20/30 | 295 | 31.1510% | 652 |

| ID | fixed100 | tempo10 | tempo20 | tempo30 | Stable tempo |
| --- | ---: | ---: | ---: | ---: | ---: |
| 02 | 0 | 0 | 0 | 0 | 0 |
| 19 | 212 | 150 | 183 | 212 | 150 |
| 08 | 59 | 43 | 67 | 80 | 39 |
| 12 | 21 | 21 | 20 | 19 | 19 |
| 05 | 24 | 22 | 24 | 22 | 20 |
| 06 | 96 | 67 | 100 | 107 | 67 |

From fixed100 to tempo20, **376 pairs retain identity, 18 references become
resolved, 36 become unresolved, and zero shared references change identity**.
For admitted primary pairs, median half-widths are 59.14ms in 19, 120.60ms in
08, 184.05ms in 12, 161.62ms in 05 and 103.02ms in 06. Thus tempo20 tightens
many fast passages even though it allows wider windows elsewhere.

The 553 primary unresolved references comprise 393 with no candidate under one
or both clocks, 61 whose entire window lacks support, 3 with multiple score
candidates, 19 sharing a score attack, 4 in grace/ornament contexts, and all 73
from 02. These are mutually exclusive outcome reasons; clock rejection counts
elsewhere may be nonexclusive.

Only the contrast between the two new local window conditions isolates the
window policy. The prior-global versus new-local comparison also changes
support admission, ambiguity accounting and full-window guards. It cannot be
presented as a single-factor timing improvement or independently correct note
alignment.

## Duration after onset identity

Of 394 primary onset pairs, **388** have complete duration support in both
clocks. **Six paired durations remain unsupported**, alongside the 553 unpaired
references. The descriptive duration band is centred on each projected written
slot with half-width max(50ms, 20% of that slot duration).

| Primary duration classification | Supported pairs |
| --- | ---: |
| Inside both clock-derived bands | 258 |
| Shorter than both bands | 57 |
| Longer than both bands | 22 |
| Depends on which clock/band is used | 51 |
| **Supported duration total** | **388** |

None of those four labels is a score-error label. In particular, 51 results
depend on the clock despite admitted onset identity. The fixed100 comparator
has 405 supported durations out of 412 pairs: 268 inside, 61 shorter, 21 longer,
55 clock-dependent, and seven unsupported duration spans.

| Articulation class | Fully supported primary durations | Mean ratio, beat clock | Mean ratio, piano clock | Shorter / inside / longer / clock-dependent |
| --- | ---: | ---: | ---: | --- |
| Staccato family | 37 | 0.5341 | 0.5367 | 29 / 3 / 2 / 3 |
| Accent family | 22 | 1.0965 | 1.1021 | 1 / 13 / 6 / 2 |
| Mixed articulation | 8 | 0.9643 | 0.9300 | 0 / 7 / 0 / 1 |
| Unmarked | 321 | 0.9694 | 0.9774 | 27 / 235 / 14 / 45 |

Ratios are annotated sounding duration divided by the time-projected symbolic
slot. The unmarked onset class contains 327 references; six lack full duration
support, leaving the 321 above. Tenuto/other-marked have no admitted samples.

The staccato contrast is concentrated in two pieces: **33 notes in 19, four in
08**. In 19 alone the staccato ratio medians are 0.4275/0.4527 under beat/piano
clocks. Its 141 supported unmarked notes have medians 0.9079/0.9192. These are
selected per-recording observations, with confounding repertoire and annotation
effects. They do not calibrate a universal 0.5 staccato correction. Cohort means
use summed ratios and counts; per-recording medians are not averaged into a
claimed cohort quantile.

## Rest ranges retain boundary uncertainty

The complete 36 instrument-wide rest intervals remain accounted for. **18**
are projected (19: nine, 08: eight, 12: one) and **18** are unprojectable. Both
the complete interval and the expanded boundary bands must be supported.
All 18 projected intervals have a nonempty guarded shared interior.

| Region across supported rests | Union duration | Overlap with annotated violin notes |
| --- | ---: | ---: |
| Possible two-clock envelope | 10.963546s | 3.699460s |
| Shared interior after tempo20 guards | 3.403845s | 0.042037s |
| Boundary-uncertain envelope minus interior | 7.559701s | 3.657423s |

Envelope duration and overlap equal interior plus boundary-uncertain quantities,
with union arithmetic preventing double counting. The interior overlap is
10.660ms in 19 and 31.377ms in 08. Even the common interior is therefore not
established acoustic silence. No audio or prediction occupancy was evaluated.

The old result's 0.921344s / zero note overlap used a fixed100ms guard and only
the globally admitted recording. The new 3.403845s / 0.042037s uses new support
and different guards, so the larger number is not a direct rest-accuracy gain.
In 19 alone, the smaller tempo guards expand the interior to 1.618424s and
introduce 10.660ms of annotated overlap. The range analysis exposes that tradeoff
instead of eliminating it from the report.

## Synthetic expression controls and source limits

The published controls use four constructed notes and a 600ms pulse; they are
kept outside all six-recording denominators.

| Constructed case | Observed behavior |
| --- | --- |
| Straight notes with fixed 5–17ms onset deviations | All 4 intended identities admitted at 10% pulse tolerance |
| Known 2:1 swing, supplied correct swing map | 4/4 intended identities admitted |
| The same swing timing, straight map | 2/4 admitted at the same tolerance |
| Deliberately wrong subdivision | Rejected by 10%, falsely admitted by 30% when it is the only candidate |
| Wrong subdivision plus correct competing candidate | Wide-window ambiguity retained; no unique pair admitted |
| Staccato at 0.4 of its written slot | Described as shorter; unchanged symbolic intent is not called an error |

The swing ratio is supplied by construction, not inferred. These examples
demonstrate why a rhythmic time-map and an uncertainty window have different
roles; they do not benchmark a real swing detector or human acceptability.

All six violin XMLs have zero explicit swing/straight or note attack/release
attributes, while all 947 annotation velocities are 127. Absence of a tag does
not establish straight performance. The source authors explicitly identify
fixed violin velocity and less reliable offsets. No acoustic dynamics, real
swing presence, or perceptual release quality can be inferred here.

## Previous gate outcomes remain unresolved

Every scope partitions all 947 references and retains both decoders and all
four previous arms. **All prior gains and losses remain unresolved in all five
new scopes**, for both onset and onset+offset matching. The broader local
coverage still does not explain the earlier gate changes by articulation.

Primary resolved classes contain 102 default-decoder and 99 onset0.65
onset+offset matches in every arm. Their unresolved complements retain 145 and
188 respectively, preserving total matches 247/287. These are conditional
reference matching counts, not class F1; false-positive assignments and new
tolerance-aware model matching cannot be recovered from the saved masks.

## Exact receipt and audit status

The exact seventh metadata ZIP, artifact **13939819598**, is preserved without
recompression as [kraisler-expressive-43210425240.zip](receipts/kraisler-expressive-43210425240.zip).

- ZIP: **72,066 bytes**, SHA256
  `e51fae082cf3c97240a9746cf2ba2214923ce30555ae2f70130f6043cffd478f`.
- Sole `report.json`: **1,546,689 bytes**, SHA256
  `32005007594058ee941fd367aab5cd0ad093cef130fc38a23f47912e36f580bc`.
- Original notes, beats, XML, Match files, event arrays, audio and weights are
  not republished. Exact prior receipts remain unchanged.

Both post-run independent audits **passed**, without modifying the frozen
implementation or exact scientific receipt:

- [Metadata arithmetic and provenance audit](receipts/kraisler-expressive-audit-43210425240.json):
  127,130 assertions, six exact historical baselines, 30 scope partitions, 96
  prior mask/F1 identities, 3,360 case ledger rows and 560 aggregate rows;
  duration count/sum means and rest decompositions; 11 new / 27 retained code
  hashes and 30 original member SHA256/CRC identities. This audit uses only
  standard-library arithmetic and does not reconstruct raw pair identities.
- [Independent source reconstruction audit](receipts/kraisler-expressive-source-audit-43210425240.json):
  2,553 original tick anchors, 30 anchor/support hashes and all 30 scope pair
  hashes/partitions; independently reconstructed duration ratios, quantiles,
  interval unions/overlaps and 3,360 conditional ledger rows. Maximum numeric
  difference was zero. It reuses the frozen XML/Match parser, eligibility,
  tie collapse and symbolic rest union; it does not import the new local-clock,
  correspondence or range helpers. This is a mathematical/source audit, not
  independent acoustic annotation or a complete parser reimplementation.

The source audit independently confirms that all four distinct references
changed by the previous gate remain unresolved in every new scope. In
particular, the final note in recording 19 is 155.7ms / 122.8917ms from the two
source clocks; its 374.2ms local pulse gives 74.84ms / 112.26ms half-widths for
tempo20 / tempo30. A tempo30 window is not the previous global fixed200
sensitivity. These exclusions do not establish the cause of a gate edit.

Receipt schema clarification: `onset_residuals_pulse_fraction` contains
**dimensionless pulse fractions**. Its nested `median_s`/`p95_s`/`max_s` names
are inherited helper keys, not second units; the exact scientific artifact is
preserved with this explicit qualification. `stable_tempo` deliberately marks
`residual_statistics_computed=false`; its empty residual fields are not a claim
of zero timing error.

**148 new contract tests** passed locally and in the actual study workflow.
The [initial-head CI](https://github.com/JDeun/audio-score-tool/actions/runs/43210425500)
passed with **2,119 product tests / nine optional skips; 1,062 research tests /
one existing upstream warning; 200 product / 42 research files and zero
omissions; 69 frontend E2E tests**. Required `verify` passed; PR Tauri was
conditionally skipped (`required=false`).
[Research Evidence Contracts](https://github.com/JDeun/audio-score-tool/actions/runs/43210425309)
passed 34 tests. The result/receipt-only commit requires its own CI. Current
final-head and actual-main integration evidence is recorded on
[PR #278](https://github.com/JDeun/audio-score-tool/pull/278).

## Next decision

Keep a separate performed-time representation and symbolic candidates with
explicit timing support, duration/phase hypotheses and uncertainty. A future
articulation-aware notation selector should use held-out calibration and
multiple compatible candidates; it should not learn a universal shortening
rule from these 37 selected staccato annotations. A real swing layer requires
independent offbeat evidence or explicit context, with inferred phase kept
separate from residual tolerance.

The next high-value validation is independent checking of ambiguous releases
and the still-unresolved gate-change locations against original source/audio,
plus the separate grace/tie parser issue in 02. Preserve the frozen global and
local diagnostics as comparison baselines. No automatic notation correction
or gate setting is activated by this study.

Primary context: [mir_eval](https://mir-eval.readthedocs.io/stable/api/transcription.html),
[MusicXML duration](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/duration/),
[MusicXML swing](https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/swing/),
[KRAISLER annotations](https://reference-global.com/article/10.5334/tismir.338?tab=article).
