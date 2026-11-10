# Independent vocal/chord evidence in the actual product

The current revision-4 scores for the five specified recordings were copied
into an isolated app database and checked with the real
`POST /api/songs/{id}/validate` route. The API ran a fresh official pinned
Demucs 4.0.1 htdemucs CPU separation for each original waveform, then compared
its vocals and no_vocals backing with the CURRENT canonical MusicXML.
All five API executions completed without changing score text or revision.
This reused the original transcription predictions, not five new SheetSage2 runs.

| Recording | Stable vocal notes compared / predicted | Octave suspects | Other pitch suspects | Chord spectral warnings / compared intervals |
| --- | ---: | ---: | ---: | ---: |
| Me So Bad | 66 / 410 | 29 | 33 | 22 / 159 |
| FANCY | 67 / 573 | 37 | 29 | 2 / 181 |
| American Idiot | 31 / 354 | 20 | 11 | 1 / 277 |
| 나의 노래 | 166 / 531 | 91 | 75 | 3 / 171 |
| 사건의 지평선 | 229 / 573 | 149 | 80 | 4 / 149 |

These are acoustic review signals, **not error counts, transcription accuracy,
or chord WCSR**. Only 559/2,441 predicted notes met the stable-note observation
conditions. The remaining notes are unmeasured, not correct. The product uses
NumPy YIN difference minima and an FFT-chroma triad comparison; this is not
the earlier research pYIN/CQT implementation. No_vocals includes drums, whereas
the earlier diagnostic backing was bass+other. Counts between these methods
must not be compared as improvements in musical accuracy. Repeated MusicXML
harmony entries also differ from raw model LAB intervals.

## Calibration and limits

The same fixed vocal verifier was checked on all 40 original vocadito v3
solo-vocal recordings and BOTH independent human note annotations. For this
validator calibration only, human note Hz were rounded to MIDI semitones to
simulate a notated score. The original Hz remain unchanged in the primary
AMT benchmarks. No thresholds were tuned using these results.

Across 4,113 annotated notes (two annotators counted separately), 2,096 met
the stable observation conditions: 1,926 were consistent, 6 were flagged as
octave suspects and 164 as other pitch suspects. Thus even a score surrogate
derived from human annotations produces review warnings. These results do
not calibrate correctness probabilities or authorize automatic pitch edits.
Separation bleed, harmonies, short notes and unstable pitch require abstention
or review. Coverage on solo vocals does not transfer to mixed popular songs.

## Product changes and checks

- Acoustic comparison runs independently of the optional FluidSynth/SoundFont
  resynthesis. All five fresh API checks completed with no SoundFont configured;
  only resynthesis was explicitly skipped.
- Original source time is computed from the score tempo map plus an actually
  applied crop. Unknown/nonfinite crop clocks are unmeasured, never guessed.
- The desktop shows observed note coverage, octave/chord review counts and
  truncation after 200 issue entries. Evidence never changes the score.
- Competing MT3 vocal parts are ranked by absolute waveform pitch/time support.
  Insufficient/ambiguous support refuses selection instead of picking by note
  count. A two-note vocal versus ten-note guitar-leak regression selects the
  vocal without rewriting its values. Single-part identity and real mixed-song
  selection quality still need the musical-quality evaluation.
- The first API attempt found Demucs in-place normalization of an expanded
  mono tensor. That attempt remains recorded as unmeasured. A shared stereo
  PCM normalization now covers all four current/legacy Demucs callers; fresh
  five-song separation completed after the fix.

Validation: 41 focused tests passed with real FFmpeg pitch/channel checks;
Chromium current-song selection/acoustic evidence test and production build
passed. With optional mir_eval installed, the full local suite had 1,900
passes and three localhost-bind sandbox failures; the two affected test files
then passed all 17 tests outside that restriction. Required PR CI is tracked
on [#208](https://github.com/JDeun/audio-score-tool/pull/208).

[Metadata-only receipts](ACOUSTIC_PRODUCT_VALIDATION_2026-11-10.json) retain
recording/score/checkpoint/wrapper/source hashes, failed attempt and calibration
counts. Original audio, stems and symbolic scores remain private.

Remaining: improve transcription, validate actual lead selection against
references, measure full-song note/chord accuracy and editing cost, then fix a
single final model/configuration. This product wiring is not final quality approval.
