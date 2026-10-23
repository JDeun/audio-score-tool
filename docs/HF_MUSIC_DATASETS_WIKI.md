# Music Dataset Survey: Hugging Face and Authoritative Sources (2026-10-23)

## Decision
Use **two separate benchmarks**: (A) chord/beat estimation and (B) audio-to-MIDI multi-instrument transcription. Hugging Face is a distribution channel, not proof of licensing or ground-truth quality. Do not train and test on overlapping recordings, including repackaged datasets.

## Chord / beat / harmony
| Dataset | Source | Audio included? | Annotation | Conditions / recommendation |
|---|---|---|---|---|
| CASD | https://github.com/chordify/CASD | No | 50 Billboard songs × 4 experts, JAMS chords | CC BY-NC-SA 4.0; excellent for inter-annotator chord evaluation; acquire matching audio separately |
| Isophonics | https://isophonics.net/datasets | Not generally redistributable | chords, beat, key, segmentation | Verify source-specific licensing and recording alignment |
| Billboard | https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation | No generally open commercial audio | chord reference | respect MIREX splits; potential CASD overlap |
| ChoCo | https://github.com/smashub/choco | No | >20K pieces' harmonic annotations/metadata | heterogeneous licensing; not an audio benchmark without pairing |
| GuitarSet | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | Yes (repackaged) | guitar JAMS, pitch and some harmony-related annotations | upstream CC BY 4.0 as reported by aggregator; confirm upstream files |

## Audio/MIDI aligned transcription
| Dataset | Hub / authoritative source | Audio and MIDI | License and evaluation suitability |
|---|---|---|---|
| Slakh2100 Redux | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 ; https://zenodo.org/records/4599666 | rendered mixtures, stems, MIDI | upstream CC BY 4.0 reported; strongest initial multi-instrument benchmark; synthetic instruments domain shift |
| MAESTRO v3 | https://magenta.tensorflow.org/datasets/maestro | aligned piano audio and MIDI | CC BY-NC-SA 4.0; piano only |
| GuitarSet | https://github.com/marl/GuitarSet | guitar audio + JAMS | CC BY 4.0 per aggregator; guitar-specific |
| URMP | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | chamber ensemble stems, MIDI/score | verify upstream conditions; limited production-music transfer |
| MusicNet-EM | https://zenodo.org/records/7793404 | classical audio + aligned MIDI | inspect source LICENSE.txt before use |
| MDB Drums++ | https://huggingface.co/datasets/xavriley/MDBDrumsPlusPlus | drum audio + hits | per-source terms; percussion-only |
| ENST-Drums | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | drum audio + hits | research/source terms; percussion-only |
| IDMT-SMT-Bass | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | bass audio + MIDI | research/source terms; bass-only |
| RWC Popular Music | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | recordings and external annotations | CC BY-NC 4.0 reported; verify provenance and source terms |
| ASAP | https://github.com/fosfrancesco/asap-dataset | classical piano aligned MIDI, audio references | source-specific licensing; piano only |
| GAPS | https://huggingface.co/datasets/xavriley/GAPS | guitar audio/MIDI/score | source-specific terms |

## Hub collection: MIMuT Data v2
https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2
Aggregator claims **13 source datasets, 82,046 files, ~151 GB**, not 82K songs. Hub metadata license is **other**; underlying source datasets have **different licenses**. Never treat entire collection as uniformly CC-licensed. Avoid bulk downloading to GitHub-hosted CI.

## Recommended staged implementation
1. Metadata-only registry with task, source, license, rights, splits, download mode, estimated size, and source-specific reference formats.
2. Minimal local smoke set: CASD JAMS annotations only (no audio), small Slakh sample, small GuitarSet sample; store source IDs/hashes, not source media.
3. Chord evaluation: `mir_eval.chord` WCSR and multi-annotator CASD scoring; use same exact reference recording.
4. AMT evaluation: onset/offset note F1, instrument-aware metrics, per-class/drum metrics, real vs synthetic domain shift.
5. Cross-dataset validation: held-out source split, training overlap audit, hardware latency and memory.
6. Explicitly keep NC sources outside commercial-training or redistribution pipelines.

## Caveats
No exhaustive Hugging Face search or automatic license audit is claimed. Dataset card claims are provisional until verified against original publishers. Repackaged files may have different provenance and terms. Some listed corpora have no usable audio; do not imply that downloading their annotations yields a ready-to-run audio benchmark.

## Sources
- https://github.com/chordify/CASD
- https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2
- https://github.com/ismir/mir-datasets/blob/master/mir-datasets.yaml
- https://github.com/smashub/choco
- https://magenta.tensorflow.org/datasets/maestro
