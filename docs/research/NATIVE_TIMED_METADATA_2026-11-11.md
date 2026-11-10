# Native timed metadata evidence

The native importer preserves source chord changes, including NoChord, and places source key changes on the existing sixteenth-note grid. Initial key is inherited; an initial implicit NoChord precedes the first explicit chord. A first positive source chord spanning the score origin is inherited at the origin with its original time and residual recorded; earlier finished intervals and later out-of-range changes fail closed. Original annotations are observations, not verified musical truth.

Ten cached cases combine five source songs with the baseline clock and a separately evaluated DBN clock. On source commit `b6f5497`, canonical MusicXML and MIDI were rebuilt from cached inputs without model inference or PDF rendering. All ten passed the 2 ms interpretation guard and direct comparison with their earlier MIDI; pitch, program and drum identity were preserved. All 1,596 noninitial source changes fell inside their existing canonical audio clocks. Inputs were checked unchanged during the rebuild.

| Case | Clock | Changes | Maximum placement residual (s) | Internal chord agreement |
| --- | --- | ---: | ---: | ---: |
| tinashe-me-so-bad | baseline | 120 | 0.000000 | 1.000000 |
| tinashe-me-so-bad | dbn | 120 | 0.070000 | 0.980643 |
| twice-fancy | baseline | 163 | 0.000000 | 1.000000 |
| twice-fancy | dbn | 163 | 0.059997 | 0.979486 |
| green-day-american-idiot | baseline | 207 | 0.000003 | 0.999996 |
| green-day-american-idiot | dbn | 207 | 0.040003 | 0.976651 |
| ham-boo-young-my-song | baseline | 167 | 0.000001 | 0.999999 |
| ham-boo-young-my-song | dbn | 167 | 0.119998 | 0.967388 |
| younha-event-horizon | baseline | 141 | 0.000003 | 0.999999 |
| younha-event-horizon | dbn | 141 | 0.075003 | 0.983698 |

Agreement is duration-weighted source-to-output timeline agreement, not original-song accuracy or WCSR. The source NoChord runs were retained in the timeline comparison. The Ham key-change timing discrepancy in the DBN case changed from approximately 2.301 s to 0.019 s; initial key display timing is excluded. Quantization can collapse a very short interval, which is recorded rather than hidden.

Canonical MusicXML retains standard NoChord harmony. For PDF rendering only, a temporary renderer input displays its label as words, respecting hidden and custom labels; the canonical file remains unchanged. Owned tests cover held notes, rests, ties, accidentals, origin and tempo, source chord aliases and editor round trips. UTF-16 rendering and compressed MXL fallback have separate coverage.

A subsequent narrow inversion fix (`0d714a5`) supports recognized sixth and minor-major-seventh chord-tone basses. The five cached source chord files contain 112 previously supported slash labels and none of those newly supported labels. Owned source-row tests cover all 15 native qualities, native aliases and the three sixth/minor-major-seventh slash examples. Other unsupported Harte slash forms remain explicit failures; this is not a claim of full slash grammar support. The ten-case `b6f5497` run was not repeated. Neither source observations nor these checks establish pitch, harmony or notation quality against expert references; commercial quality approval remains false.

The accompanying JSON records input/output hashes, source and script hashes, event counts and per-case limits. No source media, note events or model weights are included.
