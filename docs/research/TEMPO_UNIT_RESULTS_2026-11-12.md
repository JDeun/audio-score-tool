# #259 / #260 — completed pulse-unit and playback invariance experiment

## User correction and decision

The user's point is correct: a doubled pulse rate can represent half a quarter-note
per pulse. Eighth=150 and quarter=75 describe the same time scale. Do not classify
all half/double estimates as failed rhythm perception. Preserve BOTH pulse rate
and the associated note-value hypothesis, instead of treating every output BPM as
quarter-notes/minute. Do not gate tempo on downbeat or meter identification.

This study supports unit-aware representation. It DOES NOT yet automatically
identify the correct note unit or infer a complete score. No main, product/default,
automatic score, other-session, training, GPU or paid/API-provider changes.

## Execution and receipt verification

- Issue https://github.com/JDeun/audio-score-tool/issues/259
- Draft PR https://github.com/JDeun/audio-score-tool/pull/260
- Final successful CPU Actions https://github.com/JDeun/audio-score-tool/actions/runs/43130672916
- Executed head858582b79c45787760c51980effd15937353cd94; PR merge checkout
  315272e9faa912b768d170e9cd3d9068c96fc61a. Pinned mido1.3.3, pytest8.4.2,
  ruff0.16.6; lint/compile/regression/evaluation completed.27 tests including the
  numerical-boundary regression. Research Evidence Contracts also succeeded.
- Final artifact13905625095 ZIP SHA256
  d276100fd9b6a5e8ad86a218e68f53653acafb0017cb507f98827de5763072e0.
  report.json SHA256
  0313d24d6a4d4ad3ef26f7ad8896012586effc60df490381809aa2f85ecb19c7.
- Original model predictions from completed #258 Actions43122028203/artifact13900383659.
  Original ZIP SHA256d62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d,
  JSON SHA25636f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82.
- This NEW unit/sequence/serialization experiment replays fixed real predictions;
  no original WAV/model inference was repeated. Normal job-scoped actions:read
  permission fetched only our original artifact. No external API credentials.
- Audit verified both ZIP digests, source hashes,16 unique source IDs, all80
  method evaluations,12 median-IBI calculations, every grouped denominator,
 36 authored conversion cases and the timestamp roundtrips. All source rates and
  source WAV hashes remain identical to the original receipt. Nominal reference
  is accessed only by evaluation, not unit-candidate generation.

### Numerical correction after first receipt audit

Initial run43130105062 completed, but independent arithmetic found that a
mathematically exact10% boundary was represented as0.10000000000000009. The same
binary issue affected6 intervals exactly on4% boundaries. Added a1e-12 numerical
comparison allowance and one regression, then re-ran the unchanged inputs.
No musical thresholds, model predictions, candidate ratios, source selection or
track-level successes changed. Interval counts changed468->474 at4%,524->525
at10%. Independent exact-decimal Fraction arithmetic confirms final counts.
This is a disclosed comparator fix, not post-result musical parameter tuning.

## Same12 model-admitted recordings: distinct evaluation questions

Every predictor's original numeric rate is kept. All3 hypotheses u={0.5,1,2}
are generated, qpm=pulse_rate*u. No automatic unit winner is selected. Reference
family scoring allows these three possibilities and is not a new model gain.

| Method | Nominal QPM within4% | Tempo family within4% | Alias-only | Other wrong |
|---|---:|---:|---:|---:|
| Detected-hit mean8 |7/12|10/12|3|2|
| Detected-hit consensus |7/12|10/12|3|2|
| Continuous-flux mean8 |8/12|11/12|3|1|
| Continuous-flux consensus |8/12|11/12|3|1|
| Beat This matched validation fold |9/12|11/12|2|1|

The specialized model is still better at selecting nominal QPM on this subset,
but NOT better at obtaining the correct half/normal/double family than continuous
DSP.75% vs91.67% for Beat This is a changed evaluation question, not an improved
inference model. These reused sources are development evidence, not independent
mixed-song or composition-disjoint tests.

### Keep all16 source coverage

| Method | Strict/all16 | Family/all16 | Evaluated | Unavailable |
|---|---:|---:|---:|---:|
| hit mean8 |8|14|16|0|
| hit consensus |9|13|16|0|
| flux mean8 |9|15|16|0|
| flux consensus |10|15|16|0|
| Beat This |9|11|12|4|

