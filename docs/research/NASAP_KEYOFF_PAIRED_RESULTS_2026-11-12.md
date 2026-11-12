# #263 — completed key-release vs publisher sustain-duration comparison

Related #262/#259/#249. Research only; no main, product/default, automatic score,
other-session, GPU, model/training or external-provider changes. Keep draft.

## Decision

Do NOT globally replace sustain-duration observations with key-release durations.
For the unchanged articulation method, written-duration agreement increases from
213/1,614 to233/1,614, but98 previously wrong durations become right while78
previously correct durations become wrong. Only2/7 passages improve,4 worsen,
1 is unchanged. Joint onset+duration correctness FALLS from90 to80.

The endpoint representation matters but does not explain away the low recovery
scores. Nearly all target durations are representable, and coordinate arithmetic
passes. Move next to genuine voice/rest/measure-context decoding rather than
retuning endpoint ratios on these seven passages. This does not invalidate the
user's half/double pulse-unit equivalence or measure-constraint proposal; neither
was redesigned or disproved here.

## Frozen cohort and fair comparison

All12 previous planned IDs preserved. Same7 admitted passages, same1,702 observed
notes, same1,614 uniquely aligned evaluation notes; the prior5 unsupported windows
remain explicitly unavailable. No passage replacement, no extra notes admitted
because key durations are shorter, and no incomplete paired input was discarded.
All7 pairs completed. Six arms =2 representations x3 inherited methods.

Inputs: publisher CSV sustain/performance duration versus original MIDI key-off.
Keep original CSV onset, pitch, identity and count; only the endpoint changes.
Every note maps uniquely one-to-one to MIDI onset/pitch/channel within2ms. Same
annotated variable-tempo beat clock, quarter origin and CORRECT UNIT supplied.
No score voice supplied; no unit selection, learned model or audio inference.
Written score and alignment are read only after all six sets of predictions.

CSV source identity and observation fingerprint, prior predictor/parser identity,
all musical input byte hashes, and previous three CSV score totals reproduced.
No musical threshold, vocabulary, model cost or evaluator change after results.
This is a reused small piano development sample, not mixed-song generalization.

## Primary results: duration agreement

Micro weights each of1,614 evaluation notes equally. Macro weights the7 passages
equally. Exact duration means within the inherited1/96-quarter tolerance.

| Method | CSV sustain correct | Key release correct | CSV micro | Key micro | CSV macro | Key macro |
|---|---:|---:|---:|---:|---:|---:|
| Literal nearest |198|212|12.2677%|13.1351%|14.4316%|14.4650%|
| Log fit + spelling preference |211|231|13.0731%|14.3123%|15.5291%|16.0817%|
| Same + latent performed/written ratios |213|233|13.1970%|14.4362%|15.8067%|16.3399%|

For articulation, endpoint-only gain is20 net notes, +1.2392pp micro and+0.5333pp
macro. With key-release inputs, articulation still adds only2 net notes over
spelling(231->233), just as with CSV(211->213). Do not credit the input-ablation
improvement to a new algorithm. No significance or robust-generalization claim.

| Endpoint change, same method | Corrected durations | Former correct damaged | Better / worse / equal passages |
|---|---:|---:|---|
| literal |92|78|2 /4 /1|
| spelling |99|79|2 /4 /1|
| articulation |98|78|2 /4 /1|

### Joint onset+duration is worse, not better

All six arms preserve EXACTLY the same onset correctness mask:524/1,614. Neither
input duration change fixes an onset. Joint correct counts:
- literal84->71;
- spelling89->79;
- articulation90->80 (19 pairs fixed,29 damaged).

Thus aggregate duration-only improvement does not establish whole-note or
notation improvement. Gains can occur on notes with wrong onsets while losses
occur on previously joint-correct notes. These are symbolic exact metrics under
a supplied clock, NOT audio transcription note F1 or rendered-score accuracy.

### Per-passage correct durations (literal / spelling / articulation)

| Original passage | n | CSV | Key release |
|---|---:|---|---|
| Chopin Etudes op25/8 MORET03 |353|14 /14 /14|54 /52 /52|
| Liszt Transcendental5 KIM_W02 |445|65 /68 /67|39 /44 /44|
| Bach Prelude bwv862 Song04M |155|38 /43 /45|33 /37 /39|
| Beethoven Sonata31-1 Zuber04M |278|24 /25 /26|37 /43 /43|
| Beethoven Sonata5-1 SunD02M |77|16 /17 /18|13 /16 /17|
| Mozart Sonata11-3 Stahievitch02 |178|16 /17 /17|11 /12 /12|
| Haydn Sonata50-1 Tak01 |128|25 /27 /26|25 /27 /26|

