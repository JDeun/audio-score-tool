# MR-MT3 instrument-program MIDI serialization: measured before/after

**Status:** actual author-provided audio + reference MIDI measured on Linux CPU. This is a diagnostic research result, **not** a held-out model-quality certification, source-rights signoff, or commercial release acceptance.

## Reproducibility

- Baseline unmodified `mt3-infer==0.2.0`: [successful four-ensemble run #42490888388](https://github.com/JDeun/audio-score-tool/actions/runs/42490888388), head `c070cc5d6845ebcec024eca057b134d68ce035c5`.
- Program-preserving AudioScoreTool bridge: [successful four-ensemble run #42497603878](https://github.com/JDeun/audio-score-tool/actions/runs/42497603878), head `c409fabbbfbce5fb2be3cafd41dfdae6a0e615c2`, [source fix PR #169](https://github.com/JDeun/audio-score-tool/pull/169), merge `a9d241dd6f16bab541795abf0ff02c990bbcdb90`.
- Both runs use the same official author-published CocoChorales examples pinned to source commit `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a`, the same per-archive Git blob and SHA-256 verification and the same reference MIDI, case identifiers, note-matching tolerances, and pinned MR-MT3 checkpoint.
- Model: `mr_mt3` via `mt3-infer==0.2.0`, `transformers==4.57.6`, `torch==2.7.1`; upstream original model commit `7bd24c3e1dc26468a6a9354c0a4f174405c9bad8`, checkpoint SHA-256 `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`. Model inference occurs offline after checksum verification.
- New experiment runtime revision: `mt3-infer-0.2.0-transformers-4.57.6-ast-program-preserving-v1`. Original baseline remains a separate unmodified runtime revision.
- The new run's **metadata-only** artifact is `coco-real-mrmt3-evidence-pending` (artifact ID `13624272848`). It contains per-track exact WAV/MIDI/source SHA-256, prediction MIDI/MusicXML SHA-256, GM note histograms, scores, CPU inference duration and a combined JSON report. No original WAV, MIDI, source ZIP, predicted score, or model weights are uploaded.

## Actual same-model F1 changes

| Ensemble | Onset F1 baseline → program preserving | Onset + offset F1 baseline → new | GM-aware onset + offset F1 baseline → new | MusicXML parts baseline → new |
| --- | ---: | ---: | ---: | ---: |
| String (`string_track001010`) | 34.19% → **75.21%** | 23.08% → **58.97%** | 0.00% → **52.14%** | 1 → 7 |
| Brass (`brass_track049013`) | 37.61% → **60.55%** | 22.02% → **40.37%** | 0.00% → **11.01%** | 1 → 16 |
| Woodwind (`woodwind_track097010`) | 14.91% → **67.54%** | 5.26% → **41.23%** | 0.00% → **22.81%** | 1 → 9 |
| Mixed (`random_track145011`) | 19.65% → **57.54%** | 11.93% → **35.09%** | 0.00% → **4.91%** | 1 → 16 |
| **Four-case macro (unweighted)** | **26.59% → 65.21%** | **15.57% → 43.91%** | **0.00% → 22.72%** | — |

Exact macro F1 from the trusted JSON is 0.26591029 → **0.65212963** (onset), 0.15572064 → **0.4391428** (onset+offset), and 0 → **0.22716306** (strict GM-aware onset+offset). Each case's reference and predicted note counts remained the same across runs: string 109/125, brass 89/129, woodwind 105/123 and mixed 105/180.

Onset matching requires pitch and onset within 50 ms. Full note F1 additionally requires an offset within max(50 ms, 20% of reference note length). Instrument-aware full F1 also matches the *actual* GM program. A higher onset-only score after preserving different program/channel assignments is possible when overlapping same-pitch notes were conflated by the old single-channel MIDI serialization. No model weights, decoded pitches, model tokens or reference labels were changed to obtain the new result.

## Traced root cause and remaining quality problem

Source review of the exact [upstream `mt3-infer` v0.2.0 MRMT3Adapter](https://github.com/openmirlab/mt3-infer/blob/2d20ee5bb6ca727968bd23c6100fd2a35154166b/mt3_infer/adapters/mr_mt3.py) and [vocab_utils](https://github.com/openmirlab/mt3-infer/blob/2d20ee5bb6ca727968bd23c6100fd2a35154166b/mt3_infer/adapters/vocab_utils.py) established that token decoding retains program identifiers in `Note.program` but the upstream MIDI serializer wrote a single pitched channel 0, never emitting `program_change`. The actual baseline's 4/4 tracks therefore had **one MIDI track and GM0 only**, with strict GM F1=0.

The AudioScoreTool-owned `mt3_program_midi.py` bridge consumes those original decoded notes and serializes each program to its own track. It reuses an inactive MIDI channel only when the other program's notes have ended and refuses impossible simultaneous overflow rather than silently truncating notes or guessing reference instruments. It is invoked by both the installed `audio-score-mt3` CLI and the private native frozen entrypoint; only the upstream 0.2.0 adapter can be patched.

The new MIDI files have multiple GM programs and genuine matching instrument identities: the string model predicted GM 40/41/42 (the three distinct original programs), brass 56/57/58/60, woodwind 68/70/71/73 and mixed 41/42/56/71, alongside spurious other programs. For brass and mixed, **16 distinct GM programs and 16 MusicXML parts** now appear despite only four original ensemble voices. The bridge corrects **loss of program labels**; it does **not** solve model over-segmentation, instrument hallucination, voice separation within a shared GM program, or edition-ready notation quality.

These four examples all come from CocoChorales **train**. The measured F1 is not a true held-out test result and does not establish real popular-music quality, independent copyright provenance of all sources, model commercial redistribution rights, clean-machine acceptance, memory usage, or human post-editing time. Both #34 commercial-quality and #154 test-split dataset acceptance remain open.

## Subsequent work

Test against independently SHA-bound CocoChorales *test*-split source shards and multiple real-performance genres; report false instrument families and over-segmentation separately from pitch/onset/offset. Implement musical part editing and timed human corrections before any publication-quality claim. Recheck the Windows/macOS private native PyInstaller QA for the new bridge; model and executable publication require the independent license/SBOM/signoff gate #29.
