# CPU specialist diagnostics: verified results, 2026-11-10

Status: completed research diagnostics; NOT a production-model selection, held-out generalization claim, or final-score acceptance.

Related: #218 (piano/BiLSTM), #219 (beats), #220 (strings/TAB), #221 (separator eligibility), #217 (external pipelines), #34/#200 (actual publishing quality).

## Execution and verification

- Research PR: https://github.com/JDeun/audio-score-tool/pull/222
- Real model workflow: https://github.com/JDeun/audio-score-tool/actions/runs/42782697921
- Tested PR head: `471d58cb63d6603050d2ddb362225292a3190880`.
- Actual pull-request merge checkout recorded in ALL three receipts: `0fa45a779bfe132fa2f9fe759aad0dcc3b80a7ac`.
- CPU only, Ubuntu 24.04, Python 3.11, PyTorch 2.7.1 CPU, seed 0, two computation threads. No GPU, model credentials, or model training. Exact packages and model/data hashes remain in the JSON receipts.
- All three model jobs completed successfully: piano 3/3 fixtures, Beat This 6/6 recordings, StringNet 6/6 recordings. General CI run 42782697830 and Research Evidence Contracts run 42782697865 also succeeded for that tested head. This is not a claim about a subsequent documentation commit's CI.
- Independently downloaded all three report ZIPs, matched their GitHub artifact SHA-256 digests, verified every planned case and completion flag, recomputed every reported macro from the individual rows, and confirmed identical GuitarSet audio/JAMS hashes between beat and string experiments. String correct-count denominators were also checked. This verifies report consistency, not an independent rerun of inference or a re-score from raw notes.

| Report | GitHub artifact ID | Downloaded ZIP SHA-256 |
| --- | --- | --- |
| piano | 13748110880 | `2ad52911ab0c674302bc3a00c235f0ad3e213e31c2e69f10dbf33634c03ace13` |
| beat_this | 13748096060 | `a22054138c4ad683cd302872cdc3d066b3f313c5ffb0e3a0fce5e2e80a91369d` |
| stringnet | 13746189480 | `d3f37bc72674c98548e33ef1f0b0907fb5f2436224f8d04fec7159eb4b87ac69` |

Artifacts have a 14-day retention period. The aggregate and per-case measurements below persist independently of those downloads; exact original runtime receipts must be retained separately before expiry for full provenance replay. Original recordings, annotations, note sequences, MIDI, SoundFont and weights were NOT uploaded as artifacts.

## 1. Piano CRNN and Basic Pitch: SYNTHETIC audio diagnostic

Three original note patterns (melody, chords, octave-repeats), containing 16/40/24 reference notes, were rendered with the same TimGM6mb/FluidSynth settings. Both actual pretrained transcribers received the same WAV per case. Reference MIDI was used for scoring only, never as a model input. Onset tolerance 50 ms; pitch tolerance 50 cents; offset tolerance max(50 ms, 20% of reference duration). Macro is the unweighted mean of three case F1 scores.

| Model / processing | Pitch+onset F1 | Pitch+onset+offset F1 |
| --- | ---: | ---: |
| ByteDance/Kong piano CRNN, raw | 96.666667% | 91.527778% |
| Same CRNN prediction -> pretrained Rescored BiLSTM | 96.666667% | 91.527778% |
| Basic Pitch 0.4.0 ONNX, raw | 83.830902% | 4.938272% |
| Same Basic Pitch prediction -> pretrained Rescored BiLSTM | 83.830902% | 4.938272% |

| Case | Reference count | CRNN prediction count | CRNN onset / offset F1 | Basic Pitch prediction count | Basic Pitch onset / offset F1 |
| --- | ---: | ---: | --- | ---: | --- |
| melody | 16 | 16 | 100% / 93.75% | 24 | 80% / 0% |
| chords | 40 | 40 | 90% / 85% | 41 | 98.765432% / 14.814815% |
| octave-repeats | 24 | 24 | 100% / 95.833333% | 42 | 72.727273% / 0% |

BiLSTM actually loaded the pretrained state_dict and produced new MIDI files. All six model/case comparisons retained the same measured onset and offset F1 after refinement. The resulting MIDI hashes changed, so this is NOT proof that the refiner was a no-op or preserved every event unchanged. It is evidence of no measured F1 gain on this small synthetic set, not a general rejection of sequence refinement or of LLM correction.

The reference offset is the generated MIDI key release, not the end of the sound's decay. These fixtures contain no sustain pedal. Differences in release-tail treatment can affect offset scoring; the exact cause of Basic Pitch's low offset score has not been independently diagnosed. Do not compare these numbers with vocadito vocals, claim general real-piano accuracy, or promote a final MusicXML/PDF engine. Real paired piano recordings, held-out split checks and human editing costs remain #218/#60/#34 work.

