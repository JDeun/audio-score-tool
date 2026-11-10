# Real vocal-model conversion fidelity and lead-selection checks

All 40 original vocadito recordings' existing MR-MT3 and YourMT3+ predictions
were converted MIDI → MusicXML → playback MIDI with the current application
functions. No model was rerun, no note was added from a reference, and both
human annotators' original Hz were retained in scoring. Training overlap is
unknown; this is converter evidence on real solo vocals, not held-out
multi-genre generalization or final product-quality approval.

## Observed converter bug and fix

The first 80-output check preserved pitch/onset/offset, but MR-MT3 instrument
preservation fell to 0.99139289 macro F1. Three outputs (`vocadito_2`, `_6`,
`_37`) routed some pitched notes onto channel 10. music21 allocates channels
by GM program alone; an explicitly restored drum program 0 captured pitched
Piano/GM 0. In `_6`, 42 piano notes became percussion despite unchanged pitches
and times. Scorers that exclude percussion could consequently show a spurious
change in the reference score.

Playback restoration now leaves the unpitched-percussion program unset, so
its allocation key stays separate from pitched GM programs. Unspecified pitched
parts retain normal program-0 playback when drums are present. Canonical
MusicXML and the original model MIDI remain unchanged. Regressions cover same
pitched/drum program 0, 1, 40 and 127 and an unspecified pitched instrument.

The second check reused all identical 80 raw predictions:

| Model | Cases | Own-raw onset F1 | Own-raw onset+offset F1 | Own-raw strict instrument F1 |
| --- | ---: | ---: | ---: | ---: |
| MR-MT3 | 40 | 1.0 | 1.0 | 1.0 |
| YourMT3+ | 40 | 1.0 | 1.0 | 1.0 |

Tolerance is onset 50ms and offset max(50ms, 20% of reference duration).
Instrument identity means pitched GM program or percussion, not drum-kit
program variants. **These are preservation scores against each model's OWN
MIDI, not original-song transcription accuracy.** All 160 comparisons against
the two independent human annotators retained exactly the raw model's note
onset and onset+offset F1 after conversion. Thus the conversion no longer
changes which predicted notes enter those reference comparisons.

## Actual lead-selection assessment

The new acoustic vocal selector was also exercised on these 80 real predicted
scores using the original SOLO vocal waveform. References were read only for
subsequent scoring, never selection. This does not assess Demucs bleed on a mix.

| Model | Outputs | Competing parts | Selected | Explicit abstentions | Acoustic changes from largest-part choice |
| --- | ---: | ---: | ---: | ---: | ---: |
| MR-MT3 | 40 | 40 | 0 | 40 | 0 |
| YourMT3+ | 40 | 1 | 40 | 0 | 0 |

This result is deliberately retained: refusing all MR-MT3 examples is NOT
successful automatic vocal transcription. Its fragmented/incorrect part
predictions do not support one confident melody under this fixed rule.
YourMT3+ selection success is also not note accuracy; 39 cases had only one
part, and the earlier raw reference F1 remains limited. The synthetic vocal
versus guitar-leak regression establishes that the implementation can avoid
the largest-part failure; these actual data do not establish a real quality
gain from changing a selected part.

Validation: 62 focused converter/MT3/backend tests passed; full local suite
1,907 passed and one optional FFmpeg-discovery test skipped. That actual
FFmpeg decoder/stereo test separately passed in the 41-test focused run with
the explicit QA binary. Ruff/diff checks passed. [Metadata-only receipts](
VOCAL_CONVERSION_FIDELITY_2026-11-10.json) include before/after metrics,
prediction SHA, original-reference scores and all selection abstentions.

The converter bug belongs to #184. Actual melody quality, source-part
reconstruction, readability, full-song references and editing cost remain
tracked by #34/#185/#200; none is approved by a fidelity F1 of 1.0.
