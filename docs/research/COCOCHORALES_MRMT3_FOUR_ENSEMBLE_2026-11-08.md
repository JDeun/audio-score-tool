# MR-MT3: four-ensemble CocoChorales author-example measurement

Status: actual pretrained-model CPU reference evaluation complete; **NOT held-out, commercial-quality or redistribution approved**
Last reviewed: 2026-11-08
Tracking: [#154](https://github.com/JDeun/audio-score-tool/issues/154), [#34](https://github.com/JDeun/audio-score-tool/issues/34), [PR #168](https://github.com/JDeun/audio-score-tool/pull/168)

## Immutable experiment and dataset identity

- Successful [GitHub Actions run #42490888388](https://github.com/JDeun/audio-score-tool/actions/runs/42490888388), private model inference and reference scoring, branch head commit `c070cc5d6845ebcec024eca057b134d68ce035c5`.
- Metadata-only artifact `coco-real-mrmt3-evidence-pending`, artifact ID `13622190221`, includes `four-ensemble-score.pending.json`, four pairs of original-source/score receipts and the model-source pending receipt. No original audio, reference MIDI, prediction MIDI, MusicXML, model weights or source ZIP are uploaded.
- Official [CocoChorales author examples](https://lukewys.github.io/cocochorales/) are pinned to `lukewys/lukewys.github.io` source commit `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a` and each original ZIP's exact Git blob OID plus newly calculated SHA-256. `main_dataset/mix.wav`, `mix.mid`, `metadata.yaml` were verified in private CI, along with CC BY 4.0 sample-use metadata.
- All four tracks are from the official **train** split; model train-set overlap and generalization are **not independently excluded**. These are Bach-style *generated* samples, not actual licensed commercial recordings.
- Genuine pretrained model `mr_mt3`: `mt3-infer==0.2.0`, `transformers==4.57.6`, `torch==2.7.1`, original HF commit `7bd24c3e1dc26468a6a9354c0a4f174405c9bad8`, checkpoint SHA-256 `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`; Ubuntu CI CPU, HF fallback disabled during inference. Model publication remains pending.

## Actual measurements

| Ensemble (source ID) | Audio duration | Reference MIDI notes | Predicted MIDI notes | Note onset F1 | Note onset+offset F1 | GM-aware onset+offset F1 | CPU inference | Predicted MusicXML parts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| String (`string_track001010`) | 31.020 s | 109 | 125 | 34.19% | 23.08% | 0.00% | 38.005 s | 1 |
| Brass (`brass_track049013`) | 25.028 s | 89 | 129 | 37.61% | 22.02% | 0.00% | 34.258 s | 1 |
| Woodwind (`woodwind_track097010`) | 18.012 s | 105 | 123 | 14.91% | 5.26% | 0.00% | 28.483 s | 1 |
| Mixed (`random_track145011`) | 25.920 s | 105 | 180 | 19.65% | 11.93% | 0.00% | 56.823 s | 1 |
| **Unweighted macro, four scored cases** | — | — | — | **26.59%** | **15.57%** | **0.00%** | — | — |

Onset F1: pitch equality and onset within 50 ms. Onset+offset F1: additionally offset within max(50 ms, 20% of reference duration). Instrument-aware also requires equal GM instrument program. There is no automated human editing/publishing-time, peak RAM/VRAM, true test split, or commercial quality approval. The macro score is a four-case arithmetic average, not a pooled/micro F1 or statistical confidence interval.

## Root-cause localization: instrument program and score part evidence

The scorer now records *actual MIDI content* before conversion, not just MusicXML. For **all four source tracks**:

- The original reference has 3 or 4 distinct note-bearing GM programs, corresponding to the respective SATB instrumentation.
- The actual **predicted MIDI has exactly one note-bearing track, with every note assigned default GM program 0 (Acoustic Grand Piano)**.
- The final MusicXML also has one part. Thus the one-part score is *not* shown to be a conversion-induced reduction: the source MIDI from the transcription engine was already single-track and missing independent instrument identities.
- The strict GM-aware note matching was 0/4 because the predicted program-0 notes share **no GM program** with any of the four ensemble references. This observation does **not** establish whether the upstream pretrained model predicted no instruments, whether its wrapper discarded them, or whether a final MIDI serialiser flattened them. Instrument-aware F1 is a valid description of delivered MIDI, not an isolated test of the model's internal instrument classifier.

| Source ensemble | Reference GM program distribution (program: note count) | Predicted MIDI GM | Predicted note-bearing MIDI tracks |
| --- | --- | --- | ---: |
| String | 40:47, 41:29, 42:33 | 0:125 | 1 |
| Brass | 56:21, 57:21, 58:31, 60:16 | 0:129 | 1 |
| Woodwind | 68:19, 70:40, 71:26, 73:20 | 0:123 | 1 |
| Mixed | 41:25, 42:32, 56:27, 71:21 | 0:180 | 1 |

Next engineer review: inspect `mt3-infer==0.2.0` MR-MT3 adapter model output, MIDI token-to-GM/channel/track mapping and downstream file encoder *before* applying any program heuristics. Never infer instruments from a known test dataset's reference labels in production scoring; doing so would contaminate the evaluation and fabricate segmentation success.

## Pinned original ZIP digests

| Source ZIP | SHA-256 |
| --- | --- |
| `string_track001010.zip` | `ffe955c473a88c02a52344562b5d7a8551e93dc61ed811e5045030b117b0bac3` |
| `brass_track049013.zip` | `1aac4c6ad8b00e1ab0aa8f593627578e9fa48c99e551a00685986ed271f058b6` |
| `woodwind_track097010.zip` | `b528b11b4b6d54be559abd93a2a186eabbcb8afe4ee7b6b99a63e47ddbef03ec` |
| `random_track145011.zip` | `2a1e11f0145b66362b4aef6b5a6545296d3e658d891e70858720306a6ef427ac` |

Original authors and copyright: Yusong Wu, Josh Gardner, Ethan Manilow, Ian Simon, Curtis Hawthorne and Jesse Engel, *The Chamber Ensemble Generator: Limitless High-Quality MIR Data via Generative Modeling*, 2022. [CocoChorales data license CC BY 4.0](https://magenta.tensorflow.org/datasets/cocochorales). We retain source attribution, record all changes as experimental predictions/metrics only, and do not republish the media.

## Remaining acceptance

Real held-out `test`-split paired data with independently checked official shard signatures/checksums, wider realistic/popular-music and genre-specific references, legitimate model redistribution rights, human editing time-to-publish, correction counts and cross-platform packaged runtime acceptance remain open. #154 and #34 are **not** closed or quality-approved by this four-sample research run.

## Program-preserving bridge experiment — pending independent new run

The pinned [upstream mt3-infer v0.2.0 `MRMT3Adapter.decode`](https://github.com/openmirlab/mt3-infer/blob/2d20ee5bb6ca727968bd23c6100fd2a35154166b/mt3_infer/adapters/mr_mt3.py) writes all decoded pitched note events on channel 0 without emitting `program_change`. Its earlier `vocab_utils` state machine does retain `Note.program`. The repository's optional `audio-score-mt3` CLI and native PyInstaller entrypoint now preserve those **model-decoded** programs as separate MIDI tracks/channels without reference-label injection. Any new measurement must use a distinct runtime revision `mt3-infer-0.2.0-transformers-4.57.6-ast-program-preserving-v1`. The preceding four-ensemble results above are the **unmodified upstream baseline** and must remain unchanged. This is an experiment and **not** evidence that the model internally decoded meaningful programs until actual post-bridge MIDI/score evidence arrives.
