# Same written score across expressive performances — completed CPU results

## Decision

The next experiment under [#281](https://github.com/JDeun/audio-score-tool/issues/281)
completed all **488 predeclared cases** in execution
[#284](https://github.com/JDeun/audio-score-tool/issues/284), through
[PR #285](https://github.com/JDeun/audio-score-tool/pull/285). The
[frozen protocol](SAME_SCORE_EXPRESSION_PROTOCOL_2026-11-12.md) was committed
before any cohort inference. No model, threshold, window or population was changed
after seeing outcomes.

**Local phase helps some authored changing-expression cases, but does not improve
the actual identical-score performances.** The primary local-switch-cost model
changes main synthetic full-score results from global **201 correct / 84 wrong /
195 abstentions** to **210 / 15 / 255**. On the four actual performances it changes
ordinary attack results from **751 correct / 25 wrong / 1 abstention / 5 unobserved**
to **720 / 22 / 35 / 5**, on the same 782 targets. The 31 lost correct decisions
all become abstentions; no actual target becomes newly correct.

The user's target remains the shared written rhythm underlying variable timing,
swing and strength. These results support keeping interpretation separate from
the original performance, but do not establish a successful common-score
recovery method. In particular, reducing wrong decisions by abstaining is not
the same as correctly recovering more of an actual score. This bounded research
implementation and its evidence can be integrated; the tested local model is
not accepted as a product correction. #281 remains open.

## Execution and original source admission

[CPU run 43247249315](https://github.com/JDeun/audio-score-tool/actions/runs/43247249315),
attempt **1**, completed successfully. The study recorded 488/488 inferences and
488/488 input preservation checks; all private predictions were saved before
either evaluation loader ran. Runtime was **39.121820 seconds**, including
19.365037 seconds in the runner's inference stage. This is a small symbolic CPU
experiment, with zero neural model calls or audio transcription.

| Identity | Recorded value |
| --- | --- |
| Base actual main | `61b77bec85d60733aac5af751ae272fa33e60daf` |
| Frozen scientific head | `ce59cd16fe53072c5967cd8c1c555f8eb30ece79` |
| Actual PR merge checkout | `747bef7f53160fb1549b4725138ab67db7585aa8` |
| Scientific checkout tree | `969ad8bf5e408a28184be0d309f0573769be6398` |
| Checkout parents | Base main, then frozen head above |
| Runtime | CPython 3.12.16; mido 1.3.3; pytest 8.4.2; Ruff 0.16.6 |
| Workspace | Clean at execution |
| Measured scientific files | 18, including six literal inherited byte pins |
| Private prediction bytes | 55,312,147; hashes recorded, raw predictions not published |

The [source manifest](../../scripts/nasap_same_score_manifest.json) pins official
[nASAP revision 4097b45757bed854818cf87e77b92323ebf90615](https://github.com/CPJKU/asap-dataset/tree/4097b45757bed854818cf87e77b92323ebf90615).
The execution verified all **25 original files / 2,241,212 bytes**. Input preparation
used only four original MIDIs and four performance beat TSVs: eight requests /
48,459 bytes. After prediction freezing, evaluation used eight validated cache
hits plus 17 new requests / 2,192,753 bytes. All source and canonical-pair admission
checks completed; no performance was replaced or silently omitted.

The four original performances share two byte-identical XML score pairs. Use of
the author's beat/downbeat annotations supplies a musical clock. Native MIDI
PPQN/120 BPM is decoded into seconds and is not mistaken for the score-quarter
clock. The first supplied downbeat starts input quarter 0; the fixed 32-quarter
window corresponds to XML quarters **[4,36)**. Score/alignment identity enters
only evaluation, after every prediction has been frozen.

| Performance | XML family | Original selected attacks | Ordinary targets | Observed ordinary | Deletion | Outside input window |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Denisova06M (`nasap001`) | BWV848 | 180 | 180 | 179 | 0 | 1 |
| Lee01M (`nasap002`) | BWV848 | 183 | 180 | 179 | 0 | 1 |
| LuA01M (`nasap003`) | BWV854 | 213 | 211 | 210 | 1 | 0 |
| MiyashitaM01M (`nasap004`) | BWV854 | 213 | 211 | 209 | 2 | 0 |
| Total | Two scores | **789** | **782** | **777** | **3** | **2** |

All 789 inputs are retained: 777 ordinary-target observations, two grace
observations, five insertions and five observations matched to score notes outside
the canonical target window. The two grace targets are recorded separately.
All 782 ordinary targets are supported by this study's Q12 onset lattice;
there are no ordinary performance pitch mismatches in these windows. Therefore
onset-only and pitch-plus-onset correctness happen to agree here. Neither fact
was used to select only well-behaved target rows.

Source correspondence is a supplied publisher annotation. Ordinary-target
accuracy does not charge the 12 non-ordinary input observations as precision
errors, so it is reference-conditioned attack accuracy, not full AMT precision.
Missing targets remain in the denominator. Raw velocity, note timing and
controller bytes are preserved, but velocity does not enter phase fitting and
no MIDI export or perceived-naturalness claim is made.

## 1. Actual identical-score performance results

### Ordinary attack decisions: all 782 targets

The two straight arms share the same nearest-position interpretation and differ
only in the acceptance gate. Global uses one of four phases per take. Local
uses a phase per fixed four-quarter block, with no switch penalty, the primary
0.0025-quarter-squared penalty, or the 0.01 sensitivity penalty. See the frozen
protocol for exact path budgets and gates.

| Arm | Correct | Wrong | Abstained | Unobserved | Correct / all targets | Gain / loss versus global |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Straight narrow | 751 | 25 | 1 | 5 | 96.0358% | 0 / 0 |
| Straight wide | 752 | 25 | 0 | 5 | 96.1637% | 1 / 0 |
| Global phase | 751 | 25 | 1 | 5 | 96.0358% | 0 / 0 |
| Local raw | 720 | 22 | 35 | 5 | 92.0716% | 0 / 31 |
| **Local switch 0.0025 — primary** | **720** | **22** | **35** | **5** | **92.0716%** | **0 / 31** |
| Local switch 0.01 | 720 | 22 | 35 | 5 | 92.0716% | 0 / 31 |

The equal-score mean correctness is **96.0005%** for straight narrow/global,
**96.1190%** for straight wide and **92.1439%** for each local arm. This gives
BWV848 and BWV854 equal weight instead of weighting them by their 360 and 422
performance-target instances. Both views show the same direction of change.

Every primary-local transition from global is accounted for: 720 correct remain
correct; **31 correct become abstained**; 22 wrong remain wrong; **three wrong
become abstained**; the original abstention and five unobserved targets retain
their status. The local model does not turn any actual wrong or abstained target
into a correct decision. Widening the straight gate resolves one abstention in
LuA01M correctly, without changing the other 781 statuses in this pilot.

| Performance | Global C / W / A / U | Primary local C / W / A / U |
| --- | ---: | ---: |
| Denisova06M | 167 / 12 / 0 / 1 | 163 / 11 / 5 / 1 |
| Lee01M | 177 / 2 / 0 / 1 | 172 / 2 / 5 / 1 |
| LuA01M | 198 / 11 / 1 / 1 | 188 / 9 / 13 / 1 |
| MiyashitaM01M | 209 / 0 / 0 / 2 | 197 / 0 / 12 / 2 |

All four global diagnostic best trajectories are straight. Local alternatives
occur in the first four-quarter block of the BWV848 performances and the last
block of the BWV854 performances. Some local best trajectories use phase 3/4
in that last block, but the fixed near-best budget also retains competing
canonical interpretations. All local arms retain the true tick among diagnostic
candidates for **751 targets**, exactly the global count, while uniquely deciding
only 720 correctly. Additional flexibility increased ambiguity without gaining
target coverage. Different switch costs alter some retained state sets but yield
the same real per-reference decision masks.

This is evidence about the frozen model and these sources, not a finding that
human expressive variation is absent. Beat-scale tempo variation has already
been absorbed into the supplied clock, and a four-phase warp is a narrow model
of human timing. The last-block best phase is not independently identified
musical swing.

### Same written note across both takes: all 391 canonical pairs

Each score contributes every ordinary canonical occurrence, even if a performer
omits it or its matched event falls outside the input window. Thus the pair
denominator is **180 + 211 = 391**, not only the 388 both-observed pairs. A pair
with either unobserved note remains unobserved; otherwise a missing decision
remains abstention. Two identical wrong ticks count as **same wrong**, not success.

| Arm | Both correct | Same wrong | Different decisions | Either abstained | Either unobserved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Straight narrow | 364 | 1 | 22 | 1 | 3 |
| Straight wide | 365 | 1 | 22 | 0 | 3 |
| Global phase | 364 | 1 | 22 | 1 | 3 |
| Local raw | 350 | 1 | 19 | 18 | 3 |
| **Local switch 0.0025** | **350** | **1** | **19** | **18** | **3** |
| Local switch 0.01 | 350 | 1 | 19 | 18 | 3 |

Both-correct recovery falls from **364/391 (93.0946%)** to **350/391 (89.5141%)**.
By score, global versus primary is **166→162 /180** for BWV848 and **198→188 /211**
for BWV854. The one stable-wrong pair remains under every arm. Merely reducing
disagreement, 22→19, would conceal the increase in abstention and the loss of
correct common interpretations.

### Whole-input decisions and conditional candidate availability

Straight/global make one strict full-input decision, for Denisova06M; that
performance still has 12 incorrect ordinary attacks. Each local arm makes zero
strict full decisions. The other three inputs fail the whole-input residual
condition, even when most individual ordinary notes have correct diagnostic
positions. This preserves the difference between per-note and complete-sequence
validity.

For MiyashitaM01M, the observed ordinary target assignment exists in the diagnostic
path set under every arm, but not in the residual-gated full-input path set.
The other three performances have no path matching all observed ordinary targets
within the fixed diagnostic budget. These are conditional path-existence
statements: they neither recover missing notes nor establish unique notation.

Strict full signatures produce zero equal same-score pairs and zero equal
different-score pairs. **These numbers are not an independent rhythm
discrimination test:** BWV848 inputs contain 180 versus 183 attacks, so a
count-preserving signature cannot match; every cross-score pair compares 180 or
183 attacks with 213. The inventory difference already separates them. The
constant-score diagnostic collapses all two same-score and four different-score
pairs, illustrating why output equality without correctness and inventory
accounting is insufficient.

## 2. Reused authored development controls

### Full onset-score decisions on the 480 main cases

The original generator, timing, velocity, case order and exact truth are retained;
only opaque case IDs and equivalent MIDI pitch labels change. The four additional
identical-observation controls are reported separately below. These data were
already used in #283 and are not new validation evidence.

| Arm | Correct | Wrong | Abstained | Truth-compatible retained path |
| --- | ---: | ---: | ---: | ---: |
| Straight narrow | 105 | 234 | 141 | 105 |
| Straight wide | 132 | 321 | 27 | 135 |
| Global phase | 201 | 84 | 195 | 381 |
| Local raw | 195 | 0 | 285 | 462 |
| **Local switch 0.0025 — primary** | **210** | **15** | **255** | **441** |
| Local switch 0.01 | 201 | 84 | 195 | 387 |
| Always four-on-the-floor | 60 | 420 | 0 | 60 |

The straight/global decision counts exactly preserve the preceding experiment.
Primary local retains all 201 global-correct cases and gains nine: six formerly
wrong cases and three formerly abstained cases become correct. Of the other
global wrong cases, 63 become abstentions and 15 remain wrong. Thus most of the
84→15 wrong-decision reduction comes from refusing an uncertain interpretation.
It is not a 69-case increase in recovered scores.

Unpenalized local makes zero wrong full decisions but loses 27 global-correct
cases to abstention, while gaining 21 correct cases elsewhere. Its 195 correct
cases are fewer than global's 201. The higher switch penalty gives the same
201/84/195 full decisions as global; its small candidate-path difference does
not translate into additional correct choices. The declared sensitivity arm
therefore matters to the interpretation of the primary improvement.

| Population | Arm | Correct | Wrong | Abstained | Retained truth path |
| --- | --- | ---: | ---: | ---: | ---: |
| Stationary, in-vocabulary: 384 | Global | 201 | 0 | 183 | 381 |
| Same 384 | Local raw | 174 | 0 | 210 | 381 |
| Same 384 | Primary local | 201 | 0 | 183 | 381 |
| Same 384 | Local 0.01 | 201 | 0 | 183 | 381 |
| Changing, out-of-vocabulary: 96 | Global | 0 | 84 | 12 | 0 |
| Same 96 | Local raw | 21 | 0 | 75 | 81 |
| Same 96 | Primary local | 9 | 15 | 72 | 60 |
| Same 96 | Local 0.01 | 0 | 84 | 12 | 6 |

The changing profile switches 0.56→0.70 across bars while the hypothesis
vocabulary remains 0.5/0.6/2/3/0.75. Stationarity and exact vocabulary support are
confounded in this stress set. A local improvement on it does not isolate a
general rule for human swing or establish a continuous expression model.

There are **13,440** main synthetic event targets. Diagnostic per-event results
are global **11,109 correct / 417 wrong / 1,914 abstained**, local raw
**10,992 / 33 / 2,415**, primary **11,127 / 108 / 2,205**, and local 0.01
**11,097 / 405 / 1,938**. Zero wrong full decisions for local raw therefore does
not mean zero erroneous per-event diagnostics. Candidate inclusion and
truth-compatible complete paths also remain separate from selected correctness.

### Family stability and the user's four-on-the-floor example

No inference arm makes all 60 versions of any of the eight families select the
same correct score: **0/8 fully stable-correct families**. For the explicit
four-on-the-floor eighth-note family, global gives **12 correct / 12 wrong /
36 abstentions**, local raw **12 / 0 / 48**, primary **12 / 6 / 42**, and local
0.01 **12 / 12 / 36**. The intended invariant score is still unresolved for many
versions of the user's motivating pattern.

The population includes 14,160 same-family and 100,800 different-family pairs.
Primary local has 3,609 equal decided same-family pairs out of 3,762 both-decided
pairs, and zero equal different-family pairs out of 21,438 both-decided pairs.
Global has 3,480/5,631 equal same-family pairs and 54/34,839 equal different-family
pairs. These conditional coverage counts must accompany any claim of fewer false
merges; primary abstains on many more complete cases.

Always selecting four-on-the-floor makes that one family perfectly stable but
creates **seven stable-wrong families**, gets 420/480 cases wrong and collapses
all 100,800 different-family pairs. This control is intentionally degenerate;
high consistency alone cannot establish common-score recovery.

### Identical observed performances with different written targets

Both counterfactual pairs retain identical input and complete prediction hashes,
while their written onset targets differ. Global and all three local arms
abstain on both members of each pair, retaining a compatible path for each truth.
Straight and constant controls choose one interpretation, yielding one correct
and one wrong result per pair.

The corresponding ambiguity is structural: the same observed timing can encode
swung eighths or a different literal written rhythm. More tolerance or a more
flexible warp cannot make those observations uniquely identify notation without
additional assumptions or context. This does not contradict different
performances sharing a score; it limits how that shared score can be inferred
from timing alone.

## 3. What the next experiment must resolve

The implementation now measures actual correspondence to an identical written
score across performers, with preserved source attacks and explicit ambiguity.
The next study should keep that target while addressing the demonstrated loss of
useful decisions:

1. Separate changing versus stationary expression from in-vocabulary versus
   out-of-vocabulary expression in matched controls. The present 96-case stress
   cannot distinguish the two effects.
2. Test evidence for choosing or retaining a local expression hypothesis, with a
   declared complexity/uncertainty rule and the straight alternative present.
   The current local candidate sets create 31 extra real correct-to-abstained
   transitions without one new correct note. Do not retrospectively tune this
   cohort until it appears improved.
3. Use additional preselected actual same-score performances and different-score
   controls with comparable attack inventories. Keep observed insertion/deletion
   coverage, exact canonical reference pairing and whole-input rejection visible.
   The present strict cross-score signature diagnostic is count-confounded.
4. Evaluate accent/velocity as a separate performance variable if it is used for
   interpretation. Here it is retained but not used, so the result cannot establish
   improved accent handling or performance naturalness.

These are follow-up requirements, not results of an unreported second run.
Two classical piano works with supplied clocks/alignment and reused authored
controls remain development evidence. Written durations/rests, inferred voices,
audio-derived beat clocks, full engraving, real drum-score transfer and product
editing benefit remain unmeasured.

## Exact receipts and verification

The exact [Actions ZIP](receipts/same-score-expression-43247249315.zip) is retained
with the repository beyond the service's 14-day artifact retention. It contains
only bounded metadata, compact correctness masks and provenance, not original
MIDI/XML/alignment arrays or complete predicted note sequences.

| Object | Bytes | SHA256 |
| --- | ---: | --- |
| Artifact 13958980529, exact ZIP | 319,774 | `38107d18e89058ef4e870214e0ba5af0bb7b97eb92d1b7ef056e9096c30c7f17` |
| Exact `report.json` member | 7,260,857 | `0b5b2d14c7f49c75a18413d9876dd8960e224c06131b8e5c47e4f47657860a1a` |
| Independent model audit | 17,587 | `fec1127fa935d55231ccacfabb05fb88bc44c7702a99a90782b6f2bd023e4c5b` |
| Independent source/arithmetic audit | 97,979 | `a64e5498aea36ab54b5a4804306fb8830fd72f7f7094d3c4c40a38224947ec89` |

The report records the complete ordered plan hash
`4affb916e699de8c1c849e180971e5db3c38168794ba23140b1403fb1c4b0ded`,
prediction-set hash
`cf33aebe199ad13bae9c5c63b8ea0fbc4b83cfe9a0b05d4f2902cbc99b6e83c9`
and evaluation hash
`e5bd569079d2200119e1fc55bfe32f4fa228b5207c62494f9e8450dd6b8fa85c`.
Per-case exact file hashes and semantic fingerprints have distinct names.

Independent [model replay](receipts/same-score-expression-model-audit-43247249315.json)
and [source/arithmetic audit](receipts/same-score-expression-source-audit-43247249315.json)
are retained alongside the original receipt. They are audit replays of frozen
decisions, not additional trials or replacements for the original run.

The model audit does not import the new estimator/evaluator. It directly searches
the full lattice and enumerates complete local paths, up to 4^8, rather than
using the implementation's dynamic program. **244,395 checks passed**, including
all 1,952 fits and 2,928 arms across 14,341 input events. Input file/content hashes
and complete prediction file/content hashes each match **488/488 exactly**.
The maximum difference across 11,553 numerical comparisons is **0.0**, with zero
semantic or public-summary mismatches. Audit CPython 3.12.14 and execution
CPython 3.12.16 are recorded separately despite their exact matching outputs.
The old authored generator is reused for synthetic input generation; real inputs
and targets come from the second audit's independent original-byte reconstruction.

The source audit imports no repository parser or estimator. It decodes SMF bytes
and XML/TSV/CSV directly, verifying original attacks, controllers, beat clocks,
canonical ties/grace, score maps and alignments. Its **135,415 source checks**
and **197,298 receipt/arithmetic checks**, **332,713 total**, pass with maximum
numerical difference **0**. It verifies all 25 source identities, all 18 measured
code hashes, official checkout/tree/parents, actual acquisition counters,
782-target masks, 391-pair masks, per-score means and synthetic family/profile/
regime/pair aggregates. Model decisions are ledger inputs to this second audit
and are reconstructed independently by the first; source consistency remains
distinct from new human annotation ground truth.

The scientific workflow passed **172 contracts** and Ruff. The research inventory
contains **54 files**, the product inventory **200**, with zero omitted files.
The unchanged baseline source pins, metadata-only publication checks, knowledge
links, forensic hygiene and historical-ledger checks passed. The five existing
knowledge-source pin warnings remain unchanged.

[Initial-head CI](https://github.com/JDeun/audio-score-tool/actions/runs/43247249018)
passed **2,119 product tests / 9 optional skips**, **1,475 research tests / one
existing upstream warning**, and **69 frontend tests**. Its required verify job
passed; Tauri was correctly skipped for that research-only PR diff.
[Evidence Contracts](https://github.com/JDeun/audio-score-tool/actions/runs/43247249156)
passed 34. Final result-head and actual-main verification, including the main
Tauri/stress/soak and security/compatibility checks, are recorded on
[PR #285](https://github.com/JDeun/audio-score-tool/pull/285).
