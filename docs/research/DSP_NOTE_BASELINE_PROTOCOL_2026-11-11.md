# DSP F0 -> note baseline: fixed development experiment

Related #245/#214/#200/#239/#244/#34. Research branch from main7e3458e.
No product changes, automatic correction, training, LLM, GPU, model credentials,
private song access or merge. Existing PRs are untouched.

## Question and actual scope

Can a classic pYIN tracker plus deterministic note segmentation compete with the
measured AMT outputs on the SAME solo-vocal development corpus? Frame F0 and note
transcription are different outputs; neither is a final notation/PDF quality score.
Harmonic diagnostics run on owned synthetic signals only. Applying harmonic or
periodicity evidence to existing AMT octave candidates is a subsequent experiment,
not implemented or claimed here. No inferred accuracy for unsupported polyphony.

## Frozen arms, before real-corpus inspection

- Common F0: librosa0.10.2.post1 pYIN,16kHz mono,float32,2048samples,hop160,
  55..880Hz,center=True,constant padding, otherwise upstream defaults. Voiced flags
  gate F0, like the prior F0 benchmark. No additional learned model or secret.
- A4=440Hz and nearest-semitone notes; retain unquantized F0 privately for separate
  original-Hz frame scoring. No reference-derived retuning/transposition.
- `pitch_runs`: contiguous voiced nearest-MIDI runs; minimum80ms.
- `pitch_hysteresis`: pitch change must persist5frames/50ms; when confirmed,
  backdate to the FIRST frame of that run. Smaller excursions keep the prior pitch.
  Every unvoiced frame resets state; never fill silence. Minimum80ms after segmentation.
- `pitch_hysteresis_reattack`: split the preceding arm's stable same-pitch interior
  at spectral-flux peaks only, never move its existing endpoints. Both resulting
  lengths>=80ms. Seven-frame F0 neighborhood must be entirely voiced, pitch median
  within0.35semitones of the note, range<=0.75, median voiced probability>=0.8.
  Spectral novelty uses n_fft512/n_mels64/hop160,center=True; normalized peak picking
  pre/post_max3,pre/post_avg10,wait8,delta0.2,backtrack=False. This hypothesis may
  over-split; added notes alone are not success. It is NOT #239's failed onset snap.
- Frames use their actual center time i*hop/sr; intervals end at the exclusive
  frame boundary, clipped to recording duration. No guessed half-window shift.
  Hysteresis backdating is not a global alignment. Performed seconds are not
  snapped to a music grid. Rounding cents/phase is not used in primary scoring.

Synthetic receipt: pure220/440/880, dominant second harmonic, absent fundamental
with second+third, even-harmonics ambiguity, vibrato, repeated same pitch with gap,
real octave leap, silence, seeded noise. These test candidate behavior rather than
asserting all pitch estimates must succeed. FFT peak, normalized lag correlation
and weighted six-harmonic sum are diagnostics, not calibrated confidence. In
particular subharmonic lags can also correlate strongly. The local compatibility
check used librosa0.11/NumPy2.3, not the pinned experiment: it exposed a high-bound
880Hz octave mistake and a noise-induced note. These observations are preserved,
not used to widen the fmax or change thresholds before the fixed CI run. The fixed
range intentionally matches prior F0 evaluation; boundary sensitivity needs its
own later protocol. The local check is NOT vocadito evaluation.

## Evaluation and comparability

Original vocadito v3 archive58492257bytes/MD5dea40fd18f14d899643c4ba221b33a46,
40 complete recordings; original A1/A2 Hz annotations. Corpus is repeatedly used
development data, not independent holdout. Shared original scorer from main:
pitch50cents including octave, onset50ms, offset max50ms/20% duration. Raw references
are first read only AFTER all predicted arms are created. References never feed
segmentation. Event/source fingerprints must remain unchanged after scoring.

Report all3arms x40recordings x2annotators, empty predictions as zero, actual
runtime/preparation failures separately. A missing/failed/duplicate row prevents
a complete mean. Macro gives each recording and annotator equal weight. Also
report precision/recall, prediction counts, strict unmatched counts, and per-file
improved/worse counts. Unmatched IDs are NOT human-confirmed causal error labels.
F0 metrics include unvoiced regions and out-of-range reference coverage, independently
from note F1. Same F0 among the three arms isolates segmentation.

Reuse existing YourMT3 and BasicPitch baseline/improved metadata only AFTER source
WAV/reference/scorer identities match. Do not rerun large models just for a table.
Do not claim hardware-normalized speed comparison with prior runs. Exact runtime
versions are recorded even for transitives not explicitly pinned; bit-identical
outputs are not presumed. No oracle candidate choice or per-song winner.

## Execution, safety and decisions

One standard Ubuntu CPU job,2threads,25minute hard cap. PR-open/reopen or explicit
dispatch only; documentation pushes do not repeat inference. Store inputs/F0/notes
and model logs inside a private runner directory. Upload only named JSON receipts,
no media, full note arrays or user material. Failures remain visible. No cloud
inference API or extra credentials. Owned synthetic diagnostics do not qualify
real audio -> note -> notation -> publishable score.

Local preflight:26 tests and compile passed with installed runtime; synthetic
compatibility executed with the stated version mismatch. Real pinned Actions
inference pending at protocol publication. Read actual receipts for results.

Next gate: decide whether DSP is an independent candidate, warning aid, source of
bounded alternatives, or unsuitable for the evaluated role. Before integration,
verify pitch-correction harm/coverage, independent recordings and downstream
notation/editing cost. Do not promise improvements from math alone.

First-party APIs:
- https://librosa.org/doc/0.10.2/generated/librosa.pyin.html
- https://librosa.org/doc/0.10.2/generated/librosa.onset.onset_detect.html
- https://mir-eval.readthedocs.io/en/latest/api/transcription.html
