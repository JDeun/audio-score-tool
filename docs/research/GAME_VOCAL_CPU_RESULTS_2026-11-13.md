# GAME-large CPU vocal evaluation

Related: #172, #214, #200. All 40 solo-vocal recordings and all five full-length
acceptance-song inferences, Song publications and bounded reference comparisons
completed.

GAME improves pitch-and-onset matching over the frozen local YourMT3 baseline
on this development corpus. Its official integer MIDI loses much of the gain
seen with fractional-pitch CSV. Offset-inclusive quality remains substantially
lower, with losses on previously matched reference notes. The subsequent
mixed-song comparison does not establish a publication-quality improvement.
Retain the frozen YourMT3 development baseline; do not promote GAME or add a
product option from these results. Final publishing quality remains unapproved.

## Fixed candidate and protocol

- [Official GAME source](https://github.com/openvpi/GAME/tree/69ba01ded0ddda5495e51ba373685f1be1a67ea2),
  revision `69ba01ded0ddda5495e51ba373685f1be1a67ea2`, with no tracked source changes.
- One [GAME-1.0-large checkpoint](https://github.com/openvpi/GAME/releases/tag/v1.0.0).
  Archive SHA256 `f45eac9fbb92b82fe67c00f29efad52954469897eb64e5bd5924a43dc5deb9b6`;
  extracted checkpoint `1a286ae10cd460cbce46de1f96c2922d048d03dd88fbd089433787f8d8f97661`.
  The code is MIT; the release explicitly licenses the weights CC BY-NC-SA 4.0.
- Python 3.11.15, PyTorch 2.15.0, Lightning 2.6.6, NumPy 1.26.4, librosa 0.11.0.
  The isolated environment and all other package versions are in the
  [metadata receipt](GAME_VOCAL_CPU_RESULTS_2026-11-13.json).
- CPU, two threads, seed 0 reset per recording, float32, batch size 1, zero workers.
  A separate launcher forces Lightning `accelerator='cpu', devices=1`; the official
  inference source is unchanged. No MPS/CUDA execution or model caching acceleration.
- Default segmentation/presence thresholds 0.2, boundary radius 0.02 s,
  D3PM `t0=0, nsteps=8`, language ID 0 for every recording.
- The same original vocadito v3 WAVs and both original-Hz A1/A2 note annotations.
  All 40 WAV hashes match the original ZIP and the previous local baseline.
  No pitch shift, reference-based alignment, case exclusion or per-recording tuning.

The official CLI emits fractional-pitch CSV and rounded-pitch MIDI. Both are scored
separately at onset 50 ms / pitch 50 cents. Offset-inclusive matching additionally
allows max(50 ms, 20% of reference duration). Macro scores give each of the 40
recordings and both annotators equal weight. Dataset training overlap is unknown;
this repeatedly used corpus is development evidence.

## All-recording results

| Saved output | Pitch + onset F1 | Pitch + onset + offset F1 | Predicted notes |
| --- | ---: | ---: | ---: |
| Frozen local YourMT3 selected MIDI | 54.320241% | 30.870417% | 1,809 |
| GAME fractional-pitch CSV | 70.301646% | 36.235586% | 1,913 |
| GAME official integer MIDI | 63.486867% | 31.979941% | 1,913 |

This local YourMT3 baseline reproduces the exact selected-MIDI hashes and per-case
scores of the earlier local comparison. Its aggregate is not the separate public
CPU workflow's 54.340549% / 30.937724% figure; those values are not substituted here.

| Compared with local YourMT3 | Improved / worsened recordings | Gained / lost reference judgments |
| --- | ---: | ---: |
| GAME CSV, onset | 36 / 4 | 962 / 266 |
| GAME CSV, onset + offset | 30 / 10 | 631 / 398 |
| GAME MIDI, onset | 33 / 7 | 771 / 348 |
| GAME MIDI, onset + offset | 26 / 14 | 506 / 438 |

Improvement counts average A1/A2 within each recording. Reference judgments count
each annotator separately; they are matching diagnostics, not causal error labels.
The MIDI improvement is 9.166626 percentage points for onset and 1.109524 points
including offset. F1 gains do not establish reduced human editing effort.

## Serialization diagnostic

After the fixed comparison, a separate diagnostic crossed the saved CSV and MIDI
pitch/time arrays. It did not edit outputs or run inference. All 1,913 events pair
in order; CSV/MIDI timing differences are below 1.1 ms.

| Pitch values / time values | Onset F1 | Onset + offset F1 |
| --- | ---: | ---: |
| CSV / CSV | 70.301646% | 36.235586% |
| Official MIDI / CSV | 63.498701% | 31.975543% |
| CSV / official MIDI | 70.310304% | 36.239985% |
| Official MIDI / official MIDI | 63.486867% | 31.979941% |

The large difference follows pitch quantization in this original-Hz evaluation;
sub-millisecond time serialization has a small effect. This does not supply a
correct written-note interpretation for detuned singing. No tuning-offset or
pitch-correction rule is inferred or applied from this diagnostic.

## Verification and remaining work

Every inference exited zero. Initial dependency failures for h5py, colorednoise
and matplotlib are retained in the execution record; they are not quality results.
The isolated environment was repaired before the full cohort. The first recording
was inferred twice with byte-identical CSV and MIDI.

A separate re-scoring script read all saved predictions and original annotations,
verified all source hashes and prior baseline MIDI hashes/scores, and recomputed
the macro and paired matching diagnostics. It agrees with the producer's shared
scorer. The metadata includes per-case/annotator scores, counts and identities;
raw audio, annotations, prediction events and weights remain private.

## Five full-length songs and actual publication

All five frozen Demucs vocal stems completed with the same checkpoint/settings,
including FANCY's full 118.08-second default slice. No fresh separation, source
download or SheetSage2 inference was performed. The existing frozen SheetSage2
beat/chord/key context was rebuilt around each GAME MIDI, imported, saved as a
notation-import Song in an isolated store, and exported through `build_exports_v3`.
This is a cached-context conversion test, not a new Job/API integration test.

| Song | Raw GAME notes | Represented / omitted | PDF pages |
| --- | ---: | ---: | ---: |
| Me So Bad | 550 | 535 / 15 | 5 |
| FANCY | 616 | 612 / 4 | 7 |
| American Idiot | 297 | 295 / 2 | 9 |
| 나의 노래 | 613 | 570 / 43 | 5 |
| 사건의 지평선 | 568 | 551 / 17 | 7 |

All canonical/published interpreted-note MIDI guards passed: 2,563 represented
events from 2,644 source events, maximum published timing error 0.02084 ms against
the declared interpretation. This is conversion fidelity, not original-song
accuracy. All inputs remained unchanged. First-page images for all five were
inspected; every PDF page was not visually reviewed. Korean titles, tempo/key
display and chord symbols render. The American first page still displays the
frozen context's approximately 219 BPM and long N.C. regions; changing the vocal
model does not repair that structure/harmony evidence.

An initial publication launcher exited before processing because its preflight
had created the guarded output store. That attempt was preserved. The successful
fresh run isolated all product/model import preflight work in a subprocess and
used hash-verified pure-Python dependencies privately, without changing the main
environment.

### Whole American chart

The existing 310-note community vocal chart and its independently frozen
drum-only source-time fit were reused, with no GAME-based alignment.

| Output | Pitch + onset F1, 50 ms | Pitch + onset + offset F1 |
| --- | ---: | ---: |
| YourMT3 raw | 68.599034% | 56.682770% |
| GAME raw MIDI | 68.533773% | 53.377265% |
| YourMT3 published | 63.430421% | 47.572816% |
| GAME published | 63.471074% | 45.289256% |

GAME raw matches 208 onset / 162 onset+offset reference judgments, versus
YourMT3's 213 / 176. The very small published onset-F1 difference accompanies
fewer predictions and fewer matches (192 versus 196); it does not establish
better melody recovery. At 100 ms the raw onset F1s are similar, while GAME's
raw and published offset-inclusive scores remain lower.

### Partial arrangements

On the existing Me So Bad chorus, four FANCY sections, and two American excerpts,
GAME MIDI's 50 ms onset result is lower than YourMT3 under both the authored-endpoint
and nominal-BPM projections. At 100 ms some nominal-projection comparisons improve;
all projections/tolerances remain in the metadata. Approximate community sync and
arrangement differences prevent treating these low excerpt scores as full-song
accuracy.

For the publisher-preview pitch-order diagnostic, 나의 노래 improves raw LCS from
5/7 to 6/7, but its published output returns to 5/7. 사건의 지평선 raw GAME matches
7/9 and 8/9, versus the frozen raw YourMT3's 8/9 and 8/9; published results are
7/9 and 8/9 versus 8/9 and 7/9. These short, model-window-assisted comparisons
provide no independent timing or whole-song quality approval.

Final model selection, commercial use of weights, whole-song chord/note accuracy,
readable written rhythm and human correction cost remain unapproved. Product
defaults and dependencies are unchanged.
