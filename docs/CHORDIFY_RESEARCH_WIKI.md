# Chordify: Competitive Research & Benchmark Protocol (2026-10-23)

## Executive findings
Chordify is a **chord-and-beat-aligned play-along product**, not a full multi-instrument AMT engine. Its official technical explanation describes spectrogram inputs, separate deep neural networks for automatic chord recognition and beat/downbeat tracking, and time-aligned chord display. Its paid MIDI exports contain **chord notes, not full instrumentation**. AudioScoreTool should benchmark **harmonic transcription independently from note transcription**, while distinguishing chord-only MIDI from full-song MIDI.

## Verified sources
- Technology and architecture: https://chordify.net/pages/technology-algorithm-explained/
- Beat/downbeat tracking: https://chordify.net/pages/algorithm-summer-bootcamp/
- Current feature overview: https://chordify.net/pages/chordify-app/
- MIDI export behavior: https://support.chordify.net/hc/en-us/articles/360002164538-How-to-use-Premium-features
- Melody transcription limitation: https://support.chordify.net/hc/en-us/articles/360002272998-Which-instruments-can-I-use-with-Chordify
- CASD multi-annotator chord references: https://github.com/chordify/CASD
- MIREX 2025 chord-estimation evaluation: https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation
- MIREX 2025 results/baselines: https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation_Results

## Product decomposition
| Capability | Chordify | AudioScoreTool target | Verification |
| --- | --- | --- | --- |
| YouTube play-along | Yes | URL -> audio -> transcription -> synchronized editor | E2E |
| Chord recognition | Yes | SheetSage2 plus alternative ACR baseline | WCSR, root, maj/min, sevenths |
| Beat/downbeat | Yes | Time-aligned bar/beat grid | beat F-measure, downbeat F |
| Key/BPM | Exposed | Exposed | key accuracy, tempo error |
| Chord diagrams | Guitar, piano, ukulele, etc. | Future UI | UX |
| Loop/speed/transpose | Paid practice features | Future UI | UX |
| Chord-only MIDI | Paid | Distinguish from full instrumentation | MIDI content |
| Full multi-instrument MIDI | Not offered | YourMT3/MR-MT3/MuScriptor | note F1 |
| Sheet music | Chord chart, not full lead/melody lines | MusicXML multi-part score | notation quality |

## Scientific validity
1. Chordify outputs are **competitor predictions, not ground truth**. Compare model-to-model agreement separately from annotated accuracy.
2. Use CASD/JAMS multiple references to measure annotator ambiguity; consider MIREX/Isophonics reference sets, license and split provenance.
3. Use `mir_eval.chord` weighted chord symbol recall (root, maj/min, thirds, sevenths), segmentation and no-chord handling. Normalize chord labels into a common Harte representation; report unsupported-label rate.
4. For beat/downbeat use `mir_eval.beat` and independent annotated beats; tempo tolerance and half/double-tempo ambiguity need explicit reporting.
5. For AMT use note onset and onset+offset F1, instrument-aware F1, duration and runtime; use manually verified MIDI/reference, not chord-only exports.
6. Report confidence intervals across **songs**, not frames; separate genre, production density and vocals; avoid inferring performance from one Tinashe track.
7. Chordify research reports substantial human disagreement (CASD): a single reference may not represent unique musical truth.

## Experimental protocol
- Input: authorized audio from the **same exact recording and time window** for every model. Track SHA256, duration, sample rate, source ID, download policy, model/weights/runtime revisions, CPU specs and execution time.
- Candidate AMT: YourMT3, MR-MT3, MuScriptor small/medium/large as feasible.
- Harmony: SheetSage2, Chordify manual export (when legitimately available), and Chordino/NNLS baseline.
- Hybrids: YourMT3+SheetSage2, MR-MT3+SheetSage2, MuScriptor+SheetSage2.
- Ensemble: YourMT3+MR-MT3 consensus (precision-first), plus union and confidence-aware variants only after ground-truth measurement.
- Pipeline gates: successful download/ingest, MIDI and MusicXML validity, no duplicated notes, valid chord timeline, successful rendering and synchronized playback.
- **Never label a smoke test as a benchmark score**. A model can produce files and still transcribe incorrectly.
- Copyright: do not commit or publish commercial source audio; avoid public artifacts containing source audio; use appropriately licensed/authorized test recordings.

## Gaps and prioritized implementation
P0: fix Actions package import, actual model CLI compatibility, and GitHub hosted runner execution; retain full logs.
P0: make source ingestion work on real video URLs without relying on synthetic audio; persist only derived metrics by default.
P0: fix hybrid dependency/CLI contract; test end-to-end output and musical timing.
P1: add Chordify-vs-SheetSage2 normalized chord event importer and `mir_eval` scoring.
P1: create human-annotated multi-song test set; use CASD and other licensed datasets.
P1: MuScriptor authenticated inference on CPU small, MPS/CUDA medium/large, gated by accepted HF license.
P1: compare AMT ensemble consensus against single-model recall/precision.
P2: chord-aligned player, diagrams, loop, tempo, transpose, editable chord grid.
P2: cost/latency/accuracy Pareto analysis on GitHub Actions CPU and optional GPU.

## Limitations
No public official Chordify inference API or model weights were verified in this investigation. Do not automate scraping, assume Chordify results are reference annotations, or claim its algorithm can be reproduced from the high-level description. The exact commercial production model architecture and accuracy are undisclosed.

## CASD feasibility and alternative corpora (verified 2026-10-23)
- CASD **is usable for noncommercial research** under **CC BY-NC-SA 4.0**, with attribution and share-alike requirements on adaptations. Repository: https://github.com/chordify/CASD ; license: https://github.com/chordify/CASD/blob/master/LICENSE.md .
- CASD contains 50 Billboard songs, four expert chord annotations per song, JAMS/Harte format. **It does not distribute the copyrighted source audio**. Acquire matched audio separately and verify recording/version/time alignment and rights.
- CASD can measure chord recognition but **cannot evaluate full instrument note-level AMT**. Use independent MIDI-aligned audio corpora for AMT.
- `scripts/import_casd_annotations.py` converts JAMS to per-annotator intervals, preserving all references; requires no network at runtime.
- Isophonics (https://isophonics.net/datasets): annotated chord/key/beat datasets; original commercial audio not automatically licensed.
- ChoCo (https://github.com/smashub/choco): large harmonically annotated symbolic/audio-aligned metadata collection, not a turnkey audio dataset.
- ASAP (https://github.com/fosfrancesco/asap-dataset): classical piano MIDI/audio-alignment and beats, better for AMT than pop harmony.
- Hugging Face hosts community datasets but presence on HF **does not imply permission to redistribute commercial recordings**. Inspect each dataset card, actual audio availability, license and alignment; prefer authoritative source when available.
- 2026 MIREX ACE guidelines (https://music-ir.org/mirex/wiki/2026%3AAudio_Chord_Estimation) prohibit Billboard 2013 test material for training, validation or model selection in the competition; maintain split provenance if seeking MIREX-comparable results.
