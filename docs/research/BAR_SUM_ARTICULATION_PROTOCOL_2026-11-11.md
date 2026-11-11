# #249 follow-up: sounding-versus-written duration and waveform-derived meter evidence

Research only. Base: #250 \`research/bar-sum-joint-rhythm-20261111\` head
\`54d9cbff8362b255d79b365a3c5c4f57a6f1c88b\`.
Do not merge, alter production settings or change another session's PRs.

## Why

#250's known-phase joint notation inference was 50.56% exact written-onset+duration
agreement on 48 correlated symbolic cases; the staccato-60% condition scored 4.44%.
Unknown first-bar phase was almost always abstained without supplied accents and
improved with *idealized synthetic* rhythmic strengths. These are NOT real audio
transcription or user editing quality measurements.

This follow-up tests two independent changes:
1. Permit a latent sounding gate: notation duration can exceed audio sustain.
2. Extract accent evidence by signal analysis from newly synthesized accompaniment
   pulses rather than passing beat/downbeat labels directly to the selector.

## Frozen models and conditions

- Original 12 authored phrases, same four profiles and generators from #250.
  Add two predeclared profiles per phrase: per-note mixed gate uniformly in
  [0.48,1.06] with fixed onset/release jitter, and variable short gate uniformly
  in [0.48,0.78]. These additional cases are still authored, NOT an untouched
  holdout. Total 12 x 6 = 72 correlated cases.
- All methods receive the SAME observations, explicit correct meter (4/4,3/4 or
  6/8), fixed BPM/beat unit, the SAME candidate durations/starts and notation
  complexity cost. Identity, MIDI pitch, attack count are immutable; no inserted
  notes, changed reference or learned checkpoint.
- Original C: joint dynamic program with cost for literal sounding offset.
- New: same DP, with a latent sounding fraction chosen from
  \`(1.0, penalty0.0), (0.75, penalty0.09), (0.50, penalty0.17)\`.
  Onset penalty is the original squared error; offset squared error is evaluated
  at start + fraction x written duration. This is a hand-set **hypothesis**, not a
  probability calibrated to recordings. The prior staccato failure motivated
  these trials; performance on the old48 cannot be independent validation.
- A/B duration choice is tested with the **correct phase supplied in both**.
  They do not estimate downbeat and are diagnostic only.
- Phase: old and articulated DP each with no accent, and with the SAME derived
  accent observations. Truth phase is never given to unknown-phase branches.
  Preserve abstention where the frozen near-tie margin retains multiple phases.

## Generated audio source and feature extraction

The audio is **newly synthesized other-part percussion pulses**, NOT recordings
or actual user tracks. Known ground-truth phase is used ONLY to generate the
waveform. The selector receives a waveform-derived low-band spectral energy
novelty at regular candidate positions and clock metadata, NOT the phase, beats,
score or generator's labels. Synthetic downbeats have stronger bass transients
than synthetic non-downbeat pulses; this is an intentionally easy source, so
successful inference cannot establish performance on real acoustic recordings.
Do not call it a real beat/downbeat detector or real audio validation.
Audio bytes stay transient; report only hashes, accent counts and metrics.

## Metrics

- Primary symbolic exact written onset **and** duration per note ID; onset-only,
  duration-only, exact rest-interval F1 as separate descriptive metrics.
- Measure old vs new per-phrase and profile, improved/worse/equal cases, exact
  note-ID gains/losses including clean-note damage, and structural validity.
- Phase outcomes per 72 cases: correct, wrong, abstain, and reference in retained
  near-optimal set. Conditional phase accuracy must NOT be reported as all-case
  accuracy. Audio presence is an additional input, not a pure algorithmic effect.
- No scores or test truths enter note/phase selection. Source hashes, settings,
  runtime, all cases, failures and partial coverage retained. Do not publish a
  full macro unless all72 planned IDs and all6 arms completed.
- Stage0 old48 are development/reused. The24 new artificial variants are still
  hand-designed and correlated with the same 12 phrases. No significance claim,
  model-generalization claim, real-song note F1 or MusicXML/PDF claim.
- No threshold tuning, manual best-case selection, rerun with a changed
  decision rule after inspecting the results, or normal-event damages hidden
  behind the mean. If negative, preserve the negative result.

## Execution and decision

Standard GitHub-hosted Ubuntu CPU, Python3.11, numpy1.26.4, two math threads,
no GPU/authentication/public weights/LLM/training/paid APIs. One bounded
on-PR-open job with test/compile/lint before the evaluation; only a JSON
artifact is uploaded. Later report-only commits do not rerun inference.

A positive result justifies *evaluation on real score-performance pairs*,
preferably a time-aligned, rights-checked subset. ASAP is a potential research
dataset but has non-commercial-sharealike data terms and multi-voice classical
piano scope: verify rights, actual score-performance note identity/clock
alignment, and exclude unsupported rubato/tempo/meter changes before claiming
comparable results. A valid notation reference is not interchangeable with
vocadito's performed-note F1 labels.

Production acceptance requires real performances, representative genre,
actual audio-derived beat/downbeat evidence, stable handling of staccato/legato,
pickup/ambiguous phase, MusicXML/PDF readability and time-to-publish. Keep
#249/#200/#34 open. Do not enable this prototype as an auto-corrector.
