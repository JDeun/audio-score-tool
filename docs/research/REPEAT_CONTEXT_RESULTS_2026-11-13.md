# Repeated rhythm context — completed CPU results

## Decision

Execution [#286](https://github.com/JDeun/audio-score-tool/issues/286), through
[PR #287](https://github.com/JDeun/audio-score-tool/pull/287), completed all
**1,520 predeclared cases**. The original run failed while serializing the final
public report. The separately frozen recovery reproduced every original input
and prediction file before publishing the unchanged evaluation in compact JSON.
The original failed artifact remains intact and is not relabelled successful.

**The tested repeat prior does not establish better common-score recovery.**
Against the local-expression baseline, the primary `repeat_soft010` arm gains
nine correct full scores on the 480 reused authored cases, without adding a
wrong full decision there. On the 1,024 new factorial cases it gains only four
correct full scores while adding eight wrong decisions and removing the true
joint score from 26 candidate sets. On all eight actual performances the repeat
detector finds no links, and the primary arm has exactly the local baseline's
outcomes. The four cohorts retain separate denominators throughout this report.

The user's target remains the same written rhythm underneath differences in
timing, swing and accents. No inference arm recovers every expression version
of any authored family correctly. In particular, the original four-on-the-floor
eighth-note family remains **12 correct / 6 wrong / 42 abstained** out of 60,
and the new repeated `four_on_floor_eighth/AAAA` family remains **0 / 3 / 29**
out of 32. These are authored controls; the actual data are Bach piano
performances, not a human-played four-on-the-floor notation validation.

The bounded research code and negative evidence can be integrated. The tested
prior is not accepted as an automatic product correction, and the continuing
goal [#281](https://github.com/JDeun/audio-score-tool/issues/281) remains open.

## Execution, failure and recovery

The [scientific protocol](REPEAT_CONTEXT_PROTOCOL_2026-11-13.md) was frozen
before inference. The [recovery protocol](REPEAT_CONTEXT_RECOVERY_2026-11-13.md)
was frozen before the official recovery. No population, source, target,
selector, gate, prior weight, evaluation arithmetic or byte limit was changed.

| Identity | Original scientific execution | Official recovery |
| --- | --- | --- |
| Actions run, attempt 1 | [43256776331](https://github.com/JDeun/audio-score-tool/actions/runs/43256776331) | [43261359821](https://github.com/JDeun/audio-score-tool/actions/runs/43261359821) |
| Status | `evaluation_failed`; evaluation and summary null | `complete` |
| Source head | `cbcf97e0dc7fbd56bc3052e3f8daa30475b36cad` | `ae0e09eae5b39cb0d06ab4d71d8a6868a884de74` |
| Actual checkout | `357c7531fd3d10364c515b8a45a0607bea30afa4` | `ae0e09eae5b39cb0d06ab4d71d8a6868a884de74` |
| Checkout tree | `5cccebbe6b4aa5342790feae9183b1be36505134` | `a609d685d4b2c6a2ae47601d54781d2bf8dfc697` |
| Artifact ID | 13962156613 | 13963788382 |
| Exact ZIP bytes | 361,958 | 1,519,299 |
| Sole `report.json` member bytes | 2,842,632 | 16,524,883 |

Both runs use the same scientific base main
`b7561cc64e2a595ba9d99cbaf1cf2170f00ae2ee`. The original PR checkout has that
base and the scientific head as parents. The recovery is a clean direct push
checkout with the original scientific head as its parent.

| Preserved file | SHA256 |
| --- | --- |
| [Original failed ZIP](receipts/repeat-context-incomplete-43256776331.zip) | `cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e` |
| Original failed report | `568898b9c1f1fb6d5d2671e1805305eaa2939b2d1580175f0e2d6fc43e16c559` |
| [Official recovery ZIP](receipts/repeat-context-recovery-43261359821.zip) | `d77222eef446dbe9f24caa4b733139c59f2f06b96c8dcaf461dba34c3caa8528` |
| Official compact report | `b64985586ec5f0340a61b45bce99107bccfd60d50bd3d19491e0f524c699bf93` |
| Evaluation object, original indented encoding | `88009a2d8d72bba3a8bb20cf076d8e36e37d415d9affeb95d6b2602cdb0e5027` |

The recovery completed **1,520 inferences and 1,520 preservation checks** in
171.584862 seconds, including 104.247212 seconds in inference. It retained
265,464,728 private prediction bytes. Each original input-file hash and complete
prediction-file hash matches both the new ledger and the actual replayed
private file. All predictions were saved before any of the four evaluation
loaders ran. The recovery invokes the unchanged runner once and the unchanged
evaluator once; it verifies the known combined-report budget failure before
publishing compact public JSON. The original private JSON encoding is unchanged.

CPython 3.12.16, mido 1.3.3, pytest 8.4.2 and Ruff 0.16.6 were recorded.
This is a CPU symbolic experiment with **zero neural model calls and no fresh
audio transcription**. Both source caches together used 50 verified requests /
4,602,128 transferred bytes; metadata is duplicated between caches. The unique
source set is 49 files / 3,985,273 bytes. No original MIDI, XML, alignment,
event arrays or model weights are republished.

## 1. Actual same-score performances

The reused cohort contains the four BWV848/BWV854 performances from #285.
The additional cohort contains the two preselected BWV857/BWV858 same-XML
pairs. Each uses a fixed 32-quarter input window and the corresponding XML
quarters [4,36), with the publisher's beat/downbeat clock and alignment supplied.
All source attacks and canonical targets remain, including deletions,
outside-window targets, insertions and unsupported lattice targets.

| Cohort | Performances | Input attacks | Ordinary targets | Observed ordinary | Unobserved ordinary | Grace targets | Canonical same-score pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Reused actual | 4 | 789 | 782 | 777 | 5 | 2 | 391 |
| Additional actual | 4 | 605 | 596 | 571 | 25 | 0 | 298 |

For the additional cohort, the 25 unobserved targets comprise 23 publisher
deletions and two targets outside the input window. Its 605 inputs comprise
571 ordinary observations, 29 insertions and five attacks matched outside the
canonical target window. There are 560 lattice-supported targets out of 596;
unsupported targets are not silently dropped. The new adapter's binary32 CSV
serialization admission leaves exact XML fractions as truth. The 40 admitted
scalar differences are all outside the chosen evaluation windows; this is not
a wider musical tolerance.

### Ordinary target outcomes

Each cell is **correct / wrong / abstained / unobserved**. These are
reference-conditioned pitch/onset decisions, not complete transcription F1.

| Arm | Reused actual, 782 targets | Additional actual, 596 targets |
| --- | ---: | ---: |
| Straight narrow | 751 / 25 / 1 / 5 | 529 / 35 / 7 / 25 |
| Global phase | 751 / 25 / 1 / 5 | 529 / 35 / 7 / 25 |
| Local switch 0.0025 | 720 / 22 / 35 / 5 | 492 / 41 / 38 / 25 |
| Weak repeat, `repeat_soft0025` | 720 / 22 / 35 / 5 | 492 / 41 / 38 / 25 |
| **Primary repeat, `repeat_soft010`** | **720 / 22 / 35 / 5** | **492 / 41 / 38 / 25** |
| Hard repeat | 720 / 22 / 35 / 5 | 492 / 41 / 38 / 25 |

The primary arm gains **zero** correct target and loses **zero** correct target
against local in each cohort. Against global, the local/repeat methods still
lose 31 correct targets in the reused cohort and 37 in the additional cohort.
The additional local result also has six more wrong decisions than global.

Same-score reference pairs where both performances are correct remain
**350/391** and **229/298** for every local/repeat arm. Global gives 364/391 and
255/298 respectively. Same-wrong pairs remain one and seven. For primary,
the remaining paired outcomes are disagreement 19 / 14, abstention 18 / 33,
and unobserved 3 / 15, in reused/additional order. No repeat arm produces a
strict full real-input decision.

### Why repeat context has no actual effect

There are **zero repeat links in all eight performances**. This is an observed
coverage failure of the declared detector; it is not evidence that real musical
repetition is absent. No-link cases fall back to the local baseline by design.

| Block eligibility reason | Reused actual, 32 blocks | Additional actual, 32 blocks |
| --- | ---: | ---: |
| Canonical candidate falls outside its observed block | 24 | 20 |
| Coarse quarter disagrees across phases | 0 | 3 |
| Too few attacks | 0 | 2 |
| Eligible | 8 | 7 |
| Resulting repeat links | **0** | **0** |

The detector assigns an event to a fixed observed four-quarter block and then
requires every phase hypothesis to keep its canonical position inside that
block. An attack just before a block boundary can therefore disqualify the
whole block. This explains a concrete sensitivity worth testing separately;
the current report does not infer that all 44 rejected blocks would become
valid repetitions after a boundary change. Even the 15 eligible blocks yield
no matching earlier pitch/quarter skeleton.

A post-run replay diagnostic found next-block canonical candidates in all 44
blocks rejected for this reason, and none pointing to a previous block. This
describes the frozen candidate geometry, not an independently established true
bar membership for every attack. It does not measure the benefit of a revised
boundary model; that requires a separately frozen experiment.

## 2. Authored full-score outcomes

Counterfactual controls are excluded from the following main-case denominators
and reported separately below. A full score here means the complete canonical
pitch/onset pattern, without written durations, rests or notation export.
All four-quarter context and expression variants are dependent development
controls, not independent human recordings.

| Arm | Reused authored, 480: correct / wrong / abstained | New factorial, 1,024: correct / wrong / abstained | New factorial: true joint score retained |
| --- | ---: | ---: | ---: |
| Straight narrow | 105 / 234 / 141 | 202 / 400 / 422 | 202 |
| Global phase | 201 / 84 / 195 | 314 / 344 / 366 | 427 |
| Local switch 0.0025 | 210 / 15 / 255 | 79 / 12 / 933 | 683 |
| Weak repeat, `repeat_soft0025` | 210 / 15 / 255 | 82 / 14 / 928 | 677 |
| **Primary repeat, `repeat_soft010`** | **219 / 15 / 246** | **83 / 20 / 921** | **657** |
| Hard repeat | 222 / 18 / 240 | 89 / 95 / 840 | 592 |

Primary versus local preserves every previously correct full score. On reused
controls it resolves nine abstentions correctly. On new controls it resolves
four correctly and eight incorrectly; it also loses the true joint candidate
in 26 cases. A stronger hard prior gains ten correct full scores but adds 83
wrong decisions and loses truth in 91 candidate sets. Reduced abstention alone
is not an improvement criterion.

All inference arms have **zero fully stable-correct families** across all
expression variants: 0/8 reused families and 0/32 factorial families. The
always-four-on-the-floor control makes 60/480 and 32/1,024 correct decisions,
but collapses the remaining seven and 31 families to stable wrong outputs.
Stability without correctness cannot meet the user's target.

### Stationarity and phase vocabulary are now separated

Each row contains 256 cases. Phase trajectories have equal separation and
balanced exposure, and matched random draws are reused across factors.

| Expression condition | Local: correct / wrong / abstained | Primary repeat: correct / wrong / abstained | Joint truth retained, local → primary |
| --- | ---: | ---: | ---: |
| Stationary, supported phase | 50 / 0 / 206 | 52 / 0 / 204 | 251 → 250 |
| Stationary, outside vocabulary | 21 / 12 / 223 | 23 / 14 / 219 | 188 → 183 |
| Changing, supported phase | 7 / 0 / 249 | 7 / 1 / 248 | 166 → 151 |
| Changing, outside vocabulary | 1 / 0 / 255 | 1 / 5 / 250 | 78 → 73 |

Changing expression remains difficult even when its phase values are in the
declared vocabulary. In the exact repeated AAAA context, both changing rows
have zero correct full decisions out of 64 per row under either local or
primary repeat. Across all written contexts the repeat prior adds no correct
decision in either changing-expression group. The experiment separates the
two factors but does not solve either inference limitation.

### False repeat links explain a risk of the coarse skeleton

| Main authored cohort | Cases with links | Links | Canonically same links | Canonically different links | Equal / different linked event pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reused, 480 cases | 156 | 156 | 156 | 0 | 2,184 / 0 |
| Factorial, 1,024 cases | 387 | 748 | 313 | 435 | 7,961 / 2,384 |

**435/748 factorial links (58.16%) connect different written rhythms.** All
10,345 linked event pairs in that cohort are scorable, so no unknown truth is
hidden in this count. Matching pitch/quarter inventories is insufficient to
certify matching within-quarter rhythm. The original reused controls did not
expose this failure because their linked blocks really were identical.

The all-phase nearest-tie rule separately excludes 93 reused and 288 factorial
blocks; the original protocol already disclosed this behavior for clean
offbeat observations. The result does not justify silently relaxing the rule.
Boundary membership, correspondence and the strength of a repeat preference
need separate evaluation.

### Identical observations with different written truth

All four observational pairs retain identical inputs and complete predictions
within each pair. The four old controls remain abstained under the primary arm,
with both interpretations retained per pair. The four new changing-expression
controls also remain abstained, but only one of the two written interpretations
per pair remains in the joint candidate pool. Thus abstention does not guarantee
that the correct interpretation is available. A repeat prior restricted to the
original local candidate pool cannot restore a truth excluded by that pool.

## 3. Verification and permanent evidence

The exact failed and successful ZIPs are retained alongside the original
[model audit](receipts/repeat-context-model-audit-43256776331.json) and
[source audit](receipts/repeat-context-source-audit-43256776331.json).
Those original audits cover predictions and source interpretation, not the
failed run's nonexistent final evaluation. The recovery's input/prediction
identity chain connects them to the completed report without rewriting their
scope.

The post-run checks add independently implemented evaluation to the existing
model/source identity chain:

| Audit | Actual coverage | Result |
| --- | --- | --- |
| [Recovery and authored evaluation](receipts/repeat-context-recovery-evaluation-audit-43261359821.json) | All 1,520 original/recovery ledgers; 1,512 authored input/prediction replays; independent full-score, per-hit, joint-path, false-link, family and pair arithmetic | 248,070 checks passed; maximum numeric difference 0 |
| [Public real arithmetic and source continuity](receipts/repeat-context-real-receipt-audit-43261359821.json) | Prior source hashes and canonical denominators; all real reference-mask aggregates and transitions; public link/eligibility partitions | 36,971 checks passed |
| [Actual source replay and independent evaluation](receipts/repeat-context-real-replay-audit-43261359821.json) | 49 exact source files; eight original input/prediction hashes; canonical truth hashes; independent target, joint-path and all same-score pair decisions | 5,259 checks passed; no unverified pair categories |
| [Audit negative controls](receipts/repeat-context-recovery-audit-negatives-43261359821.json) | One-byte ZIP corruption and a changed correct-count summary | Both rejected; original artifact unchanged |

The authored audit reuses the frozen generators and selector, whose exact
outputs are tied to the earlier independent model implementation by hashes.
Its evaluation code does not call the study's evaluator, outcome counters,
joint-truth helper or link-truth scorer. This is independent evaluation of
reproduced predictions, not a newly implemented independent model or a new
accuracy sample. The public real-mask audit alone cannot distinguish two
different wrong ticks from the same wrong tick; its receipt states that scope
limit explicitly.

The additional actual replay closes that specific limit. It reconstructs all
eight predictions from the 16 input-only MIDI/beat members, verifies complete
input/prediction hashes, and only then loads the remaining reference files.
Frozen source adapters and selector are reused, with canonical map, target and
input-link hashes tied to the prior independent source audit. Separate scoring
code rejudges every target mask, joint-path truth check and pair category from
the reproduced pitch/ticks, including the one reused and nine additional
both-wrong reference pairs. All agree with the official report. The final
audit verifies 49 cached files / 3,985,273 bytes and correctly reports zero
network transfers for that cached replay. This adds verification, not a new
data cohort.

The permanent [recovery audit script](../../scripts/audit_repeat_context_recovery.py)
supports an offline identity/aggregation check and an optional full authored
replay. For example, from the repository root:

```bash
python scripts/audit_repeat_context_recovery.py \
  --replay-authored --work /tmp/repeat-context-private \
  --output /tmp/repeat-context-evaluation-audit.json
```

The [real public-receipt script](../../scripts/audit_repeat_context_real_receipt.py)
accepts the extracted `report.json` and the original committed source-audit JSON.
The [actual replay script](../../scripts/audit_repeat_context_real_replay.py)
additionally needs Python 3.12, `mido==1.3.3` and an outside-repository `--cache`.
It verifies cached source identities or downloads only the pinned original
members when missing. Its `--report`, `--source-audit` and `--output` arguments
make the input and derived receipt locations explicit.
Replay work remains outside the repository and public receipts contain no
musical arrays. All **35 recovery-measured files** remain byte-identical; of the
30 original measured paths, only the recovery's previously declared research
test-inventory extension differs. Final-head and actual-main checks are
recorded on [PR #287](https://github.com/JDeun/audio-score-tool/pull/287).
A result-only commit does not rerun or retune the original experiment.
Repository tests verify software contracts, not musical accuracy or product
acceptance.

## 4. Next work under #281

The next bounded experiment should separate two failures before adding a
stronger prior:

1. **Boundary membership:** represent plausible early/late attacks around a bar
   boundary while retaining their original timing. Compare coverage and wrong
   memberships against the frozen hard observed-block baseline. Do not silently
   turn legitimate anticipations into downbeats or discard boundary cases.
2. **Rhythm correspondence:** test timing-compatible repeat hypotheses with an
   explicit different-rhythm alternative. Keep equal-inventory AAAA, ABAB,
   AAAB and ABCD controls and the identical-observation counterfactuals, and
   report false links and lost joint truth alongside correct gains.
3. **Actual relevance:** retain all eight current performances as development
   evidence. A claim about human four-on-the-floor recovery needs multiple
   performances of a verified identical drum score and a different-score
   control; the current piano pairs do not establish it.

Freeze the next model, population, denominators and failure policy before its
first outcome. Timing-only and velocity/accent evidence should remain separate
arms if strength information is introduced. The present study supplies clocks
and score correspondence and does not evaluate inferred audio beats, duration,
rests, voices, engraving, human edit cost or perceived naturalness.
