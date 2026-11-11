# BPM from rhythmic repetition — completed tempo-only CPU study

Issue #252 / draft PR #255. User clarification is decisive: this tests **BPM
from rhythmic patterns**, not the first beat of a bar. Meter/downbeat ambiguity
is neither an inference prerequisite nor a failure criterion in this study.
No main merge, production defaults, automatic correction, other-session branches,
user songs, external metadata API calls, model credentials, GPU or training changed.

## Execution and independent receipt checks

- Successful Actions run: https://github.com/JDeun/audio-score-tool/actions/runs/43043360699
- Experimental head b0833d2a791bf8844d2a575278f698e277047f56; actual PR merge checkout
  cd59a5c24b9efd78e6088bc14c4c7e1e3dced8fc. These are distinct Git objects.
- MIDI job130600724136; audio job130600724407. Pinned dependency/pip checks,
  Ruff, compile, 16 targeted tests and both actual evaluation jobs completed.
- Initial run43043019663 stopped BEFORE dataset evaluation because librosa0.10.2
  emits a Python3.11 importlib.resources.path deprecation under the repository's
  warnings-as-errors test policy. The retry filters only this exact third-party
  import warning in the test command; numerical warnings, assertions, algorithms,
  data selection, scorer and all musical parameters remain unchanged.
- MIDI artifact13866666438 ZIP SHA256
  f05553e111a1de55df4f7a716605df5a734d3e10d67e8cb0b107829f7a49515d;
  report.json SHA2561dc12bf478e4a22f8d2ac663402e70a22473e3e21d2cdcafc26d1151228fc068.
- Audio artifact13866262051 ZIP SHA256
  83aa762fa222305a179af58d6c20ddb3268fc721fb6e8d8248fa2b646589b507;
  report.json SHA256e8589c0db1d4a701714aca24567cf761ee8adab0bb2aa47ec0328b714c256bc2.
- Downloaded ZIP digests match Actions metadata. All planned IDs, source/runtime/
  settings, new-script hashes, every nominal/half-double decision, candidate recall,
  medians and grouped denominator arithmetic were independently recomputed.
- All53 overlapping MIDI source hashes match the earlier #253 receipt. The four
  previous WAV source hashes match #254. Excerpts here are up to24s, not necessarily
  the prior12s excerpt; no direct claim of onset-F1 improvement over #254.
- Audio used57,217,598 bytes in32 strict HTTP206 range requests; full5.11GB ZIP was
  not downloaded/hash-verified. Member CRC and publisher metadata linkage checked.
- This is a receipt arithmetic/provenance audit, not a fresh independent rerun of
  raw audio. Original audio/MIDI/envelopes were not published.

## Fixed design, no reference BPM input

All estimators receive only onset-activity values/time and a duration. No song
BPM, meter, first-beat phase or annotated hit roles reach the WAV estimator.
Four methods: attack-count/minute NEGATIVE CONTROL; windowed ACF with flat tempo
preference; SAME ACF with predeclared broad120BPM preference; librosa tempo with
explicit120BPM preference. The latter preferences are not per-song metadata.
Only after predictions finish is catalog nominal BPM read for evaluation.

Success means top1 BPM is within4% of nominal catalog tempo. Half/double values
remain errors, not silently counted as successes. Top3 recall is a separate
oracle diagnostic, never actual automatic-selection accuracy. These tests do
not estimate meter/downbeat or note/score accuracy.

Data attribution: Groove MIDI Dataset v1.0.0, Google LLC, CC BY4.0,
https://magenta.tensorflow.org/datasets/groove . The audio is the original aligned
Roland TD-11 sound-module recording of human drumming, not acoustic full-band music.

## Human MIDI event diagnostic

All134 planned recordings completed: official test129 (all4/4), supplemental
non-test3/4 five. Same24s maximum observation; reference tempo is NOT passed to
inference (MIDI tempo map is necessarily used to convert ticks to seconds).
The following primary representation uses supplied kick/backbeat event identities.