Do not compare DSP15/16 to learned11/12 as a paired ranking. Four sources remain
unadmitted to learned inference because published file-fold membership was not
established, NOT because they failed this new experiment. Earlier training-
overlap and validation-selection caveats still apply.

## New result: actual half/double sequences are stable, not just their medians

Diagnostic ONLY: evaluator supplies the reference-compatible unit, then checks
every original interval against60*u/reference_qpm. First predicted timestamp
anchors relative time. No reference downbeat, offset fitting, event deletion,
smoothing or interpolation is used. Nominal tempo is a metronomic reference,
not an independent annotation of each performed beat; human microtiming and
sampling quantization contribute to residuals.

| Source / reference | Observed pulse/min | q per pulse | Expected interval | Intervals within10% | Max relative cumulative discrepancy |
|---|---:|---:|---:|---:|---:|
| drummer7/session2/93, quarter=75 |150.00|0.5|0.400000s|60/60|60.00ms|
| drummer4/session1/5, quarter=184 |92.31|2.0|0.652174s|36/36|45.22ms|

For the11 reference-family-matched sequences:525/525 intervals within10%,
474/525 within4%,0 intervals longer than1.5x or shorter than0.67x expected.
The remaining157->103.45 source is not admitted by the frozen0.5/1/2 unit set.
We did not introduce a2/3 ratio just to turn that known error into a success.

These findings support interpreting these two original alias cases as usable
pulse clocks under the correct unit. They are NOT automatic unit-selection,
beat-location F1, correct barlines or final-score proof. Four-point caveat:
- relative anchoring intentionally removes unknown absolute phase;
- reference-compatible unit is evaluator-supplied;
- the interval-count diagnostic does not prove no missed musical event;
- a half-rate sequence does not recover intermediate beat observations by itself.

All3 hypotheses for each of12 real pulse sequences also preserve original
seconds/counts under seconds->pulse->quarter->seconds conversion; maximum floating
roundtrip error3.552713678800501e-15s. This invertibility is true for wrong units
as well, so it cannot select the correct musical unit.

## New output test:36 authored MusicXML/MIDI conversions

Four authored monophonic scores x3QPM(75,120,184) x3units =36/36 pass.
Includes same-pitch reattacks, rests, dotted rhythms, supplied pickup and ties
across barlines. Display uses eighth/quarter/half + per-minute, while sound tempo
stores quarter-notes/minute. Read generated restricted MusicXML back, merge only
explicitly tied fragments, then independently serialize/read MIDI timing.

All pitches, actual reattack counts, rest gaps, bar occupancy and total duration
were preserved. Maximum MIDI event-time discrepancy3.913043475911593e-7s,
below1 microsecond (integer MIDI tempo rounding). Analytic unit-omission control
is correct only for12/36 unit=1 cases; the other24 duration scales are wrong.
That negative control is an arithmetic check, not36 separate naive XML renders.

The correct written score, pulse-coordinate event positions, unit, meter and
pickup are PROVIDED. These are not36 inferred songs, not recovery of actual
GMD melodies, not the product exporter, not full MusicXML XSD validation, not
editor/PDF visual QA, and not measured human correction time.

## Failure controls and resulting architecture

Constructed exact-double pulse sequences with one missing pulse or a middle
switch of pulse spacing still have a valid median-rate family. Interval/relative
time diagnostics correctly expose the gap/change. Thus family success is not
sufficient to accept an entire grid. Malformed inputs, corrupt source receipts
and mismatched displayed/playback units are rejected.

Proposed research representation:
- measured pulse rate and original pulse timestamps (never discard on alias alone);
- unit hypotheses and corresponding quarter-note BPM;
- separate evidence for choosing a unit, and separate observed-sequence quality.

What is now demonstrated: declared unit conversion can preserve playback and
score timing; the two real alias examples support this interpretation rather
than arbitrary rhythm failure. What is NOT demonstrated: automatic selection
among75/150/300 for an unknown recording. Metadata/user input or constrained
notation/context must be evaluated as a separate selector, without using the
reference score to select a winning unit and calling it automatic accuracy.

Keep #259/#252/#249 open and #260 draft. No product defaults were changed.