## Preflight results

- Exact and tolerance-admitted vocabulary coverage:1,613/1,614(99.9380%). One
 written duration is unrepresentable under the frozen vocabulary; keep it in
 the denominator. It cannot explain the bulk of these errors.
- All1,614 reference onsets can be represented within evaluation tolerance on
 the fixed grid. Literal true-score-input diagnostic preserves1,613 durations
 and1,614 onsets. This is a PROVIDED-SCORE identity check, not model success.
- Original onset and both endpoint representations pass seconds->quarters->seconds
 arithmetic; max difference7.105427357601002e-15s. This verifies computation, not
 infallibility of the publisher's beat/score alignment.
- Existing three CSV-arm counts reproduced exactly per passage. Neither a new
 source set nor a hidden denominator change created the measured differences.
- No raw data/audio model re-inference was performed locally for audit; remote
 runner performed the six actual source-data evaluations.

## Descriptive stratification, not a selector

Among1,614 aligned evaluation notes,849 have CSV duration >key-held by10ms;
765 do not. This is NOT the previous896/1,702 all-observation count.

Within the849 extended notes, articulation CSV duration correctness89->109 under
key release:98 fixed,78 damaged. In the765 other notes, correctness124->124 with
no articulation changes in correctness. The old pedal-extension hypothesis does
identify where the changes concentrate, but removing extension does not reliably
recover the score. No oracle per-note mixture was selected or reported as an
automatic accuracy gain. The124 previously unexplained publisher-duration cases
remain a source-semantics caveat; this study does not recreate that preprocessing.

## Execution and independent receipt audit

- First CPU run succeeded: https://github.com/JDeun/audio-score-tool/actions/runs/43141870109
- Job130930518812; executed head0b030927424da74434498323c41b325684cb1ac8;
 actual PR merge checkout ea985640f30c5644b2a5891a435ae77c448c5bf3.
- Python3.11.18, mido1.3.3, pytest8.4.2, ruff0.16.6; pip check, lint, compile and
 **54 tests passed**(23new +31inherited). Research Evidence Contracts passed.
 First measured run completed all7 paired sources; no retry or scoring patch.
- Artifact13910660014 ZIP SHA256
 a9fd6bb76b56ac0e7dc609e3dd9562326265571820d59cbab2edcf5833f99760;
 report.json SHA256
 ef57078bf20bff35a56e2f35cada222fe05bea3d0754785781296531111d0890.
- Previous artifact13908396922/report/source-audit hashes checked as declared.
 All42 passage-by-arm evaluations were independently recomputed from correctness
 bit masks: duration/onset/pair counts, subset representability, paired gains and
 losses, macro/micro totals, per-passage directions and descriptive strata.
 Original12 IDs, prior5 exclusion reasons, all musical source hashes and inherited
 predictor/parser identities checked. New code/test artifact hashes checked.
- Downloaded own experiment code was executed locally in54 offline tests, all
 passed under Python3.13; this is additional regression verification, not a
 second real-performance re-inference. No network is available locally.
- Evaluation6.615seconds excluding installation on one runner; source data read
 3,333,599bytes. These are one-run resource observations, not latency guarantees.
- Uploaded only derived receipt and our experiment source/tests; no original
 score/MIDI/WAV/note-value arrays. Correctness masks expose evaluation outcomes
 but not the musical note contents. This is not full product CI/rendering QA.

## Scope and next gate

Do not promote either endpoint representation as universal notated duration.
Retain their distinct meanings. The next proposed study is an actual score-
structured rhythm decoder comparing independent note-value choices with joint
voice/rest/measure interpretation, initially with the SAME provided clock and
voice information in both arms. Only then replace supplied context with estimated
context and test actual audio transcription. That future study has NOT run here.

(n)ASAP data CC BY-NC-SA4.0, sourceCPJKU/asap-dataset@4097b45757bed854818cf87e77b92323ebf90615.
Attribution Foscarin et al.(ISMIR2020), Peter et al.(TISMIR2023). No commercial-use
clearance or raw data redistribution implied; do not bundle research data in the
product. Explicit rests, ties, compound-meter support, score readability and user
editing time remain unmeasured. Keep #263 draft and #259/#249 open.
