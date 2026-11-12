# #264 — completed joint voice/rest/measure decoding pilot

Related #249/#259/#263. Research-only, draft, no main/product/default/automatic-score/other-session edits. No new audio inference, learned-model training, GPU or external provider credentials.

## Decision

Joint structure materially improves written-note recovery on this SMALL, PRIVILEGED-CONTEXT subset. It is worth continuing as a notation-decoder research direction. It is NOT a production approval: explicit-rest recovery remains very poor, some previously correct notes are damaged, and reference voice/chord/inventory/clock context was supplied. Do not call this whole audio-to-score accuracy or evidence that a measure-sum equation alone uniquely recovers a score.

Do not globally switch all observations to key-release durations. Both representations were tested separately with fixed algorithms. The stronger gain here occurs with the publisher sustain representation plus joint structure, not with a universal key-off replacement.

## Execution and provenance

- Draft PR https://github.com/JDeun/audio-score-tool/pull/264
- First measured CPU run succeeded: https://github.com/JDeun/audio-score-tool/actions/runs/43144673880
- Job130939584294, executed head866b2c78f27cb3bb4de2bcd682a04a775e42d6c5; PR merge checkout79bde832c7c1b04440ab4303bdf3967decf8ad81. This merge checkout is NOT a merge into main.
- Pinned Python3.11.18, mido1.3.3, pytest8.4.2, ruff0.16.6. pip check, functional Ruff F checks, compile, **81 tests passed** (27 new +54 inherited), then real-source evaluation. Full repository style lint and product CI/rendering were NOT claimed. Research Evidence Contracts also passed.
- Artifact13911212291 ZIP SHA256 `224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4`.
- report.json SHA256 `281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59`.
- Previous #263 artifact13910660014 ZIP SHA256 `a9fd6bb76b56ac0e7dc609e3dd9562326265571820d59cbab2edcf5833f99760`, previous report SHA256 `ef57078bf20bff35a56e2f35cada222fe05bea3d0754785781296531111d0890`.
- Exact inherited musical-file byte hashes, CSV/key-release observation hashes and previous six full-cohort prediction masks are checked before XML block admission. No cost, tolerance, selection rule or source was changed after results. The first completed result is retained, including exclusions.
- Receipt audit independently recalculated all228 block-arm mask counts, joint conjunction masks, paired fixes/damage, aggregate counts, source totals and rest precision/recall/F1. Checked artifact digest against Actions, prior report link, all36 original-file hashes and included reproduction-code hashes. Original inherited source/test bytes match the preceding artifact.
- Downloaded executed source/tests passed all81 offline regressions locally too. That is regression and receipt arithmetic verification, NOT a second original-score/MIDI inference or independent manual alignment check. Rest-match and tie-relation raw event identities are not reconstructable from this count-only receipt; do not claim raw rest re-annotation.
- Measured evaluation19.959s excluding setup; source bytes11,060,511 including7 new XML files. One runner observation, not a latency guarantee. No raw musical data or note arrays uploaded, only counts/masks/hashes and our source.

## Coverage and supplied information

All12 original planned sources remain visible. Five prior unsupported-meter sources were not replaced. Of the prior7 sources:
- Five compositions provide38 admitted voice blocks, each spanning2 full measures.
- The38 blocks contain655 unique evaluated notes and35 semantic explicit-rest intervals, with rests in23 blocks and15 rest-free blocks. These are correlated excerpts from5 works/4 composers, NOT38 independent songs.
- Chopin Etudes op25/8 has no admitted block under the fixed complete-alignment/occupancy rules.
- Haydn Sonata50-1 is not evaluated after the restricted MusicXML parser reports a noncontiguous or unmatched tie. The source annotation versus parser limitation has NOT been resolved; do not blame the dataset or silently remove the tie.

Across the six structurally scanned sources,121 voice-block attempts:38 admitted,64 missing unique performance alignment,3 note/tie crossing outer block edge,7 explicit voice occupancy not exact,1 XML/CSV note-semantics mismatch,8 grace-note blocks. No failed block was replaced or changed after seeing its score.

Every admitted block completed all6 conditions: publisher-sustain/key-release x independent/joint-structure/joint-rest-cost. All have the SAME655-note denominator. This subset is only655 of the prior1614 evaluated notes, with DIFFERENT privileged context and an onset candidate lattice. Do NOT compare the new percentages directly to #263's14% duration scores.

Supplied to EVERY arm: annotated variable-tempo clock, correct quarter unit, bar boundaries, reference voice membership, chord membership, and complete aligned note inventory. Grouping played chord tones already supplies information an automatic audio pipeline would have to infer. Reference start/duration/rest values are used for admission/label construction and evaluation, not passed to the decoder. This is a conditional algorithm comparison, not a fully reference-free score recovery claim.

The explicit rest labels come from MusicXML, not from manufactured silence gaps. Adjacent rests are merged as equivalent silence intervals. Tied chains crossing the internal barline retain one real attack; outer-edge continuations and unsupported overlap/grace structures are excluded with reasons.

## Same-lattice comparison

All arms use the same onset/duration candidates and unary costs. A) independent selection; B) exact DP imposing voice non-overlap plus spellable rest partition across supplied measures; C) the same DP plus a fixed rest-token complexity cost. Therefore B vs A isolates the combined structural constraints; C vs B separately tests the rest preference. This does NOT isolate the arithmetic sum constraint from every other structural restriction.

