# #273 / #274 — frozen gate on new violin recordings: completed results

## Decision

**The vocal-development tail-only gain did not transfer to these six new violin
recordings.** With onset0.65 decoding, raw onset+offset F1 is 31.9305%; tail-only
is 31.8055%, a **0.1250 percentage-point decrease**. One recording improves, one
worsens and four tie. Tail-only restores 0.33 seconds of annotated gap time but
additionally removes **1.41 seconds of annotated-note time**.

Full relative-soft improves macro F1 to 33.7766%, but that must not be described
as recovering more correct note pairs overall: both raw and full have **287**
matched onset+offset reference notes. Full gains one match and loses another
while reducing prediction count from 912 to 852. Its complementary non-tail arm
has unchanged matching masks and 33.9726% F1, with remaining time/onset damage.

The prior [vocadito attribution](AUDIO_GATE_ATTRIBUTION_RESULTS_2026-11-12.md)
remains valid for its repeated development corpus. This external-recording pilot
limits its generalization; it does not justify promoting tail-only or the
observed winning arm to a general automatic correction. Do not tune on these
results and continue calling the same six recordings untouched validation.

## Frozen population and actual execution

The [pre-execution protocol](KRAISLER_GATE_PROTOCOL_2026-11-12.md) selected IDs
**02, 19, 08, 12, 05, 06** by a fixed SHA256 ordering before model results.
All six complete original KRAISLER VN dry recordings were admitted, with no
replacement, excerpt choice, time shift or normalization: **403.2338095 seconds**,
**947 performed-note annotations**, two unchanged decoders and four fixed arms.
All **48 conditions** completed. These are six correlated recordings from the
same collection/performers, not 48 independent samples.

