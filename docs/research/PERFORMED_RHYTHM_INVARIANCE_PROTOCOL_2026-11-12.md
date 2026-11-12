# #282 — same-score expression invariance, before execution

## User hypothesis and target

The user clarified that different performers, and different takes by the same
performer, may vary swing, timing and accent while expressing the **same written
rhythm**. The target is recovering the common rhythm across those realizations.
Preserving original events is a necessary bookkeeping contract, not the primary
scientific outcome. Waveform boundary uncertainty is a different question.

This is the first bounded execution under [#281](https://github.com/JDeun/audio-score-tool/issues/281),
linked to [#249](https://github.com/JDeun/audio-score-tool/issues/249), #259 and #223.
The execution issue is [#282](https://github.com/JDeun/audio-score-tool/issues/282).
Baseline actual main is `3023db6ce3e3544b189716ffc9d0836c569dff2a`.
Prior #278/#280 evidence stays unchanged. Product corrections and draft #236
are outside this study.

**Freeze this protocol, generator, selector, scorer, source manifest and workflow
before the first cohort inference.** Source admission and small independent
contract tests are permitted before freezing; whole-cohort outcomes are not.
Record all results, including failure, ambiguity and regression, without tuning.

## Two distinct populations

### Authored canonical-onset controls: 480 + 4

Eight original two-bar 4/4 patterns use the same instrument inventory: eight kick,
four snare and sixteen closed-hi-hat attacks. They are four-on-the-floor eighths,
offbeat kick, anticipated snare, sixteenth-displaced hats, literal long-short
triplet positions, literal dotted positions, mixed thirds/sparse beats, and
syncopated holes. Their exact onset positions differ; inventory cannot reveal
the family. They are not recordings of human performers or existing songs.

All eight are crossed with five expression profiles, four seeded takes and three
nominal quarter-note tempos (80/120/160 BPM), giving **480 main cases**:

- Four stationary phase profiles: middle subdivision at `1/2`, `3/5`, `2/3`,
  or `3/4` of each quarter. These yield **384 in-vocabulary cases**.
- A fifth profile places that subdivision at `0.56` in the first bar and `0.70`
  in the second: **96 nonstationary, out-of-vocabulary stress cases**. It changes
  both stationarity and vocabulary support; it cannot isolate either factor.
- Take0 has exact phase timing and flat velocity100. Takes1/2/3 add declared
  instrument-dependent push/pull and seeded residual timing. Take3 also has a
  small correlated phrase displacement. Velocity conditions are flat,
  on-beat emphasis, reversed emphasis and varied strength.
- Takes1/2/3 use an 8% sinusoidal local tempo variation. Generated seconds are
  converted back using the **supplied exact beat boundaries**. This is an oracle
  clock condition shared by every selector arm, not recovered tempo.
- Seeds depend only on study version/profile/take, not hidden family or tempo.
  Tempo variants share expression and are not independent observations.

The public generator fixes every value and ordered case ID. Truth is the full
multiset of `(mapped instrument, exact canonical onset tick)`, with a separate
per-event identity check. It does **not** provide written note lengths, rest
spelling, ties/tuplet brackets, voice assignment or finished engraving truth.

Four further cases form two counterfactual pairs. Swung eighths at `2:1` and
`3:1` are paired with respectively literal triplet and dotted positions played
straight. Each pair has **identical observed events but different written onset
targets**. They are evaluated separately from the 480 cases. Identical input and
prediction fingerprints, and distinct targets, are hard preconditions.

### Actual GMD: four drummers performing the same ten beat instructions

The [official GMD description](https://magenta.tensorflow.org/datasets/groove)
states that four drummers recorded the same ten beats in their own styles.
The actual archive paths use `eval_session`, although the page says
`eval-session`. Include all `drummer1/5/7/8 × groove1..10`: **40 files**, official
test split, 4/4. GMD is licensed CC BY 4.0; cite Gillick et al., *Learning to
Groove with Inverse Sequence Transformations*, ICML2019.

The original MIDI-only ZIP is fetched at most once per cold run:

- URL: `https://storage.googleapis.com/magentadata/datasets/groove/groove-v1.0.0-midionly.zip`
- Exact bytes: **3,260,318**.
- Official SHA256: `651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e`.
- [Frozen source manifest](../../scripts/gmd_same_groove_manifest.json) pins
  `info.csv` and each MIDI's member path, bytes, SHA256 and ZIP CRC32.
- No WAV, model, external credential, training or GPU is used.

Use the first **15 supplied 4/4 bars**, `0 <= onset_q < 60`, in every file.
Admission checked all source ends exceed60q. It found 11,493 positive note-ons,
with10,818 in the fixed window and675 outside. These are source-admission counts,
not rhythm results. Keep full original MIDI bytes/tempo/controllers privately;
report excluded counts. Never choose a different window from its outcomes.

Use the official paper drum mapping to nine kit categories, sorted target MIDI
pitches `(36,38,42,43,46,47,49,50,51)`. Report original pitch counts as well.
Unknown pitches, changed clocks, invalid channels or unavailable coverage fail
admission rather than being silently dropped. Mapping rim/head/edge variants is
a supplied taxonomy choice, not inferred instrument recognition.

Tick/PPQN gives quarter-note coordinates using the supplied MIDI clock and file
bar origin. The ten grooves' BPMs are mostly distinct: metadata could leak the
label. **BPM, seconds duration, filenames, style, drummer, groove and reference
score never enter the selector.** Only label-free event ID, mapped instrument,
onset_q and velocity, plus the fixed span, enter it. Velocity is retained but is
not used by the phase selector. Groove1/7 and groove2/9 are same-BPM contrasts.

The archive supplies no canonical written score. Same beat instructions do not
guarantee identical hits, fills, ghost notes or instrumentation. GMD outcomes
therefore measure **within-groove consistency and between-groove discrimination**,
not exact notation accuracy. The source's test split is used here as development
evaluation and must not later be called an untouched holdout for these choices.

## Frozen onset interpretation

Every arm uses `Q=12` ticks per quarter and the same within-quarter lattice
`{0,3,4,6,8,9}`, covering binary sixteenth and triplet-third positions. There is
no score-template library, groove label, reference alignment or family grouping
in the selector. Each take is interpreted independently.

For one global phase `s` per take, define a monotone piecewise-linear map with
`f_s(0)=0`, `f_s(1/2)=s`, `f_s(1)=1`, repeated each quarter. The phase set is
`s ∈ {1/2,3/5,2/3,3/4}`. It acts on **all** canonical positions, including thirds;
this is a declared mathematical model, not every musical swing convention.
No per-event, instrument-specific or bar-specific phase fitting is allowed.

Each fit maps every observed hit to its nearest warped lattice position.
Retain all nearest alternatives within1e-12; use the smallest tick only for the
representative diagnostic. Count all attacks, including collisions. Different
instruments may coincide; same-instrument attacks mapped to the same tick are
an invalid full-score interpretation, never silently merged or deleted.

| Arm | Phase hypotheses | Maximum residual admitted |
| --- | --- | --- |
| straight_narrow | s=1/2 | 0.08 quarter |
| straight_wide | s=1/2, identical nearest positions | 0.18 quarter |
| phase_aware | fits within minimum mean squared residual +1e-4 quarter² | 0.08 quarter |

The margin is not calibrated confidence. Deduplicate retained representative
canonical hashes. A single score is selected only if there is exactly one and
no retained nearest-position tie or collision. Retained ambiguity is never
removed to make a different fit uniquely acceptable. Representative hashes do
not exhaust alternative scores when a nearest-position tie is present.

## Outcomes and degenerate controls

### Exact authored controls

Report correct decision, wrong decision, abstention, truth admitted among
retained per-event alternatives, diagnostic per-hit correctness, and selected
per-hit correctness. Selected correctness requires both canonical multiset and
event correspondence. Report all480 cases and the predeclared384/96 regimes,
profile strata, paired gains/losses and all8 family groups.

For each family, distinguish every take choosing the same correct score,
every take choosing the same wrong score, disagreement, and abstention.
There are14,160 within-family pairs and100,800 between-family pairs; report
decided equality/false merges with their denominators. Common abstention is
never an equal score. Shared candidate intersections are descriptive and do
not give the inference algorithm the hidden family grouping.

An `always_four_on_floor` baseline assigns the same canonical pattern to every
input while preserving the declared equal inventory. It exposes stable-wrong
and different-score collapse; high consistency alone is not success.

### Real GMD: fixed representation and candidate-set comparison

Full canonical decisions remain separate from profile-based retrieval. A profile
folds mapped hits into a **9-kit × 48-tick bar-position count table** and is
normalized to unit mass. It discards bar order and represents repeated rhythmic
content, not a completed multi-bar score. Counts retain all hits.

Compute these declared representations without labels:

- straight_narrow and straight_wide: the same straight profile, **identical by
  construction**, with full-score acceptance reported separately.
- phase_best_single: one minimum-MSE fit fixed per take, ties following declared
  phase order. This representative is diagnostic even if a full score is rejected.
- phase_aware: all near-best diagnostic profiles; pair distance is the minimum
  across candidate combinations. The same take can use different phases against
  different partners. This is an **optimistic set-distance**, not a stable unique
  recovered score or necessarily a metric.
- instrument_inventory: normalized nine-category counts, removing timing.
- velocity_weighted_straight: straight position counts weighted by original
  velocity, then unit normalized; separates a strength-sensitive representation.
- constant_profile: identical representation for every performance.

Distance is total variation, half the L1 distance of normalized vectors. Profiles
may come from fits rejected as complete scores for collisions/residuals. Report
that limitation with any retrieval result; do not relabel it notation recovery.

Use **600 unordered cross-drummer pairs:60 same groove,540 different**. Report
means, zero-distance collapse and pair-separation AUC (a tie earns1/2). For40
queries, the gallery is the30 performances by the other three drummers. No model
is trained. Nearest distances tie within1e-12; if nearest examples contain more
than one groove label, report ambiguous rather than a favorable label tie-break.
Report each held-out drummer, correct/wrong/ambiguous, candidate inclusion and
paired gains/losses against straight. These are closed ten-groove exemplar
comparisons, not open-set score inference. Same-BPM contrasts are separate.

Pairs, bars and repeated tempo variants are dependent. Do not attach independent
sample confidence intervals or combine synthetic and real denominators into one
accuracy. Numerical consistency does not establish perceptual naturalness.

## Execution, failure and provenance

The dedicated Actions workflow uses Ubuntu CPU, Python3.12, mido1.3.3,
pytest8.4.2 and Ruff0.16.6. Analysis beyond MIDI parsing is standard-library code.
It triggers on opening/reopening this research PR or explicit dispatch; result-only
updates and main pushes do not rerun the scientific study.

Record actual PR head, checkout commit/tree/parents, clean state, runtime, run and
attempt, and hashes of12 measured files: four modules, source manifest, four new
test files, workflow, this protocol and research-test inventory. Scope IDs are
fixed before cohort preparation. After planning, retain all **524 planned rows**
on failure. If workflow contracts or provenance fail before planning, preserve
the expected 484/40 denominators and an explicit execution-not-started or
preparation-failed receipt; individual rows are not yet available.

All524 full predictions are stored privately and input mutation hashes checked
**before evaluation first reads hidden labels or truth**. Missing source,
inference or preservation stops the complete evaluation; summary remains null.
Per-case source failures remain in the40-case denominator. Wrong scientific
answers do not cause the runner to hide cases or tune the model.

Keep exact raw source ZIP/MIDI and full predictions private. Publish only bounded
metadata, hashes, case/fit summaries, pair distances, retrieval outcomes and
failure status in report.json, at most8MB. Runner `*_file_sha256` values hash
the exact indented JSON bytes plus newline. Study `*_content_fingerprint` values
hash compact canonical JSON; their scopes are deliberately distinct.

The immutable source and event checks establish absence of mutation, not MIDI
export fidelity. Preserve the exact Actions ZIP beyond artifact retention,
independently audit arithmetic/source provenance, document findings and limits,
then verify the final results commit and actual merged main. No post-outcome
parameter changes, best-seed selection, discarded negative results or product
activation are authorized by a successful research run.
