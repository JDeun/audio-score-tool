# #265 — frozen joint rhythm decoder on composition-disjoint works

Related #249/#259/#264. Research only. No main/product/default/automatic-score or
other-session edits, new audio inference, models/training, GPU or paid endpoints.
Keep this PR draft; positive conditional note recovery is NOT release approval.

## Decision

The frozen joint decoder's NOTE-recovery improvement reproduces on new
compositions under the SAME privileged structural context. On385 notes in19
admitted voice blocks from7 new works, publisher-sustain input gives117/385
independent ->223/385 joint structure ->289/385 joint+rest cost. The last arm
improves all7 work totals against independent; structure alone improves6 and ties1.
No decoder parameters or parser logic were retuned on the new works.

Rest recovery is still unsafe. Joint+rest cost reduces false rest intervals but
removes one entire quarter-note unit of a true rest. Its exact rest F1 rises due
to fewer false positives, NOT because more true rest boundaries were recovered.
Only8 true rest intervals exist in this admitted subset. Do NOT report75.06% as
whole-score, full-song or audio-to-score accuracy.

Coverage is a major limitation: only7/24 preselected compositions yield admissible
blocks. The other17 remain visible. A successful Actions job does NOT mean all24
compositions were successfully decoded. Do not repair or replace unsupported
sources after looking at results and call this the same frozen validation.

## Provenance and fixed design

- Parent #264 head f70581b72e037e44b156c1863fb8e8938e94341b.
- Previous artifact13911212291 ZIP SHA256
  224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4;
  report SHA256281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59.
- Four inherited source files checked byte-for-byte against that executed artifact:
  nasap_joint_rhythm.py, nasap_keyoff_paired.py, nasap_duration_probe.py,
  audit_nasap_duration_source.py. Same decoder/parser/costs/lattice/evaluator.
- Pinned (n)ASAP revision4097b45757bed854818cf87e77b92323ebf90615.
  Metadata Git blob and previous metadata SHA verified before selection.
- Excluded ALL12 original planned composer/title pairs, including previous failed
  sources, plus shared XML/MIDI-score/folder paths and two schema-inspection works.
  New24 unique compositions selected by the committed hash rule, max3/composer.
  Entire manifest saved before reading new musical content. No replacements.
- Composition-disjoint does not mean performer-disjoint, external-dataset,
  standardized test-split or representative popular-music validation.
- Same annotated beat8..40 window, supported2/4,3/4,4/4; same complete aligned
  two-measure voice/chord blocks, explicit XML occupancy and restricted tie rules.
- EVERY arm receives annotated beat clock, correct quarter unit, bar boundaries,
  reference voice/chord membership and complete aligned note inventory. Actual
  note/rest target times are not passed to the decoder, but admission and context
  are reference-assisted. No automatic voice/beat/AMT inference is claimed.
- All six fixed arms completed on the same19 blocks/385 notes; no unequal-arm
  denominator. The additional silence-occupancy/tie metrics reuse unchanged
  predictions and do not alter the objective.

## Data coverage

24 planned sources ->7 with evaluated blocks,17 not evaluated:
-7 unsupported meter or change under the fixed window rules;
-6 rejected by restricted parser for noncontiguous/unmatched tie;
-1 rejected by parser for duplicate identity/ambiguous tied pitch;
-2 source reads returnHTTP404;
-1 exported input lacks the required last_beat column.
These indicate current source/loader/parser coverage, not proven musical invalidity
or blame assigned to the dataset. No scored-source replacements or parameter fixes.

Across the7 structurally scanned sources:82 voice-block attempts,19 admitted,
45 missing unique performance alignment,9 note/tie crosses outer block edge,
5 explicit voice occupancy not exact,4 fewer than two notes. New candidate ceiling
is385/385 under the local lattice, a reference-assisted availability diagnostic,
not achieved correctness or proof of a globally correct path.

Evaluated sources:7 works by4 composers;6 in4/4 and1 in2/4, NO new3/4 evaluation.
19 correlated two-measure voice blocks,385 unique notes,8 semantic XML rest
intervals in6 blocks;13 blocks have no reference rest. This rest-sparse selection
is unsuitable for strong claims about rest-preserving performance.

