# BeatThis DBN clock experiment — 2026-11-11

The previous [minimal-decoder experiment](BEAT_CLOCK_WIP_2026-11-11.md) remains unapproved. This branch uses the pinned BeatThis final0 observations with the upstream DBN postprocessor only: 50 fps, 3 or 4 beats per bar, 55–215 BPM and transition lambda 100. The decoder uses madmom code without madmom pretrained weights. This is not an accuracy or production-quality approval.

A previous five-recording DBN run produced observations for all five source recordings. The current adapter was then tested using those cached observations, without new model inference. All five passed the interpretation-to-MIDI 2 ms guard. The visible approximate tempo and UI tempo use the same median of observed beat periods; changing the display tempo did not change performed events within the guard.

| Case | Observed beats | Observed downbeats | Selected notes | Represented | Omitted | Observed median BPM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| tinashe-me-so-bad | 338 | 84 | 564 | 550 | 14 | 100.00 |
| twice-fancy | 474 | 119 | 710 | 693 | 17 | 130.43 |
| green-day-american-idiot | 538 | 135 | 311 | 308 | 3 | 187.50 |
| ham-boo-young-my-song | 330 | 83 | 605 | 558 | 47 | 63.83 |
| younha-event-horizon | 487 | 122 | 623 | 614 | 9 | 96.77 |

The observed median is a display estimate, not a claim about the original tempo. Whole-song accuracy, chord alignment, readability and production readiness remain unverified. The global phase guard is conservative and was chosen after seeing conflict in the minimal-decoder run; passing it does not certify every bar. Meter changes, compound meters and 2/4 are unsupported; 3/4 and 4/4 are conditional on matching, dominant downbeat evidence. No silent fallback is allowed.

The fixed runtime pins BeatThis revision `b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`, final0 SHA-256 `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`, and madmom source revision `27f032e8947204902c675e5e341a3faf5dc86dae`. Logits and decoded clocks are preserved with source-bound receipts.

[Five-case metadata](BEAT_THIS_DBN_CLOCK_2026-11-11.json) records the source hashes, votes and checks. Cached DBN five-report SHA-256: `b4df197abf834e0fc769e88288914d812447be8c800a3321b7a9e584426c4947`. Current cached adapter report SHA-256: `fa3989cee6f410a7620a9e3ff7f010d0245b541a8e7c4a6dfbc73633f98fd197`.

A subsequent single-recording beat CLI smoke used an isolated runtime and separate snapshot. The source, checkpoint and adapter remained unchanged; the decoded clock and both logits arrays matched the prior cached arrays exactly. The source-derived STFT frame-count check passed. This was not a complete transcription Job. madmom Python sources are pinned independently of architecture; native extension hashes and platform are recorded as build-specific evidence, not cross-platform approval.

The [Me So Bad product run](BEAT_THIS_DBN_PRODUCT_2026-11-11.md) records the full Job, PDF/MIDI/MusicXML export and actual Job deletion in an isolated clone.

Commit `b0ef546` estimates the displayed BPM from the median duration of complete bars. A single beat interval on the 50 fps clock is rounded to a 20 ms step, which can bias the displayed median. The bar calculation changed the cached FANCY estimate from 130.43 to 131.87 BPM and Event Horizon from 96.77 to 98.36 BPM. The other three estimates were unchanged.

The FANCY [community transcription](https://www.hooktheory.com/theorytab/view/twice/fancy) links the same music video and lists 132 BPM and 4/4. The [ranked game chart](https://osu.ppy.sh/beatmapsets/960258) also has a single 132 BPM, 4/4 timing point in its [timing file](https://osu.ppy.sh/osu/2010513), SHA-256 `2252b8a3d4f5b9a4bb685658daf1934d7bef9f1cbb5d9d51ab95770f445e8f93`. Its 10.1-second preview matched the frozen audio at correlation 0.964. The waveform alignment and chart's video offset differed by 140 ms. This leaves the absolute beat times unverified.

Both changed scores were rebuilt from cached input. The BPM text appeared in each embedded PDF and matched the product metadata. Before and after MIDI events were identical for all 693 and 614 performed notes, respectively. Both passed the 2 ms notation guard and all inputs retained their hashes. Cached rebuild report SHA-256 `6d3d0592af2a137124710b0c701d55040d58976137b44cb23b9606fbe066ce51`. The focused beat and recipe tests passed 28 checks.
