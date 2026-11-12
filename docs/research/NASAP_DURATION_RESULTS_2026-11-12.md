# #262 — real (n)ASAP duration / pulse-unit pilot and source-semantics audit

Related #259/#261/#249. **No production, main, automatic score, other-session,
GPU, learned-model/training or external credential changes. Keep PR draft.**

## Decision

The simple performed-duration model gives a small improvement over nearest
quantization on the evaluated real piano passages. Against the stronger spelling
baseline, the latent-duration gates add only TWO correct note values. Blind unit
selection does not beat a fixed120QPM preference. Neither result justifies
production adoption or an audio-to-score accuracy claim.

A more important source finding: the publisher-exported `duration_sec` is often
NOT raw key-held duration. The initial protocol sentence calling MIDI duration
a performed key-event duration was too specific and is superseded here. A separate
original-MIDI/CC64 audit demonstrates large pedal-related extensions in the
actual CSV input. Preserve the measured result, but interpret it as prediction
from the PUBLISHED performance-duration representation, not from raw key release.
No predictor, threshold, vocabulary, source selection or measured outcome was
changed after that finding.

## What was evaluated

Official CPJKU/asap-dataset commit4097b45757bed854818cf87e77b92323ebf90615;
metadata Git blobf9b655ca92b3d88febab09763e7ed3b74c2c7878 checked.12 robust
unique compositions chosen with a committed hash rule and max2/composer.
No failed source was replaced. Each candidate window is annotated beat8..40.

-12 planned sources;7 supported/evaluated,5 unavailable under the predeclared
 simple-quarter-meter admission. All5 report unsupported meter/change.
-7 windows:2 in2/4,3 in3/4,2 in4/4;7 distinct compositions,6 composers.
-1,702 performed note observations;1,614 unique pitch-consistent aligned score
 notes used for evaluation. Predictions used ALL1,702 observed notes, not just
 notes later found in the alignment. Unmatched/grace/window-excluded score notes
 are not claimed to have been recovered.
-Annotated variable-tempo beat times AND quarter-coordinate origin provided.
 This is a privileged-clock MIDI-to-written-duration diagnostic, NOT audio beat
 extraction, neural AMT, pitch correction or a wholly automatic score pipeline.
-Written note values loaded after blind predictions. Reference voice membership
 is supplied ONLY in the separately labelled privileged-voice arm.
-Explicit rest symbols, complete voice reconstruction, full bar-sum rhythm DP,
 MusicXML/PDF appearance and human editing effort were NOT evaluated. The voice
 arm uses possible gaps to subsequent performed attacks, not true rest labels.

Publisher data are CC BY-NC-SA4.0; this isolated pilot is research evidence and
not permission to bundle data in a commercial product. Attribution: Foscarin
et al., ASAP, ISMIR2020; Peter et al., Automatic Note-Level Score-to-Performance
Alignments in the ASAP Dataset, TISMIR2023. Publisher alignments are not assumed
infallible. There was no fit/training on this sample; these are newly introduced
research passages, not a representative/pop-music or statistical-significance
benchmark.

## Duration recovery with the correct quarter unit supplied

Exact duration tolerance1/96 quarter (+numerical epsilon). Every method shares
same observed notes, clock and fixed duration vocabulary. Onsets snap once to
1/48 quarter. Score duration must be recovered, not copied from the reference.

| Method | Correct duration /1,614 | Note-weighted accuracy | Passage-equal mean | Fixes vs literal | Former correct damaged |
|---|---:|---:|---:|---:|---:|
| Literal nearest duration |198|12.2677%|14.4316%|0|0|
| Log-duration fit + fixed spelling preference |211|13.0731%|15.5291%|13|0|
| Same + latent performed/written ratio |213|13.1970%|15.8067%|16|1|
| Same + PROVIDED score voice membership |229|14.1884%|17.6686%|32|1|

Articulation versus literal: +15 net notes, +1.3751 percentage points in the
passage-equal mean. Articulation versus spelling control: +2 net notes,
+0.2775pp. Do NOT attribute the entire literal-to-articulation change to the
latent gates. No significance claim, and absolute performance remains poor.
Correct duration increased in6 passages and stayed equal in1 versus literal;
compared with spelling alone some individual passages worsened.

All four methods have524/1,614 onsets within the strict1/96-quarter criterion.
Joint onset+duration counts are84,89,90,98 respectively. This simplistic onset
snapping was not redesigned. These numbers are NOT the previous vocadito audio
note F1 and must not be compared directly to those benchmarks.

### Passage counts (literal / spelling / articulation / privileged voice)

| Performance | Matched notes | Correct written durations |
|---|---:|---|
| Chopin Etudes op25/8 MORET03 |353|14 /14 /14 /14|
| Liszt Transcendental5 KIM_W02 |445|65 /68 /67 /69|
| Bach Prelude bwv862 Song04M |155|38 /43 /45 /47|
| Beethoven Sonata31-1 Zuber04M |278|24 /25 /26 /29|
| Beethoven Sonata5-1 SunD02M |77|16 /17 /18 /25|
| Mozart Sonata11-3 Stahievitch02 |178|16 /17 /17 /19|
| Haydn Sonata50-1 Tak01 |128|25 /27 /26 /26|

Unavailable, NOT replaced: Chopin Ballade1 SINKEV11; Balakirev Islamey Yi04M;
Bach Prelude bwv876 Song01M; Liszt Paganini2 La campanella Seredenko02;
Debussy Reflets dans lEau ParkJH13M. Their exact paths/reasons stay in the receipt.