## Primary metric: exact written onset AND duration

Inherited1/96-quarter tolerance, same pitches and note identity/count. Micro
weights385 notes equally; macro gives7 source works equal weight.

| Input | Method | Onset correct | Duration correct | BOTH correct | Micro BOTH | Equal-work BOTH |
|---|---|---:|---:|---:|---:|---:|
| CSV sustain | Independent |332|122|117|30.3896%|38.6724%|
| CSV sustain | Joint structure |349|234|223|57.9221%|67.0238%|
| CSV sustain | Joint + rest cost |351|298|289|75.0649%|81.9411%|
| Key release | Independent |332|126|113|29.3506%|32.3492%|
| Key release | Joint structure |333|134|123|31.9481%|34.1902%|
| Key release | Joint + rest cost |344|266|257|66.7532%|72.1735%|

Do not compare these absolute percentages directly to #264's655-note sample;
this is a new, differently admitted set. The fair claim is the WITHIN-set paired
improvement using the frozen methods, not58.17->75.06% from a new algorithm.
No outcome-guided combination of key and sustain inputs was used.

| Comparison | Wrong pairs fixed | Former correct pairs damaged |
|---|---:|---:|
| Sustain structure vs independent |109|3|
| Sustain structure+rest vs independent |179|7|
| Sustain adding rest cost vs structure |70|4|
| Key structure vs independent |16|6|
| Key structure+rest vs independent |154|10|
| Key adding rest cost vs structure |140|6|

Sustain structure improves6 works/ties1. Sustain+rest improves7/7. Key structure
improves2, worsens1, ties4; key+rest improves7/7. This again does not support a
universal switch from sustain to key-release input. Some correct notes are harmed
by every new joint setting even where the aggregate improves.

### Per-work same-note counts (independent / structure / +rest)

| New performance | n | CSV sustain BOTH | Key-release BOTH |
|---|---:|---|---|
| Bach Prelude bwv889 Wang01M |21|15 /15 /20|15 /15 /20|
| Beethoven Sonata24-1 Lou02M |33|25 /26 /30|6 /6 /28|
| Bach Fugue bwv865 Teo01M |73|21 /27 /44|19 /24 /43|
| Beethoven Sonata11-1 DeTurck01 |87|28 /36 /68|28 /36 /68|
| Chopin Etude op25/11 Tang03 |31|12 /31 /31|9 /9 /24|
| Chopin Etude op10/12 Staupe02 |95|10 /47 /55|26 /23 /46|
| Liszt Transcendental10 SUDBIN02 |45|6 /41 /41|10 /10 /28|

## Rests: lower false positives can hide erasure of real silence

Eight explicit semantic rest intervals, boundaries matched with the inherited
strict tolerance. Adjoining reference rests are treated as equivalent intervals.

| Input/method | Predicted intervals | Exact /8 | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| Sustain independent |131|4|3.05%|50.00%|5.7554%|
| Sustain structure |129|5|3.88%|62.50%|7.2993%|
| Sustain structure+rest |42|4|9.52%|50.00%|16.0000%|
| Key independent |188|4|2.13%|50.00%|4.0816%|
| Key structure |188|4|2.13%|50.00%|4.0816%|
| Key structure+rest |56|4|7.14%|50.00%|12.5000%|

An F1 gain from7.30 to16.00% is NOT recovery of more true rests: exact matches
fall5->4. Fewer false rest intervals improve precision, while recall worsens.
The fixed cost cannot yet be approved as safe automatic rest correction.

### Added silence-occupancy diagnostic

Lengths below are sums over separate VOICE timelines in quarter-note units,
not total seconds of a whole song. True rest length sums to8quarter units.

| Input/method | Predicted rest length | Overlap with true rest | False-rest length | Erased true-rest length |
|---|---:|---:|---:|---:|
| Sustain independent |36.1667|8.0000|28.1667|0.0000|
| Sustain structure |35.7708|8.0000|27.7708|0.0000|
| Sustain structure+rest |23.5417|7.0000|16.5417|1.0000|
| Key independent |54.7500|8.0000|46.7500|0.0000|
| Key structure |54.5208|8.0000|46.5208|0.0000|
| Key structure+rest |28.7917|7.0000|21.7917|1.0000|

