# Repeated rhythm context across expressive performances — frozen CPU protocol

Execution [#286](https://github.com/JDeun/audio-score-tool/issues/286), continuing
[#281](https://github.com/JDeun/audio-score-tool/issues/281) after
[#284](https://github.com/JDeun/audio-score-tool/issues/284) /
[#285](https://github.com/JDeun/audio-score-tool/pull/285). Base actual main:
`b7561cc64e2a595ba9d99cbaf1cf2170f00ae2ee`.
The document date uses Asia/Seoul; the corresponding preparation began on
2026-11-12 UTC.

**Commit all scientific code, manifests, tests, workflow and this protocol before
the first cohort prediction.** Small invented contracts and declared source
admission are allowed before freezing. Run the original study once on the frozen
head, retain failures and every planned case, and make no outcome-driven changes
to thresholds, population or model. Append results and independently check the
original artifact before merging. This is research evidence; it does not activate
a product correction. Unrelated draft #236 is outside this work.

## Question and primary comparison

Can input-derived repeated rhythm hypotheses resolve the local model's ambiguity
while preserving different written rhythms? The previous real result lost 31
correct ordinary attacks to abstention and gained none. Its synthetic changing
condition also used phases outside the vocabulary, confounding two causes.
This study tests repeat context and separates those expression dimensions.

The primary method is **`repeat_soft010`**, compared with the unchanged
**`local_switch005`**. Straight, global phase, weaker soft repeat and a hard repeat
prior provide controls. Correctness means canonical **pitch/onset attacks**, with
onset-only correctness separately reported. It does not mean written durations,
rests, voices, engraving, audio transcription or perceived naturalness. Original
velocities and attack times remain intact. Velocity is not used for selection, so
no claim about an accent model follows from this study.

Keep all four cohorts separate. Do not pool their accuracy denominators.

| Cohort | Fixed IDs and count | Purpose |
| --- | --- | --- |
| `reused_authored` | `syn001`–`syn484`, 484 | Exact old 480 authored cases and four observational counterfactuals. |
| `factorial_authored` | `fac0001`–`fac1028`, 1,028 | 1,024 balanced controls and four new counterfactuals. |
| `reused_real` | `nasap001`–`nasap004`, 4 | Exact BWV848/BWV854 inputs from #285. |
| `additional_real` | `nasap005`–`nasap008`, 4 | Two newly declared same-XML works with two takes each. |
| Execution total | **1,520** | All predictions saved before any evaluation loader. |

The original 17 inherited scientific files remain byte-pinned. The prior
research-test inventory is recorded by its historical SHA256
`18fe7728c15a8bdb06da0ea32bce99f6b708f24514c80859e2a0bbc858f04a36`;
the expanded current inventory is measured separately. The exact prior ZIP is
also pinned. Its report is opened only during post-prediction evaluation, when
all 488 reused input fingerprints and complete original six-arm prediction
fingerprints must match. Public prior findings are already development evidence.

## Authored factorial and counterfactuals

The main design has eight base patterns × four written contexts × two phase
stationarity conditions × two vocabulary conditions × two balanced trajectories
× four takes = **1,024**. Each case is four 4/4 bars, 16 quarters and 56 attacks:
16 kick, eight snare and 32 closed-hat. Nominal tempo is 120 BPM with a supplied
exact generated beat clock; there are no extra tempo replicas.

Use the first bar of the old eight `_written` patterns as A. Form B/C/D by rotating
each nonzero within-quarter tick by one/two/three positions in the declared cycle
`(3,4,6,8,9)`; zero anchors stay zero. This preserves pitch/quarter inventories,
while changing canonical rhythm. The four written contexts are AAAA, ABAB, AAAB
and ABCD. There are 32 distinct canonical families and 32 expression versions per
family. Different-context controls are essential: equal coarse inventories do
not certify a repeated score.

| Factor | Level 1 | Level 2 |
| --- | --- | --- |
| Phase stationarity | Constant A or constant B | ABAB or BABA by four-quarter block |
| Phase vocabulary | A=1/2, B=2/3 | A=11/20, B=43/60 |

Both phase pairs have separation 1/6. Across the two trajectory variants,
stationary and changing conditions expose each phase for the same number of
blocks. All canonical targets use the supported Q12 lattice; outside-vocabulary
here describes performed phase, not unsupported written targets.

Take0 has zero jitter and velocity100. Takes1/2/3 use the declared old-style
instrument push/pull offsets, uniform jitter amplitudes .008/.012/.020 quarter,
accent/reverse-accent/random velocities, and an additional slow .012-quarter
sinusoid in take3. Nonzero takes have an 8% sinusoidal variation in the supplied
beat durations. The exact values and conversion are in the fixed generator.
Master seed is `repeat-context-factorial-v1-20261113`; a seed depends only on
trajectory variant and take, not stationarity, vocabulary, base pattern or written
context. Thus the two factorial axes share their random draws. These common
random numbers, overlapping truth and paired references make cases dependent.

New counterfactual pairs compare repeated eighth-note AAAA with alternating
straight/swing expression against an alternating written rhythm played straight.
One uses 2/3 phase and literal triplet-long hats; the other uses 3/4 phase and
literal dotted hats. Each pair has exactly identical observed attacks and
velocities, but different written truth. They are outside the 1,024 main cases.
If a repeat prior chooses one latent score, the other interpretation can become
wrong. Identical-input controls must have identical complete predictions; truth
is never passed to inference. The old four controls are reported separately too.

Generating inputs necessarily constructs authored latent positions. Preparation
does not read or return the evaluation object. A later loader regenerates truth
from the fixed seed after every prediction is saved. These are new development
controls, not an independent human-performance validation cohort.

## Additional actual sources and source admission

Use the official [CPJKU/asap-dataset revision](https://github.com/CPJKU/asap-dataset/tree/4097b45757bed854818cf87e77b92323ebf90615)
`4097b45757bed854818cf87e77b92323ebf90615`. Metadata SHA256 is
`5c6622cae9ae34643fc5b35150de5e2891fd8ffbddd1fd579fa6b984014e6924`.
The [new manifest](../../scripts/nasap_repeat_context_manifest.json) pins exact
source paths, byte counts, hashes, selection receipt and parser contract.
Its SHA256 is `87544fc4e8774a54f63cf49075ddec077171745a12eb98efd43edaa7b97669ba`.

Before reading musical source, select the next two robust-alignment Bach/Fugue
groups with at least two performances of one exact XML, lexicographically after
the previous BWV854 path. Choose each group's first two MIDI paths. No replacement
is allowed. Both selected works are absent from the prior 12 development / 24
joint-holdout / BWV846-and-848 schema lists; this limited check is not proof of an
unseen population. Source admission happens before outcomes and is disclosed.

| Input | Score family | Work / performance |
| --- | --- | --- |
| `nasap005` | `score003` | BWV857 / Bult-ItoS02M |
| `nasap006` | `score003` | BWV857 / Lan01M |
| `nasap007` | `score004` | BWV858 / VuV01M |
| `nasap008` | `score004` | BWV858 / Zhang01M |

Like the old cohort, input zero is the first annotated performance downbeat;
the input interval is [0,32) quarters. Evaluation uses the corresponding XML
interval [4,36). The first downbeat is annotation index3 in all four new takes.
XML meter is 4/4, windows are available, and no explicit repeat is present. MIDI's
tempo value is a time encoding, not a measured musical tempo. Lan's metadata end
field is not treated as the full MIDI endpoint; source annotations and the MIDI
are checked directly. All original MIDI attacks, velocities, offsets/controllers
and input-file hashes remain preserved privately.

Admission predicts no model outcome. The new inputs have **605 attacks**
(131/112/181/181), **596 ordinary targets** (106/106/192/192), zero grace targets,
571 observed ordinary targets, 23 deletions and two outside-input targets. Input
classification is 571 ordinary +29 alignment insertions +five matched
outside-target attacks. Insertions can include ornaments; they are not
automatically performer mistakes. All 298 canonical reference pairs remain in the
same-score paired denominator. The old cohort remains 789 attacks /782 ordinary
targets /two grace targets, with five ordinary targets unobserved.

### Explicit CSV serialization contract

Old strict XML/CSV admission fails both BWV858 takes because six tuplet notes near
XML quarter87 have decimal CSV representations different from exact XML fractions.
The discrepancies are outside the chosen [4,36) window. This failure is retained
and the old adapter is unchanged.

The new adapter uses XML `Fraction` values as canonical truth. Every full-score
CSV onset/duration quarter and beat scalar must either equal its XML fraction
exactly or pack to identical IEEE754 binary32 bytes. This is a discrete format
identity rule; no absolute or relative musical tolerance is fitted. IDs, pitches,
voice, tie continuity, score clock and correspondence checks remain exact under
their existing contracts. The rule applies to all rows, not only discrepant IDs
or selected-window targets.

Declared source admission checks 17,992 timing scalars: 17,952 exact and 40
binary32-admitted (20 per BWV858 take). Maximum absolute decimal discrepancy is
2.666666666666667e-6 quarter; all 40 are outside evaluation. Record every mismatch,
original strict failure and exact canonical hash. Do not alter written truth.

Attribution: Foscarin et al., ASAP, ISMIR2020; Peter et al., Automatic Note-Level
Score-to-Performance Alignments in the ASAP Dataset, TISMIR2023,
[doi:10.5334/tismir.149](https://doi.org/10.5334/tismir.149). Source license is
CC BY-NC-SA4.0. Only derived research metadata is published; no original musical
files are bundled or commercial-use clearance implied.

## Input-only repeat model

Inference receives only immutable `(event_id,pitch,onset_q,velocity)` attacks and
the supplied length. It receives no case ID, filenames, score/group identities,
reference notes, voice, performed phase labels or true repeat labels.
Retain the old Q12 within-quarter positions `(0,3,4,6,8,9)`, phase hypotheses
`(1/2,3/5,2/3,3/4)`, fixed four-quarter blocks, .08-quarter residual gate,
.0025-quarter-squared phase-switch cost, and 1e-4-quarter-squared per-event
near-optimal margin. Numeric epsilon is1e-12. At most eight blocks /32quarters
permit exact enumeration of all 4^B phase sequences. Empty blocks are retained.

1. A block can supply repeat evidence only if complete, with at least four attacks
   in at least two quarters. Any nearest-candidate tie in any phase excludes the
   whole block from linking; events remain in inference and evaluation.
2. All four hypotheses must place each event in the same relative canonical
   quarter, inside its observed block. Same-pitch attacks whose observed onsets
   are indistinguishable within numeric epsilon also exclude the block.
3. The block skeleton is the count of attacks per relative quarter and pitch.
   A block links only to the previous eligible occurrence of the identical
   skeleton. Within each quarter/pitch group, observed onset order defines event
   correspondence. There is no pitch transposition, voice oracle or label-based
   pairing.
4. For each linked block pair, phase-state cost is the fraction of corresponding
   events with different relative canonical ticks. Sum that fraction over links
   to obtain R. This prefers equal canonical rhythm, not equal performed phase.

**Known coverage limit before the run:** a clean .5 or2/3 observed offbeat can be
at a nearest tie under the 3/5 hypothesis. Under the fixed all-phase tie rule,
such a block supplies no repeat evidence. This is not changed after seeing model
outputs. Report exclusions and no-link cases, retaining them in every denominator.

Let E0 be summed squared residual plus .0025 for every phase switch. First fix
C0 to paths with E0 no greater than the global minimum E0 + N×(1e-4+1e-12), where N
is all original input attacks. The three repeat arms can only restrict C0.

| Arm | Candidate selection |
| --- | --- |
| `straight_narrow` | Exact old straight baseline. |
| `global_phase` | Exact old global baseline. |
| `local_switch005` | Exact old local baseline, primary comparator. |
| `repeat_soft0025` | Within C0, minimize E0+.0025R and retain within N×(1e-4+1e-12). |
| `repeat_soft010` | **Primary:** within C0, minimize E0+.01R and retain within the same margin. |
| `repeat_hard` | Within C0, retain minimum R within1e-12; strong-prior stress control. |

After these budgets and candidate paths are fixed, apply the full residual gate
without recentering or substituting a higher-cost path. Diagnostic per-event
gates are separate from strict full decisions. A full decision requires all
retained canonical assignments to agree, with no same-pitch/tick collision.
No-link arms reproduce the local baseline exactly. Preserve complete path sets
as private base-four-index bit masks; marginal unions alone are not joint scores.

## Evaluation, execution and failure rules

Report every cohort, case and arm. Authored main outcomes include full correct,
wrong and abstained; per-hit correctness; gains/losses versus all three baselines;
joint truth availability; all-version stable-correct/stable-wrong families;
same-family and different-family decided equality; and an always-four-on-floor
control. Report the 16 factorial context/stationarity/support cells, both trajectory
variants and every take. Identical-observation controls are separate.

Actual outcomes retain ordinary targets whether observed, deleted, outside input
or outside the canonical lattice. Report pitch/onset correctness, onset-only
correctness, wrong decisions, abstentions, unobserved targets, per-score results
and equal-score-weighted rates. Canonical source IDs align same-score references:
both-correct, same-wrong, disagreement, abstention and unobserved. Give gains/losses
and transition counts versus the local baseline. Strict full observed-input hashes
and constant-score collapse are auxiliary: different attack inventories already
separate some real cases, so strict inequality is not independent rhythm evidence.

For repeat links, use evaluation truth only after predictions to count true,
false and unscorable linked event pairs and block links. Partial real ordinary
truth cannot certify a complete repeat. A known difference plus an unknown pair
still falsifies equality. Report link/exclusion coverage and no-link outcomes;
do not select only favorable linked cases. Joint-truth checks use exact saved
path masks and event gates, not products of marginal alternatives. Candidate
truth retention is not a decided score or recovery of missing attacks.

Input acquisition reads only each cohort's original performance MIDI and beat
annotation files. All1,520 predictions and immutable input snapshots are saved,
hashed and checked before loading any synthetic or real evaluation source.
Evaluation loaders run reused authored → factorial authored → reused real →
additional real. Public metadata is bounded and excludes raw sources, attacks,
alignments, canonical target arrays, assignments and candidate masks.

| Resource | Fixed bound / expectation |
| --- | --- |
| Old source cache |25members /2,241,212bytes; input8 /48,459bytes |
| New source cache |25members /2,360,916bytes; input8 /69,674bytes |
| Actual cold-cache acquisition |50HTTPS requests /4,602,128bytes across separate caches |
| Unique declared source set |49members /3,985,273bytes; metadata transferred twice |
| Individual source |Exact pinned length/hash, absolute cap4,000,000bytes |
| Private prediction |4,000,000bytes each;512,000,000bytes total |
| Events |At most10,000per case |
| Evaluation / public report |30,000,000 /32,000,000bytes |
| Metadata component |1,000,000bytes |
| Actions |CPU, Ubuntu24.04, Python3.12,15minutes, two-thread environment limits |
| Dependencies |mido1.3.3, pytest8.4.2, Ruff0.16.6 |

No model downloads, paid APIs, GPU, credentials or silent replacement. Downloads
are pinned official HTTPS paths; redirects, links, wrong size/hash or unsupported
semantics fail closed. A failure in source, preparation, inference, preservation,
evaluation or budget leaves all planned rows and null aggregate summary. Workflow
preparation failure also emits the full planned population. The science workflow
triggers on PR opened/reopened or explicit dispatch, not synchronize or main push.
Verified known-member subsets and actual transfer counters are recorded before
full-coverage validation; missing coverage still fails closed and preserves every
planned row with a null summary.

Retain the exact original ZIP/report, run and checkout identities, file hashes,
source acquisition accounting, immutable input/prediction hashes and all failures.
Independently regenerate model predictions and source/canonical/metric arithmetic
against the original artifact. After appending results, verify final PR head and
actual merged main CI, compatibility/security and required repository checks.
Small contract tests are not model-performance evidence; the original run is.

Only two new real works and 32 authored canonical families are included. Supplied
clocks and correspondences, no accent fitting, conservative repeat coverage,
fixed phase vocabulary, dependent examples, and observational ambiguity remain
material limits regardless of the result. No population confidence interval or
automatic product integration is justified by this bounded study alone.