Primary metric: exact written onset AND duration, each within the inherited1/96-quarter tolerance. No pitch/count changes. Micro scores weight the655 notes equally.

| Input | Method | Onset correct | Duration correct | BOTH correct | Both/655 |
|---|---|---:|---:|---:|---:|
| Publisher sustain | Independent |546|116|105|16.0305%|
| Publisher sustain | Joint structure |554|341|322|49.1603%|
| Publisher sustain | Joint + rest cost |551|397|381|58.1679%|
| Key release | Independent |549|113|106|16.1832%|
| Key release | Joint structure |540|139|137|20.9160%|
| Key release | Joint + rest cost |537|254|254|38.7786%|

Publisher-sustain BOTH-correct gain: +217 notes for joint structure, then +59 from rest cost; +276 versus independent. Key-release gain: +31, then +117; +148 versus independent. The inputs and methods are not mixed per note or per source using reference winners.

All three arms also share weak metrical onset preferences and supplied chord membership. Their improved onset accuracy relative to #263 is not credited to joint constraints. The fair primary comparison is within this table.

### Correction and damage, joint onset+duration

| Input and comparison | Previously wrong fixed | Former correct damaged |
|---|---:|---:|
| Sustain: structure vs independent |221|4|
| Sustain: structure+rest vs independent |288|12|
| Sustain: adding rest cost to structure |67|8|
| Key: structure vs independent |35|4|
| Key: structure+rest vs independent |154|6|
| Key: adding rest cost to structure |119|2|

For duration alone, sustain structure+rest fixes303 and damages22 versus independent; key structure+rest fixes154 and damages13. Normal-note harm is not hidden behind averages.

### Composition-level joint correctness

| Source | Notes | Sustain independent / structure / +rest | Key independent / structure / +rest |
|---|---:|---|---|
| Liszt Transcendental5 KIM_W02 |192|23 /56 /70|11 /16 /36|
| Bach Prelude bwv862 Song04M |141|42 /51 /77|35 /38 /68|
| Beethoven Sonata31-1 Zuber04M |237|27 /192 /197|46 /68 /118|
| Beethoven Sonata5-1 SunD02M |53|11 /21 /31|12 /13 /26|
| Mozart Sonata11-3 Stahievitch02 |32|2 /2 /6|2 /2 /6|

Five works improve with structure+rest versus their same-input independent baseline, but a large portion of the pooled gain comes from Beethoven Sonata31-1. Equal-work means for sustain are16.03%,38.44%,50.29%; key15.77%,18.95%,36.91%. No significance or new-work generalization claim.

## Explicit rests — major remaining failure

The true reference contains35 semantic rest intervals. Exact matching requires both ends within1/96quarter, so these are strict symbolic-rest metrics, not listening judgements.

| Input/method | Predicted rest intervals | Exact matches /35 | Rest F1 |
|---|---:|---:|---:|
| Sustain independent |191|9|7.9646%|
| Sustain structure |193|10|8.7719%|
| Sustain structure+rest |113|5|6.7568%|
| Key independent |279|4|2.5478%|
| Key structure |308|4|2.3324%|
| Key structure+rest |180|4|3.7209%|

Rest cost reduces the number of predicted gaps but does not reliably preserve the original rests. In the sustain condition, true matches fall10->5 while joint-correct notes rise322->381. Thus maximizing note correctness or reducing rest count is NOT the same as producing a good complete score. Do NOT report58.17% as complete notation quality.

Independent structural validity:15/38 sustain blocks and22/38 key blocks. Joint arms:38/38. This is expected from constraints, not proof of score correctness. In particular a perfectly filled measure may still contain wrong notes/rests.

## Candidate limits, ties and other caveats

The shared lattice admits the exact reference onset+duration for648/655 notes in either input representation;7 are outside the fixed local candidate restriction. This is reference-assisted candidate coverage, NOT achieved accuracy or a globally attainable oracle result.

Inner-bar crossing relations were also counted, but their positive-class prevalence and full tie confusion matrix were not saved. High agreement may be dominated by notes that need no cross-bar tie. Do not claim a solved tie detector or MusicXML exporter from these counts. No engraved score/PDF, listening validation or user editing-time measurement occurred.

The strict parser rejection for Haydn and complete-alignment exclusions limit coverage. The source notes were not newly predicted by YourMT3/Basic Pitch: AMT missed/extra notes, wrong pitches, erroneous voice grouping and inaccurate beat clocks are absent or screened out. Real commercial/mixed-music deployment remains untested.

## Next gate

Retain joint structural decoding as a promising research candidate. Do not enable the current rest-cost setting as automatic production correction. First freeze this comparison and verify on disjoint new compositions with explicit-rest labels, while testing rest-preservation objectives on a separate development split. Then remove oracle chord/voice context and replace the supplied clock with detected timing one factor at a time. The user-proposed measure-consistent joint interpretation is supported conditionally; it is not a unique inverse solution guaranteed by total duration alone.

Data attribution/licensing: (n)ASAP CPJKU/asap-dataset@4097b45757bed854818cf87e77b92323ebf90615, CC BY-NC-SA4.0; Foscarin et al., ISMIR2020; Peter et al., TISMIR2023. No commercial-use clearance or source-data bundling implied. Keep #264 draft and #249/#259 open.