## Unit-selection result

For each eligible real passage, construct three pulse-coordinate scales from
the annotated clock, with true quarter-per-pulse0.5/1/2. Physical performances
are real but these aliases are controlled variants, not model-estimated pulses.
No reference written values go into automatic selection. No adaptive thresholds.

| Selector | Correct /21 evaluated variants | Wrong /21 | Abstained |
|---|---:|---:|---:|
| Always keep unit1 |7|14|0|
| Fixed broad120QPM preference |15|6|0|
| Duration/spelling cost |11|10|0|
| Duration + PROVIDED voice membership |9|12|0|

21 variants are7 passages x3 scales, NOT21 independent recordings. Original
plan contains36 variants;15 are unavailable with their5 unsupported sources.
Keep-unit1's7/21 follows the balanced construction, not an end-to-end baseline
beat model losing two thirds of its real predictions. Duration cost improves on
that trivial unit convention but does NOT beat the stronger15/21 tempo-prior
control. More voice information does not help this tested unit-scoring rule.

This does not invalidate half/double timeline equivalence. Unit convention
selection, physical timing preservation and readable notation remain separate.

## Important additional semantic audit — original MIDI and sustain pedal

After seeing the initial duration distribution, inspect the input meaning rather
than silently tuning the model. Partitura's documented note-array duration can
use `sound_off` (pedal-adjusted) instead of raw `note_off`:
https://partitura.readthedocs.io/en/latest/_modules/partitura/performance.html

Added a separate audit using original pinned performance MIDI. Reconstruct key
on/off from ticks/tempo independently with mido, inspect CC64 pedal events, and
match CSV onset/pitch/channel uniquely within2ms. ALL1,702 observed notes had
unique original-MIDI onset matches. No original-score duration was used here.

| Check over1,702 observed notes | Count |
|---|---:|
| CSV duration matches raw key-held duration within2ms |795|
| CSV lasts >10ms beyond key release |896|
| CSV matches simple CC64>=64 pedal-release extension within2ms |1,578|
| Same extension with next same-pitch retrigger cap |1,264|

The largest observed CSV-minus-key extension is4.917969seconds. Simple pedal
extension matches92.71% of all CSV notes;124 do not match within2ms, so we have
NOT reconstructed all publisher preprocessing or established every mismatch's
cause. Retrigger-capped treatment fits less well; do not silently substitute it.
A plausible contributor to low scores is the representation mismatch, but no
causal accuracy gain from removing pedal extension was measured in this run.

The original protocol's unqualified key-event-duration description is corrected
by this audit. Use the phrase **publisher-exported performed/sustain duration**
for these measured results. Sustain length, physical key-held length and written
note value are distinct. Do not relabel all early-released notes as rests or all
pedal resonance as long notated notes. A next paired key-off versus sustain-input
study must be declared separately; it was NOT slipped into the present results.

## Execution and verification

- Initial run43137311246 failed at Ruff import ordering BEFORE real-data evaluation.
  Fixed import order only; no algorithmic change.
- Initial completed study43137492721, headb0d778d6ee4683458d7bddb74fb8b8289eaf7421,
  PR merge checkout80427dce5e499b14827b9b042d3605700331f133. Artifact13908605184:
  ZIP SHA2564dc70df75881df7f75bb137a59404d64de7a2797cbaabfc386b7105a8523d869;
  report SHA2562ecfcf0b5cde24f367895cabf997a91e7542797130d839c06750f156bde9d705.
- Final successful CPU run: https://github.com/JDeun/audio-score-tool/actions/runs/43138389279
  Job130919140597; headee47b87cad8060ebbc349e9bf3953229f0e65186;
  actual PR merge checkout57c8bab770e2509bae0290c0dfe62feb63f40bc5.
  Pinned Python3.11, mido1.3.3, pytest8.4.2, ruff0.16.6.31 tests passed,
  lint/compile/pip check, unchanged study replay and source audit succeeded.
  Research Evidence Contracts also passed. This is NOT full product CI.
- Final artifact13908396922, ZIP SHA256
  8aae98a772c0a6494ba243ebe0f123d0a3de7e1d4d44108dd5f61cb7ebf170b8;
  report.json SHA256ad4ab109f11850ab270bc43310e328d7e5cb9f5f8894af2e6e1975b5e2e6cd4e;
  source-audit.json SHA256dc244b40827e34516b8659208175887d76e5464540ffc2cc47a45c6ef42cd09d.
- Independently checked both ZIP digests against Actions metadata; identical
  main-study cases, summary, planned IDs, source files/hashes, settings and code
  hashes across initial/final runs. Source audit is linked to exact final report
  SHA. Recomputed all macro/micro/count/coverage/unit-selection rankings and
  aggregated source-audit outcomes. Per-note fix identity was not independently
  reconstructed from the count-only receipt; do not claim a second raw-data
  inference verification. New source audit adds original MIDI evidence, not
  another tuned model experiment.
- Main study reads4,270,863 bytes; semantic audit reads1,857,868 bytes. Only
  derived JSON metadata/counts/hashes uploaded; no original score/MIDI/WAV.

## Next research decision

Keep unit-aware measured time representation, but do not enable this automatic
unit/duration selector. The next useful controlled comparison is original MIDI
key-release duration versus the publisher sustain-adjusted duration on the same
admitted passages, retaining written-score labels only in evaluation. Then test
proper voice/rhythm context and an automatically estimated clock. Independent
new compositions, explicit rest ground truth, real mixed audio and human editing
cost remain required before any release claim. Keep #259/#249 open and #262 draft.
