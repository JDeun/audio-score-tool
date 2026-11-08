# Same-source MR-MT3 vs YourMT3+: real CocoChorales A/B (2026-11-09)

**Classification:** actual real-pretrained inference and independently paired MIDI evaluation, **research only**. Not a held-out/test-split generalization benchmark or a commercial baseline approval.

## Executed, immutable sources

- [GitHub Actions run #42535843289](https://github.com/JDeun/audio-score-tool/actions/runs/42535843289), four author-original WAV/MIDI pairs each transcribed once with independently pinned MR-MT3 and YourMT3+ **in the same workflow run**, with both candidate jobs and cross-candidate source hash comparison **successful**. [Comparison artifact](https://github.com/JDeun/audio-score-tool/actions/runs/42535843289/artifacts/13639661063); original candidate metadata-only artifacts `13639099184` (MR-MT3) and `13639726179` (YourMT3+).
- Original author material: [CocoChorales samples](https://lukewys.github.io/cocochorales/) and exact repo commit `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a`. Each ZIP was compared against the source Git blob/size, the original `main_dataset/mix.wav` and `mix.mid` were independently SHA-256 verified, and the final cross-model report required the exact same original source-proof, audio and MIDI reference hashes for all four cases.
- **MR-MT3**: checkpoint SHA-256 `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`, original HF commit `7bd24c3e1dc26468a6a9354c0a4f174405c9bad8`, `mt3-infer==0.2.0`, `transformers==4.57.6` and AudioScoreTool's program-preserving bridge.
- **YourMT3+**: **YPTF.MoE+Multi (noPS)** checkpoint, SHA-256 `ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25`, original HF Space commit `5e66c1ea173a8186e0d20432b841d3180cc015b5`, `mt3-infer==0.2.0` and `transformers==4.44.2`. The exact 536 MB-class checkpoint was independently downloaded and hashed before use, not accepted solely from a git-lfs path.
- Each candidate ran in a separate GitHub-hosted `ubuntu-24.04` CPU runner. The exact runtime versions differ **only where the adapters require incompatible T5 APIs**; shared source, note tolerances and MusicXML conversion logic are unchanged. CPU runner class matches, though CPU clock/host may differ, so latency comparisons are indicative rather than controlled identical hardware measurements.
- Both candidates were evaluated with the same `score_cocochorales_tiny` note onset tolerance (50 ms), onset+offset tolerance (maximum of 50 ms and 20% of the reference note duration), exact GM program match, and score part counter. The original recordings and model weights/outputs were not uploaded.

## Genuine four-piece measurements

| Source track / ensemble | MR onset F1 | Your onset F1 | MR onset+offset F1 | Your onset+offset F1 | MR GM-aware F1 | Your GM-aware F1 | MR XML parts | Your XML parts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `string_track001010` | 75.21% | **93.27%** | 58.97% | **80.72%** | **52.14%** | 0.00% | 7 | 1 |
| `brass_track049013` | 60.55% | **76.25%** | 40.37% | **60.00%** | 11.01% | **17.50%** | 16 | 3 |
| `woodwind_track097010` | 67.54% | **85.85%** | 41.23% | **72.64%** | **22.81%** | 0.00% | 9 | 2 |
| `random_track145011` | 57.54% | **78.39%** | 35.09% | **56.28%** | **4.91%** | 0.00% | 16 | 2 |
| **Macro, unweighted 4 tracks** | 65.21% | **83.44%** | 43.91% | **67.41%** | **22.72%** | 4.38% | — | — |

From the actual audited JSON, **exact** macro scores are MR-MT3 `note_onset_f1=0.65212963`, `note_onset_offset_f1=0.43914280`, `instrument_onset_offset_f1=0.22716306`; YourMT3+ `note_onset_f1=0.83441140`, `note_onset_offset_f1=0.67410101`, `instrument_onset_offset_f1=0.04375000`. The per-case reference MIDI notes were string 109, brass 89, woodwind 105 and mixed 105.

Raw prediction MIDI note counts: MR 125/129/123/180 vs YourMT3+ 114/71/107/94 in the same order. Indicative per-piece CPU inference wall times (sec): MR 42.51/38.05/31.50/62.91 vs YourMT3+ 37.27/27.68/23.97/27.76; model-specific CPU VM differences prohibit a tight speed ranking.

## Analysis and engineering decision

The models have a **real quality tradeoff**, not one absolute winner:

1. **YourMT3+ wins note onset and full note onset+offset F1 on all four author training examples** (macro +18.23 and +23.50 percentage points).
2. **MR-MT3 yields much better note-level GM instrument identity on three of four examples** (macro +18.34 percentage points). YourMT3+ predicts just 1–3 MusicXML parts even on the original four-voice tracks; the specific program histograms show many strings/woodwind/mixed notes mapped into a small number of broad programs instead of the real ensemble.
3. MR-MT3 preserves more distinct program identities, but its excess voice/part count is also a problem: 7/16/9/16 predicted score parts for four-voice references. Neither output is automatically publication ready.
4. The head-to-head output's **research-only ordering** prioritizes strict instrument-aware F1 and therefore lists MR-MT3 before YourMT3+ for these four examples. This is not a released product winner. A note-focused user may prefer YourMT3+, while a score editor must also consider erroneous part creation/merging, instrument remapping, and total correction work.
5. A hybrid/ensemble may be worth testing in #56, but never promote a hand-picked combination using the known reference program labels. Measure against independent held-out references; any fusion algorithm must preserve provenance, avoid duplicate note events and justify extra latency/edits.

## Hard limits / next work

All four original examples come from the upstream **train split**, with synthetic Bach-style generated audio. They are not separate held-out recordings, independent published performances or real popular music. We did not measure human edit actions, time to publish, peak RAM/VRAM or final score readability. Both model source/weight redistribution rights and the desktop managed release catalog are **still pending**. No model is removed or automatically selected as commercial default. The next meaningful gate is a legally reviewed, **held-out test split** corpus including ensemble/rock/hip-hop/piano/guitar, identical hardware/editor conditions, model license inspection, and output correction-time measurements.

See [umbrella #172](https://github.com/JDeun/audio-score-tool/issues/172), [quality #34](https://github.com/JDeun/audio-score-tool/issues/34), [model consensus #56](https://github.com/JDeun/audio-score-tool/issues/56) and [dataset #154](https://github.com/JDeun/audio-score-tool/issues/154).
