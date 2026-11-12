# #282 / #283 — common rhythm across expressive performances

## Decision

**Separating performed timing from written onset positions is useful in the
declared stationary synthetic conditions, but the tested single-phase model
does not yet recover one common score across the full expressive population.**
Widening a straight quantizer's acceptance gate increases wrong decisions.
The phase-aware arm reduces those errors in the authored controls, yet fails
under the predeclared changing-swing stress and loses same-groove retrieval
accuracy on actual human MIDI. Keep this as research evidence, not a product
correction or a claim of improved transcription.

This directly tests the user's clarified target: different timing, swing and
accents can realize the **same written rhythm**. Preserving the original timing
and velocity is required bookkeeping; it is not the success metric. The
[protocol](PERFORMED_RHYTHM_INVARIANCE_PROTOCOL_2026-11-12.md) and all measured
scientific files were committed before the first cohort inference.

The two populations answer different questions. Authored controls have exact
**instrument/onset** truth. The actual GMD performances have shared beat
instructions but no canonical written-score truth. Neither population validates
written durations/rest spelling, full engraving or beat recovery from audio.

## Actual execution

[CPU run **43236100984**](https://github.com/JDeun/audio-score-tool/actions/runs/43236100984),
attempt **1**, completed successfully at **2026-11-12 23:20:45 Asia/Seoul**.
All **524 planned inferences and 524 input-preservation checks** completed before
evaluation began. The runner took **21.111353s**, including **0.869969s** source
preparation and **17.708344s** inference. No case was dropped or rerun with a
different parameter, seed or window.

| Identity | Value |
| --- | --- |
| Prior actual main | `3023db6ce3e3544b189716ffc9d0836c569dff2a` |
| Frozen scientific head | `d56738e77a9d058de430e2f20b07bd238c544ef9` |
| Actual PR checkout | `4a167f7ac2c2eb97fe1e393ca195d947a0da61fe` |
| Identical head / checkout tree | `6fda55f0a3194f0fcc96366b9527a1466feb5e1f` |
| Runtime | CPython 3.12.16; mido 1.3.3; pytest 8.4.2; Ruff 0.16.6 |

The checkout parents are the prior main and frozen scientific head. Its
workspace was clean. Hashes of all **12 measured files** are in the receipt;
results and audits are added without modifying those files. There was no
training, neural-model inference, model download, GPU or external model token.
All 524 full predictions were stored privately before evaluation read labels.

## 1. Exact authored onset-score controls

Eight original two-bar 4/4 patterns have identical inventory: eight kick,
four snare and sixteen closed-hi-hat attacks. Each is crossed with five
expression profiles, four takes and three nominal tempos: **480 cases** and
**13,440 attacks**. Separate identical-observation controls contribute four
additional cases. Supplied exact beat boundaries remove clock-estimation error;
tempo replicas share expression and are not independent trials.

All three arms choose positions from the same binary/triplet lattice. The wide
straight arm changes only its residual acceptance limit from 0.08 to 0.18
quarter notes. The phase-aware arm considers four global phase hypotheses and
retains near-equal alternatives. A full decision requires a unique canonical
multiset with no retained nearest-position tie or same-instrument collision.
Correctness additionally requires every event's exact written position.

### Whole population, including the declared stress

| Method | Correct / 480 | Wrong / 480 | Abstained / 480 | Truth retained / 480 |
| --- | ---: | ---: | ---: | ---: |
| Straight, narrow gate | 105 | 234 | 141 | 105 |
| Straight, wide gate | 132 | 321 | 27 | 135 |
| Phase-aware | **201** | **84** | 195 | **381** |
| Always the same four-on-the-floor score | 60 | 420 | 0 | 60 |

Increasing the straight gate admits **27 additional correct decisions and 87
additional wrong decisions**, with 114 fewer abstentions. It does not change
any diagnostic nearest positions. This particular wider gate therefore does
not solve expressive invariance; it accepts more interpretations of both kinds.
This is not a test of every possible probabilistic range model.

Compared with narrow straight, phase-aware has **171 correct cases gained and
75 correct cases lost**, a net gain of 96. Lost correct cases are not hidden by
the aggregate gain. Keeping truth among 381 candidate sets is different from
selecting it in 201 cases; candidate inclusion is not exact-score accuracy.

### Supported stationary profiles versus changing-swing stress

| Population / method | Cases | Correct | Wrong | Abstained | Truth retained |
| --- | ---: | ---: | ---: | ---: | ---: |
| Stationary, in vocabulary / narrow straight | 384 | 105 | 177 | 102 | 105 |
| Stationary, in vocabulary / wide straight | 384 | 120 | 237 | 27 | 123 |
| Stationary, in vocabulary / phase-aware | 384 | **201** | **0** | 183 | **381** |
| Changing, out of vocabulary / narrow straight | 96 | 0 | 57 | 39 | 0 |
| Changing, out of vocabulary / wide straight | 96 | 12 | 84 | 0 | 12 |
| Changing, out of vocabulary / phase-aware | 96 | **0** | **84** | 12 | **0** |

The supported stationary result is bounded: 201/384 correct decisions (52.34%),
183 abstentions and no wrong decisions in these cases. The stress changes both
the phase over time and the phase vocabulary, using 0.56 then 0.70. It yields
84 wrong phase-aware decisions, so low residual and a unique retained candidate
are not reliable correctness evidence outside the assumed model. This design
cannot attribute the failure solely to temporal tracking or solely to unseen
phase values.

| Expression profile, 96 cases each | Narrow: correct / wrong / abstained | Wide: correct / wrong / abstained | Phase-aware: correct / wrong / abstained |
| --- | ---: | ---: | ---: |
| Straight | 96 / 0 / 0 | 96 / 0 / 0 | 24 / 0 / 72 |
| Light swing, phase 3/5 | 9 / 81 / 6 | 12 / 84 / 0 | 81 / 0 / 15 |
| Triplet swing, phase 2/3 | 0 / 60 / 36 | 12 / 84 / 0 | 42 / 0 / 54 |
| Strong swing, phase 3/4 | 0 / 36 / 60 | 0 / 69 / 27 | 54 / 0 / 42 |
| Changing swing, phase 0.56 then 0.70 | 0 / 57 / 39 | 12 / 84 / 0 | 0 / 84 / 12 |

The phase-aware arm abstains on many straight cases because allowing multiple
performance interpretations also exposes score ambiguity. A minimum timing
residual alone cannot choose the intended notation in all such cases.

### The user's four-on-the-floor example

For this original family alone, each profile has four takes times three tempos:
12 cases. This is a descriptive slice of the frozen population, not a new
evaluation cohort.

| Expression | Narrow straight | Phase-aware |
| --- | --- | --- |
| Straight | 12 correct | 12 abstained |
| Light swing | 12 wrong | **12 correct** |
| Triplet swing | 12 wrong | 12 abstained |
| Strong swing | 12 wrong | 12 abstained |
| Changing swing | 12 wrong | **12 wrong** |

The weak-swing success does not establish the whole requested invariance. The
model still needs information that distinguishes intended notation from an
equally compatible performance interpretation, and a better treatment of
variation within a take.

### Same-score stability must not reward collapsing different rhythms

| Method | Equal decided score within family / 14,160 pairs | Equal decided score across different families / 100,800 pairs | Different-family pairs with both decided |
| --- | ---: | ---: | ---: |
| Narrow straight | 2,571 | 1,431 | 49,203 |
| Wide straight | 4,494 | 4,095 | 89,676 |
| Phase-aware | 3,480 | **54** | 34,839 |
| Always the same score | 14,160 | 100,800 | 100,800 |

Common abstention is never counted as an equal score. Different coverage must
be considered when comparing these counts; the table is not a comparison at a
common decision rate. **None of the three inference arms makes every one of
the 60 cases (including tempo replicas) in any of the eight families choose
the correct common score.**
The constant baseline makes one family stable-correct and seven stable-wrong,
despite perfect within-family equality. This is why equality alone is insufficient.

### Identical observations can imply different written rhythms

Two pairs deliberately have byte-identical inference input and identical
predictions, but different canonical targets:

- Eighth-note spacing performed with 2:1 swing versus literal long-short
  triplet positions performed straight.
- Eighth-note spacing performed with 3:1 swing versus literal dotted positions
  performed straight.

Each straight arm and the constant baseline selects the same score for both
members of each pair: one correct, one wrong. Phase-aware **abstains on all four
cases and retains the correct target among candidates for all four**. No
deterministic function of these identical inputs can return the different true
targets without additional information. This constructed result supports
retaining ambiguity and consulting musical context; it does not identify the
most useful additional context in real recordings.

## 2. Actual human performances of shared beat instructions

The [official GMD description](https://magenta.tensorflow.org/datasets/groove)
identifies four drummers performing the same ten beats in their own styles.
All 40 specified MIDI files were admitted from the pinned MIDI-only ZIP. Cold
acquisition used **one HTTP request / 3,260,318 bytes**, verified the complete
archive SHA256 and **41 members** including `info.csv`, with zero cache hits.
The archive is CC BY 4.0; the source is Gillick et al., *Learning to Groove with
Inverse Sequence Transformations*, ICML 2019.

The fixed first 15 bars contain **10,818 attacks** of 11,493 in the source;
675 attacks outside the declared window remain accounted for. The selected
velocities span **4–127**, with **40–104 distinct velocities per take**. Within
the fixed window, performed onsets, velocities and attack counts are unchanged
by extraction. This check is not a MIDI export or perceptual-naturalness test.

BPM, filename, style, drummer, groove and reference score are excluded from the
selector. Tick/PPQN and the file's bar origin provide the clock. Every groove
has differing attack counts across its four performers, so these instructions
do not supply strict every-hit equivalence labels. No canonical written score
is present. The official test split is now used as development evidence for
this work, not an untouched future holdout.

### Same-groove retrieval, not recovered notation

Each take is represented by a unit-mass 9-kit × 48-position bar profile, folding
bar order. A query searches only the other three drummers' 30 examples from
the same closed set of ten groove instructions. Tied nearest examples spanning
multiple groove labels are ambiguous, never credited by label-aware tie breaking.

| Representation | Correct / 40 | Wrong | Ambiguous | Correct gains / losses versus straight | Pair-separation AUC |
| --- | ---: | ---: | ---: | ---: | ---: |
| Straight profile, narrow or wide | **34** | 6 | 0 | 0 / 0 | **0.913642** |
| Phase-aware candidate minimum | 31 | 9 | 0 | 1 / 4 | 0.906883 |
| One best phase fixed per take | 30 | 10 | 0 | 1 / 5 | 0.839321 |
| Velocity-weighted straight | 35 | 5 | 0 | 3 / 2 | 0.894660 |
| Instrument inventory only | 20 | 19 | 1 | 2 / 16 | 0.730355 |
| Constant profile | 0 | 0 | 40 | 0 / 34 | 0.500000 |

There are **60 same-groove and 540 different-groove cross-drummer pairs**. AUC
compares their distance distributions, with a tie worth one half. Pairs share
performances and are correlated; no independent-sample confidence interval is
claimed. For all nonconstant representations, zero-distance same-groove and
different-groove pair counts are both zero. The constant profile collapses all
60 and 540 pairs and makes all 40 retrieval queries ambiguous.

The narrow and wide straight retrieval results are **identical by construction**,
because they use the same nearest-position profile. The gate only changes
full-score acceptance. The phase-aware candidate minimum can choose a different
phase for the same take against different partners; it is an optimistic set
comparison, not evidence for one stable recovered score. Even that comparison
falls from 34/40 to 31/40 here. Its one gain is drummer1/groove10; its four
losses are drummer5/7/8 on groove2 and drummer7 on groove7.

The velocity-weighted method's 35/40 includes three gains and two losses, while
its pair AUC is below straight. This is a small, task-dependent outcome, not
proof that accent changes should define different scores or that velocity
weighting generalizes. Accent variation and timing variation were not isolated
causally in these recordings.

| Held-out drummer | Straight correct / 10 | Phase-aware correct / 10 | Fixed best phase correct / 10 | Velocity-weighted correct / 10 |
| --- | ---: | ---: | ---: | ---: |
| drummer1 | 8 | 9 | 7 | 9 |
| drummer5 | 8 | 7 | 6 | 7 |
| drummer7 | 10 | 8 | 9 | 10 |
| drummer8 | 8 | 7 | 8 | 9 |

Same-BPM contrasts are separately reported so that a tempo-label shortcut is
not mistaken for rhythm discrimination. Each contrast contains eight cases,
12 same-groove pairs and 12 different-groove pairs. For groove1 versus groove7,
straight / phase-aware AUC is **0.916667 / 0.930556**; for groove2 versus groove9,
it is **0.861111 / 0.729167**. The full receipt also includes the other controls.

### Full-score decisions remain inadequate

Each inference arm selects a complete canonical onset sequence for only **one
of 40 takes**, drummer8/groove4. There is no written truth to declare that
decision correct. Narrow straight and phase-aware reject the other 39 on the
maximum-residual rule. Wide straight has 30 residual rejections and nine
same-instrument collisions, plus the same one decision. Same-groove equal
decided-score pairs are **0/60** for every arm. This poor coverage is distinct
from the useful but weaker folded-profile retrieval result.

## Implications for the next experiment

1. Keep canonical rhythm and performed timing/strength as separate variables.
   Evaluate their relation using the same-score target, not raw-time equality.
2. Test a pattern-level model with local phase/tempo variation and explicit
   complexity control. The current residual-only, single-global-phase model is
   inadequate; merely raising its acceptance limit is not supported by this run.
3. Preserve competing interpretations where performance alone is insufficient.
   Any musical prior or repeated-pattern context must be declared before the
   next run and tested against genuinely different written rhythms.
4. Obtain several human performances aligned to one identical symbolic score,
   verifying the score file and repeated-section occurrence identities. Retain
   the GMD task as a separate groove diagnostic; it cannot supply missing exact
   notation labels. Use a fresh held-out evaluation after development choices.
5. Separate timing-only, velocity-only and combined expression changes in the
   next controlled experiment. Treat fills or decorative hits explicitly rather
   than silently dropping them to improve equality.

These are follow-up hypotheses, not fixes proven by the present outcomes.
Execution issue [#282](https://github.com/JDeun/audio-score-tool/issues/282) is
bounded to this completed pilot. Umbrella [#281](https://github.com/JDeun/audio-score-tool/issues/281)
remains open for actual common-score recovery. Draft #236 is independent.

## Receipts and verification

The exact [Actions artifact ZIP](receipts/performed-rhythm-invariance-43236100984.zip)
is retained beyond the service's 14-day artifact retention. It contains only
bounded `report.json` metadata; original MIDI and full event/prediction arrays
are not republished.

| Object | Bytes | SHA256 |
| --- | ---: | --- |
| Artifact 13951958071 ZIP | 273,834 | `7dad622b5ed1106691a5c10c387ef810b286cf49ce2bceaac920d0bdf45cd2af` |
| Exact report.json member | 4,169,391 | `30b839ab832780789eb9d4e77632d3679cd9efac2a031f40357e9080b4b4b723` |

The frozen workflow passed **136 contract tests** and Ruff before inference.
[Initial-head CI](https://github.com/JDeun/audio-score-tool/actions/runs/43236100635)
then passed **2,119 product tests** (nine skips), **1,303 research tests** (one
existing upstream warning), **69 frontend tests** and the required `verify` job.
The inventory is 200 product / 50 research test files, with zero omissions.
[Research Evidence Contracts](https://github.com/JDeun/audio-score-tool/actions/runs/43236100310)
passed 34 tests. Tauri compilation and main/manual stress and soak were correctly skipped for
this PR event under the existing workflow policy. See #283 for the subsequent
final-head and actual-main verification record.

Independent [model reconstruction](receipts/performed-rhythm-invariance-model-audit-43236100984.json)
and [source/arithmetic audit](receipts/performed-rhythm-invariance-source-audit-43236100984.json)
both passed and are retained alongside the exact receipt:

- Model reconstruction imports no project helper. It independently rebuilds
  the authored generator and enumerates the full phase lattice, and reads real
  MIDI through mido. All **524 input-file hashes, 524 prediction-file hashes and
  524 prediction-content fingerprints** match exactly, including **2,096 fits,
  1,572 arms and 97,480 event assignments**. It also reconstructs the per-hit
  targets, counterfactuals, all 600 pair distances for seven representations,
  280 query-method outcomes and summaries. Maximum numeric difference is zero.
- Source/arithmetic verification uses an independent standard-library SMF
  byte/VLQ/running-status decoder, without mido or project imports. All 40
  source admissions and input hashes match. It verifies all 41 member SHA/CRC
  identities, all 12 committed file hashes and the actual checkout's Git tree
  and parents, then recomputes the published partitions, arm policies,
  nearest ties, AUCs, paired gains/losses and summaries. Its **262,889 assertions**
  pass with maximum numeric difference zero. Model-derived primitive distances
  are ledger inputs in this audit and are independently rebuilt by the first.

| Audit | Bytes | SHA256 |
| --- | ---: | --- |
| Model | 10,822 | `8d776215fe61c14c9486d559dcbdaa43edf6a828c984b309c568793fc90ff403` |
| Source / arithmetic | 70,819 | `0c2cd62a4c204919c57fe790def7c84613413c4cb7c2d18b7d8816534fbfeac7` |

The audits use Python's specified numerical primitives and verify the declared
algorithm; they do not supply independent annotations of musical intent. The
model audit shares mido with the original execution, while the second source
parser is independent. Successful reproduction does not turn diagnostic
retrieval into canonical-score accuracy or observed runtime into independent
proof of every execution-order event.
