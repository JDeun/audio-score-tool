# Basic Pitch on five cached vocal stems — 2026-11-11

Basic Pitch 0.4.0 was run on the five existing Demucs vocal stems in separate CPU processes. This was new Basic Pitch inference; the source audio, separation, YourMT3, SheetSage2 and Tiny F0 observations were not rerun. Original inputs and producer scores matched their recorded hashes. The fixed protocol uses onset 0.5, frame 0.3, minimum note 127.7 ms, no pitch bends and Melodia; the minimum can exclude fast notes. No thresholds were tuned.

The raw Basic Pitch predictions contain **3,303 notes**. The existing 16th-note dominant-overlap grid represents **2,859**, omits **444**, and flags **676 overlap cells**. YourMT3 selected **2,813** notes, of which the same grid represented **2,693** and omitted **120**. These are different prediction sets; omission counts alone do not establish accuracy. MIDI guards passed for all five canonical and published scores, comparing each export with its own interpreted grid.

| Case | Basic raw | Basic represented | Basic omitted | Basic overlap cells | Your selected | Your represented | Your omitted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| tinashe-me-so-bad | 609 | 520 | 89 | 165 | 564 | 545 | 19 |
| twice-fancy | 698 | 636 | 62 | 195 | 710 | 695 | 15 |
| green-day-american-idiot | 286 | 272 | 14 | 75 | 311 | 308 | 3 |
| ham-boo-young-my-song | 846 | 674 | 172 | 56 | 605 | 551 | 54 |
| younha-event-horizon | 864 | 757 | 107 | 185 | 623 | 594 | 29 |

Cached Tiny F0 gave stable comparisons for 2,650/3,303 raw Basic Pitch notes and 2,164/2,859 final Basic notes. The corresponding consistent counts were 2,296 and 1,949. These are waveform-consistency observations, not accuracy: the note sets, coverage and periodicity filtering differ. No expert reference exists for the whole five-song set.

For two visible measures of a published arrangement, a manual nonexpert pitch-order comparison gave Basic raw **8 attacks/LCS 8** and **9/LCS 9**; Basic final **8/LCS 8** and **8/LCS 8**. Your raw gave **10/LCS 8** and **8/LCS 8**; Your final **10/LCS 8** and **7/LCS 7**. All use the same S2 model-clock windows. The arrangement is not an independently aligned reference for the recording, and this does not measure onset accuracy or whole-song quality.

The separate [40-recording CPU benchmark](CPU_PUBLIC_VOCADITO_RESULTS_2026-11-10.md) reported Basic Pitch onset F1 0.49102 versus YourMT3 0.54341, and onset+offset F1 0.31583 versus 0.30938. That benchmark uses original human note annotations and is a different task from these five stems.

Retain YourMT3 as the incumbent for vocal development. Basic Pitch has not established better whole-song performance on these five; this does not reject the model more broadly. Model rights, packaging, UI, defaults and production quality were not changed or approved.

## Provenance

Stem-inference report SHA-256: `9ce42c50231fb2264ea5b7f5d9686df769156e4764c8ab109ca743ff0d18b582`. Native rendering report SHA-256: `508511db04a3a4cda0fd63f6cf6f8f3f54c2469e886dd61d27be527eada8bf8a`. ONNX asset SHA-256: `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`; Git blob `c30e5f9438e798604b7177aa26be1fe64482f767`. The [metadata JSON](BASIC_PITCH_FIVE_STEMS_2026-11-11.json) records exact runtime, code, input and output hashes.
