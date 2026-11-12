# Offset-tail study — Basic Pitch complete; YourMT3 in progress at this snapshot

Related PR #248 / #200 / #245 / #215. Product defaults, main and other branches
are unchanged. This is a partial model-completion snapshot, not a release approval.

## Actual execution and audit

- Actions42999100639; BP job130450466370 succeeded after fixed runtime install,
  remote Ruff and31 targeted tests. YourMT3 job130450466677 is in actual inference
  at this snapshot; its result is not inferred from BP.
- Experiment head85f362ab1e9af80f14578c515f762d813bdc8eea; actual PR merge checkout
  7953ff7368c7b13d6fbd8181af76c8daa596280d. Later docs do not identify inference code.
- Downloaded artifact13845741903 ZIP SHA256
  bb7f439a61b8f49dda1fe32a3e8889952e5b73ad0f4597449df62c987b873c6d matched GitHub.
- Verified40/40 planned IDs,2base decoders x3arms x2annotations, all statuses scored,
  all row-to-macro arithmetic, paired improved/worse counts, count conservation,
  unique-anchor partitions and exact onset-F1 invariance. No failed recordings.
- All40 WAV/A1/A2 hashes, archive/scorer and BOTH raw event fingerprints matched
  #239's archived BP receipts. Default decoder replay passed on every recording.
- Core SHA256 5adb61edca4b68deac9a0f9f6f619009d8295f006a5913b9f14c6a30f6ce0b4c;
  runner44730f903b4e8eddc1755ff0ae89793052c43abc129f15028b91b0d16562939e.
  These match locally tested files; their remote Git blob identities also match.
- This is receipt/provenance/arithmetic verification, not independent model
  re-inference or rescoring raw recordings. Full product CI is a separate scope.

## Complete forty-recording BP note results

Original-Hz A1/A2, pitch50cents incl octave, onset50ms, offset max(50ms,20%ref length).
Equal recording/annotator macro. The SAME base prediction is used for all arms.

| Decoder | Arm | Offset-inclusive F1 | Delta | Changed offsets | Improved/worse recordings |
|---|---|---:|---:|---:|---:|
| default | raw |31.583077%|0|0|0/0|
| default | activation tail |31.914701%|+0.331624pp|31|9/3|
| default | same + pYIN corroboration |31.726278%|+0.143201pp|7|4/1|
| onset0.65 | raw |37.257207%|0|0|0/0|
| onset0.65 | activation tail |37.659315%|+0.402108pp|37|10/3|
| onset0.65 | same + pYIN corroboration |37.393240%|+0.136033pp|6|3/1|

Pitch/onset F1 is EXACTLY unchanged for every recording/annotator/arm: macro
49.102129% default and54.192265% onset0.65. Event counts2086/1783 are unchanged.
This is a modest actual offset-score gain, not an onset/segmentation improvement.

Exploratory paired-recording bootstrap95% delta intervals (not independent or
multiple-comparison-corrected) for onset0.65 are [+0.0364,+0.8083]pp activation-only
and[-0.0016,+0.3266]pp corroborated. The latter includes zero. No post-result
threshold tuning or per-recording winner selection was performed.

## Normal-event damage and coverage

Among37 activation-only changes for onset0.65:
- A1:25 unique pitch/onset anchors;11 offset mismatches become matches,3 matches
  become mismatches,6 remain matches,5 remain mismatches;12 changes unassessable.
- A2:21 unique anchors;10 improve,3 worsen,4 remain matches,4 remain mismatches;
  16 changes unassessable.
These are two conditional annotation-based evaluations of the SAME37 changes,
not74 independent musical corrections or independently reviewed damage labels.

The corroborated arm changes6 events: A1 has3 repair/0harm/1unassessable; A2 has
2repair/1harm/2unassessable. Additional guard does not prove harmlessness.

For onset0.65 screening across1783 events:1135 already near observed release,
184no release,92would overlap,229source overlap,101release outside allowed range,
5no early sustain,37proposed. This is procedural coverage, not error causation.
Only a small part of the whole output was edited; overall quality remains limited.

## Separate meter/BPM calculation controls

These are designed known clocks, NOT audio-based beat or downbeat estimates.
For explicit tempo unit u in quarter lengths, bar duration is (60/BPM)*(4*n/d)/u.

| Constructed example | Correct bar interval | Error from first-note anchoring |
|---|---:|---:|
|4/4, quarter120, first note on downbeat|2s|0|
|3/4, quarter120, first note on downbeat|1.5s|0|
|4/4, quarter120, one-quarter pickup before full bar|2s|0.5s phase error|
|4/4, quarter120, first note after two quarter rests|2s|1s phase error|
|6/8, dotted-quarter60, first note on downbeat|2s|0|

Treating actual120BPM as121 produces0.826446s error after50full4/4bars (same
indexed bar). A designed four-bar120→four-bar100 change incurs1.6s at the endpoint
if the original tempo is extrapolated. These arithmetic examples demonstrate why
meter/BPM plus a VERIFIED downbeat, appropriate tempo unit and changing tempo map
are needed. They do not show that an automatic estimator has solved those inputs.
The metrical controls were never used to move performed note offsets.

## Current decision

No product automatic offset correction: improvements are small, some recordings
worsen, conditional normal-event damage remains and many edits are unassessable.
The40recordings are repeatedly used development data; no independent holdout,
mixture/stem, MusicXML/PDF readability or human editing-cost gain is established.

YourMT3 correction uses BP as an extra evidence model and awaits its own final
receipt. Do not report its result from this BP study. Both branches/rules remain
frozen; documentation pushes do not rerun or cancel either model job. Keep PR#248
draft and all relevant music-quality issues open.
