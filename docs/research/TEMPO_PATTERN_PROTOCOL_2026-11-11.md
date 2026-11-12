# Tempo-only rhythmic pattern study — user-corrected scope, #252

Base #254 d6fa009c203d1799c2329e802acf85b514c4bb70. Isolated draft PR;
no merge, production change, external API keys, learned weights, GPU or training.

## Hypothesis and separation

The user's hypothesis is BPM from rhythmic repetition, NOT finding bar beat one.
BPM estimates must not be suppressed for ambiguous meter/downbeat. No tempo,
meter, phase, score, genre or filename is passed to the estimators. Known ground
truth BPM is used only after every prediction is computed. 120 BPM is a FIXED
broad preference in explicitly named arms, not externally fetched song metadata.

Four frozen arms on the same observation envelope:
1. count_negative_control: distinct detected time bins / observed seconds x60.
   This counts attacks, not necessarily beats; intentionally naive negative control.
2. acf_flat: mean normalized autocorrelation of onset activity over 8s windows,
   hop4s (shorter when necessary), evaluated at beat periods and 2x/4x periods with
   weights1/.5/.25. Candidate40..240 step1, no meter templates; exact ties use
   ascending BPM. This is a preregistered heuristic, not a learned model.
3. acf_prior120: SAME scores multiplied by exp(-.5*log2(BPM/120)^2), sigma1 octave.
4. librosa_prior120: librosa0.10.2.post1 feature.tempo on the SAME envelope,
   sr100/hop1, ac_size8,start_bpm120,std_bpm1,max_tempo241,mean aggregation.
   It does not enforce our40BPM lower bound; document this method difference.

For ACF, save up to3 candidate peaks separated by8%; candidate recall is an
oracle diagnostic, NEVER a top1 correctness rate. Report nominal BPM within4%,
half/double aliases separately, other errors and all unavailable/failed cases.
Do not silently accept 60 or240 when truth is120. Do not tune after results.

## Paired inputs and cohorts

GMD v1.0.0, Google LLC, CC BY4.0. Human drumming is recorded as MIDI and aligned
Roland TD-11 sound-module audio, not acoustic full-band popular music.
MIDI-only ZIP SHA256651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e.

MIDI job: ALL official test recordings; supplemental non-test3/4 separately.
First up to24 seconds measured from MIDI event time. MIDI tempo map is needed to
convert ticks to seconds; catalog tempo does not constrain tempo inference.
Representations: kick/backbeat and kick/backbeat/hat (not all percussion).
Timing impulse trains at100Hz, identical3tap smoothing; no minimum kick/snare
pair count. Silence/too short remain unavailable, never filled with120.
Multiple MIDI tempo values are unsupported; no selective drop from denominator.

Audio job: original metadata-selected4 #254 WAVs as a repeated cohort; plus
six official-test4/4 beats12..40s and two test4/4 fills4..15s disjoint from them,
chosen by SHA256('tempo-only-v1/'+id), regardless of ground truth BPM or outputs.
Fewer eligible files reduce declared coverage explicitly. First up to24s WAV.
The previously used3/4 waveform is validation, never a claimed3/4 test.

WAV representations: previous fixed DSP detected-hit train (role labels ignored)
and continuous unclassified spectral flux, mean of99th-percentile-normalized
45..210/210..2000/2000..7000Hz bands, log1p spectrum,1024FFT/160hop at16kHz.
No source MIDI events or note labels are supplied to the WAV feature extractors.
These are drum-kit recordings, not estimated drum stems and not mixed pop tracks.

Keep prior RangeZipReader byte limits: max140MiB total,10MiB/request,55MiB/member,
strict HTTP206, original publisher CSV exact match, zip member CRC, measured
member SHA. Preflight the whole selection's compressed bytes plus conservative
cache overhead; abort/report blocked if over budget. No4.76GiB download fallback.
Full ZIP hash is NOT verified by member reads. Never swap a failed or low-scoring
file for another file. Source audio/MIDI/envelopes never uploaded.

## Metrics and reproducibility

Top1 relative error, within4% counts/rates over ALL planned cases by cohort and
representation, half/double count, other wrong, no estimate, candidate recall,
per-case outputs and reference retained. Median relative error is explicitly
conditional on available estimates. Previous downbeat ambiguity is irrelevant
here. Do not compare onset F1 to BPM accuracy. Group by beat/fill and source split
when reporting. Reused corpus and small additional selection are exploratory,
not independent product-generalization evidence.

CPU2threads, Python3.11; numpy1.26.4/scipy1.13.1/librosa0.10.2.post1/
numba0.60.0/mido1.3.3/soundfile0.13.1. Source/runtime/settings/data SHA retained.
Local16 unit tests passed with a different installed numeric runtime; actual
pinned-runtime checks and full evaluation occur in Actions. Compile and YAML
parse are preflight only. No post-result threshold changes or per-case winners.

A positive BPM result does not assert correct meter, downbeat, note transcription,
score duration, MusicXML/PDF, or editing time. Use tempo candidates as a separate
module before returning to the user's bar-sum constrained notation hypothesis.
If original plus half/double hypotheses remain indistinguishable, retain that
uncertainty; exact-recording metadata may eventually help select the metrical
level, but no provider is called or its availability assumed in this experiment.

Primary sources: https://magenta.tensorflow.org/datasets/groove and
https://librosa.org/doc/0.10.2/generated/librosa.feature.tempo.html .
