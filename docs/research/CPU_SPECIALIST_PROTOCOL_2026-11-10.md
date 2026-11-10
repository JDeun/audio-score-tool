# CPU specialist model diagnostics — protocol, not measured results

Related #218 (piano/refinement), #219 (beats), #220 (guitar strings), #221 (separation), umbrella #217.

## Scope

Only public, credential-free models on standard Ubuntu CPU runners. No GPU runner, cloud model API, gated Hugging Face token, model training, production engine/default change, or automatic merge. Existing #213 and #216 are untouched.

| Job | Actual pretrained models | Inputs and references | What a score means |
|---|---|---|---|
| piano | Kong/ByteDance Note_pedal CRNN; Basic Pitch ONNX; Rescored BiLSTM on each model's predicted MIDI | Three ORIGINAL generated melody/chord/octave-repeat MIDI phrases rendered by FluidSynth and TimGM6mb | Synthetic note-onset/offset diagnostic, not real pianist accuracy; refiner never receives truth |
| beat_this | Official Beat This! final0 CPU, dbn=False | GuitarSet v1.1.0, predeclared players03/04/05 × comp/solo, lexicographically first filename per group | **Seen-training-dataset diagnostic**: GuitarSet was among final0's training datasets; not held-out validation |
| stringnet | Song2Sheet's trained CNN, CPU | Same six GuitarSet microphone recordings, supplied reference onset and discrete pitch | CONDITIONAL string classification, NOT audio-to-note or end-to-end TAB accuracy |

Six examples do not represent an entire corpus or multi-genre product quality. Musical content is not silently shifted to match a reference. Piano note scoring uses mir_eval 0.8.2, onset50ms/pitch50cents/offset max(50ms,20%). Beat/downbeat scoring uses70ms and explicitly excludes the first5 seconds from both reference and prediction, matching the mir_eval convention. StringNet reference pitch is rounded to its required discrete MIDI input, not used to alter any AMT reference.

A job must complete all its planned cases to publish a macro. Empty valid MIDI remains zero. Exceptions/nonfinite output/missing pretrained state fail the job; incomplete reports retain cases but no complete macro. Model inference success, model accuracy, notation fidelity, and release approval are distinct.

## Source identities

- Piano inference: `qiuqiangkong/piano_transcription_inference@0226e74cbc805660e34bbd6a8fed2083890ebb88`; pretrained file from versioned Zenodo record4034264. Verify record's declared MD5/size before loading; record actual SHA256 and source-record SHA. This is an author-source checksum, not a signed provenance attestation.
- Basic Pitch0.4.0 ONNX: Git blob `c30e5f9438e798604b7177aa26be1fe64482f767`,230444 bytes; same asset as prior CPU experiment. No TensorFlow/GPU required.
- Beat This source: `CPJKU/beat_this@b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c`. Download original final0.ckpt from the official cloud host, require SHA256 `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`. Expected digest is also documented by an independent converter's source-lineage record (https://huggingface.co/musetric/beat-this-onnx#source--lineage); the converted ONNX model is NOT used here. Reject differing original bytes instead of accepting a mutable latest model.
- Song2Sheet: `6aee2a2139b28af871f4c9a878b7e18650c38226`, MIT. Source modules and stringnet.pt are checked by pinned Git blob and byte count before import/load. Training players00–02 vs03–05 is upstream's claim, not independently audited.
- Rescored: `4c7dd9dfebc96560073cfd06b114d6ca35938ba2`, MIT repository. Verify refiner source and bilstm_best.pt by pinned blob/size; preserve source unchanged in the runner's private workspace, run CPU with weights_only loading. Its model/data training provenance and downstream redistribution are not approved by this diagnostic.
- GuitarSet: https://zenodo.org/records/3371780, CC BY4.0, Xi et al., ISMIR2018. Fixed annotation.zip MD5 `b39b78e63d3446f2e54ddb7a54df9b10`; audio_mono-mic.zip MD5 `275966d6610ac34999b58426beb119c3`. Original member bytes are SHA256 recorded. String IDs follow annotation_metadata.data_source,0=low E. Validate all six strings and model tuning before inference.

## Blocked / not executed

- RoFormer: exact checkpoint author's rights/provenance not cleared. BS-Roformer-SW is explicitly unknown in SwingScribe's notices. This is not a claim that all RoFormer checkpoints are unusable or cannot run on CPU; research gate #221 remains open.
- open-fret: no independently verified public pretrained weights, so do not execute random initialization or call a deterministic fallback an ML result. #220 tracks this.
- ESSENTIA, Transkun, HOMR are not added to this matrix: respectively a separate rhythm implementation, a mentioned but unused piano alternative, and OMR rather than audio transcription. They are not silently counted as tested.

## Safety and interpretation

Only HTTPS allowlisted downloads, size bounds, and verified source/model files. torch serialization uses weights_only. No original audio/annotation payloads, predictions, piano rolls, scores or checkpoints are committed or uploaded. Artifacts are explicitly named metadata JSON files. Selected third-party source remains temporary and unmodified; no code vendoring or model redistribution occurs. Runtime dependency versions, script/code revision and hashes are recorded.

Future acceptance requires independent actual audio appropriate to each task: real piano recordings and note references, unseen beat/downbeat data or correctly matched fold checkpoints, predicted-note end-to-end guitar TAB evaluation, and actual human editing cost. Do not compare these scores with vocadito AMT F1 or proclaim a new best general model.
