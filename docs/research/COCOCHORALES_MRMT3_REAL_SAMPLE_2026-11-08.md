# Observed MR-MT3 on an original CocoChorales author sample

Status: measured on a real, author-published synthesized recording; **not production approved**  
Last reviewed: 2026-11-08  
Tracking: [dataset #154](https://github.com/JDeun/audio-score-tool/issues/154), [Tier 2 #34](https://github.com/JDeun/audio-score-tool/issues/34), [runtime #29](https://github.com/JDeun/audio-score-tool/issues/29)

## Reproducible observed run

- GitHub Actions: [Real CocoChorales MR-MT3 benchmark #42489135513](https://github.com/JDeun/audio-score-tool/actions/runs/42489135513), conclusion **success**, head commit `7903982e31c0277325fcea50297c7f9bac2f8c7a`.
- The run generated actual MIDI/MusicXML with the genuine pretrained MR-MT3, then applied the independent note reference scorer. These results are **not** synthetic fixture results.
- Dataset: [official CocoChorales authors' example page](https://lukewys.github.io/cocochorales/), `string_track001010` (string ensemble; 4 voices; **train** split; 31.02 s of audio, 30.023438 s reference MIDI).
- Original sample ZIP: commit `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a` in `lukewys/lukewys.github.io`; Git blob `81fd702d468094a11b30cc2d41e87a85da4651b7`; SHA-256 `ffe955c473a88c02a52344562b5d7a8551e93dc61ed811e5045030b117b0bac3`. Local media/reference are **not** committed.
- Official original `mix.wav` SHA-256: `cd9dd7d76185cdceed85155b77ca0292061f8752eb3b0e4f3942439f99fc9519`.
- Official reference `mix.mid` SHA-256: `6d5f0b8e8d5e6712794d8e3ad8eeec78772b616693eec1e8d1a41c4bca17a0f7`.
- Provenance and metadata: [JSON-only Actions artifact](https://github.com/JDeun/audio-score-tool/actions/runs/42489135513) (`coco-real-mrmt3-evidence-pending`, retention 30 days); corpus paired fingerprint `4fbe1b7eea852050d47e7825363d78192e7d3080c20048dfe9aa15f59010122e`.
- Model: `mr_mt3`, `mt3-infer==0.2.0`, `transformers==4.57.6`, `torch==2.7.1`; original checkpoint source revision `7bd24c3e1dc26468a6a9354c0a4f174405c9bad8`, checkpoint SHA-256 `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`. CPU inference, network fallback disabled.

## Actual reference-based observations (one piece)

| Metric | Observed |
| --- | ---: |
| Reference MIDI notes | 109 |
| Predicted MIDI notes | 125 |
| Note **onset** F1 (pitch + 50 ms onset tolerance) | 0.34188034188034183 (34.19%) |
| Note **onset + offset** F1 (50 ms onset; offset tolerance max(50 ms, 20% of note duration)) | 0.23076923 (23.08%) |
| Instrument-aware onset + offset F1 (strict matching GM program) | 0.0 (0%) |
| Matched onset + offset notes | 27 |
| Matched instrument-aware onset + offset notes | 0 |
| Onset MAE, onset-matched notes | 23.5201 ms |
| Offset MAE, onset-matched notes | 282.3748 ms |
| Predicted MusicXML parts | 1 |
| Predicted MusicXML non-rest note elements | 178 |
| CPU model inference wall time | 41.577731 s |
| Real-time factor (41.577731 / 31.02), derived | 1.340 |
| Human correction actions and time to final publish | **not measured** |
| Peak resident RAM / GPU RAM | **not measured** |

Original ensemble metadata lists violin, violin, viola, cello (GM programs 40, 40, 41, 42). The model generated only **one** MusicXML part for this four-voice example, and no note satisfied the strict instrument-aware match. This is a concrete diagnostic finding for #34 and the part-mapping pipeline, not proof of the root cause: analyze predicted MIDI GM program distribution, conversion, and the original separate stems before assigning blame.

## Interpretation and evidence boundaries

1. **One genuine recorded sample, not a benchmark distribution:** the author-generated Bach-style recording is in the upstream **train** split, so no held-out generalization, real-world genre coverage or commercial-quality claim is possible.
2. **Metric definitions matter:** onset-only F1 and onset+offset F1 have different matching conditions; the latter is not interchangeable with onset F1. The MusicXML non-rest element count can differ from MIDI note events due to notation conversion.
3. **No music media or model weights were republished:** only provenance, hashes, counts and scores were uploaded in CI. Original dataset attribution: Yusong Wu and coauthors, *The Chamber Ensemble Generator: Limitless High-Quality MIR Data via Generative Modeling* (2022), [CocoChorales CC BY 4.0](https://magenta.tensorflow.org/datasets/cocochorales).
4. **Release gate still blocked:** `release_quality_approved=false`, `model_redistribution_approved=false`. #154 still needs a held-out/test-split official pair, multi-song comparative baseline and #34 human correction/publishing evidence. No acceptance decision follows automatically from this report.

Reproduce from this repository's `CocoChorales Real MR-MT3 Benchmark (research-only)` workflow; compare its metadata-only artifact to the exact run above. Do not replace this historic measured result with a later experimental run without labeling the run and commit separately.

## Follow-up diagnostics — designed, not retroactively measured

The original #42489135513 report did not include per-program and per-MIDI-track provenance. New scoring runs now record the actual reference vs prediction GM program note histograms, channel use, note-bearing MIDI tracks and MusicXML part count. A strict zero instrument F1 *might* be explained by no shared program, by note timing/assignment, or by both; the historical run alone cannot establish which. Similarly, only a new run with both actual MIDI track counts and XML part counts can indicate whether part loss arose before or during MIDI→MusicXML conversion. Do not overwrite the historical results in this section; link each new run separately.