| Method | Within4% /129 | Half/double /129 | Other wrong /129 | Unavailable /129 |
|---|---:|---:|---:|---:|
| Count attacks/minute, negative control |3|5|79|42|
| Repetition ACF, no tempo preference |25|44|18|42|
| Same ACF + fixed broad120 preference |57|12|18|42|
| librosa + fixed120 preference |39|15|33|42|

The42 unavailable are <4s observations: two beat clips and40 fills. They remain
in all planned denominators and are not converted into false120BPM estimates.
With the ACF+prior method, regular beat recordings give55/77 correct (two too
short included); fills give2/52 correct (40 too short included). Thus57/129 is
not comparable to a favorable success-subset rate of57/87 without disclosure.

Adding hi-hat event timing changes ACF+prior to55/129 and librosa to46/129;
more rhythmic attacks do not mechanically imply a better nominal BPM estimate.
For the five supplemental3/4 recordings, kick/backbeat ACF+prior is1/5; adding
hat timing is2/5 (librosa2/5). There is no official-test3/4 accuracy claim.
All nominal references are inside the searched40..240BPM range.

## Actual WAV tempo estimates — no MIDI roles provided

Twelve predeclared recordings were evaluated: four previously studied files
(three test4/4 and one validation3/4) plus eight additional test4/4 files
(six beats, two fills). Extra files are selected by hash and duration only.
They are not12 independent popular songs; some GMD eval-session exercises
repeat musical patterns across drummers. No claim of representative generalization.

Primary WAV representation is the previous DSP's detected-hit timing train,
with instrument-role names ignored for tempo inference:

| Method | Previous4 correct | Additional8 correct | All12 within4% | Half/double | Other wrong |
|---|---:|---:|---:|---:|---:|
| Count detected attacks/minute |0|0|0/12|0|12|
| Repetition ACF, no tempo preference |1|1|2/12|8|2|
| SAME ACF + fixed broad120 preference |1|6|7/12|4|1|
| librosa + fixed120 preference |1|6|7/12|4|1|

The continuous spectral-flux input does not classify kick/snare at all. Its
all12 nominal results are0/12 for flatACF,6/12 for ACF+prior and7/12 for librosa.
The same inference methods are compared, not a per-recording winner ensemble.

Concrete ACF+prior detected-hit examples: nominal138 ->138 (one137),102 ->102,
120 ->119/120; failures75 ->150,93 ->182/184,157 ->105. The last is not half/double
and remains an ordinary error. The four half/double errors are nominal failures
although they show related rhythmic periodicity. Prior120 helps some candidate
choices but is not guaranteed to resolve the perceptual/annotated beat level.

For ACF+prior detected-hit input, the reference-compatible value occurs among
its top3 candidates on12/12 excerpts. **This is NOT100% tempo accuracy**: only
7/12 top1 choices are correct. An external exact-recording tempo prior might
help choose among candidates, but no provider was called, no metadata selector
was implemented, and ground-truth reranking is not reported as product quality.
The additional eight's6/8 and prior four's1/4 must be shown together; do not
promote6/8 alone to a general accuracy claim.

## Decisions and next useful comparison

The user's proposal is supported as a useful tempo module: recurring drum
patterns can yield BPM estimates without meter/downbeat determination. ACF/
librosa substantially outperform merely counting attacks on this sample, but
metre-level aliases and short/nonstationary fills remain material limitations.
The current broad prior improves these observed choices, not proof of a learned
or universally reliable beat interpretation.

Keep tempo output independent: candidate BPMs, repeated-pattern strength,
uncertainty/short-evidence status. The next non-oracle comparison should add a
fixed candidate selection rule using longer consistent groove context or
permitted recording-matched metadata, against established audio beat trackers
on the SAME clips. Explicitly keep 1x/0.5x/2x alternatives and ordinary errors.
Do not keep tuning on these results and relabel them held-out. Testing the
same methods on licensed mixes and separated drums is still necessary; these
inputs were already drum-kit-only. None of this establishes accurate MusicXML,
original note transcription, automatic barline correction or lower edit time.

Keep #255 draft and #252/#249/#34 open. No automatic changes to user scores.
