# #259 follow-up: can notation priors choose the pulse unit without reference BPM?

Base draft #260 at 58ab50cf6be509e476913c7be460bdf43047c30f. Research only; do not merge, change product defaults/main/other branches or claim final-score improvement.

## Question and limits

#260 verified unit-preserving time/XML/MIDI conversion, not automatic unit selection. Here the three hypotheses quarter/pulse = 0.5, 1, 2 are ranked without reference BPM, meter, score, recording name or provider metadata. The original Beat This pulse timestamps from run43122028203/artifact13900383659 are frozen. No new model inference, training, GPU or external API keys. All16 original IDs stay in the coverage denominator; only12 have admitted learned-model pulse sequences. No replacement of the four unadmitted sources.

This is reused developmental GMD evidence, not an independent test. GMD audio is human-performed Roland drum-kit sound, not full-band music. We analyze the same first24s and require exact original WAV/sample hashes. Known-role human MIDI events are a SEPARATE privileged-observation diagnostic; original MIDI tempo is used only to convert ticks into seconds, not to select a unit. MIDI note durations do not constitute notation labels and will NOT be used.

## Fixed input representations

1. **Audio only:** existing fixed low/high spectral-flux detector from #254 produces (time, kick/backbeat) from the original WAV. No MIDI role labels, BPM or meter reaches this detector or the selector. Same source SHA/decoded sample SHA/duration as #258.
2. **Known-role diagnostic:** original paired human MIDI kick/backbeat times, same excerpt. This removes acoustic hit/role errors and is NOT a deployable audio-only pipeline.

No raw WAV/MIDI/onset arrays are uploaded. Receipt has hashes, counts, per-candidate costs and outcomes. Strict206 range reader limits total audio transfer to140MiB and refuses full5.11GB fallback; full ZIP SHA is not verified. Metadata-only ZIP SHA651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e is verified. GMD attribution: Google Magenta Groove MIDI Dataset v1.0.0, CC BY4.0.

## Frozen selector design

- Input signature accepts ONLY observed pulse timestamps and (onset_seconds, role). Raw pulse rate =60/median(diff(pulses)); preserve all three unit candidates and original event identities/times.
- Map onsets into piecewise-affine measured pulse coordinates. Snap ONCE to1/12 pulse, common to all units. Convert those physical grid points into1/24-quarter ticks using factors1/2/4 for units0.5/1/2. This deliberately ensures IDENTICAL physical fit across units. A smaller grid residual cannot falsely masquerade as evidence for an arbitrary musical scale.
- For each role independently, score spans between consecutive onsets. These spans are NOT inferred note sustains or true rests. Simultaneous roles are not added into one voice. Coincident snapped attacks are counted, never merged in output.
- For candidate3/4 and4/4 meters and quarter-beat phase steps, partition every positive span exactly at hypothetical barlines. Edge bars may be partial. Compute exact minimum additive spelling costs by dynamic programming; no deletion/insertion/retiming. All hypotheses satisfy bar partitioning, so their ranking comes from spelling PREFERENCES, not a unique sum equation.
- In1/24-quarter ticks, fixed duration/cost pairs:
  (96,1),(72,1.15),(48,1),(36,1.15),(24,1),(18,1.25),(12,1.15),(9,1.5),(6,1.4),(3,1.8),(64,1.45),(32,1.45),(16,1.45),(8,1.6),(4,1.85),(2,2.1),(1,3).
  The latter entries cover triplet/fine subdivisions. Add0.15 per additional bar-separated fragment. Average total over positive same-role spans; minimize over meter/phase. This is a hand-set compact-notation proxy, NOT a trained music model or calibrated likelihood.
- Five methods: (A) keep quarter/pulse1; (B) choose nearest broad120QPM log-space prior; (C) minimum notation cost; (D) notation+0.25*[0.5*log2(QPM/120)^2]; (E) C with absolute inter-unit cost margin >0.10, otherwise abstain. Exact ties abstain in B/C/D/E, no arbitrary favorable unit. Require8 onsets and4seconds for notation arms; all unavailable/abstained cases stay in denominators.
- Meter and phase are nuisance candidates ONLY, not evaluated as successful automatic meter/downbeat estimation. No source's correct meter or phase is supplied. No note-duration/score-export claims.

## Evaluation and controls

Reference catalog QPM is used ONLY AFTER predictions. Same +/-4% nominal criterion (epsilon1e-12 numerical inclusivity); family membership remains an evaluation-only ceiling. Report same12 paired correct/wrong/abstained, all16 coverage, error types, correction of original aliases, formerly-correct damage and per-recording selection. Do not report conditional precision without coverage/correct-all. Audio and known-role diagnostic must stay separate; no per-source best-of method selection.

Controls: identical physical pulse/onset arrays admit two different legal notation conventions (75/150QPM). Selector MUST return identical results for identical arrays; it cannot know which original convention the evaluator labels correct. Also check scale-equivalent grid residuals, pulse/time shift invariance, malformed/nonfinite/unordered events, silent/short inputs, simultaneous roles, empty spans, exact DP spellings and counterexample ties. A sum constraint alone is not proof of the original unit.

All costs, source selection and methods frozen before this real-data evaluation. Do not tune after inspecting results. Source/checksum failures must be reported explicitly, not scored as zeros or replaced. A green infrastructure job is not automatically a successful scientific result.

## Execution

Single standard Ubuntu CPU Actions job,2threads,15min cap; pinned Python3.11, numpy1.26.4/scipy1.13.1/mido1.3.3/pytest8.4.2/ruff0.16.6. Job-scoped actions:read fetches only the original repository artifact; no provider credentials. Only structured metadata result published. Report-only pushes do not rerun. Keep #259/#252/#249 open and this PR draft.

Duration representation reference: https://music21.org/music21docs/moduleReference/moduleDuration.html . The experimental cost/prior is our hypothesis, not an algorithm claimed by that documentation.
