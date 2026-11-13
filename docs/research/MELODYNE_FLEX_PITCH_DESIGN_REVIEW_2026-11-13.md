# Melodyne, Flex Pitch and Tony: analysis contracts for note decoding

Status: source review and first bounded experiment completed; the tested decoder is not adopted.
Last reviewed: 2026-11-13 (Asia/Seoul).
Repository inspection base: `441ff85f2383cf3e0b501f10ba0d1f1399acbffa`.
Related: [design review #288](https://github.com/JDeun/audio-score-tool/issues/288), [completed experiment #289](https://github.com/JDeun/audio-score-tool/issues/289), #245, #281, #200, and the [completed repeat-context study](REPEAT_CONTEXT_RESULTS_2026-11-13.md).
Experiment protocol: [same-pYIN note-state decoder](NOTE_STATE_HMM_PROTOCOL_2026-11-13.md).
All external sources below were accessed on 2026-11-13.

Execution update: [the completed result](NOTE_STATE_HMM_RESULTS_2026-11-13.md)
records a negative primary comparison: HMM/RMS pitch+onset+offset F1 is 5.290052%
versus 22.149227% for original pitch runs, with historical parity and independent
saved-note audit passing. The design distinctions below remain useful hypotheses;
this adaptation did not improve extraction. [#291](https://github.com/JDeun/audio-score-tool/issues/291)
tracks its observation/transition diagnosis. The review's prospective design
language is not a claim that proposed schema fields or product changes shipped.

## Decision

Public documentation provides useful distinctions between acoustic observations,
note interpretation and audio editing. It does not disclose the complete current
Melodyne or Flex Pitch detector. We can test those distinctions without claiming
to reproduce either product.

The next bounded comparison should hold the pYIN observations fixed and test a
separate note-state decoder against our existing segmenters. This is a
**Tony-inspired adaptation**, not an exact Tony reproduction or a Melodyne
implementation. Its purpose is to measure whether a different interpretation of
the same acoustic evidence improves performed-note extraction. Written rhythm,
rest spelling, voices and expressive same-score recovery remain separate gates.

The user authorized documenting the investigation and proceeding with a research
experiment. This review does not promote a decoder to the product, change the
existing Tiny observation contract, or implement audio pitch/time resynthesis.
No Tony or other GPL implementation code is copied into the repository for this
review. The next implementation should be original work from the declared
mathematical specification and record its dependencies separately.

## What the sources establish

| Evidence category | What it supports | What it does not establish |
| --- | --- | --- |
| Celemony and Apple manuals | Observable controls, analysis/edit distinctions, intended input material and documented limitations | The exact internal detector, loss function or current source code |
| Neubäcker's published patent | A disclosed method for note-object analysis and sound decomposition | Identity with every current Melodyne algorithm, or permission to use a patented method |
| Tony research paper | A specified monophonic pitch-to-note method with a separate note HMM | The same implementation as `librosa.pyin`, or expected performance on our corpus |
| Repository code and archived runs | What this project currently saves, decodes and has measured | Results for the proposed new decoder or a new held-out population |
| Design proposals below | Testable hypotheses and candidate data contracts | Implemented features, calibrated confidence or achieved musical accuracy |

## 1. Separate the representations and the two output tasks

The following is our proposed architectural interpretation of the sources, not a
claim that the commercial applications expose these exact modules or fields.

| Stage | Representation | Question it answers |
| --- | --- | --- |
| Acoustic analysis | Time-frequency evidence, F0 observations, tonal/noise support and attacks | What is present in the recording? |
| Continuous evidence | Pitch and amplitude trajectories with a declared clock and missing-data mask | How does the sound evolve within an event? |
| Note interpretation | Segment boundaries, note-state sequence, pitch center and alternative hypotheses | Which observations belong to the same performed note? |
| Optional audio editing/resynthesis | User-selected pitch/time changes and sound-component reconstruction | How should the recording sound after an edit? |
| Separate written-score inference | Beat map, score onset/duration, rests, ties, voices and notation hypotheses | What written music is consistent with the performance? |

Continuous evidence and a plausible note segmentation can support both output
tasks. Successful resynthesis does not certify the written score; a correct
performed-note event does not alone specify its notated duration or rest.

Celemony explicitly separates **Assignment** from **Edit**: assignment corrects
the analysis of notes or tempo, whereas editing changes the musical content.
Its note-assignment training demonstrates a vocal octave error and alternate
potential notes; correcting the assignment does not itself change the sound.
These are useful precedents for preserving observations and exposing uncertain
interpretations rather than silently overwriting the source. [M1] [M2]

## 2. Useful distinctions in Melodyne

### Segment boundary, musical onset and intended grid position

These are three different quantities. A note segment can include a noisy lead-in
before the moment that matters perceptually for timing. Melodyne exposes a
musical starting point separately from the segment boundary; it can retain a
potential starting point or fall back to the segment start when no reliable
anchor was found. [M3]

The time-correction macro separately uses an inferred intended beat position and
moves the musical starting point toward it according to the correction strength.
The displayed intended notes are described as suggestions that may be wrong.
[M4] [M5]

**Our inference:** keep an observed attack, a candidate perceptual onset and a
score-grid hypothesis distinct. None should acquire the status of ground truth
merely because another layer needs a single timestamp. For #281, this allows an
early attack near a bar boundary to retain multiple plausible memberships. It
does not establish that boundary alternatives will repair the repeat detector:
the completed study also found no links among its already eligible real blocks.

### Pitch center, drift and vibrato

Melodyne offers separate control of the pitch center, slower pitch drift and
faster modulation such as vibrato. Removing both drift and modulation flattens
the pitch trajectory; moving the center need not remove expressive variation.
[M6] The pitch-correction macro can target semitones or scale/chord positions and
adjust drift separately. [M7]

**Our inference:** a discrete note pitch should be a summary attached to a
preserved contour, rather than a replacement for that contour. The conceptual
decomposition into center, slow movement and faster modulation is not a claim
about Celemony's precise filters or mathematical estimator. Attack slides,
portamento and trills also require segmentation/context decisions; smoothing a
curve is not sufficient evidence that those decisions are correct.

### Formants, sibilants and internal timing

Celemony's Formant Tool treats spectral coloration separately from the
fundamental pitch and permits formant transitions between connected notes. [M8]
Its melodic processing identifies unpitched consonant/breath components and
handles them differently during pitch and time editing. [M9]

Time handles redistribute the internal time course of a note. Attack Speed
changes the development of the initial portion while preserving its designated
musical starting point and endpoint. This illustrates why changing a note's
duration or attack need not mean uniformly resampling its entire waveform. [M10]

**Our inference:** tonal evidence, noise/attack evidence and expressive envelopes
should remain distinguishable. This can inform note-boundary hypotheses without
requiring us to implement formant-preserving resynthesis. An audible decay or
reverberation tail must not automatically become a written note duration.

### Polyphonic DNA has a specific scope

The official documentation describes DNA as note-by-pitch access in individually
recorded polyphonic instruments, with separate decay and sustain variants.
Simultaneous instruments playing the same pitch can form a combined note blob;
DNA is not instrument-stem separation. The documentation also acknowledges that
polyphonic detection is not always correct. [M9]

Accordingly, a successful piano-chord edit is not evidence that a mixed song's
vocal, guitar and bass were independently identified, or that its score voices
were reconstructed correctly.

## 3. What is public about Logic's Flex algorithms

Apple documents note pitch, position, length, split/merge and per-note controls
for vibrato, drift, gain and formants in **Flex Pitch**. These establish editing
capabilities, not a published F0 estimator or note-segmentation method. [A1]
The separate Flex Pitch parameter page exposes formant tracking and shifting
controls. [A2]

Apple explicitly identifies **phase vocoding for Flex Time's Polyphonic mode**.
Its Slicing mode instead moves transient-delimited slices at their original
speed, without stretching the slices. These are different documented timing
methods. The phase-vocoder statement must not be generalized into a claim that
Flex Pitch's detector, monophonic algorithm or all of Logic uses that method.
[A3]

This review does not assign YIN, pYIN, PSOLA, WSOLA, WORLD, a particular neural
network, or any other unconfirmed detector to current Melodyne or Flex Pitch.
The Apple references include versioned official manuals; they support the
specific documented behavior rather than an exhaustive implementation claim
about later releases.

## 4. A published note-object method

Peter Neubäcker's **EP2099024A1** discloses overlapping-window frequency analysis,
phase-derived instantaneous frequency and harmonic evidence for finding note
objects. The described iterative search can partially subtract explained energy
so overlapping notes remain discoverable. Transient/noisy events are considered
separately and associated with tonal notes when temporally plausible. Spectral
contribution factors allocate sound to note objects for reconstruction and
recombination with residual sound. Plausibility filtering and user changes to
the detected objects are part of the disclosure. [P1]

The patent explicitly allows the identification stage to support notation
without performing the sound-decomposition stage. That distinction is relevant
to our scope. The published method is evidence of an approach, not proof that
the current product implements it unchanged. This review makes no conclusion
about patent validity, territorial scope, expiry or freedom to operate.

## 5. Tony provides a more directly specified research starting point

Mauch et al. describe pYIN pitch tracking followed by a **second, independent
HMM for note transcription**, decoded with Viterbi. Note states represent
attack, stable pitch and silence; attack observations are allowed more pitch
variation than stable observations. The method also describes amplitude-based
segmentation of repeated similar-pitch notes and minimum-duration pruning.
Note events and their underlying pitch track can be edited separately. [T1]

Tony's official project page describes monophonic analysis, visual/auditory
comparison, alternate pitch tracks, note split/merge and export. It is an
annotation workflow that includes correction by a person. [T2]

Our next comparison borrows the distinction between an F0 trajectory and a
note-state decoder. It does not reproduce Tony's complete implementation,
preprocessing, parameter set, interactive correction or published benchmark.
The frozen experiment must identify every adaptation. In particular, a decoder
using this project's existing sample clock and `librosa.pyin` observations is
not automatically identical to Tony's pYIN Vamp pipeline. The versioned librosa
API returns F0, a voiced flag and voiced probabilities; it does not return the
second note model as a list of annotated note events. [L1]

## 6. Repository audit: reuse existing evidence, identify the actual gap

The following observations are pinned to the inspection base above.

| Existing path | Verified behavior | Consequence for this work |
| --- | --- | --- |
| [`fixed_vocal_lead.py`](../../src/audio_score_tool/fixed_vocal_lead.py) | Runs the Tiny pitch verifier on the vocal stem and passes its track into vocal-part selection alongside the separate YourMT3 output | A continuous acoustic observation path already exists; do not describe it as a newly introduced feature |
| [`fixed_vocal_infer.py`](../../src/audio_score_tool/fixed_vocal_infer.py) | Computes Tiny pitch and periodicity, applies the declared silence/periodicity masks, then saves only `times` and `hz` in the NPZ | The saved file does not retain periodicity, unmasked candidates, an amplitude envelope or a complete posterior |
| [`vocal_evidence.py`](../../src/audio_score_tool/vocal_evidence.py) | Accepts exactly `times.npy` and `hz.npy`, checks provenance and the 10 ms clock, then derives floating MIDI pitch; `compare_notes` summarizes covered stable interiors | Existing zeros/missing values cannot be converted into calibrated confidence or reconstructed rejected candidates |
| [`dsp_note_probe.py`](../../scripts/dsp_note_probe.py) | Forms notes from nearest-semitone runs, persistent-pitch hysteresis and a reattack-split variant, sharing the in-run pYIN output | These paths have no separate Tony-style attack/stable/silent note-state HMM after F0 tracking |
| [`score_timing.py`](../../src/audio_score_tool/score_timing.py) | Converts an existing score's quarter positions and seconds using its tempo map and audio origin | An existing conversion clock is not evidence that the acoustic beat map or intended written position has been inferred correctly |

The frozen DSP probe uses 16 kHz audio, a 160-sample hop and 2,048-sample frames.
Its `infer` function already returns pYIN voiced probability and detected attacks
to the research runner. The product Tiny NPZ and this research observation path
are different contracts; their probabilities and masks are not interchangeable.

### What the prior DSP experiment measured

The [completed DSP result](DSP_NOTE_BASELINE_RESULTS_2026-11-11.md) reports the
following equal-recording/annotator macro scores over 40 original vocadito
recordings and both A1/A2 annotations. Pitch matching is octave-sensitive (50 cents); onset
tolerance is 50 ms, and the offset condition uses the larger of 50 ms or 20% of
reference duration.

| Fixed note decoder | Pitch + onset F1 | Pitch + onset + offset F1 |
| --- | ---: | ---: |
| Nearest-pitch runs | 36.353202% | 22.149227% |
| Persistent-pitch hysteresis | 35.124455% | 13.906851% |
| Hysteresis plus reattack split | 35.346152% | 14.170140% |

The same report records raw pitch accuracy of 80.528736%. Frame-pitch accuracy
and note F1 have different units, denominators and matching rules; subtracting
them is not an error attribution. The note results establish that those fixed
segmenters were weak on this development corpus. They do not identify every
causal error or establish a ceiling for DSP.

The old artifact published metadata, not raw F0/notes. Historical metric parity
does not establish raw-array byte identity. If the new experiment regenerates
the extractor, it must state that explicitly, preserve the newly generated
arrays, and give every compared decoder the same in-run observations. It must
not claim to have reused historical F0 bytes that were not available.

## 7. Proposed evidence contract

This is a candidate extension for research. The first note-state experiment need
only implement the declared subset it actually evaluates. Missing evidence
must be represented as unavailable, not fabricated from a hard decision.

| Layer | Proposed retained fields | Interpretation constraint |
| --- | --- | --- |
| Source and clock | Source hash, channel/stem identity, original and analysis sample rates, hop, frame centering, resampling/origin map, extractor/config hashes | Every timestamp identifies its coordinate system |
| Frame evidence | F0, voiced flag, voiced probability when supplied, amplitude/attack evidence, missing-data mask | An estimator score is not automatically a calibrated probability of a correct note |
| Optional alternatives | Extractor-provided pitch candidates and their documented scores | Preserve only alternatives actually produced; a masked F0 file cannot recover them |
| Performed-note hypothesis | Segment onset/offset, state path, pitch summary, contour reference, split/merge provenance | A decoded event can be wrong or ambiguous; retain its support |
| Optional musical onset | Candidate perceptual onset and declared support | Do not conflate it with the segment start or a proved intended beat |
| Written-score hypothesis | Clock/beat candidates, canonical onset/duration, ties/rests/voice alternatives, abstention | Keep this outside the performed-note result unless independently evaluated |
| Expression residual | Original timing/pitch trajectory linked to each hypothesis | Preservation supports reversibility; it is not an accuracy gain |
| Edit history | Proposed/accepted/rejected change, source revision and undo relationship | Interpretation changes do not overwrite immutable acoustic observations |

Adding fields to the existing Tiny NPZ would currently fail its strict reader.
Any later product extension therefore needs a versioned contract, explicit
old-file handling and new provenance, rather than silently appending arrays or
changing the old adapter whose hash appears in receipts. No such migration is
made by this review.

## 8. Gates for the next experiment and later adoption

1. **Freeze the comparison before outcomes.** Declare population, settings,
   evidence schema, baseline/candidate decoders, score tolerances, resource
   bounds and failure policy. Keep legacy scripts and receipts unchanged.
   The same-pYIN comparison must share complete observation hashes across arms.
2. **Separate extraction from decoding.** Save predictions before reading
   evaluation annotations. Hold the F0, voicing and clock fixed for the primary
   comparison; make any added attack evidence a declared separate arm.
3. **Measure actual note consequences.** Report onset and offset-inclusive F1,
   precision/recall, note counts, recording-level gains and losses, repeated-note
   merging/splitting and silence/voicing errors where references support them.
   Preserve A1/A2 separately and retain failures in planned coverage.
4. **Keep development and independent evidence separate.** The 40 vocadito
   recordings have already been used repeatedly. They can diagnose the decoder
   but cannot become a newly held-out evaluation by renaming the experiment.
   Verify the final recipe on a separately declared recording population before
   considering a product change.
5. **Preserve the product baseline.** Do not replace YourMT3 or turn acoustic
   observations into automatic pitch/length edits from a development gain alone.
   A later integration must measure damage to previously correct notes, caller
   compatibility, evidence retention, undo/export behavior and editing effort.
6. **Evaluate notation and sound separately.** A note-state decoder does not
   establish written rests, swing interpretation, score duration, voice
   assignment, sound quality after resynthesis or the #281 common-score goal.
   Those require their own references, metrics and controls.

Research receipts should contain source/config identities and derived metrics.
Raw musical sources and private frame/event arrays are not republished merely
because the research code is committed. Nothing in this source review changes
dataset, software or model redistribution conditions.

## Primary sources

The manuals are evidence for documented behavior, the patent for its disclosed
method, and the paper for its described experiment. No commercial detection
accuracy was independently measured for this review.

- [M1] Celemony, *Assignment vs. editing*.
- [M2] Celemony, *Note Assignment* training, including an octave-assignment example.
- [M3] Celemony, *Tools for note assignment*, starting-point and separation tools.
- [M4] Celemony, *Quantize Time Macro*.
- [M5] Celemony, *Display and other options*, intended-note display.
- [M6] Celemony, *Pitch modulation and drift*.
- [M7] Celemony, *Correct Pitch Macro*.
- [M8] Celemony, *Formant Tool*.
- [M9] Celemony, *Audio characteristics and algorithms*.
- [M10] Celemony, *Time Handles and Attack Speed*.
- [A1] Apple, *Edit pitch and timing with Flex Pitch*, versioned Logic Pro guide.
- [A2] Apple, *Flex Pitch algorithm and parameters*, official archived guide.
- [A3] Apple, *Flex Time algorithms and parameters*, versioned Logic Pro guide.
- [P1] Peter Neubäcker, *Method for acoustic object-oriented analysis and note
  object-oriented processing of polyphonic sound recordings*, EP2099024A1,
  published 2009-09-09. Google Patents hosts the publication text; its automated
  legal-status fields are not a legal determination used by this review.
- [T1] Matthias Mauch et al., *Computer-aided Melody Note Transcription Using the
  Tony Software: Accuracy and Efficiency*, TENOR 2015, pp. 23-30, especially
  sections 3.1-3.3. DOI: [10.5281/zenodo.1289635](https://doi.org/10.5281/zenodo.1289635).
- [T2] Sonic Visualiser project, *Tony* official application page.
- [L1] librosa 0.11.0, `librosa.pyin` API documentation.

[M1]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5Training/en/HC2-Training_R1T2_Zuweisung_vs_Bearbeitung_M5
[M2]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5Training/en/HC2-Training_R1T2.2_Die_Notenzuweisung_M5?env=standAlone
[M3]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_NA_Mode_Tools?env=standAlone
[M4]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_MacroTiming?env=logic
[M5]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_ViewOptions-stand-alone?env=standAlone
[M6]: https://helpcenter.celemony.com/M5/doc/melodyneAssistant5/en/M5tour_ToolModulationDrift_2
[M7]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_MacroPitch?env=dawsWithAra
[M8]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_ToolFormants?env=standAlone
[M9]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_AudioAlgorithms?env=standAlone
[M10]: https://helpcenter.celemony.com/M5/doc/melodyneStudio5/en/M5tour_ToolTimeHandlesAttackSpeed_2?env=standAlone
[A1]: https://support.apple.com/guide/logicpro/edit-pitch-and-timing-with-flex-pitch-lgcpc53e6bef/10.7/mac/11.0
[A2]: https://help.apple.com/logicpro/mac/10.1/en.lproj/lgcpba8e3301.html
[A3]: https://support.apple.com/en-ge/guide/logicpro/lgcpa77a4a3f/10.7/mac/11.0
[P1]: https://patents.google.com/patent/EP2099024A1/en
[T1]: https://www.tenor-conference.org/proceedings/2015/04-Mauch-Tony.pdf
[T2]: https://www.sonicvisualiser.org/tony/
[L1]: https://librosa.org/doc/0.11.0/generated/librosa.pyin.html
