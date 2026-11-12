# #267 — performed quiet-core preservation, DEVELOPMENT result

Related #249/#259, research integration #266. This records a completed research experiment, NOT approval of product automatic correction. No new audio/model inference, training or GPU. All inputs still include privileged clock/unit/bar/voice/chord/inventory.

## Execution and fixed cohort

First CPU run43155095702 succeeded. Executed head1ff3d99fcad2fd57a3a3cd12fc8acbd1e09db95b, actual PR merge checkoutab34c43a5962f2d5a247b0b02dd16a5b4865be7f. Only #264 DEVELOPMENT data used; #265 validation musical inputs were NOT reopened. All12 original statuses retained, same5 completed works/38 blocks/655 notes/35 semantic XML rest intervals. All10 arms completed each block, no hard-guard failures. All6 old controls reproduce their original masks and exact-rest counts.

Artifact13916200034 ZIP SHA256c245fb1eccf8e9dffe6cf7da4f763b4b0c76a3cdc6c9db1d8ad58e8d363c6058; report SHA25682116d0ed540b3d5ae0c9f5d72faa661bc6ec47256bed52e1ad443578b27c9a4. Run URL: https://github.com/JDeun/audio-score-tool/actions/runs/43155095702

Pinned new-code lint/compile and inherited/new regressions passed. Local113 offline checks passed before execution. Receipt audit verified ZIP digest against Actions metadata and all380 block-arm note mask counts/conjunctions plus paired gains/damage. This is not independent source re-inference or manual rest reannotation.28.57s evaluation on one runner, excluding installation.

## Hypothesis

Use both observed endpoint representations to identify INTERNAL quiet cores: union occupied intervals, minimum gap0.25quarter, trim1/16quarter at both ends. No target rest labels enter the evidence or decoder. Candidate silence is an imperfect proxy: staccato and expressive release can create silence without a written rest. Both new arms have extra paired-endpoint evidence versus the one-representation unary control.

Fixed soft objective adds8.0 cost per quarter of a note covering quiet evidence. Fixed hard objective disallows such overlap. Both retain the original exact rest-cost dynamic program, lattice, all other costs and observations. Zero evidence must exactly reproduce old predictions. No post-result tuning or oracle choice of best arm.

## Same-input comparisons

Durations below are sums over separate VOICE timelines in quarter-note units, not seconds of a whole recording. Total true-rest duration34.5quarters.

| Unary input / method | BOTH onset+duration correct /655 | Rest predicted / exact matches | Rest F1 | Erased true-rest time | False-rest time |
|---|---:|---:|---:|---:|---:|
| Sustain / original rest cost |381|113 /5|6.7568%|14.6875|34.6667|
| Sustain / soft quiet evidence |379|126 /8|9.9379%|7.9792|37.8333|
| Sustain / hard quiet evidence |377|126 /8|9.9379%|7.9792|38.3333|
| Key release / original rest cost |254|180 /4|3.7209%|6.8125|56.1250|
| Key release / soft quiet evidence |255|185 /5|4.5455%|4.0625|57.4167|
| Key release / hard quiet evidence |253|185 /5|4.5455%|4.0625|57.9375|

Sustain soft versus old rest cost fixes5 previously incorrect note pairs and damages7; hard fixes5/damages9. Key soft fixes2/damages1; hard fixes2/damages3. A reduction in erased rest duration is not blanket score improvement: false-rest duration increases and normal-note damage remains. Strict rest F1 is still poor.

The unchanged sustain joint-structure control WITHOUT rest complexity cost has322 correct notes,10 exact rest intervals,6.4375quarters erased and45.4792 false-rest quarters. The new soft objective preserves more notes and reduces false rests relative to that control, but does NOT beat it on erased-rest length or exact rest matches. No claim of a uniformly dominating method.

## Evidence reliability

25/38 blocks contain candidate quiet cores. Their total duration34.9545quarters overlaps true rests for15.2700quarters and written-note regions for19.6845quarters. Thus most candidate evidence time is NOT a true written rest in this sample. This explains why hard preservation can protect spurious rests. The source endpoints are observations, not intended notation.

## Decision

Soft evidence is a useful DEVELOPMENT tradeoff: it recovers some real rest time with a small note-score loss, but is not production-safe. Hard exclusion is not preferred: same rest recovery and more note damage. Do not deploy either automatically or say the previously observed holdout failure was fixed; this trial did NOT evaluate #265. Next research should improve discrimination between articulation gaps and intended rests, and evaluate on a separately reserved rest-rich set before replacing provided context. Do not keep changing weights on this validation while claiming an untouched test.

Merging this code/results into main is research consolidation only. Data (n)ASAP@4097b45757bed854818cf87e77b92323ebf90615 CC BY-NC-SA4.0; attribution Foscarin et al.(ISMIR2020), Peter et al.(TISMIR2023). No raw score/MIDI/audio distributed, no commercial-use clearance implied. Full audio transcription, automatic voice assignment, readable MusicXML/PDF and user editing time remain unmeasured.