Concrete failure: Beethoven Sonata11-1 DeTurck01 blockP1/1/768 has one true
quarter-unit rest. Independent and structure preserve the entire rest and match
its endpoints; the +rest-cost arm predicts NO rest in that block. Both endpoint
representations suffer this loss. This is not merely a few-millisecond boundary
mismatch or an artifact of strict rest F1.

Conversely the same work's blockP1/5/384 contains a four-quarter rest. The rest-cost
arm preserves it and removes extra small gaps. Therefore the cost is sometimes
helpful, but it cannot reliably distinguish unnecessary gaps from required rests.

Structural validity: sustain independent4/19, key independent10/19; joint arms
19/19 each. Full measure sums are guaranteed by constraints, not score accuracy.

## Inner-bar crossing diagnostic

There are only TWO positive crossing notes in the reference. The new confusion
counts avoid being misled by the383 negatives:
- sustain independent:TP1 FP9 FN1 TN374;
- sustain structure:TP1 FP0 FN1 TN383;
- sustain+rest:TP2 FP0 FN0 TN383;
- key independent:TP1 FP1 FN1 TN382;
- key structure:TP1 FP0 FN1 TN383;
- key+rest:TP2 FP0 FN0 TN383.
Two examples cannot validate general tie creation, and no MusicXML exporter or
engraving was tested. Report this only as a small conditional boundary diagnostic.

## Execution and audit

First measured CPU run succeeded:
https://github.com/JDeun/audio-score-tool/actions/runs/43151862920
Job130962690624. Headab7b79c3e62e1c57b66afffc6e086eaead130456;
actual PR merge checkoutea7617f7680ce1ce9d6cce6b8fa7b5d26b40b8b0 (not a main merge).
Python3.11.18; mido1.3.3, pytest8.4.2, ruff0.16.6. pip check, repository-config
lint on the TWO NEW Python files, compile and101 tests(20new+81inherited) passed.
This is not a full product CI or complete inherited-code style-lint claim.
No retries, input replacements, scorer patches or parameter changes after results.

Artifact13913459307 ZIP SHA256
5896bccaca08d3a56958ab7d2236960b96fb2a25a53e1fd1b4554852f2891e3d;
report.json SHA256
337211e9d916af3d006f461422970d62187d6ffaec1f9d63434a4a1d348c6d8f.
Evaluation36.622seconds excluding setup,23,807,070 source bytes on one runner;
these are observations, not production latency guarantees.

Independent receipt audit checked ZIP vs Actions digest, report/code/protocol
hashes, all inherited source/test bytes against the previous executed artifact,
local new-code bytes, prior settings/metadata identity and declared disjoint work
labels/IDs. Recomputed all114 block-arm masks/counts, onset-duration conjunctions,
paired fixes/damage, micro and equal-work values, full/common denominators, exact
rest ratios, silence-overlap identities and positive-crossing confusion totals.
No raw note/XML/MIDI reinference, manual alignment verification, independent
source-note annotation or proof that all same-work aliases in the catalog were
resolved. Per-block rest-overlap totals cannot reconstruct original intervals;
this is outcome arithmetic validation plus unchanged-code evidence.

Only derived counts/masks/hashes and our code/protocol were uploaded, no original
musical notes/XML/MIDI/audio. CC BY-NC-SA4.0 source data, attribution in protocol;
no commercial-use clearance or source-data product bundling implied.

## Next decision

Keep joint structural decoding as a research direction: it now has a repeated
conditional note gain on different compositions with unchanged parameters. Do not
enable current rest-cost correction. Improve rest-preserving objectives on a
separately designated DEVELOPMENT set; do not tune on these validation works and
still call them untouched tests. Repair loader/tie-parser coverage independently
without silently changing this trial's sample. Then remove supplied voice/chord
and clock information one factor at a time, before actual audio/AMT and readable
score or user-editing evaluation. Those experiments have not been run here.
