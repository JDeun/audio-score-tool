# PRISM: Drums review and drum-event acceptance

Status: source review and repository audit; no PRISM inference benchmark.
Reviewed: 2026-11-14 (Asia/Seoul).
Inspection base: `33ec72a76c53c1bd17f3c2f2170ca504c23aeb3a`.
Tracking: [#303](https://github.com/JDeun/audio-score-tool/issues/303), under
[#36](https://github.com/JDeun/audio-score-tool/issues/36). Reuse editing
[#299](https://github.com/JDeun/audio-score-tool/issues/299), evidence/schema
[#300](https://github.com/JDeun/audio-score-tool/issues/300), and quality
[#34](https://github.com/JDeun/audio-score-tool/issues/34).

## Decision

The supplied video reviews **Aurally Sound PRISM: Drums**, a drum-audio-to-MIDI
product. Its useful design references are performed-hit timing, drum identity,
velocity, source-audio comparison and correction. These inform our drum
acceptance work; they do not resolve the vocal note-boundary experiment or
written-score inference.

The video page's complete transcript and expanded description were inspected.
This review did not independently listen-score its examples, operate the
commercial plugin, or measure its accuracy. The publisher discloses sponsorship
and an affiliate link. Treat the demonstration as workflow evidence. [V1]

## 1. What was demonstrated

The timestamps below refer to the supplied video's transcript. They are concise
paraphrases, not an independent evaluation of the audio.

| Video time | Observation |
| --- | --- |
| 0:38–1:23 | Clean input is recommended; unusual rim sounds may be misidentified. |
| 1:30–2:25 | ARA analysis, detection selectivity and MIDI placement are demonstrated. |
| 3:48–4:09 | The presenter corrects misclassified hits by moving groups between drum rows. |
| 4:33–5:39 | The standard insert captures playback, then analyzes it; exported MIDI retains its position. |
| 6:26–6:45 | Open hi-hats and closely spaced flams are discussed. |
| 7:30–8:14 | Destination drum-library mappings can be selected and edited. |
| 9:01–10:17 | The host first obtains a tempo map; the presenter reports that exported MIDI stays aligned. |

Source: [V1]. A capture-during-playback workflow is not evidence of causal,
low-latency transcription while someone plays a live instrument.

## 2. Official claims and their limits

The manufacturer identifies a proprietary machine-learning engine with nine
classes: kick, snare, closed/open hi-hat, crash, ride and high/mid/low tom. It
describes timing and dynamics extraction, local processing and an acoustic-drum
focus. Stem-separation artifacts may degrade results. The checked primary
sources do not disclose the exact network, loss, training corpus or an audited
comparative benchmark. [S1] [S2]

**PRISM and PRISM: Drums are separate products.** The former analyzes pitched
instruments, including monophonic and polyphonic material; the latter estimates
drum type, timing and velocity. ARA exposes the host's audio, tempo map, time
signatures and bars. Thus the video's tempo-map example tests integration with
supplied musical context, rather than establishing blind tempo/meter inference
from drum audio. [S3]

The drum manual documents source/MIDI comparison, manual edits, explicit start
quantization and configurable export mappings. Its default sensitivity is 0.5;
higher values produce fewer hits, and changing detection settings regenerates
notes. Semantic drum identity remains distinct from the export mapping, which
uses MIDI channel 10. These are observable product contracts, not a disclosed
neural architecture. [S4]

## 3. An implementable interpretation, not a reverse-engineering claim

A drum estimator can be designed around separate outputs for each drum class
over time, followed by hit extraction, dynamics estimation and MIDI export.
Time-frequency features and a learned multilabel detector are one plausible
implementation. No inspected source establishes that PRISM uses a particular
spectrogram, CNN, Transformer, separator, frame rate or peak-picking method.

For our implementation, two constraints follow from the task itself:

1. A kick and hi-hat at the same time require two events. A single mutually
   exclusive class decision for each global onset cannot represent that case.
2. A flam requires preserving two nearby events of the same class. A global
   suppression window must not erase them by construction.

Keep the performed event in source-audio seconds. Convert those times into MIDI
ticks using a declared tempo map, then check the exported file independently.
Use a separate score hypothesis for written duration, rests, voices and swing
notation. A percussion MIDI pitch number primarily selects a drum sound; it
does not have the same acoustic meaning as a sung fundamental frequency.

For ordinary drum transcription, onset plus semantic class is the primary
matching task. Dynamics, export note-offs, choke behavior and written notation
need their own checks. In particular, the current vocal offset-inclusive F1
cannot simply be reused as the sole drum-quality measure.

## 4. What the repository already does

All source observations in this section refer to the inspection base above.

| Area | Existing evidence | Remaining gap |
| --- | --- | --- |
| Audio transcription | Registered generic AMT engines and vocal-specific routes in `engine_api.py` / `transcription_engine.py` | No registered PRISM integration or dedicated nine-class drum provider |
| Research drum proxy | `gmd_audio_range_probe.py::detect_audio_roles` emits kick/backbeat novelty peaks | Only two labels; one shared peak list cannot represent independent simultaneous classes |
| MIDI timing | `midi_score_import.py`, `notation_backend.py` and `score_timing.py` preserve explicit timing and source origin | Add combined drum-specific controls; supplied clocks do not certify inferred tempo |
| Fidelity tests | `test_midi_musicxml_fidelity.py` covers leading silence, tempo/meter changes, nearby attacks and percussion identities | The main fixture uses velocity 90; varied dynamics and custom drum maps are not certified |
| MIDI metrics | `metrics.py::MidiNote` includes pitch, timing, channel/program and percussion identity | It does not retain velocity, so its F1 cannot certify dynamics |
| Editing and evidence | #299 and #300 define outstanding source-linked correction and schema work | Measure correction time, retain edits and semantic identity through reanalysis/export |

### A precise limitation of the existing research proxy

`detect_audio_roles()` takes the maximum of low/high spectral novelty, builds a
single global peak list, and suppresses a following peak less than **85 ms**
later, retaining the stronger one. Each retained peak gets one of two labels.
Consequently, this representation cannot emit a simultaneous kick-plus-hat pair,
and sufficiently close detected peaks are explicitly collapsed. This is a code
property of the research proxy, not a measured limitation of every production
AMT backend. Keep this historical detector unchanged as a baseline.

The [four-excerpt GMD study](GMD_AUDIO_RANGE_RESULTS_2026-11-11.md) already records
its narrow task and failures. Those selected sound-module recordings do not
constitute an acoustic-kit or mixed-song generalization benchmark.

### Preserve the timing foundation

Existing regression coverage includes a nonzero source-audio origin, tempo
changes, leading silence, closely spaced pitched attacks, simultaneous
percussion sounds and overlapping repeated pitches. Inspect
`tests/test_score_timing.py`, `tests/test_midi_musicxml_fidelity.py` and
`tests/test_selected_stem_score.py` before duplicating that work.

The MR-MT3 bridge's fixed 120 BPM is a serialization clock for elapsed seconds.
It does not establish a musical BPM estimate. A source onset can remain correct
in seconds even when the musical beat interpretation is still unresolved.

## 5. Bounded acceptance plan

These are proposed test conditions. They are not measured PRISM results or a
preregistered new model experiment. Before detector inference, freeze the input
inventory, class mapping, tolerances, parameter settings and evaluation split.

| Condition | Required independent observation |
| --- | --- |
| Simultaneous hits | Preserve kick+hat and kick+snare+crash multiplicity and class identity at identical onsets. |
| Flams and rolls | Include same-class pairs at 15/30/60/90 ms and single-hit controls; report missing second hits and spurious doubles separately. |
| Class confusion | Include open/closed hat, rim/snare, tom/kick and ride/crash; retain unsupported labels and failures in the denominator. |
| Quiet hits and dynamics | Use varied known MIDI velocities for serialization; for audio detection report recall by supported dynamics bands and matched-hit velocity error separately. |
| Clock preservation | Combine initial silence, a nonzero clip origin, multiple tempos and meter changes; check reconstructed onset seconds and pairwise gaps within a declared tick-resolution bound. |
| Mapping invariance | Export the same semantic events under GM and a custom map; only destination pitch assignments may change. |
| Raw versus quantized events | Keep original microtiming and a separate written-grid hypothesis; explicit edits must be reversible and scoped to the selection. |
| Correction workflow | Loop, compare source/MIDI, add/delete/reclassify/move/change velocity, undo and save/reload; measure time and residual errors. |
| Audio-domain separation | Report clean kit, estimated stem and full mix separately; distinguish the detector from the separator-plus-detector pipeline. |

MIDI velocity is not simply waveform amplitude: recording gain, microphone,
instrument and sampler response affect that relationship. A known symbolic
velocity can validate file preservation without proving recovery of a drummer's
physical strike force.

For #300, a candidate event record should preserve a source/event identifier,
source onset seconds, semantic drum class, velocity estimate, detector/settings
identity and user-edit revision. The target sampler's MIDI note mapping belongs
to export configuration. This is a proposal; no new schema is claimed shipped.

## 6. Bounded product follow-up

The review reproduced a serialization defect in
`mt3_program_midi.py::midi_from_program_notes`: a decoded note with velocity zero
was accepted but encoded as a MIDI note-off, losing its sounded onset. The
follow-up requires velocity 1–127 and rejects zero explicitly, without inventing
a replacement velocity. MIDI's zero-velocity convention is also described in
the MIDI Association's [output tutorial](https://midi.org/arduino-midi-output-basics).

New tests in `tests/test_mt3_program_midi.py` save and reload raw MIDI to check
pitched/drum velocity boundaries, initial silence, simultaneous kick/hat,
a 15 ms snare flam, open hat, channel 10, all event counts and timing. The combined
drum fixture uses the default 220 PPQ and a half-tick per-boundary rounding limit.
It does not exercise a custom mapping UI, variable-tempo MusicXML conversion,
or audio hit detection; those retain the separate acceptance conditions above.

The scoped serializer/history suites passed 36 tests; scoped Ruff and whitespace
checks passed. All 66 frozen #298 source hashes remain unchanged. Older reports
retain their original serializer hash and source commit. Full final-head and
actual-main CI status is recorded separately on the integration PR.

## 7. Current experiment status and sequencing

The latest completed study is [#298 / PR #301](NOTE_BOUNDARY_PARENT_GUARD_RESULTS_2026-11-13.md).
On 40 vocadito recordings, the parent-preserving guard changed onset F1 from
57.225361% to 53.469785% and onset+offset F1 from 24.270837% to 23.113588%.
Its coverage preservation did not satisfy the musical acceptance conditions;
the candidate was rejected and product defaults were not changed.

At this review's starting snapshot, main was the inspection SHA above, with
37 open issues and one open draft PR (#236), before creating #303. Main CI
[43393032958 attempt 2](https://github.com/JDeun/audio-score-tool/actions/runs/43393032958/attempts/2)
remained failed at exact synthetic-input regeneration. The open prerequisite is
[#302](https://github.com/JDeun/audio-score-tool/issues/302), not an unfinished
run of #298. PR #236 separately needs beat/vocal runtime routing and current-main
integration acceptance.

Proceed with #302's versioned input-only environment qualification, preserving
the original scientific sources, manifests and failed runs. Record this video's
drum acceptance requirements under #303 and reuse #299/#300. Only then define a
separate fixed-input drum-detector comparison. Neither this review nor a MIDI
serialization regression is evidence of improved audio transcription accuracy.

## Sources

- **[V1]** HIFIMIDI, *FINALLY! Drum Audio to MIDI That ACTUALLY Works! | PRISM: Drums Review*,
  published 2026-11-13, duration 11:19. [Supplied video](https://www.youtube.com/watch?v=5KlTZG6Zuc4).
  Complete page transcript and expanded description inspected; transcript may
  contain automatic-transcription errors (for example, “Aura” for ARA).
- **[S1]** Aurally Sound, [Announcing Prism Drums](https://docs.aurallysound.com/blog/Announcing%20Prism%20Drums),
  2026-11-01.
- **[S2]** Aurally Sound, [PRISM: Drums product page](https://aurallysound.com/pages/prism-drums-audio-to-midi-for-drums).
- **[S3]** Aurally Sound, [Quick Start: Prism and Prism Drums](https://docs.aurallysound.com/prism/intro).
- **[S4]** Aurally Sound, [Using Prism Drums](https://docs.aurallysound.com/prism/using-prism-drums).

All external sources accessed 2026-11-14. Source documentation establishes
documented behavior; repository code, regression results and model benchmarks
are separate evidence categories.