Model identity:
- CRNN source `qiuqiangkong/piano_transcription_inference@0226e74cbc805660e34bbd6a8fed2083890ebb88`; checkpoint from Zenodo record 4034264, 171966578 bytes, MD5 `22b961b77c1878239fec963362097045`, SHA-256 `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141`.
- Basic Pitch ONNX SHA-256 `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`.
- Rescored source `4c7dd9dfebc96560073cfd06b114d6ca35938ba2`; BiLSTM checkpoint SHA-256 `ad2b6354795569bd77936a9927777e7fdf718d3d9a1a840ce049e55ea8a4585b`.

## 2. Beat This!: real audio, SEEN-TRAINING-DATA diagnostic

GuitarSet v1.1.0 microphone recordings were selected before inference by name-sort: players 03/04/05, first comp and first solo recording for each. All six are variations of the same BN1-129-Eb pattern, not six different genres/compositions. `final0`, CPU, dbn=False; beat and downbeat F1 use 70 ms tolerance and trim both reference and prediction events before 5 seconds.

**GuitarSet was included in final0 training.** This is not a fair held-out performance estimate. Independent evaluation requires GTZAN or correctly paired validation/fold checkpoints and data, as the upstream README specifies.

| Recording | Beat F1 | Downbeat F1 |
| --- | ---: | ---: |
| 03_BN1-129-Eb_comp | 98.666667% | 94.736842% |
| 03_BN1-129-Eb_solo | 33.898305% | 27.272727% |
| 04_BN1-129-Eb_comp | 100% | 94.736842% |
| 04_BN1-129-Eb_solo | 40.816327% | 35.294118% |
| 05_BN1-129-Eb_comp | 98.666667% | 94.736842% |
| 05_BN1-129-Eb_solo | 45.614035% | 25% |
| **Six-recording macro** | **69.610333%** | **61.962895%** |

The three accompaniment examples average 99.111111% beat F1, but the three solo examples average only 40.109556%. Do not hide this spread in the overall mean. Beat F1 is not note transcription accuracy, meter correctness, or final notation quality.

Source `CPJKU/beat_this@b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`; actual final0 checkpoint SHA-256 `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`.

## 3. StringNet: reference-conditioned string classification

Same six original GuitarSet microphone recordings. **Reference note onsets and rounded reference MIDI pitches are supplied to StringNet**. Reference string identities are used only by the evaluator. This deliberately isolates the string-selection problem; it does not test audio-to-note detection or end-to-end TAB transcription. Viterbi fingering optimization was not evaluated.

| Recording | Notes | StringNet correct | Lowest-fret baseline correct |
| --- | ---: | ---: | ---: |
| 03_BN1-129-Eb_comp | 157 | 74 | 20 |
| 03_BN1-129-Eb_solo | 58 | 42 | 23 |
| 04_BN1-129-Eb_comp | 127 | 98 | 22 |
| 04_BN1-129-Eb_solo | 42 | 36 | 0 |
| 05_BN1-129-Eb_comp | 148 | 121 | 27 |
| 05_BN1-129-Eb_solo | 44 | 32 | 5 |
| **Total counts** | **576** | **403** | **97** |

Unweighted mean of per-recording accuracy: StringNet **72.818537%**, lowest-fret **16.553957%**. Count-weighted accuracy is a different statistic; do not substitute one for the other. The upstream authors claim training on players00-02, excluding these03-05, but that training history was not independently audited. Same-pattern coverage is narrow. Exact-string agreement also differs from whether an alternative fingering is playable.

Source `kishormorol/song2sheet@6aee2a2139b28af871f4c9a878b7e18650c38226`; StringNet weights SHA-256 `6c516876596922aad0d9c978769d7f4f3673c7ab1337525f5ab49a9c425c9a41`.

## Decisions and next boundaries

Retain the piano CRNN for a real-piano comparison; do not select it from synthetic scores alone. Retain Beat This for a held-out, role-specific beat comparison and eventual fixed-AMT grid ablation. Retain StringNet for full AMT-to-TAB tests, preserving the conditional-versus-end-to-end distinction. BiLSTM showed no F1 benefit here and needs broader tests before adoption.

RoFormer checkpoints with unresolved provenance/rights and open-fret without verified trained weights were not executed. They remain blocked, not 0-point failures or successes. Production source, default models, PR #213/#216, and managed-release approvals were not changed. PR #222 remains a research PR rather than an automatic main merge.

No LLM was run in this experiment. A future music-context correction layer must be evaluated against unchanged baseline, deterministic correction, and evidence-grounded model variants; syntax/notation readability, original-song note accuracy, repair damage and human editing time are separate outcomes.
