# Bar-sum joint rhythm recovery — completed CPU study

Issue #249 / PR #250. No production/default/main/other-branch changes. This is an
actual constrained inference experiment on authored symbolic performance events,
NOT audio AMT accuracy, MusicXML/PDF quality, a learned model or human edit cost.

## Execution and verification

- Actions43005121772, job130470559697: success. Python3.11.18, standard CPU;
  compile,21 targeted contracts, all48 cases x5 arms, and report upload completed.
- Executed PR head8f0310bec64fbaf57fcb69c97ec3d4f834771270; actual merge checkout
  3eafa9223c48bedbd44c146144949b880f30ff9b. Later documentation is not inference code.
- Artifact13848420230 ZIP SHA256:
  1e6431cfa5172bac72b6c85e580dbb28a293e650400394c54f12b4505c4b9e5a.
  Sole member report.json SHA256:
  53c5b9136d5d37964a58d931d43e0e5d475f91a53b1c5e153bc179b4197db31d.
- Downloaded ZIP hash matched GitHub metadata. All48 planned IDs, five arms,
  authored reference and observation fingerprints, note ID/pitch/count invariants,
  note/rest metrics, interval coverage, phase sets/decisions and macro arithmetic
  were checked. Independent direct interval arithmetic reproduced the receipt.
- Source hashes matched the locally executed algorithm, runner, tests and protocol.
  The same fixed local study also completed; all notes, phase sets, decisions and
  metrics were identical. Local Python3.13.5 vs remote3.11.18 differed in19
  independent-arm summed costs by at most4.44e-16, not in any output or score.
  This is symbolic solution/metadata verification, not independent real-audio testing.
- The initial ordinary CI43005121700 failed only Ruff I001 import ordering in
  the new runner; full Python tests were skipped there. Commit7ebbdcb reorders
  imported names only. Non-import AST and21 local contracts are unchanged.
  The completed research receipt remains identified by the ORIGINAL SHA. Later
  ordinary CI status is separate; do not call the failed original run successful.

## Design boundary

12 original phrases x4 profiles =48 correlated variations,652 note observations.
Each has correctly supplied pitch/attack count, known fixed meter and BPM beat
unit. No model-generated mistakes, missing notes or polyphonic assignment are
included. A/B/C also receive the correct phase as a diagnostic; D/E do not.
No score-based parameter changes, best seed selection or automatic application.

A: independent nearest-cost note candidates.
B: joint non-overlap/exact coverage, no notation prior.
C: B plus weak predeclared duration-token/tie complexity cost.
D: C with unknown phase and near-optimal-set abstention.
E: D plus idealized synthetic other-part accent observations.

Important causal limitation: B fills all gaps with rests. When arbitrary rest
fragments are allowed, bar-sum equality by itself excludes no extra monophonic
path; B's effective additional restriction over A is non-overlap. Thus B's gain
must NOT be attributed solely to the arithmetic bar-sum constraint. C's larger
gain comes with additional notation priors, not equality alone. The experiment
implements and separates these aspects rather than claiming totals determine
one score. Fine tied/rest fragments and abstract symbol cost are not full beaming
or tuplet-group engraving rules.

## Known-phase notation recovery

Metric is exact agreement of BOTH written onset tick and written duration for
an immutable note ID, averaged equally over cases. It is NOT the earlier50ms
performance-note F1 and must not be compared to vocadito54%.

| Arm | Exact onset+duration | Exact onset | Exact duration | Rest-interval F1 | Structurally valid cases |
|---|---:|---:|---:|---:|---:|
| A independent |37.8198%|66.9411%|58.3409%|26.1364%|25/48|
| B joint coverage |40.1084%|69.6116%|56.4545%|25.7576%|48/48|
| C joint + notation cost |50.5629%|79.1658%|59.0603%|33.5354%|48/48|

C minus A =12.7431 percentage points; B minus A =2.2886pp. C improves18 cases,
worsens1, leaves29 unchanged. Across the correlated variants,92 note pairs that
A got wrong become exact, while14 formerly exact pairs become wrong. Therefore
positive mean gain is not a harmless automatic correction guarantee. B repairs
29 and damages16 pairs;13 cases improve and4 worsen. All12 clean cases remain
100% exact in A/B/C. Structural48/48 is an enforced property, not score accuracy.

| Profile (12 phrases each) | A pair agreement | B | C |
|---|---:|---:|---:|
| clean |100%|100%|100%|
| timing jitter |22.2418%|27.2552%|44.1827%|
| staccato60% sounding gate |0%|0%|4.4444%|
| timing jitter + flat accents |29.0376%|33.1784%|53.6245%|

A/B/C do not receive accents; the last profile has its own fixed jitter seed.
The severe staccato failure confirms this observation objective does not properly
infer written duration from shortened sounding duration. Knowing the bar length
is insufficient to choose between articulation and written rests. The only
case-level regression for C is internal_rests/weak_accent; normal-event damage
also occurs within cases with positive net changes. No post-result fix is applied.

## Unknown phase and pickup

These arms receive NO true phase. A decision is made only with one retained phase;
abstention does not count as a correct selected barline. E has additional
SYNTHETIC accents and must not be called an actual audio downbeat detector.

| Arm | Correct phase | Wrong phase | Abstained | Truth retained in candidate set |
|---|---:|---:|---:|---:|
| D notation only |1/48|2/48|45/48|33/48|
| E + synthetic accents |32/48|3/48|13/48|39/48|

E's conditional accuracy is32/35 =91.43%, but decision coverage is35/48 and
correct-and-decided rate over ALL inputs is32/48 =66.67%. Do not report91.43%
as whole-input or real-song accuracy. One jittered triplet case chooses phase47
rather than0 (one tick circular error). The two other wrong decisions are flat-
accent cases. No relaxed phase tolerance was substituted after seeing results.

For the TWO pickup phrase designs under four profiles (8 correlated cases):
D is1 correct/0 wrong/7 abstained; E is7 correct/0 wrong/1 abstained. The remaining
case has flat accents and multiple retained phases. This demonstrates pickup can
be searched rather than hard-coded away, given informative additional evidence;
it does NOT prove meter+BPM+duration sums alone resolve arbitrary pickups.

## Identifiability controls

An equal-quarter repeated sequence has the same sum-only objective under ALL48
candidate phases. With notation complexity, four phases0/12/24/36 remain equally
plausible, and the algorithm abstains. First audible note is not silently used
as the answer. In a second construction, staccato quarters and eighths+rests
produce identical sounding intervals but different written durations. Their
input hashes are identical. These are demonstrations of ambiguous observations,
not runtime failures and not claims about a unique source intention.

## Decision and useful next gate

The joint constrained formulation is a useful research direction, especially
compared with independently assigning each event. This prototype's useful gain
requires non-overlap and notation preferences; exact totals alone are largely
nonselective. It is not a finished general rhythm grammar. Pickup/phase needs
reliable musical evidence and explicit ambiguity handling. Articulation needs a
separate observation model instead of literal release-to-duration equality.

Keep #249 open and #250 draft. Next validate a fixed model of sounding-vs-written
length and real audio beat/accent observations, then use paired performance and
score references on independent material. Do not tune these48 variants into a
new held-out claim. Existing vocadito annotations cannot substitute for intended
notated duration truth. Tempo/meter changes, fermatas, multi-voice inference,
MusicXML/PDF readability and human editing costs remain untested.
