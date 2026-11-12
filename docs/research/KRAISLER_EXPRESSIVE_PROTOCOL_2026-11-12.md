# #277 — local timing support and note/rest ranges

## Question and baseline

The user proposed treating performed note/rest lengths as ranges because human
timing, articulation, dynamics and swing need not follow an exact mechanical
grid. This study asks what that proposal can establish with the existing six
KRAISLER sources. It follows the completed
[source correspondence study](KRAISLER_ALIGNMENT_RESULTS_2026-11-12.md).

The previous global-admission result remains **1/6 recordings, 225/947 primary
reference correspondences, 137/947 stable**. It is not redefined as a new result.
All six recordings (02, 19, 08, 12, 05, 06) are previously observed development
material, not an untouched holdout. The new procedure is declared before its
cohort outcomes are computed. Source-format observations and the preceding
negative gate/correspondence results informed its design.

Three different quantities must remain distinct:

1. Symbolic position and duration, represented by exact MusicXML quarter-note
   fractions, including actual tuplet durations and collapsed explicit ties.
2. Performed time and source uncertainty, including local tempo, articulation,
   ensemble asynchrony and imperfect annotations.
3. A researcher's evaluation/compatibility tolerance. The windows below are
   declared diagnostic policies, not measured human perceptual limits or
   statistical confidence/credible intervals.

The unchanged performed-note scorer already uses pitch-aware onset matching
within 50ms and offset matching within max(50ms, 20% of the reference performed
duration). Its reference is the same recorded performance. The new score
correspondence and duration analysis answers a different question and does not
replace those model metrics.

## Fixed evidence and execution

Reuse all 30 original metadata members, their exact range/CRC/SHA identity,
and the prior source loader. A cold run makes seven bounded HTTP 206 requests,
776,325 bytes. No audio, weights, model inference or training is required.
No new archive members or dataset selection are introduced.

Preserve both exact historical artifacts:

- Alignment ZIP `kraisler-alignment-43201534121.zip`, 25,366 bytes, SHA256
  `6f8af87bef6fa8febc977e037130b520d05d0dab8df815e3684ae6239d475005`;
  sole 543,226-byte `report.json`, SHA256
  `ec5048b11ede7364ca5c68e9f7fb6f4889ed818d881f502aa34726ba54335f7a`.
- Gate ZIP `kraisler-gate-43184102838.zip`, 16,111 bytes, SHA256
  `ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e`;
  sole 155,591-byte `report.json`, SHA256
  `e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754`.

Twenty-seven inherited source/protocol/workflow/test files are byte-pinned.
The test inventory is intentionally extended and fingerprinted with the new
study, rather than falsely claiming its previous bytes are unchanged. The old
loader, parsers, scorer and scientific workflows remain unchanged.

Run the unchanged source-only global analysis again for an exact reproducibility
check. Complete and hash all six new source analyses before the runner opens
either previous receipt for baseline verification or gate attribution. Require
the regenerated old analysis to match the saved old analysis exactly after JSON
normalization. Contract tests may read historical receipts for integrity; this
ordering describes the analysis runner, not hidden or unavailable prior results.

## Local source support, independent of note tolerance

Require the old strict piano Match/XML consistency and compatible violin/piano
measure structures. The grace/tie representation issue in 02 remains outside
scope. Select **exactly one** contiguous symbolic beat sequence using only the
supplied downbeat and meter pattern. Timing residuals, violin notes and prior
gate outcomes do not select among multiple structural candidates.

Use the original eligible piano anchors and median onset at coincident symbolic
positions. Preserve every original anchor and adjacency:

- If adjacent median onsets are equal or decreasing, quarantine both endpoints
  and every edge incident to either endpoint. An exact lookup at a quarantined
  anchor is also unsupported.
- Gaps over 4 quarter notes or 3 seconds remain unsupported. Do not remove
  anchors then connect their former neighbours. Do not fit isotonic values,
  tempo scale, shift, or extrapolate beyond observed support.
- An observed beat cell must have complete piano-edge support throughout its
  interval, and its own gap must satisfy the same 4-quarter/3-second limits.
- Check absolute global-beat versus piano-clock disagreement at both cell
  boundaries **and every interior piano breakpoint**. Every check must be at
  most 100ms. Endpoint agreement alone is insufficient.
- Keep only the connected components of admitted beat cells as final support
  for both clocks. No whole-recording 90% support gate is imposed. Report all
  rejected cells/reasons and support within the observed beat span, separately
  from whole-cohort reference coverage.

The pointwise 100ms source-support bound is a conservative method choice. A
failure can reflect expressive microtiming or annotation limitations and is not
proof of a musical error or incorrect source. Multiple local components may
overlap in performance time; no globally invertible clock is assumed.

## Correspondence conditions and ambiguity

The annotated pulse is the original symbolic beat unit: denominator beats in
simple meters and dotted beats in compound meters such as 6/8. Its period is
the adjacent observed beat interval in seconds, not a universal quarter-note
duration. At an exact interior beat boundary, use the smaller adjacent period.

Compare these four predeclared conditions on the same local support:

| Scope | Onset half-width |
| --- | --- |
| `fixed100` comparator | 100ms |
| `tempo10` sensitivity | clamp(0.10 x local pulse period, 50ms, 200ms) |
| **`tempo20` primary** | **clamp(0.20 x local pulse period, 50ms, 200ms)** |
| `tempo30` sensitivity | clamp(0.30 x local pulse period, 50ms, 200ms) |

