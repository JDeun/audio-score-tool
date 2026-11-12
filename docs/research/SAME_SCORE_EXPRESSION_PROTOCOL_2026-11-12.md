# Same written score across expressive performances — preregistered CPU study

Execution issue [#284](https://github.com/JDeun/audio-score-tool/issues/284), under
[#281](https://github.com/JDeun/audio-score-tool/issues/281). Base actual main:
`61b77bec85d60733aac5af751ae272fa33e60daf`.

**Commit the source manifest, selector, evaluator, runner, tests and this protocol
before the first cohort inference.** The original Actions study runs once on the
frozen PR head. Report every failure, regression, ambiguity and unsupported case;
do not tune the model or replace performances after reading outcomes. Completed
research evidence may be merged after its audits and final-head/main checks.
This does not activate a product correction.

## Question and populations

Can different actual performances of one identical symbolic score recover the
same correct canonical onset attacks, while preserving the original performance?
Does a phase model that changes within a take help relative to the frozen global
phase and straight controls without conflating different written rhythms?

The primary target is **canonical pitch/onset attacks**. Report onset-only
correctness separately from pitch mismatches. Written durations, rests, voice
assignment, tie spelling in an exporter, full engraving, audio transcription,
acoustic beat recovery and perceived performance naturalness are not evaluated.
MIDI velocity and controllers are preserved, but velocity does not enter this
selector's fitting objective. This is not a test of whether accent modelling helps.

Keep the two populations separate; do not pool their accuracy denominators:

| Scope | Fixed cases | Purpose |
| --- | ---: | --- |
| `synthetic_exact_onsets` | 484: `syn001` through `syn484` | Reuse 480 authored cases and four identical-observation counterfactuals from #283 as development and regression controls. |
| `real_same_score` | 4: `nasap001` through `nasap004` | Two actual performances of each of two byte-identified MusicXML scores. |
| Total execution population | **488** | Every input is predicted and privately saved before evaluation loaders run. |

The old generator and core remain byte-pinned and unchanged. The wrapper maps
its three instrument categories to MIDI pitches 36/38/42 without changing onset,
velocity, order or length. It assigns opaque new case IDs. The 480 main controls
remain eight two-bar 4/4 families × five expression profiles × four takes × three
tempo replicas. Four profiles use the model's stationary phase vocabulary
(384 cases); the changing profile switches between 0.56 and 0.70 (96 cases).
This stress changes both stationarity and vocabulary support, so it cannot isolate
the two causes of failure. Tempo replicas share expression and are dependent.
The four counterfactuals remain two identical-input/different-target pairs,
reported separately from the 480 main cases.

The generator necessarily constructs its fixed authored truth internally. Input
preparation does not read or return that truth; the selector receives only the
four event fields below. The synthetic evaluation loader reconstructs the seeded
truth only after all predictions are saved. These are previously seen controls,
not a new holdout. The nASAP cohort is also development evidence: BWV848 was
previously inspected for schema, and only two works are included.

## Fixed real sources and selection

Use official [CPJKU/asap-dataset](https://github.com/CPJKU/asap-dataset/tree/4097b45757bed854818cf87e77b92323ebf90615)
at revision `4097b45757bed854818cf87e77b92323ebf90615`. The
[source manifest](../../scripts/nasap_same_score_manifest.json) pins every path,
byte count and SHA256, metadata identity, parser dependency and case order.
Metadata Git blob: `f9b655ca92b3d88febab09763e7ed3b74c2c7878`;
metadata SHA256: `5c6622cae9ae34643fc5b35150de5e2891fd8ffbddd1fd579fa6b984014e6924`.
Manifest SHA256:
`27c576542fef26dbca605db4a9f938cc00451702b2c7f441aa84013fe3496239`.

| Case | Canonical family | Actual performance | Shared XML |
| --- | --- | --- | --- |
| `nasap001` | `score001` | Denisova06M | `Bach/Fugue/bwv_848/xml_score.musicxml` |
| `nasap002` | `score001` | Lee01M | Same BWV848 XML |
| `nasap003` | `score002` | LuA01M | `Bach/Fugue/bwv_854/xml_score.musicxml` |
| `nasap004` | `score002` | MiyashitaM01M | Same BWV854 XML |

BWV848 and its two performances are the already disclosed mandatory admission
pair. For the distinct-score control, consider robust-alignment Bach/Fugue groups
with at least two distinct performance paths, sort their shared XML paths, and
choose the first path lexicographically after BWV848. Choose that group's first
two MIDI paths lexicographically. This yields BWV854/LuA01M/MiyashitaM01M.
BWV846 Fugue has only one performance attached to its exact XML and cannot supply
the required pair. The metadata rule is reverified during evaluation. No
replacement is made if admission fails. A robust-alignment metadata flag is not
independent certification that every published correspondence is correct.

Attribution: Foscarin et al., ASAP, ISMIR 2020; Peter et al., Automatic Note-Level
Score-to-Performance Alignments in the ASAP Dataset, TISMIR 2023,
[doi:10.5334/tismir.149](https://doi.org/10.5334/tismir.149). Source license:
CC BY-NC-SA 4.0. No original musical data is bundled into product or public
artifacts, and this research is not commercial-use clearance. Draft #236 remains
outside the study.

### Acquisition ordering and budgets

Exactly **25 unique source files / 2,241,212 bytes** are declared. Each file is
bounded by its exact expected bytes and SHA256, under a 4,000,000-byte absolute
per-file limit. Requests are restricted to the pinned official HTTPS revision;
redirects, wrong lengths/digests, unsafe paths and linked cache files fail closed.

1. Input preparation reads only four original performance MIDIs and four
   performance beat TSVs: **8 files / 48,459 bytes** on a cold cache. It does not
   read actual MusicXML, score annotations, metadata CSV, part/ppart CSV or note
   alignment semantics.
2. After all 488 predictions and preservation checks, the evaluation loader
   validates those eight cached files again and reads the remaining **17 files /
   2,192,753 bytes**: shared XML/score annotations, individual part/ppart/alignment
   files and metadata. All 25 file identities must agree with the manifest.

Each stage reports its own actual HTTP, byte and cache counters. Sum the stages
for the real acquisition total; do not double-count validation of cached input
files as a second transfer. The combined cold bounds are **25 requests and
2,241,212 bytes**. Original source files stay in private work storage.

## Input clock, source admission and fixed window

Decode original MIDI event time through its actual tempo map into seconds,
retaining attack identity, pitch, onset, offset, velocity and available controller
information privately. The MIDI PPQN and a single encoded 120 BPM are a timebase,
not the musical score-quarter clock. Key releases and controllers are recorded
but do not enter onset inference.

Provide the author's performance beat/downbeat annotation clock explicitly.
Require finite strictly increasing times, supported `b`/`db` labels, constant 4/4,
consistent downbeat phase, and sufficient clock support. The first annotated
downbeat is input quarter **0**. Interpolate linearly between supplied adjacent
beat times; do not extrapolate. Keep **all original positive-velocity note-ons in
[0,32)**, the first eight supplied 4/4 bars. Selection uses only observed onset
and this fixed clock, not alignment, target membership, pitch or expected success.
Report events before and at/after the window separately.

The inference call is exactly `infer_performance(events, length_q)`. Events are
immutable `OnsetEvent(event_id, pitch, onset_q, velocity)` values, and real
`length_q` is 32. No score ID, target, XML note ID, voice, grouping, filename,
composer, performer label or score-aware CSV column is passed. Local block indices
are derived from observed quarter time. Synthetic events near an outer boundary
retain their original time; only the block index is clamped to the declared span.

Actual evaluation, after prediction freezing, verifies that this supplied origin
corresponds to **XML score quarter 4**, so the canonical target window is **[4,36)**.
The author `last_beat`/`last_beat_ref` fields and score annotations verify this
origin only in the evaluation loader. They do not establish or adjust the
predictor's input origin. If this correspondence fails, preserve a source failure
instead of searching for a better offset or window.

The unchanged parser binds XML attacks to the complete part.csv map, requiring
exact onset, duration and pitch agreement. Tied continuations belong to their
original attack; same-pitch reattacks remain distinct. Grace identities are
retained separately. This trial supports the frozen parser's constant full 4/4
structure and occurrence suffix `-1`; explicit repeats, unsupported pickups,
malformed ties, duplicate occurrences or unmatched XML/CSV semantics are admission
failures. Verify identical canonical maps within each shared-XML pair and distinct
maps for the two different scores. These checks verify publisher/source
consistency, not independent human annotation accuracy.

Alignment binding uses original track/channel/pitch and onset identity with the
frozen source tolerances (1e-7 seconds for MIDI onset identity; 1e-4 seconds for
author CSV/beat consistency). Preserve score-side coverage classes `observed`,
`deletion`, `outside_input_window`, `ambiguous`, `unsupported_alignment` and every
input-side class: ordinary target, grace target, insertion, matched outside the
target window, or unsupported. Do not choose only the observed intersection.
These are source-identity tolerances, not widened scoring gates.

### Source-admission counts known before model inference

Source-only admission established the following fixed-window bookkeeping; it did
not execute the rhythm selector or inspect correctness outcomes:

| Case | Original input attacks | Ordinary targets | Observed ordinary targets | Unobserved ordinary targets |
| --- | ---: | ---: | ---: | --- |
| `nasap001` | 180 | 180 | 179 | 1 outside input window |
| `nasap002` | 183 | 180 | 179 | 1 outside input window |
| `nasap003` | 213 | 211 | 210 | 1 deletion |
| `nasap004` | 213 | 211 | 209 | 2 deletions |
| Total | **789** | **782** | **777** | **5** |

The input inventory is 777 ordinary-target observations + 2 grace observations +
5 insertions + 5 observations matched outside the target window. Grace is outside
the declared ordinary-onset primary metric but remains in inference and coverage.
The 782 ordinary targets include all five unobserved targets. Their corresponding
same-score reference-pair denominator is **391 canonical occurrences**: 180 for
BWV848 and 211 for BWV854. This is not an observed-intersection denominator.

The 5 insertions, 2 grace observations and 5 outside-target observations are not
precision errors in the reference-conditioned ordinary accuracy denominator.
Consequently this accuracy is not full AMT precision or full-notation quality.
They still affect the fits and strict full-input sequence because no attacks are
removed. The different observed attack counts also constrain strict comparisons:
BWV848's 180/183 inventories cannot yield equal count-preserving full signatures;
all four different-score performance pairs have 180 or 183 versus 213 attacks,
so event count alone separates them. Treat these strict-signature comparisons as
inventory diagnostics, not proof of rhythm discrimination or failure to interpret
the same underlying score.

## Six frozen inference arms

All arms use the same original observations and Q12 lattice. Within each quarter,
allowed ticks are `{0,3,4,6,8,9}`; only positions inside the declared span exist.
No target-induced lattice expansion is allowed. Four phase hypotheses are fixed:
`1/2`, `3/5`, `2/3`, `3/4`. A piecewise-linear within-quarter warp fixes integer
beat anchors and moves the half-quarter point to the phase. It transforms the
other lattice positions too, including thirds; it is not a universal swing rule.

| Arm | Phase trajectory | Switch cost (quarter squared) | Residual gate (quarter) |
| --- | --- | ---: | ---: |
| `straight_narrow` | Phase 1/2 only | Switching forbidden | 0.08 |
| `straight_wide` | Phase 1/2 only | Switching forbidden | 0.18 |
| `global_phase` | One of the four phases for the entire take | Switching forbidden | 0.08 |
| `local_raw` | One phase per fixed four-quarter block | 0 | 0.08 |
| **`local_switch005` — primary** | Same local blocks | **0.0025** | 0.08 |
| `local_switch010` — sensitivity control | Same local blocks | 0.01 | 0.08 |

The switch costs are squared 0.05/0.10-quarter scales; the arm suffixes are not
additional residual thresholds. No fitting of these costs from this cohort is
allowed. Compare primary local against both straight-narrow and global phase;
report all six arms, including reversals and the sensitivity control.

For each phase, fit every original event to its nearest rendered lattice position,
retaining exact nearest-position ties within numeric epsilon 1e-12. Pitch and
velocity are preserved, not optimized. Partition events into fixed four-quarter
blocks by observed onset. This is supplied-coordinate partitioning, not inferred
meter, voices or phrase structure. Empty blocks remain represented.

The layered four-state dynamic program minimizes
`(sum squared onset residuals + switch_cost × number of phase changes) / N`,
where N is every input attack in the take. Exact forward/backward min-marginals
retain every block state lying on some complete path within the best unnormalized
cost plus `N × (1e-4 + 1e-12)`. Tie-breaking of a displayed best path is deterministic;
it does not erase other retained states. The margin is a fixed cost tolerance,
not calibrated confidence. This model does not infer continuous local tempo;
beat-tempo variation has already been absorbed into the supplied annotation clock.

### Per-event diagnostics versus strict full-input decisions

The diagnostic graph uses all attacks without a maximum-residual filter. For each
event, union the candidate ticks from retained block states whose residual for
that event passes the arm's gate. One tick is a diagnostic decision; more than
one is ambiguous; none is residual-rejected. Record same-pitch/same-tick diagnostic
collisions separately. Individual decisions can pass even when another attack
fails or when no jointly valid full-input assignment exists.

The strict graph admits a block state only when every event in that block passes
the residual gate. It uses the same frozen cost budget as the diagnostic graph,
not a newly relaxed budget after filtering. A strict full-input decision requires
a feasible retained complete path, a unique candidate tick for every original
event, and no same-pitch/same-tick collision. Otherwise preserve rejection,
ambiguity or collision. The selected signature is the multiset of pitch/tick
pairs, without source event IDs. Equal signatures are not correctness evidence
by themselves, especially under the inventory limitations above.

A union of per-event candidate ticks is **not** a Cartesian set of jointly
possible scores. Evaluation-only truth membership runs a constrained DP over the
saved graph, requiring target-compatible states and a path within the original
cost budget. It never supplies truth back to inference. For real data the
constraint uses only observed ordinary targets: deletion, outside-window and
unsupported references have no input event to constrain. Report this explicitly
as conditional observed-target path availability. It cannot establish full-score
coverage or validate extra attacks, grace interpretation, collisions or spelling.
Empty constraints have undefined availability rather than automatic success.

## Evaluation and retained denominators

For each ordinary canonical target, convert its relative quarter onset to the
fixed lattice only if representation error is at most 1e-7 and the tick is in
the declared vocabulary. Unsupported targets remain in the complete denominator.
Correctness requires the selected exact target tick and pitch; onset-only
correctness is also reported. There is no musical timing tolerance around the
reference target. Distinguish `correct`, `wrong`, `abstained` and `unobserved`.
Report lattice support, pitch mismatches, diagnostic collisions, candidate truth
inclusion, and strict full-input coverage as separate quantities.

For actual performances report all 782 ordinary target instances, per-case and
per-score results, target-weighted totals and the equal-score mean. Record paired
correctness gains and losses against straight-narrow and global phase on identical
reference identities. For each of the 391 same-score canonical reference pairs,
retain exactly one status: same correct, same wrong pitch/tick, disagreement,
abstention in either take, or unobserved in either take. Preserve all six actual
performance pairs (two same-score, four different-score) for the bounded strict
signature/inventory diagnostic. Do not count shared abstention as equal recovery.

Use canonical-reference hashes and deterministic ordering to publish compact
per-reference correctness/coverage masks and same-score paired masks. Include a
legend so independent auditors can reconstruct denominators, paired changes and
counts. Never publish raw source pitch/time arrays or full prediction assignments.

For the reused synthetic controls report main-480 full-score correctness, wrong
decisions and abstentions, per-event diagnostics, candidate versus joint-path
truth availability, profile/regime breakdowns, gains/losses and family stability.
Keep the four identifiability controls separate. Report same-family equality,
different-family collisions and stable-wrong families together. The old
always-four-on-the-floor control illustrates how equality can coexist with wrong
notation. The real constant control always emits 32 C4 quarter-note attacks,
independent of input, so it collapses both same- and different-score pairs. It is
an intentionally inventory-ignoring collapse control, not a valid preserving
competitor or a notation-accuracy result.

No p-values or independent-sample confidence intervals are planned. Takes,
tempo replicas, notes and reference pairs are dependent. Any gain is conditional
on the supplied clock, source alignment, fixed lattice and this development
population. Full strict equality is not required for a correct diagnostic note,
and diagnostic gains do not establish a complete recovered score.

## Execution, preservation and completion

Use the new CPU Actions workflow with Ubuntu 24.04, Python 3.12, mido 1.3.3,
pytest 8.4.2 and Ruff 0.16.6. Inference/evaluation are standard-library code.
Limit the job to 15 minutes and two CPU threads; use no audio, model downloads,
training, neural inference, GPU or external model credentials. Contents permission
is read-only and checkout does not persist credentials.

Trigger only on opening/reopening the designated research PR or explicit dispatch.
Result-only synchronize events and main pushes must not rerun the scientific
study. New tests join the explicit research inventory; product dependencies and
old frozen scientific files are unchanged. Before freezing, execute only small,
self-contained contracts and source-admission bookkeeping. Do not execute the
488-case selector/evaluator population to preview results or choose parameters.

The runner records source head, actual checkout SHA/tree/parents, clean state,
runtime, run/attempt and all **18 measured paths**: 12 new/source-manifest/test/
workflow/protocol/inventory paths and six literal byte-pinned inherited modules.
The inherited modules are the old generator/core and the four source-parser
modules; their hashes are fixed from the declared actual main before runtime.

Create fresh separate private work and public-output paths outside the repository.
Write the fixed 488-row plan before source preparation. Save each full input and
six-arm prediction privately, preserving event identity/pitch/onset/velocity and
checking both originals and the inference copy for mutation. Store exact-file
hashes as `input_file_sha256` and `prediction_file_sha256`; compact semantic
fingerprints use distinct names. Only after every prediction is saved may either
evaluation loader run. Recheck frozen inputs/predictions after label loading and
evaluation, and preserve the whole planned population on failure.

Source-byte/parser mismatches, failed input or evaluation admission, inference
exceptions, mutation, missing scope, malformed public output or budget violations
produce a failed/incomplete receipt with **null summary**. Expected unsupported
notes and unobserved references inside a successfully admitted case remain in
its coverage ledger and denominator; they are not operational success exclusions.
Early workflow/provenance failures preserve expected 484/4/488 counts even if
individual rows could not yet be initialized. Exception details remain private.

Upload only bounded `report.json` (8 MB maximum; evaluation component 7 MB maximum).
Full prediction files are limited to 2 MB each and 256 MB combined. Preserve the
exact Actions ZIP beyond the service's 14-day retention, with source/model/
arithmetic audits and a result document. Independent replay of the frozen model
for audit must not tune it or replace the original attempt. Verify the final
result head and actual merged main, including normal product/research/frontend,
Tauri, stress/soak and security/compatibility gates. Completion means the declared
study and verification were carried through, not that common-score recovery was
solved. Keep #281 open for the remaining scientific and product requirements.