[CPU run 43184102838](https://github.com/JDeun/audio-score-tool/actions/runs/43184102838)
and [job 131066914555](https://github.com/JDeun/audio-score-tool/actions/runs/43184102838/job/131066914555)
succeeded on 2026-11-12, finishing at 08:36:37 UTC / 17:36:37 Asia/Seoul.

- PR head: `faac53d0b9b63d8b8420e8fdb788dd3ec4cf4cda`.
- Actual PR test-merge checkout: `7491b822c2d0d8cfe82193dea9c7135b91ebec2a`,
  combining that head with main `1c9514e30e2aac92ba6857e67a940dc48b6a03e6`.
- Six recording-level predictor invocations, all completed. Both decoders share
  each recording's neural output; the model can use multiple internal windows.
- All eight inherited gate/model/decoder/scoring source hashes matched. No
  thresholds, edit costs, candidates, decoder settings or scorer were retuned.
- Source transfer: seven exact HTTP 206 responses, 28,339,853 bytes, zero cache
  hits, all 24 source member CRC/SHA/size identities verified. No full ZIP or
  whole-archive MD5 verification is claimed.
- The old 40-recording vocadito corpus was not rerun.

One CI measurement recorded 63.81s for acquisition/model preparation/inference/
evaluation combined, with 20.10s summed recording-level model calls and 0.77s
model preparation. Package installation is excluded. The first model call
includes cold-start work; these observations are not a controlled speed benchmark.

## Note metrics, both unchanged decoders

Percent values below are equal-weight means over the six recordings. No note-
weighted or outcome-selected aggregate is substituted. Matching is against the
source's reviewed alignment-derived violin note CSV: 50ms onset, 50 cents pitch,
and max(50ms, 20% reference duration) offset tolerance.

| Arm | Default onset F1 | Default onset+offset F1 | onset0.65 onset F1 | onset0.65 onset+offset F1 |
| --- | ---: | ---: | ---: | ---: |
| Raw | 48.7229% | 22.2367% | 58.1478% | 31.9305% |
| Full relative-soft | 50.8138% | 23.2138% | 61.3392% | 33.7766% |
| Tail-only | 48.7229% | 22.2116% | 58.1478% | 31.8055% |
| Complementary non-tail | 50.8138% | 23.2391% | 61.3392% | 33.9726% |

The default decoder's tail-only change is also negative, **−0.0251pp**; full is
+0.9771pp and non-tail +1.0024pp. For onset0.65, full is +1.8460pp, tail-only
−0.1250pp and non-tail +2.0421pp. Arm differences are nonlinear and must not be
added as causal-contribution percentages.

### Edits and matching ledger, onset0.65

| Arm | Output notes | Changed parents | Tail / onset trim / delete / split | Offset matches gained / lost | Recordings better / worse / equal |
| --- | ---: | ---: | --- | --- | --- |
| Raw | 912 | 0 | 0 / 0 / 0 / 0 | 0 / 0 | 0 / 0 / 6 |
| Full relative-soft | 852 | 69 | 8 / 1 / 60 / 0 | 1 / 1 | 6 / 0 / 0 |
| Tail-only | 912 | 8 | 8 / 0 / 0 / 0 | 1 / 1 | 1 / 1 / 4 |
| Complementary non-tail | 852 | 61 | 0 / 1 / 60 / 0 | 0 / 0 | 5 / 0 / 1 |

Tail-only preserves every onset and output count, but not every previously
correct offset match. All four arms have 287 matched offset-reference notes in
total. Full/non-tail also lose one onset-only match with no gained onset match,
despite their improved macro onset F1. Their count reduction improves precision
while some correct content is damaged.

For the default decoder, raw/tail retain 1,215 notes and full/non-tail have 1,151.
Full changes 72 parents: eight tail trims and 64 deletions. Each arm has 247
matched offset-reference notes; tail/full gain one and lose one. Default full
improves five recordings and worsens one; non-tail improves five and ties one.

### Per-recording onset+offset F1, onset0.65

| ID | Reference notes | Raw | Full relative-soft | Tail-only | Non-tail |
| --- | ---: | ---: | ---: | ---: | ---: |
| 02 | 73 | 36.5854% | 36.8098% | 36.5854% | 36.8098% |
| 19 | 295 | 25.8687% | 26.2548% | 26.2548% | 25.8687% |
| 08 | 203 | 22.3464% | 22.7920% | 22.3464% | 22.7920% |
| 12 | 65 | 29.5455% | 39.0625% | 28.4091% | 40.6250% |
| 05 | 151 | 40.0000% | 40.3909% | 40.0000% | 40.3909% |
| 06 | 160 | 37.2372% | 37.3494% | 37.2372% | 37.3494% |

Track **12** is the clearest warning against treating F1 gain as endpoint
recovery. Raw has 111 predictions and **26** matched offset-reference notes;
full has 63 predictions and **25** matches. F1 nevertheless rises from 29.5455%
to 39.0625% because the denominator shrinks. Non-tail keeps the 26 matches with
63 predictions, reaching 40.6250%. Tail-only keeps 111 predictions but loses the
match, falling to 28.4091%. This comparison does not reconstruct which private
events were deleted or authorize a per-file oracle choice.

## Time occupancy: additional damage is larger than restored gaps

Same inherited 10ms grid and first-to-last performed-reference-note scope.
Reference union contains **319.51s of note time** and **35.90s of gap time**.
Totals below use a single annotation per recording, not A1/A2 averages.

| onset0.65 arm | Wrongly covered gap | Wrongly unoccupied note | Gap restored vs raw | Additional note time removed |
| --- | ---: | ---: | ---: | ---: |
| Raw | 21.69s | 21.14s | 0 | 0 |
| Full relative-soft | 20.67s | 23.63s | 1.02s | 2.49s |
| Tail-only | 21.36s | 22.55s | 0.33s | 1.41s |
| Complementary non-tail | 21.00s | 22.22s | 0.69s | 1.08s |

Default decoder tail-only restores 0.34s and removes an additional 1.51s of note
time; full restores 1.07s and removes 2.49s; non-tail restores 0.73s and removes
0.98s. None of these arms dominates the raw control on all measured outcomes.
The original gate's union occupancy metric ignores pitch and does not include
easy outer silence; note matching includes all predictions. Keep those scopes
distinct when interpreting track 12 or the aggregate.

## Score/rest admission: useful sources, no invented alignment

All six XML/beat structural audits succeeded, but **zero** violin score-to-audio
mappings were established. The source includes 77 XML `<rest>` elements, 64
staccato tags, 32 tenuto tags, 93 accent tags, 109 chord members and 16 grace
notes across 234 measures. These are structural element counts, not 77 verified
silent audio intervals or 64 timed articulation-gap labels.

| ID | XML rests | Staccato tags | Chord members | Notable structure |
| --- | ---: | ---: | ---: | --- |
| 02 | 6 | 0 | 0 | 3/2↔4/4, six grace notes, 28 tenuto tags |
| 19 | 11 | 51 | 76 | double stops, eight grace notes |
| 08 | 33 | 13 | 22 | 6/8, multiple voices |
| 12 | 12 | 0 | 0 | 2/4 |
| 05 | 14 | 0 | 11 | 2/2, 49 accent tags |
| 06 | 1 | 0 | 0 | two grace notes, no articulation tags |

A mono-channel stem can contain overlapping notes. A rest in one voice does not
mean the whole instrument is silent. Violin note CSV has no MusicXML IDs, and
global beat timestamps require validated pickup/measure/beat-unit mapping.
No written-rest F1, automatic beat inference, exported-score accuracy, listening
quality or editing-time benefit is measured here.

The dataset authors state that note CSV was alignment-derived and manually
reviewed, with less reliable offsets than onsets/pitch. This limits endpoint
interpretation even when our metadata arithmetic is exact. The recordings are
new to this gate study, but pretraining overlap was not independently verified.
The small, single-collection sample does not establish transfer to new players,
voices, mixtures or reverberation conditions.

## Durable receipt and validation

Artifact **13927279033**, retained exactly as
`receipts/kraisler-gate-43184102838.zip`:

- ZIP size: **16,111 bytes**; SHA256
  `ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e`.
- Sole member `report.json`: **155,591 bytes**; SHA256
  `e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754`.
- Source manifest SHA256:
  `a18857a4b7a2025ea327f9a03855ca02dca0964110d973d5224b85dfbb258c60`.
- No raw audio, source XML/CSV, prediction events, MIDI, neural arrays or model
  weights are included. Full detail is derived metric/provenance metadata.

A separate standard-library audit, without importing experiment scoring or
aggregation helpers, verified six unique complete IDs, all 48 conditions,
96 F1/mask identities, 96 gain/damage ledgers, 48 operation/count/occupancy
ledgers, 12 disjoint tail/non-tail partitions, all 24 source member hashes and
17 measured source-file hashes. It independently rebuilt every macro,
per-recording comparison and occupancy total within 1e-12 arithmetic tolerance.
The head and actual PR checkout have the same Git tree
`75e790d82812b3e4986114bb05cf529a32f9007c`, as independently retrieved from GitHub.
This verifies metadata arithmetic and source identity; it does not rematch the
private source events, rerun the model or establish missing score alignment.

**88** new source/evaluator/failure-path tests passed locally and in the CPU
workflow. [Initial-head CI 43184102607](https://github.com/JDeun/audio-score-tool/actions/runs/43184102607)
passed: 2,119 product tests, nine optional skips; 719 research tests, one existing
upstream warning; 200 product / 33 research files, zero omitted. Python,
frontend and required `verify` succeeded; Tauri was conditionally skipped for
the PR. [Research Evidence Contracts 43184102593](https://github.com/JDeun/audio-score-tool/actions/runs/43184102593)
also passed at the same head. Later report-only commits require their own CI;
the current status is linked from [PR #274](https://github.com/JDeun/audio-score-tool/pull/274).

## Next research decision

Keep the negative tail-transfer result. The next score-rest step is to validate
violin note/beat-to-MusicXML correspondence, with explicit handling of grace
notes, ties, pickups, compound meter and overlapping voices. Only then can
gating harm be separated by written rest versus articulation labels. The full
and non-tail F1 gains here support examining rejected predictions and precision,
not declaring reliable offset recovery or automatic product quality.

Source: Kim, Park, Lee, Kwon, Won and Nam, *KRAISLER: A Multi-Track Dataset of
Piano and Violin Duet Recordings for Music Information Retrieval Research* (2026),
https://zenodo.org/records/21082251, https://doi.org/10.5334/tismir.338.
The source lists CC BY 4.0 together with noncommercial wording; this work is
research evaluation and does not assert commercial clearance. See also
[PR cleanup](PR_CLEANUP_2026-11-12.md) and the [receipt index](receipts/README.md).