Also retain the identical unique pair intersection of tempo10/20/30 as
`stable_tempo`. Larger windows may increase ambiguity; do not select the best
window or infer that wider agreement means more accurate timing.

The full purely structural beat projection supplies a provisional candidate
graph even in unsupported cells. Such interpolation is only a conservative
competitor locator, never evidence of admitted timing. The piano graph uses
supported local times. Consider all score attacks and references together,
across all components. An unsupported same-pitch beat competitor can therefore
prevent false uniqueness after local filtering.

Require the same mutually unique same-MIDI pair in both graphs. The proposed
pair's full +/- onset window must lie within a connected supported component
in both clocks. Keep the original grace/ornament-context exclusions. All
reference notes, including competing, unsupported and excluded notes, remain
in the membership denominator. Use onset/pitch only; no reference offsets,
predictions, nearest-neighbour tie-break or fitted swing ratio resolve identity.

The contrast `fixed100` versus `tempo20` changes only the onset window under the
new procedure. Comparison with the old global baseline changes several support
and ambiguity rules as well; it is not a pure segmentation-effect estimate.

## Performed duration after identity is fixed

For fixed100 and tempo20 pairs, require the entire symbolic interval from the
attack onset through its tie-collapsed end to be supported in both clocks.
Unpaired references and paired but unsupported durations remain counted.

For each clock, compute annotated performed duration divided by the projected
symbolic slot duration. Retain counts, sums and per-recording quantiles by the
original articulation categories. Cohort means may use sums/counts; never
average per-recording medians and call the result a cohort quantile.

As a separate descriptive diagnostic, define a duration band centred on each
clock's projected slot with half-width max(50ms, 20% of that slot duration).
Classify a fully supported pair as inside both bands, shorter than both,
longer than both, or clock-dependent. This borrowed numerical form is **not**
the unchanged mir_eval metric, whose duration is a performed reference, and
none of these categories is a musical-correctness label.

Staccato can occupy the same symbolic slot with shorter sounding duration;
legato, overlaps and swing introduce other differences. Do not convert those
differences into inserted written rests or retune a duration threshold by class.
No per-event arrays are published.

## Rest boundary ranges

Use only existing instrument-wide explicit rest intervals, with complete
support in both clocks. At each boundary use the tempo20 half-width as a guard.
The possible envelope starts at the earlier projected start minus its guard
and ends at the later projected end plus its guard. The shared interior starts
at the later projected start plus its guard and ends at the earlier projected
end minus its guard; nonpositive interiors are counted as collapsed.

Conservatively require each boundary's guard **plus the absolute disagreement
between the two clocks** to be supported as a time band in both clocks. This
keeps the expanded hull inside observed support without clipping/extrapolation.
Intervals failing this rule remain unprojectable with their reason.

Compute union duration and annotation overlap for the envelope, shared interior,
and envelope-minus-interior boundary-uncertain region. Do not confuse uncertain
boundaries with unsupported intervals or measure acoustic silence from note
annotations. Previous prediction occupancy arrays are unavailable, so no new
written-rest/gate F1 is computed.

## Swing, articulation and dynamics controls

An unequal long/short subdivision is a time-map hypothesis, not symmetric
jitter around a straight midpoint. Real-data swing is not estimated or assumed
here; count explicit source swing markers and keep its performance status
unestablished even when markers are absent. Any later swing estimator needs
separate evidence/calibration and held-out evaluation.

Run fixed synthetic metadata controls, separate from the six-recording totals:

- Straight subdivision with small known onset deviations.
- Known 2:1 swing evaluated under straight and supplied correct swing maps.
- An intentionally incorrect subdivision that an excessively broad window can
  admit, illustrating the loss of rhythmic discrimination.
- A short staccato release with unchanged symbolic onset/slot identity,
  illustrating why slot-duration disagreement is not automatically a score error.

These controls have constructed ground truth and demonstrate the declared
definitions. They are not a real swing recognizer or a model-performance claim.
The existing score parser preserves actual tuplet durations; do not apply a
second swing transformation to explicit tuplets in this study.

The KRAISLER authors fix violin velocity to 127 and identify offsets as less
reliable than onsets/pitch. Record the observed velocity value counts and
notation metadata, but do not infer real loudness, accent-detection performance
or acoustic release accuracy. Metadata ranges do not solve missing dynamics
ground truth.

## Conditional ledger, completion and interpretation

Reclassify only the immutable prior reference matching masks using the new
scope memberships, including unresolved. Retain both decoders, four gate arms,
onset and onset+offset ledgers, and whole-recording gain/loss conservation. The
old model outcomes and F1 remain identical; no new tolerance-aware model F1 can
be calculated without original prediction intervals.

Complete all six diagnostics and attributions before producing a cohort summary.
Preserve partial/failure receipts when any stage fails. Publish source hashes,
actual checkout/tree, frozen head, protocol and test hashes, exact derived
artifact, arithmetic audit and limitations. Finish final-head CI, merge the
completed PR and verify actual main CI. Research coverage does not authorize
an automatic product correction.

## Primary context

- mir_eval note metrics: https://mir-eval.readthedocs.io/stable/api/transcription.html
- MusicXML duration: https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/duration/
- MusicXML swing: https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/swing/
- KRAISLER annotation provenance: https://reference-global.com/article/10.5334/tismir.338?tab=article
- Tempo-dependent swing evidence (not this corpus): https://doi.org/10.1525/mp.2002.19.3.333

Related work: #249, #259, #217, #269. Frozen baseline: #275 / #276.
