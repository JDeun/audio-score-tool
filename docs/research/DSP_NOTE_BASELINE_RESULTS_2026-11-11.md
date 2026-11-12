# DSP note baseline — completed CPU experiment, 2026-11-11

Related #245 / PR #246 / #214 / #200. No product settings, automatic edits,
main or other-session branches changed. This is a negative/limited baseline
result, not a claim that DSP has reached a performance ceiling.

## Execution and provenance

Actions42989661618, job130419138264 succeeded: pinned isolated install/pip-check,
Ruff,26 segmentation/clock/immutability tests,11 owned signal diagnostics, and
all40 original vocadito recordings with all3 segmentation arms and both A1/A2
annotations. No failed recordings or empty note outputs in any of the three arms.

PR head `aca4a177cf9d3b92206a72f2027d0ab22d685bc7`; actual PR merge checkout
`43ef355d1be32d05bba5d065939c6ac244f6a611`.
Script SHA256 `c5f0f77ec5dc7276f84e8d4938847cf2984f72230198088aa104e30fed770752`.
Original shared note scorer SHA256
`2ee6f18518e0f4887b9f0c163fff6cfcb964a05d21da1eddd6fcf8e031259194`.
Artifact13841810951 ZIP SHA256
`6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541`.

Downloaded ZIP digest matched Actions metadata. All40 input WAV hashes and both
annotation hashes matched the archived YourMT3 and Basic Pitch decoder experiments.
Original scorer and archive hashes matched. All macro means were recomputed from
40x2 rows; matched/unmatched note count conservation and F1 arithmetic checked.
The actual script Git blob matched the locally tested file. This is metadata
arithmetic/provenance verification, NOT independent re-inference or raw-audio
rescoring. Only metadata was published; raw notes/F0/source recordings were not.

## Full-recording note results

Original Hz references, onset50ms, pitch50cents including octave, optional offset
max(50ms,20% reference duration). Equal recording/annotator macro, no oracle shift.

| Fixed method | Pitch+onset F1 | With offset F1 | Predictions |
|---|---:|---:|---:|
| pYIN + nearest-pitch runs |36.353202%|22.149227%|2497|
| Same F0 + persistent-pitch hysteresis |35.124455%|13.906851%|2757|
| Same F0 + hysteresis + reattack split |35.346152%|14.170140%|2785|
| Previous YourMT3 original, matching corpus/scorer |54.340549%|30.937724%|1809|
| Previous Basic Pitch default, matching corpus/scorer |49.102129%|31.583077%|2086|
| Previous Basic Pitch onset0.65, matching corpus/scorer |54.192265%|37.257207%|1783|

Existing AMT numbers are archived baselines, NOT new neural inference in this PR.
Baseline decoder ZIP SHA256
`6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0`;
YourMT3 recovery ZIP SHA256
`a12e8dd9404d96d7a81a78f37e2639cb6e534caf48a3efd6cd1ab4d9d0ebc064`.
Both were checksum-verified and their raw-arm means recomputed.

Hysteresis versus runs: onset F1 improved14/worsened26 recordings; offset-inclusive
F1 improved1/worsened39. Reattack adds28 events in13recordings; versus hysteresis
onset F1 improved10/worsened3, but the aggregate remains below the simplest runs.
Neither larger event counts nor a smoother pitch contour establishes correctness.
The causal reason for every added/lost event has NOT been manually annotated.

## SAME F0, separate metric

- Raw Pitch Accuracy:80.528736%.
- Overall Accuracy including voiced/unvoiced:72.524536%.
- Voicing False Alarm on reference-unvoiced frames:43.519268%.
- Outside55..880Hz:0 of92966 reference-voiced frames.

The four checked F0 metrics match the prior pYIN receipt on every recording
(maximum difference0). That is metric reproduction, not proof of identical raw
F0 bytes. All three new arms use exactly the same in-run F0; their note-score
differences therefore arise after that track is formed.80.53% frame pitch is NOT
80.53% note or score accuracy. Comparing these percentages is not a percentage-
point loss calculation: their units and matching criteria differ.

Observed note precision/recall: runs33.7898%/40.4818%, hysteresis31.1738%/41.2786%,
reattack31.2165%/41.7831%. These suggest that merely retaining/splitting more
segments is not sufficient in these settings; they do not establish a full
causal decomposition of note-boundary, pitch, timing and voicing errors.

## Owned signal controls: useful behavior AND failures

Pinned CI synthetic calculations completed, not all musical estimates correct.
-220Hz/440Hz pure tones: median voiced F0 correct.
-Dominant second harmonic: strongest FFT component440Hz while pYIN recovers220Hz.
-Missing fundamental with440+660Hz: pYIN recovers220Hz despite FFT peak440Hz.
-Even-harmonic signal440+880Hz: pYIN reports440Hz; one cannot infer a hidden220Hz
 source intention from this signal alone.
-Pure880Hz at the configured upper edge: pYIN reports440Hz. This reproduces the
 local warning; the exact cause and sensitivity to range require separate tests.
 It does NOT explain all corpus errors: no corpus reference F0 is outside range.
-Vibrato stays one note; repeated440 with a gap and octave leap produce two notes.
-Silence and seeded noise yield zero notes in pinned CI. The earlier local noise
 false note under different library versions did NOT reproduce here; preserve
 the environment distinction rather than averaging the outcomes.

Lag correlation is also high at some subharmonics; the simple harmonic-sum score
can favor an octave alternative. Neither diagnostic is a calibrated confidence,
a unique fundamental proof, or an implemented correction policy. Stronger-than-
fundamental harmonics do not justify selecting the largest FFT bin.

## Resources and interpretation

The corpus script reports124.37seconds elapsed and684204KiB peak self RSS; this
excludes workflow package installation and the separate synthetic process. It is
one run, not a controlled speed ranking against earlier AMT jobs or an inference
latency SLA. CPU2threads, no GPU/LLM/learned weight downloads or training.

The original40recordings have been repeatedly used for development. No held-out,
mixture/stem, full polyphonic, MusicXML/PDF or human-edit-cost approval follows.
No post-result retuning or best-per-song choice was used. The synthetic diagnostic
has no corpus-level correction efficacy interpretation.

## Decision and next gate

Do NOT replace the existing AMT model with these three fixed DSP segmenters.
Do NOT enable the tested hysteresis/reattack rules in production. Keep pYIN as a
candidate acoustic evidence source, not ground truth.

Next experiment should separately (1) diagnose range/time/voicing behavior on
known signals and unseen development recordings, then (2) score unchanged AMT
notes and bounded octave/segmentation alternatives using periodicity, harmonic
and reattack evidence. Include raw-keep and abstention, normal-note damage,
coverage, actual note F1 and unchanged primary tolerances. No noisy universal
onset snapping. Freeze rules before evaluating protected data. The hybrid was
NOT run here; an absent gain from these DSP baselines does not rule it out.

#245 stays open for hybrid evidence and independent validation. PR #246 remains
draft. Full product CI is separate from the succeeded research job and must be
reported from its own status; no automatic merge or release selection.
