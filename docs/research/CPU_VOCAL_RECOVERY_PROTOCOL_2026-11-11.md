# CPU vocal recovery ablation — preregistered development protocol

Related #200 #214 #215 #172 #34. Based on main `7e3458e745bf612b0cf0cb0528715b0bcc42f392`. This changes only research scripts, tests and an opt-in workflow. No product defaults, checkpoint, score, automatic correction, other session branch or release policy changes. No LLM or training.

## Why this experiment

Previous work established that transcription, pitch verification, timing and notation are different problems. The fixed grid loses some predicted attacks, but restoring more predictions is not automatically correct. Before another grid change, diagnose the raw predictions and test inexpensive non-training hypotheses. Earlier public artifacts contain only metadata, not reusable raw MIDI/F0/network outputs. Therefore regenerate the same original public vocadito40 inputs in a new private runner workspace; do not claim to access another session's private song cache.

This is a repeatedly examined development corpus, **not an untouched test set**. It cannot establish held-out generalization or original five-song score quality. No per-recording best setting or reference-guided shift is permitted. All arms below are fixed before results are inspected; none is automatically promoted.

## Paired experiments

### A. YourMT3+ noPS → bounded reference-free recovery

Reuse the existing pinned `prepare('yourmt3')` raw bridge and exact checkpoint. One AMT inference per recording feeds all four arms:

1. `raw`: unchanged events.
2. `octave_only`: fixed Tiny F0; only non-overlapping pitched notes with stable interior evidence. Margin max(30ms, min(100ms,15% duration)), at least six observations and six voiced frames, voiced fraction >=85%, 90–10 percentile spread <=0.4 semitones, median within0.2 of an integer, change exactly +12/-12. Otherwise abstain. No score-key assumptions or track-wide transposition.
3. `onset_only`: librosa0.10.2.post1 spectral-flux onset detection,22050Hz/hop220, default peak picker, no backtracking. Exactly one candidate within60ms, not shared by two notes; no order crossing, new overlap, or resulting duration below40ms. Offset/pitch/count/instrument remain unchanged.
4. `octave_and_onset`: the same two independently defined rules together.

All edits preserve event order, offsets, multiplicity and instrument identities; octave edits preserve source timing. Actual octave jumps, polyphony, weak evidence and collisions have abstention tests. F0 and audio attacks are predictions, NOT ground truth. These are conservative hypotheses, not approved correction rules.

### B. Basic Pitch: decode the SAME network activations five ways

One Basic Pitch0.4.0 ONNX CPU inference per recording, same pinned asset as the previous baseline. Private raw NPZ is immutable; decoder arms receive fresh copies to avoid in-place contamination:

| Arm | Onset threshold | Frame threshold | Minimum note ms | Melodia |
|---|---:|---:|---:|---|
| raw |0.5|0.3|127.7|yes|
| minimum_64ms |0.5|0.3|64.0|yes|
| onset_065 |0.65|0.3|127.7|yes|
| frame_050 |0.5|0.5|127.7|yes|
| no_melodia |0.5|0.3|127.7|no|

Each arm changes one factor. The replayed default decoder must reproduce the initial raw event fingerprint exactly; mismatch fails the case. The official MIDI decoder and the same MIDI parser are used for all arms. Pitch bends are not scored, as before; this does not test instrument identification.

## Scoring and reporting

Original vocadito v3 ZIP and member hashes; original A1/A2 Hz annotations; shared `scripts.vocadito_reference.score_annotations`, mir_eval0.8.2. Primary onset50ms/pitch50cents and offset max(50ms,20% reference duration). References are opened only after candidate predictions have been generated. Do not shift predictions or round original reference frequencies.

- Primary F1, precision/recall, note counts and per-recording scores for BOTH annotators.
- Additional onset100ms, circular pitch-class and onset-only scores are **sensitivity diagnostics**, not alternative primary accuracy and not a disjoint error taxonomy.
- For fixed-event recovery, report gained/lost strictly matched prediction indices per annotator. Maximum bipartite matching can change associations for ambiguous duplicates; these counts are not confirmed musical correction/harm rates.
- Equal recording/annotator macro, paired differences, improved/worse recording counts, and a seeded2000-resample recording-level bootstrap interval. Average A1/A2 within recording before resampling. This exploratory interval is not evidence of generalization, independence from prior tuning, or multiplicity-corrected significance.
- Missing, duplicated, failed cases or missing arms prohibit an overall complete macro. Valid empty predictions score zero. Never publish a successful subset as the40-recording result.
- Cases, decoder settings, model/input/scorer/script hashes and complete runtime versions are recorded. Timing includes different model lifecycles and is not a controlled model speed ranking.

## Execution and privacy

Two standard Ubuntu CPU jobs, max2parallel,75-minute cap each, seed0 and2threads. Reuse the existing credential-free, source/weight-verified model loaders and original corpus checksums. Token variables are empty, GPU visibility disabled, no paid service, training, gated model or external LLM. PR-open/reopen or manual dispatch only; later documentation pushes do not repeat inference automatically.

Source recordings, annotations, raw MIDI/F0/network arrays, proposed event sequences, weights and model logs stay in a private runner directory. Only the explicitly named metadata JSON is uploaded. Failed-preparation reports retain error type, not private paths or exception payloads. No private user recordings are fetched.

## Decision boundary and next steps

This experiment addresses **raw model decoding and evidence-bounded recovery**, not a replacement for the product's16th grid or MusicXML/PDF layout. It does not train or improve model weights. If an arm improves average F1 but damages individual recordings/matches, preserve that result rather than silently enabling it. Further independent recordings, melody-role checks, notation ablation and human editing cost are required for product adoption.

Improving the neural model itself would require a separate protocol: representative target-domain labels, recording/performer-separated validation, aligned attacks/durations, controlled fine-tuning or model/checkpoint alternatives. CPU-only inference experiments do not imply GPU training approval. Training-data overlap and redistribution rights remain unknown/pending where already documented.

Sources: [Basic Pitch inference](https://github.com/spotify/basic-pitch/blob/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch/inference.py), [official decoder](https://github.com/spotify/basic-pitch/blob/fa5997af0a8210982619003269994a1be25eddf3/basic_pitch/note_creation.py), [YourMT3+ paper](https://arxiv.org/abs/2407.04822). External methods are motivations, not this repository's measured outcomes.
