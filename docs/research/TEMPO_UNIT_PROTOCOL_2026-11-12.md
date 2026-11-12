# #259: pulse units, equivalent tempo families and serialized timing

Research branch from #258 head406b93ea59ba4cda53eadea37325822094c4ce94.
User correction: an exactly doubled pulse rate can denote eighth notes, not
quarter notes. Do not confuse nominal-QPM errors with unusable rhythmic timing.
No main, production, other-session branch or automatic score edits.

## Fixed input and evidence scope

Replay the original completed Actions43122028203 artifact13900383659, not new
learned inference. Original ZIP SHA256
`d62e26589018d0690e65104858ff37cd2763e5c9cce22166cd2b854d80fff08d`, report.json
SHA256`36f003bdff729fb63d2950930a49791fe411809551459843bb2dda961f417f82`.
Same16 actual drum-kit WAV recordings represented by frozen predictions. Beat This
was admitted on12 published validation-fold sources, unavailable on4. No sources
replaced, no hidden denominator changes. These previously inspected inputs are
DEVELOPMENT evidence, not unseen testing. WAVs, model weights, raw envelopes and
reference score performances are not downloaded or newly inferred here.

GitHub Actions may use its normal job-scoped GITHUB_TOKEN with actions:read solely
to read that repository artifact; no user-provided secrets or external service
credentials. Exact ZIP and JSON hashes must match; expired or unavailable artifact
is a blocked experiment, never silently regenerated/replaced. Archive is read in
memory without path extraction. File sizes, filenames and16 unique IDs checked.

## Frozen experiments

1. Five prior methods: hit_mean8, hit_consensus, flux_mean8, flux_consensus,
   beat_this_cv. Keep original rates; generate u={0.5,1,2} quarter-notes per
   detected pulse WITHOUT reference/name/meter/downbeat. qpm=pulse_rate*u.
   Return all3, automatically select NONE. Candidates remain ambiguous.
2. Preserve strict +/-4% nominal-QPM metric. Add reference-assisted family metric
   if one of the3 qpm values is within4%. Report same12 paired sources AND all16
   coverage, unavailable, alias-only and other errors. This is a NEW METRIC,
   not a model accuracy gain or an automatic correct unit choice.
3. For12 fixed Beat This pulse timestamp sequences, recompute60/median(diff).
   Where reference family matches, evaluator alone selects u. Compare each
   interval with60*u/reference_qpm; record fractions within4% and10%, unusually
   long>1.5x or short<0.67x intervals, and relative cumulative timing residuals.
   Anchor at FIRST PREDICTED pulse (not known score downbeat). P95 uses nearest
   rank; no time-axis fitting, event dropping, tempo smoothing or offset search.
   Nominal metronomic tempo is NOT independent annotation of each actual beat;
   residuals include human microtiming and detector variations, not proven
   per-beat mistakes. No calibrated safety threshold or beat-F1 claim.
4. All3 unit hypotheses map measured timestamps -> pulse positions -> quarter
   positions -> seconds. Preserve count and times numerically, no pulse removal
   or insertion. This invertibility holds even for a wrong musical unit; it
   therefore CANNOT identify the correct one or reconstruct missed beats.
5. Four authored monophonic score fixtures (4/4 repeated notes/rest,3/4 dotted
   rhythm/rest, explicit1-quarter pickup, cross-bar tie) x3QPM(75,120,184)
   x3pulse units =36 conversions. Written pitches/count/notes/rests/pickup/unit
   are PROVIDED, not inferred from WAV. Encode metronome beat-unit/per-minute
   plus sound tempo in quarter-notes/minute; split held notes at barlines with
   explicit ties. Read back this restricted generated MusicXML subset, then
   serialize MIDI with mido1.3.3 at960ticks/quarter and read timing back. Validate
   note pitch/count/reattacks, total duration and <10microsecond event-time error.
   Keep performed and written coordinates distinct. Analytic negative control:
   omitting beat-unit and treating pulse_rate as QPM scales durations by u.
   This is not MusicXML XSD, external notation-editor or product PDF validation.
6. Fixed adversarial controls: exact double pulse, one missing pulse, middle
   switch between pulse rates with unchanged median, outside-family2/3 rate,
   invalid/empty sequences, corrupted receipt, inconsistent XML playback tempo.
   A correct median/family alone must not conceal missing events. No additional
   ratios are admitted after inspecting the previously wrong157BPM case.

No onset/pitch/AMT F1 gains, no automatic unit-selection success, no downbeat,
barline or pickup detection claims. Higher family scores cannot approve product
integration. Unit-aware representation is an engineering prerequisite; choosing
units without reference and mixed-song validation remain separate work.

## Execution

CPU Python3.11, mido1.3.3, pytest8.4.2, ruff0.16.6; one bounded job. Source hashes,
original receipt hashes, all evaluated rows and fixture results go into new JSON.
26 local tests passed before remote execution. Original model predictions are
immutable. Record unsuccessful or incomplete trials; no post-result tuning.
Report-only commits do not trigger repeat inference.

## Primary format sources

https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/metronome/
https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/sound/

Related #252 #249 #258. Keep #259 and draft research PR open.
