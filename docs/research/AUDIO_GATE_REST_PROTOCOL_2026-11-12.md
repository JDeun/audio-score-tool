# #269 — actual waveform amplitude gate as gap evidence (frozen pilot)

User hypothesis: an audio-console-like gate can identify low-volume intervals that may be rests. Base main2f9e9bd637dd66ed07544230c01ea6e9951a6190. Research code/evidence only; no product algorithm activation, source/default/dependency lock changes. CPU2threads, no GPU/training/LLM/paid endpoint/external model credentials.

## Distinction from earlier experiments

#267 inferred quiet cores from MIDI endpoint intervals; this pilot measures actual recorded WAV RMS. The first stage uses all40 original vocadito solo-vocal recordings, with both independent note annotations A1/A2. **These labels denote performed notes, not explicit engraved rests or intended staccato notation.** We measure low-energy evidence, annotated non-note time and AMT-note damage, not final MusicXML/rest transcription correctness. The nASAP bar-sum DP is NOT run with invented beat/voice/rest truth. Score-aligned stem validation is a later gate.

Official source: https://zenodo.org/records/5578807 (Bittner, Pasalo, Bosch, Meseguer Brocal, Rubinstein,2021). Original ZIP58,492,257 bytes, MD5dea40fd18f14d899643c4ba221b33a46, full SHA256 matched to the archived baseline before use. No source audio, lyrics, note arrays or model weights are republished. Existing repeated development corpus: no holdout/generalization or previously unseen model-data overlap claim.

## Fixed common predictions

Old artifact13825524844/run42954128502 contains hashes/counts/metrics, NOT reusable note arrays. Regenerate Basic Pitch0.4.0 ONNX inference ONCE per recording, resident model, intra2/inter1threads; use the same output arrays for two original decoders(default and onset0.65). Compare each of80 raw prediction fingerprints and all160 annotator-baselines to the earlier report EXACTLY. All five postprocessing arms use that common output, not separate stochastic inference.

Baseline ZIP SHA256:6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0.
Report SHA256:dff293dc36a6642141cd235d8d958770e01d4bcd90f6f67c2ae0f82ae465309c.
Model uses existing verified nmp.onnx Git blobc30e5f9438e798604b7177aa26be1fe64482f767/230444bytes. No application defaults changed. Metadata artifact retrieval uses read-only repository Actions permission, not an external music/model API.

## Gate hypotheses frozen before measuring source recordings

Native-rate RMS20ms centered windows on10ms cells. Average channel POWERS, not signed stereo samples. Fixed absolute gate closes below-45dBFS, opens at-39dBFS. Relative gate closes30dB below the95th percentile frame RMS, opens6dB above the closing threshold. Close only after60ms continuous low frames; offline backdate to the first low cell. Start closed; opening is immediate. Exactly zero audio is all quiet. Original audio is never filtered/cut. These values are uncalibrated research settings, not a recommended universally correct console setting.

Five arms for EACH decoder:
1. raw model events;
2. absolute gate, hard intersection of predicted note spans with gate-open intervals;
3. absolute gate, soft raw-vs-intersected candidate choice;
4. relative gate, hard;
5. relative gate, soft.

Intersection can remove, shorten or split notes; do not hide changed onset/counts behind an offset-only score. Minimum resulting fragment60ms. Events outside observed audio or drums are unchanged. Pitch/channel/program preserved for all retained fragments; no pitch correction, new inferred pitch, tempo grid, lyric, F0 or reference input.

Soft rule chooses the lower fixed cost per parent note: raw cost3*seconds covering gate-closed intervals; cut cost1*removed_seconds +0.120 per changed parent +0.080*abs(fragment_count-1) +0.5*first-onset displacement_seconds. Exact ties keep raw. This is a bounded acoustic candidate selector, **NOT** the full joint metrical notation decoder or a calibrated rest probability. No post-result threshold search, per-song best parameter selection or oracle input selection.

## Evaluation and safeguards

All annotations are first read after ALL prediction candidates for that recording are fixed. Archived annotation/audio hashes also must match. Reference Hz retained; mir_eval onset50ms,pitch50cents; offset tolerance max50ms,20% reference duration, exactly as prior tests. Report both onset and onset+offset F1 for A1/A2 separately and averaged. Reference-match bit masks permit independent recomputation of gains/damage; these counts are annotator-evaluation outcomes, not independent unique notes across both annotators.

For time occupancy, evaluate ONLY within first-to-last annotated note, excluding trivial leading/trailing silence. That cropping uses truth only for scoring, not gate estimation. At10ms resolution report true non-note time preserved, true non-note time filled by estimated notes, and annotated-note time wrongly treated as quiet. Gate-alone precision/recall and final corrected occupancy are separate. These are non-note-time proxies, not actual notated rest labels. No inference that every low-energy frame is a written rest.

Gain controls: rescale the same float WAV by-12/+12dB without clipping, recompute gates without rerunning Basic Pitch. Relative gate decisions should be invariant; absolute gate sensitivity reported. This does not establish robustness to compression/noise/reverb or changes in the neural model under gain variation. Offline tests include low real-note deletion, hold/hysteresis, stereo cancellation, deterministic gains, out-of-audio abstention and identical-waveform staccato-vs-rest ambiguity.

Two bases x5 arms x40 recordings x2 annotators =800 metric evaluations, NOT800 songs. Completeness requires all40 identities; failures remain visible and suppress the full macro. Empty predicted-note output is scored zero, not dropped. Old results reproduced first; no retuning after outcomes. Metadata-only artifact contains hashes, counts, match masks and metrics, no source recordings/lyrics/MIDI/prediction event arrays.

## Execution boundary

26 new offline contract tests passed locally before any new real-waveform evaluation. Standard GitHub CPU workflow runs pinned tools, new-file lint/tests then source inference/evaluation. The heavy study is opt-in on opening this specifically scoped PR or manual dispatch, not on normal main pushes. Full repository CI remains required before research integration. Research integration is separate from product activation.

A useful result must improve annotated gap preservation WITHOUT unreported deletion of soft notes or onset/offset damage. Even a positive pilot still needs independent score-aligned stems, separation artifacts, real notated rests, multi-voice handling and final score/edit-time assessment.
