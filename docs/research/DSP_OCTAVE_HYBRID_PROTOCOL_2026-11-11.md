# DSP octave-evidence hybrid — preregistered CPU development experiment

Follow-up to #245/#246, linked #214/#239/#244/#200/#34. Based on #246 `44a4770`.
Research-only; no production editor, defaults, main merge, learning, GPU, gated
model, paid API, LLM, user songs or other-branch modifications. Keep draft.

## Question and scope

Do pYIN proposals become more reliable when corroborated by period and harmonic
structure? This is a pitch-only study: note counts, order, onset, offset, program
and channel remain fixed. It does not fix repeated attacks, segmentation or
notation. The earlier arbitrary onset snapping and failed DSP segmenters are not
reused. A lack of gain is a valid outcome, not a reason to tune this corpus again.

## Fixed paired arms

On each of40 original vocadito recordings, infer one unchanged YourMT3 noPS result
or Basic Pitch0.4.0 ONNX result using the existing verified asset loaders. BP also
uses its previously selected onset0.65 decoder on a fresh copy of the same raw
activations (frame0.3/min127.7ms/Melodia). Both BP decoders are reported; neither is
selected per recording. Public prior receipts lack raw predictions, so this fresh
inference is necessary for a genuine paired edit, not a claimed cache reuse.

1. Raw notes, no edits.
2. pYIN-only octave proposals.
3. Identical proposals, accepted only with corroborating DSP evidence.

Shared pYIN: librosa0.10.2.post1,16kHz,2048sample frames,160hop,55..880Hz,
centered constant padding; A4=440. No time shift, global tuning or reference
boundaries. Proposed notes must be isolated from other predicted pitched events,
>=160ms; interior margin max40/min100ms or15% duration. Need >=6 observed and voiced
frames, >=80% voiced, median voiced probability>=.8,90-10 percentile spread<=.8
semitones, median within.25semitones of an integer and an exact+/-12 change.
Observed F0 must be >one semitone inside the range; no pitch squashing. These are
heuristic conditions, not calibrated probabilities or proof of monophony.

For each proposal, use up to5 fully note-contained128ms windows, preserving the
same windows for both frequency hypotheses. Fractional-lag normalized correlation
is computed without multiplying by a window. Hann/8192FFT energy over60..4000Hz
is scored inside harmonic bands (+/-max(1.5 original FFT bins,1.5%F0)); at most64
harmonics. Target must have correlation>=.85 and harmonic coverage>=.65. A downward
change additionally needs >=.10 correlation improvement, >=.08 coverage improvement
and >=.08 odd-harmonic energy. Upward proposals need lower-hypothesis odd energy
<=.02. At least3 windows and >=80% supporting windows with RMS>=-50dBFS are needed.
The windows overlap; they are not independent statistical observations.

Frequencies are anchored to measured median F0 for both hypotheses (exact octave
ratio), avoiding unfair spectral comparison from rounding one hypothesis. Strong
subharmonic correlation alone cannot justify lowering a pitch. Even-only spectra
cannot establish a hidden source intention. All thresholds are fixed before the
new corpus results; no per-song settings or score-driven retries.

## Separate voicing ablation and signal diagnostics

The same raw F0 is masked only (never replaced) when probability<.8, RMS<-50dBFS
or fractional-lag correlation<.8. Report both full-timeline F0 metrics, coverage,
voicing recall and false alarm, not just accuracy on retained frames. This mask
is diagnostic only; it is not silently used as the raw input of arm2 or arm3.

Seven known tones each run with fmax880 and1760; corpus fmax stays880 regardless
of signal outcomes. Nine signal controls include correct/wrong-octave predictions,
weak/missing fundamentals, even-only ambiguity, actual octave leap, silence and
seeded noise. Synthetic conditions are source-owned interventions, not real-song
quality. Their generated predictions are distinct from actual AMT results.

## Evaluation, damage and reporting

Original A1/A2 Hz reference, original shared scorer/mir_eval0.8.2,50ms onset,
50cents including octave, offset max50ms/20% reference duration. Read references
only AFTER all proposals/F0 masks exist. Keep private original events/observations
and decisions immutable; public artifacts contain hashes, scores and counts only.

All40 original recordings must be scored for a macro. Empty output is zero;
missing/failed/duplicate recordings or arms forbid a complete macro. Report each
recording/annotator, paired mean differences, improved/worse counts and seeded
recording-level bootstrap intervals (development diagnostics, not held-out proof).

For pitch changes also use pitch-independent UNIQUE onset<=50ms and interval
IoU>=.5 temporal anchors, requiring uniqueness both directions. Count wrong->right,
right->wrong, wrong->wrong and unanchored edits separately for both annotators.
These conditional alignment diagnostics are not independent expert-confirmed
causal labels and do not replace full note F1. Report rejected/unchanged notes
and low coverage, not only accepted proposals. Raw and corrected duration/identity
must be identical. Keep differences from older, broader Tiny rules explicit.

## Runtime and decision

Two standard Ubuntu CPU jobs max2parallel,2threads,70minute caps. Signal work runs
only in the BP job. PR-open/reopen or manual trigger; documentation pushes do not
repeat or cancel expensive inference. All dependency/scoring source and asset
identities recorded. Native callbacks/failures are preserved as metadata; no
recordings/annotation/MIDI/F0/network arrays/checkpoints/private logs published.

Do not promote DSP-only or hybrid to production from this development40. Even a
positive result needs separate recordings, mixture/stem robustness, final notation
and editing-cost review. A negative result should narrow DSP to diagnostic use,
not imply that signal processing is impossible or that all pitch estimation is
at its ceiling. New candidate selection/segmentation changes require a new protocol.

Primary API contracts: https://librosa.org/doc/0.10.2/generated/librosa.pyin.html
and https://mir-eval.readthedocs.io/en/latest/api/transcription.html . The specific
hybrid gates above are this repository's experimental hypotheses, not a reproduced
published calibrated F0 algorithm. No music-language-model scores are used.
