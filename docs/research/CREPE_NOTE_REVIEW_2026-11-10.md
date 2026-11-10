# CREPE note evidence review — 2026-11-10

This is a metadata-only review, not a quality approval or an estimate of whole-song accuracy. Existing product YIN and scores remain unchanged; no automatic pitch correction is authorized by these observations.

## Calibration scope

The same Vocadito v3 archive, 40 recordings and two human annotations per recording were used. The YIN report’s audio and annotation hashes match the archive; the tiny run verified all 40 source hashes. Both reports have the same case IDs and per-annotator note counts. Original human note frequencies were rounded to the nearest semitone as a surrogate score. This calibration is separate from the primary benchmark using original Hz. The runs used different environments, so this is an observation-coverage comparison, not a controlled speed comparison.

| Verifier | Compared / surrogate notes | Coverage | Warnings / compared | Octave warnings / compared |
| --- | ---: | ---: | ---: | ---: |
| YIN | 2,096 / 4,113 | 50.96% | 170 / 2,096 (8.11%) | 6 / 2,096 (0.29%) |
| torchcrepe tiny | 2,935 / 4,113 | 71.36% | 233 / 2,935 (7.94%) | 5 / 2,935 (0.17%) |

With a one-direction +12-semitone shift of the surrogate notes, tiny flagged 2,702 of 2,935 compared notes (92.06%), or 2,702 of 4,113 total notes (65.69%); 1,178 of 4,113 (28.64%) were not compared. This does not establish detection in both directions or precision on all real errors. Tiny raw selected notes had 1,197 / 1,809 compared, with 2 octave and 256 pitch warnings; these warnings are not a ground-truth error rate.

## Five-song cross-check

The pre-existing Demucs vocal stems and existing selected and final MIDI were used without changing the source audio or running new separation or AMT. The unchanged note comparator reports only stable waveform observations; it may abstain and is not expert ground truth. Differences below are observed minus notated semitones. Octave warnings labeled +12 or −12 are within 0.5 semitone of that displacement.

| Case | Arm | Compared / predicted | Consistent | Octave | Pitch | +12 / −12 | Median / p10 / p90 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| younha-event-horizon | selected | 545 / 623 | 540 | 0 | 5 | 0 / 0 | 0.0030 / -0.1396 / 0.1036 |
| younha-event-horizon | final | 484 / 594 | 473 | 0 | 11 | 0 / 0 | -0.0005 / -0.1490 / 0.1077 |
| tinashe-me-so-bad | selected | 420 / 564 | 366 | 9 | 45 | 8 / 1 | -0.0200 / -0.3365 / 0.2262 |
| tinashe-me-so-bad | final | 372 / 545 | 326 | 8 | 38 | 7 / 1 | -0.0290 / -0.3343 / 0.1978 |
| twice-fancy | selected | 551 / 710 | 518 | 5 | 28 | 4 / 1 | 0.0130 / -0.1680 / 0.1650 |
| twice-fancy | final | 543 / 695 | 504 | 5 | 34 | 4 / 1 | 0.0110 / -0.1808 / 0.1770 |
| green-day-american-idiot | selected | 189 / 311 | 178 | 3 | 8 | 3 / 0 | 0.0450 / -0.2018 / 0.3052 |
| green-day-american-idiot | final | 182 / 308 | 172 | 3 | 7 | 3 / 0 | 0.0330 / -0.1884 / 0.2662 |
| ham-boo-young-my-song | selected | 447 / 605 | 399 | 0 | 48 | 0 / 0 | -0.0160 / -0.4006 / 0.2646 |
| ham-boo-young-my-song | final | 332 / 551 | 299 | 0 | 33 | 0 / 0 | -0.0030 / -0.3615 / 0.2647 |
| **Total** | **selected** | **2152 / 2813** | **2001** | **17** | **134** | **15 / 2** | **0.0010 / -0.2229 / 0.1999** |
| **Total** | **final** | **1913 / 2693** | **1774** | **16** | **123** | **14 / 2** | **0.0000 / -0.2268 / 0.1938** |

## Provenance

Full source-report SHA-256 values, per-case source, stem, selected MIDI, final MIDI and interpretation SHA-256 values, actual runtime versions, model and script hashes are in the [companion JSON](CREPE_NOTE_REVIEW_2026-11-10.json). No raw notes, predicted F0, media or model weights are included.

Tiny weights SHA-256: `d4993eea36ed1a0ad9ac549c740dae5265b049ce72004f00c2f59e01c0be8432`; Git blob: `18d881163b9f7ddf8daf0709c75cf204f5570da5`. CPU, 2 threads, seed 0; 55–880 Hz, 10 ms hop, Viterbi decoding, periodicity threshold 0.21, silence threshold −60 dB. The product YIN backend was not replaced.
