# Note-state decoding on fixed pYIN observations — frozen CPU protocol

Execution issue [#289](https://github.com/JDeun/audio-score-tool/issues/289),
design issue [#288](https://github.com/JDeun/audio-score-tool/issues/288).
Base main: `441ff85f2383cf3e0b501f10ba0d1f1399acbffa`.
Related #245/#200/#223; #281 concerns a separate downstream written-rhythm problem.
See [the sourced design review](MELODYNE_FLEX_PITCH_DESIGN_REVIEW_2026-11-13.md).

This protocol is committed before the first real-corpus inference. The Actions
receipt records both the PR head and actual checkout SHA, this document's digest,
the scientific source/test/workflow digests, all settings and runtime versions.
Results belong in a separate report; no outcome-based changes to this protocol,
decoder or thresholds are permitted in this execution.

## Question, estimand and limits

Does an additional attack/stable/silent note-state model improve note transcription
from the same pYIN observations? Does RMS-based boundary deletion help or damage it?
The primary comparison is **`note_state_hmm_rms` versus `pitch_runs`, using
pitch+onset+offset F1**, averaged equally over 40 recordings and both annotators.
Secondary, predeclared ablations are HMM versus runs and HMM/RMS versus HMM.
The other two historical segmenters remain controls, not options for per-song selection.

The five arms share an acoustic tracker within this run. The postprocessors can
change voicing, boundaries and the pitch read from a segment. Therefore this is a
controlled **same-F0 postprocessing comparison**, not an identification of a pure
boundary-only causal effect. All output pitches are integer MIDI, as in the old
baseline. We do not test continuous-pitch output as another scoring arm here.

This is a newly implemented **Tony-inspired adaptation**, not a reproduction of
Tony's executable or the undisclosed current Melodyne/Flex Pitch detectors.
No upstream GPL source is copied. It does not implement resynthesis, polyphonic
separation, pitch correction, score quantization or a production evidence schema.
The repeated vocadito development set cannot establish held-out generalization.

## Frozen inputs and five arms

Use all original `vocadito_1` through `vocadito_40`, archive 58,492,257 bytes,
MD5 `dea40fd18f14d899643c4ba221b33a46`, from
<https://zenodo.org/records/5578807/files/vocadito.zip?download=1>.
Validate archive size and digest before inference. Both original A1/A2 note
annotations retain their Hz values; do not tune references to integer notes.

Each waveform is loaded mono at 16 kHz. Call the unchanged
`scripts/dsp_note_probe.py:infer` exactly once per recording: librosa
0.10.2.post1 pYIN, frame 2048, hop 160 (10 ms), 55–880 Hz, center=True,
constant padding, original defaults and voiced gating. This also yields the
three original baseline arms, with the original 80 ms minimum and no new edits:

| Arm | Role |
|---|---|
| `pitch_runs` | Original nearest-semitone contiguous voiced runs; primary reference |
| `pitch_hysteresis` | Original persistent five-frame pitch changes |
| `pitch_hysteresis_reattack` | Original hysteresis with stable spectral-flux splits |
| `note_state_hmm` | The additional fixed note-state decoder below |
| `note_state_hmm_rms` | That same decoded path with the RMS rule below |

The historical artifact contains metadata, not reusable original F0 arrays. This
run therefore performs fresh acoustic inference. Save Hz, voiced probability,
spectral attacks and RMS once, together with both decoded paths, privately.
For each array record dtype, shape and SHA256 of contiguous raw bytes. An NPZ
container digest alone is not a claim of array identity across executions.
The HMM consumes the final gated Hz track; it does not consume the full pYIN
candidate distribution or substitute voiced probability for a calibrated posterior.

## Decoder definition and differences from the paper

Primary source: Mauch et al., *Computer-aided Melody Note Transcription Using the
Tony Software: Accuracy and Efficiency*, TENOR 2015, sections 3.1–3.3 and 4.1,
<https://www.tenor-conference.org/proceedings/2015/04-Mauch-Tony.pdf>.
The paper's processing rate is 44.1 kHz, frame 2048 (~46 ms), hop 256 (~5.805 ms).
Our old tracker is kept at 16 kHz/2048 (128 ms)/160 so the comparison does not
silently change the acoustic estimator. These different windows can matter.

The paper states MIDI 35–85 at three steps per semitone while also stating 207
pitches; those numbers are arithmetically inconsistent. We do not silently claim
to resolve the original implementation. Our range follows the existing F0 limits:
MIDI 33–81 inclusive in one-third-semitone steps, **145 pitches / 435 states**.
Each pitch has Attack, Stable and Silent, with IDs `3*pitch_index + phase`,
phases 0/1/2. Initial total mass is 0.5 over Attack, 0.5 over Silent, and zero
over Stable; terminal states are unconstrained. Ties choose the smallest state ID.

Allowed transitions are A(p)→A(p)/S(p), S(p)→S(p)/U(p), and
U(p)→U(p)/A(q). The paper's self probabilities 0.9/0.99/0.9999 are converted
to our 10 ms step as `p_new = p_paper ** (0.01 / (256 / 44100))`.
This preserves their nominal survival rates in seconds; it is not a full
continuous-time transition-matrix conversion. Remaining A/S mass goes to the next
phase. Remaining Silent mass goes to allowed Attack pitches with
`exp(-abs(q-p)/2)` weights, normalized per source pitch. Allowed jumps are the
same pitch or at least 2/3 semitone apart, at most 13 semitones. The exponential
formula and two-semitone scale are explicitly our fixed choices: the paper does
not fully specify this distribution's formula. No key, tempo or score prior enters.

On a voiced frame, convert observed Hz to continuous MIDI q. Attack and Stable
likelihoods are Gaussian densities centered at each pitch, with sigma 5 and
0.9 semitones respectively, each raised to tau=0.1. Normalize across **all
2×145 voiced states** to total mass 0.5; Silent states share the remaining 0.5.
On zero-Hz frames, voiced states share 1e-12 uniformly and Silent states share
1−1e-12. This finite floor keeps paths defined and can bridge a short unvoiced
gap. It is a disclosed adaptation to the old gated track, not the original
Tony handling of unavailable unvoiced candidates. Record decoded voiced support
on raw-unvoiced frames; do not claim that the new arm preserves every raw gap.

Viterbi decoding uses sparse incoming transitions and stores backpointers.
Read contiguous Attack/Stable support of a note until Silent. A subsequent Attack
after Silent creates a new event even at the same pitch. Retain the median of the
underlying strictly positive raw F0, convert to MIDI and apply NumPy `rint` for
the shared integer-pitch scoring representation. Segments without any positive
raw F0 are discarded. Frame i starts at i×0.01 seconds; the exclusive end is
clipped to waveform duration. Discard events shorter than 80 ms after extraction.
There is no half-window shift, reference-derived alignment or global tuning.

## RMS arm: possible benefit and possible deletion

Compute float64 RMS from the same 16 kHz samples in a centered 2048-sample window,
hop 160, zero padding; frame count matches pYIN. Decode the HMM **only once**.
For i=2 through T−2, if RMS[i+1]>1e-12 and RMS[i−1]/RMS[i+1]<0.7,
replace path frame i−2 with its pitch's Silent state. This is inspired by paper
section 3.3; sensitivity 0.7 is one of the paper's reported settings, fixed here
before this corpus run. The window/hop, soft voicing and 80 ms pruning still differ.

Read notes again from this modified path and prune each fragment below 80 ms.
There is no safeguard that secretly keeps a fragment because it matches a
reference. The rule creates no voiced support outside the original HMM path,
but it can introduce one-frame gaps, shift endpoints, increase event counts,
change segment medians, or delete short fragments. Call it RMS boundary
deletion/segmentation, not endpoint-preserving splitting. Publish deletion,
pruning and support diagnostics, not only a count of added notes.

## Prediction barrier, scoring and harm accounting

Two passes are mandatory. First, visit only `Audio/<case>.wav` archive members;
write all **40×5 prediction files**, observations and source identities. Verify
an exact case/arm set and a hash manifest before the first annotation member is
opened. If any prediction fails, retain all planned rows and abort scoring.
Second, load A1/A2/F0 references, score immutable predictions, and verify all
prediction/source hashes again. Reference files stay in the private work directory.

Use the unchanged `scripts/vocadito_reference.py` scorer: pitch tolerance
50 cents **including octave errors as errors**, onset tolerance 50 ms, optional
offset tolerance max(50 ms, 20% of the reference note's duration). Empty
predictions receive zero. Failed/missing/duplicate rows or an incomplete arm or
annotator set prevent a complete aggregate; do not average only surviving files.
Do not add relaxed tolerances, oracle shifts or a best-per-file arm.

Report onset and onset+offset F1, precision/recall, exact matched/unmatched counts,
prediction counts, A1/A2 means and recording-level improved/worse/tied counts.
For each arm and annotator record reference IDs gained/lost relative to runs under
both matching criteria, with totals. These are differences in a deterministic
maximum matching, not human-confirmed causal error labels: alternative valid
matchings can change the selected identities. Preserve all rows for review.
Raw F0 metrics remain separate from note metrics, with the original F0 scorer.

Require historical parity against the preserved original artifact from run
42989661618, artifact13841810951, ZIP SHA256
`6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541`.
Check source archive, unchanged extractor/scorer, every WAV/reference hash, F0
metric, all 120 baseline note-file hashes/counts and baseline scores. A discrepancy
is a failed comparison gate with its details retained, even if all new files
were scored. Historical raw F0 byte identity is unavailable and not claimed.

A separate auditor reads private source/reference/observation/note files and
reconstructs identities, direct mir_eval matching, score arithmetic, matched-ID
changes and aggregates without calling the runner's scorer/aggregate helpers.
It verifies the stored new outputs rather than independently repeating pYIN or
the full HMM on real audio. Decoder correctness is additionally checked against
an independent small-state exhaustive/dense dynamic-programming oracle in tests.
An audit cannot retroactively prove wall-clock reference access; the frozen
two-pass implementation and negative barrier tests establish that contract.

## Runtime, failure retention and decision

One Ubuntu 24.04 standard CPU job, two threads, hard timeout 35 minutes.
Python 3.11; NumPy1.26.4, SciPy1.13.1, librosa0.10.2.post1, numba0.60.0,
soundfile0.13.1, resampy0.4.2, soxr1.1.0, mir-eval0.8.2. Record all actual transitive
versions. Tests use pytest8.4.2 and Ruff0.12.12. No paid API, GPU, credentials,
neural weights, training or user audio. Research runtime is isolated from product
dependencies. PR opened/reopened or explicit dispatch triggers execution;
documentation synchronization and the eventual merge do not repeat inference.

Run owned synthetic contract tests before corpus access: transition normalization,
decoder oracle, silence/voicing/short-note handling, clock clipping, RMS deletion,
complete cohort, reference barrier, metadata/raw-file audits and tamper rejection.
These tests verify implementation contracts, not measured real-music efficacy.

Upload only named `vocadito.json` and `audit.json` metadata receipts. Do not upload
audio, annotations, private logs, full note sequences, pitch arrays or state paths.
If installation/inference/scoring/audit fails, preserve a failed or incomplete
receipt and its original run; do not overwrite it with an apparent success.
Archive the exact downloaded ZIP and its digest in the research evidence directory.

Evidence for another targeted development study requires a positive primary
delta without a decline in onset F1; report both regardless. No statistical
significance or holdout claim follows from this one reused development cohort.
Inspect per-recording losses and RMS damage before any follow-up. Even a positive
result does not authorize product activation: unseen recordings, normal-note
damage, human editing effort and downstream notation quality remain separate
gates. Keep `quality_approved=false`, record the measured decision, and leave
the wider design and written-rhythm issues open.
