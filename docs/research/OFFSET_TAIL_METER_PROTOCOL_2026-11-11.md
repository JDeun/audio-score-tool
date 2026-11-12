# Offset-only recovery and separate metrical-anchor controls

User-authorized research, 2026-11-11; related #200 #214 #215 #239 #244 #245 #247 #34.
Based on main `7e3458e745bf612b0cf0cb0528715b0bcc42f392`. No product changes,
main merge, editing of other research branches, private user songs, GPU, gated
weights, paid API, LLM or training. Keep the PR draft and do not auto-merge.

## Question and distinction

Can bounded changes of *performed note offsets* improve strict note transcription
while pitch/onset/count/order/instruments remain identical? This is NOT a notation
quantizer or a note merge/split experiment. Nearest-attack onset snapping in #239
failed; no onset relocation is reused here. Zero applicable proposals cannot be
reported as safe successful correction.

A separate analytic control addresses the user's meter/BPM suggestion. A constant
meter n/d, explicit metronome unit u (quarter lengths), BPM B and a true downbeat
t0 imply bar times t0+k*(60/B)*(4*n/d)/u. The first audible note is not assumed to
be a downbeat. Pickup, rest before entry, dotted-quarter6/8, one-BPM error and a
known tempo change are controls with constructed clocks. They are not audio beat
detection, real-song improvement, or inferred tempo/phase. No such clock is fed
into offset correction. Knowing a metrical grid does not determine performed
articulation or the duration/rearticulation of a given note.

## Frozen paired arms

Same original vocadito v3 40 recordings, SHA-bound archive, original Hz A1/A2,
unchanged main `scripts/vocadito_reference.py`, mir_eval0.8.2. Repeated development
corpus, NOT held-out. Both original annotators always reported. No score-driven
post-result retuning, per-song winner or relaxed primary metric.

Base predictions: YourMT3+noPS raw; Basic Pitch0.4.0 ONNX default and previously
chosen onset0.65. Both BP decoders use the same saved activations and default
replay must exactly match raw events. Pinned loaders/checkpoints are reused.
Public prior artifacts lack raw sequences/activations, so new paired inference is
necessary; it is not a claim to access another session's private cache.

For each base:
1. `raw`: unchanged.
2. `activation_tail`: first four consecutive BP note-activation frames below0.3
   after a three-frame >=0.3 sustain seed within onset+[30,150]ms, before the source
   offset-20ms. Use upstream `model_frames_to_time`, not uniform assumed hop time.
3. `activation_tail_pyin`: the SAME proposal, requiring local pYIN corroboration:
   >=70% same-pitch observations in the50ms before and <=30% in the50ms after the
   proposed release; at least4 samples per side,70cent pitch tolerance and pYIN
   voiced probability>=0.5. This is not a replacement global F0/voicing mask.

Only nonoverlapping pitched source events of duration>=120ms, within21..108 and
inside audio are eligible. Proposed duration>=80ms, change>=20ms and <=min(150ms,
40% source duration), no new overlap. Keep all other events. No event creation,
removal, pitch changes, source start movement, reference boundary or grid snapping.
All thresholds and abstention reasons are fixed before actual recording results.

pYIN: librosa0.10.2.post1,16kHz,2048frame,160hop,55..880Hz,center=True,constant
padding, no retuning/time shift. It is a prediction, not truth. BP note activations
are also predictions, not calibrated correctness probabilities.

YourMT3 corrected arms explicitly use the *additional Basic Pitch model*. Do not
report them as YourMT3-only inference. BP evidence is self-derived for its own
bases. Runtime/resource reporting must distinguish these compositions.

## Scoring, damage and audit

Generate all arms BEFORE reading reference annotations for that recording. Score
pitch50cents/octave-sensitive and onset50ms; offset additionally max(50ms,20% of
reference duration). Pitch/onset/count invariants imply EXACT equality of onset F1
for every arm; any violation fails the case rather than being a reported gain.

Report offset-inclusive F1 for each recording/annotator, equal macro, paired
recording deltas and bootstrap2000/seed0 exploratory intervals (average annotators
within recording). This is not independent/multiple-testing-corrected evidence.
Missing/failed/duplicate cases or arms forbid a full macro; valid empty outputs
score zero. Include every failure, unchanged result and abstention reason.

Changed-event repair/harm uses unique fixed pitch/onset anchors on BOTH sides
of the prediction-reference graph; offsets are not used to find anchors. These
are conditional annotation diagnostics, not confirmed human labels; report
unassessable changes and absolute offset-error sums as well. Do not claim zero
harm if no notes were changed or if changed notes had no evaluable anchors.

Retain source/weights/runtime/scorer/activation/F0/prediction identities, immutable
raw inputs and all paired results inside private runner workspace. Upload only
explicit aggregate/per-recording metadata JSON, never audio, annotations, predicted
sequences, scores, weights, paths or arbitrary logs. Count full end-to-end CPU cost;
parent RSS excludes YourMT3 subprocess peaks and is labelled accordingly.

## Actions and decision boundary

Two standard CPU jobs,2threads,max2parallel,70min/job. PR-open/reopen or manual
trigger; later documentation pushes do not cancel/repeat inference. Local tests
are pure contract/synthetic checks, not real model-quality evidence. Remote lint,
pinned tests and actual source inference must be reported separately.

A gain must survive normal-note harm review and later independent recordings.
Only then test note merge/split separately, then combine successful components and
assess notation/PDF and human edit cost. The known meter/BPM controls motivate a
separate beat-anchor comparison (first-note assumption vs inferred downbeat vs
provided correct downbeat) but do not establish an automatic downbeat solution.

Sources: pinned Spotify note_creation.py at fa5997af0a8210982619003269994a1be25eddf3;
MusicXML4.0 metronome element (explicit beat-unit, dots and per-minute);
existing project protocols/results #239/#244/#246/#247. Prior unsuccessful methods
are not silently relabelled as successful baselines.
