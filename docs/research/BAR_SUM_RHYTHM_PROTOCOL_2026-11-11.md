# Bar-sum joint rhythm recovery — frozen first experiment

Issue #249, related #200/#219/#248/#244/#34. Base main7e3458e. Research only:
no product settings, private recordings, main merges, paid services, credentials,
models, training or other branches change. This implements the user's proposal,
not merely another known-clock arithmetic check.

## Task and hypotheses

Given a fixed meter, BPM and its beat unit, interpret perturbed MONOPHONIC note
onsets/releases as notated starts, durations, rests and bar phase. Written pitch,
note ID and attack count remain fixed. Complete bars must be exactly covered by
notes/rests in this voice; a sustain crossing a bar has a tie, not a new attack.
The first/last spans may be partial. The recording endpoint is NOT a bar label.

The important null hypothesis is explicit: with free rests, exact bar totals
alone generally do not determine durations or phase. Sequence non-overlap and
notation priors may contribute separately. Neither metric completeness nor
filling a bar with rests demonstrates intended musical correctness.

## Information and comparison arms

All arms use the SAME candidate lattice and observation objective.
A independent_known_phase: independently minimum-cost note candidates.
B joint_sum_known_phase: exact shortest-path DP over events/end times, enforcing
order/non-overlap and filling intervening rests. No notation-complexity prior.
C joint_notation_known_phase: B plus fixed representation-complexity costs.
D joint_unknown_phase: C over every candidate bar phase; retain near-optimal set.
E joint_unknown_phase_accent: D plus separate synthetic pulse-strength evidence.

A/B/C receive the true phase ONLY as an explicitly oracle-assisted diagnostic.
All receive known BPM/meter. D/E never receive target note durations, bar phase,
pickup label, fixture name or any reference. E's idealized other-part pulse
strengths are generated observations, NOT an automatic audio beat detector.
No comparison between A/B/C and D/E is interpreted as equal-information accuracy.

## Fixed search and costs — no corpus-result tuning

12 ticks/quarter. Candidate note durations:3,4,6,8,9,12,18,24,36,48 ticks. Candidate
starts are integer ticks within3 ticks of nearest observed start, bounded at0.
Candidate ends may differ from observed release by at most max(12ticks,observed
length). All arms use these same restrictions. Event observation cost is
((start-observed)/1.25)^2 +0.35*((end-observed)/2)^2. Releases are NOT assumed to
be notation truth; the staccato condition intentionally tests that mismatch.

B's DP state is the previous end; transitions allow nonnegative rest gaps.
C adds0.15 times a shortest duration-token decomposition cost and0.08 per extra
bar-crossing tie. Tokens1/2 cost4, tokens4/8 cost1.25, other vocabulary tokens cost1.
Fine1/2-tick tokens make rest/tied fragments exactly representable; this is an
ABSTRACT notation cost, not complete beaming, articulation or tuplet engraving.

D tests integer phase0..bar_ticks-1;0 denotes a full bar at the window origin,
p>0 an initial partial interval of p ticks. No first-note or endpoint prior.
Costs are divided by note count. Retain all phases within0.02 of minimum; select
only if one remains. This tolerance is not a calibrated uncertainty probability.
A top candidate during abstention is diagnostic only, not a delivered score.

E adds4 times mean pulse-strength squared error against
0.25+0.75*exp(-0.5*(circular_bar_distance/1.2ticks)^2). Flat observed strength
range<0.12 supplies no phase evidence. Source beat unit is explicitly quarter
or dotted quarter. 3/4 and6/8 have equal quarter-length totals: totals do not
identify the grouping. Meter is supplied, not inferred in this experiment.

## Authored evaluation set (12 phrases x4 profiles =48 correlated cases)

Original patterns: regular4/4, regular3/4, eighth pickup, quarter pickup, initial
rests, syncopation, triplets, cross-bar sustain, repeated pitch, compound6/8,
internal rests, and full-bar rest. Each spans approximately3–4 bars. These are
not existing songs. Pitches are supplied correctly: no acoustic inference runs.

Profiles fixed before outcomes:
- clean: exact performed onset/release equals the written timing.
- jitter: uniform onset +/-1.8ticks and release +/-2.2ticks.
- staccato:60% of written duration sounds, with +/-0.36tick onset/release jitter.
- weak_accent: the jitter profile, but all pulse strengths0.4 (no bar emphasis).
Seeds derive from first16hex SHA256(phrase/profile), not chosen by result.
Other profiles have pulse strengths1.0 on downbeats/0.25 elsewhere, +/-0.025
strength noise, and up to0.15tick pulse timing noise except clean. This is an
idealized observation model, not a claimed model of all human performance.

Two separate ambiguity controls: identical equal-quarter pulses fit all phases
under sum-only cost; and staccato quarters vs eighths+rests can generate identical
sounding note intervals. The latter has two valid interpretations, not one gold
answer the system is expected to recover without more information.

## Outcomes and audits

A/B/C: exact notated onset, duration and their joint agreement by fixed note ID;
exact rest-interval F1; corrected and damaged previously-correct note pairs;
phrase/profile cases improved/worse; structural validity and number of full bars.
These are not mir_eval audio note F1 and cannot be compared to vocadito54%.
D/E: correct/wrong/abstained phase counts, correct-and-decided rate on ALL cases,
conditional accuracy with decision coverage, and truth-in-retained-set coverage.
Selected-phase notation metrics remain separate; a retained set is not a correct
single pickup estimate. Never score an abstained top candidate as deployed.

All case/arm failures remain visible; incomplete cases prohibit a complete macro.
Report48 variations and12 base phrases, not48 independent songs. Structural sum
checks are not quality approval. Exact source/protocol/config/input/reference
hashes, actual checkout/head and full per-case results remain in the receipt.

## Execution and boundary

Standalone standard-library algorithm, CPU-only Actions with a10minute hard cap,
no model download. Unit tests compare DP with brute force on a tiny lattice and
check immutability, ties/reattacks, partial bars and ambiguity before the study.
No threshold adjustment after corpus outcomes. Failed assertions can be repaired
only as implementation errors, documented without silently retuning this study.

No MusicXML/PDF, multi-voice, fermata, time-signature change, tempo drift or actual
AMT correction benefit is established. Independent paired performance/notation
and real AMT input are follow-ups. Vocadito Hz/onset/offset annotations alone are
not intended-score rhythm truth. #249 stays open; no product default promotion.

Sources for task motivation, not reproduced methods:
https://arxiv.org/abs/2008.12710
https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/measure-partwise/
