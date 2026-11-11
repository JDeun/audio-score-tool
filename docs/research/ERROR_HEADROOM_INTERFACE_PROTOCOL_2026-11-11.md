# Actual vocal error headroom and Qwen interface diagnosis

Related #239 #240 #243 #223 #200 #214 #215 #34. User authorized execution after the next-experiment proposal. Research-only branch based on #243 head `ca50d68f8eb22cc60ca79e3c266b57204980055c`. No existing branch, product source/defaults, scores, weights or private recordings are changed. Do not auto-merge.

## Fixed experiments

### 1. Actual note errors and reference-free candidate headroom

Re-infer all original vocadito-v3 40 recordings using the existing pinned CPU adapters: YourMT3+ unchanged; Basic Pitch0.4.0 ONNX with the unchanged default and the previously selected onset0.65 decoder. Both Basic Pitch arms use identical neural outputs with independent decoder copies and an exact default replay check. This is not a new threshold search. Prior public artifacts contain metadata, not reusable raw predictions; re-inference is necessary for this new analysis.

Full-recording primary metrics remain the existing original-Hz A1/A2 scorer, onset50ms/pitch50cents, optional offset max(50ms,20%reference duration). Compare an independently formed mir_eval matching F1 with the shared scorer. All40 cases and both arms where applicable must complete before publishing an overall macro.

A fixed-priority residual bipartite matching assigns full-match / pitch+onset with offset mismatch / same-pitch within150ms / octave within50ms / other pitch at50ms / unmatched counts. Categories are mutually exclusive by this matching algorithm but **priority-sensitive diagnostics, not human-confirmed error causes**. Wrong instrument, true insertion/deletion, and merge/split causality cannot be inferred from these counts alone.

Before references are read, select up to three complete4-second windows per recording by SHA256 ordering of recording ID and window start. Silence/clean windows are not filtered using truth. Generate at most17 alternatives per window: unchanged, one onset move to a nearby audio peak within80ms, one split at an interior peak, or one merge of adjacent equal-pitch/equal-instrument events with gap<=80ms. Only isolated notes safely inside window bounds are editable. Fixed80ms minimum pieces; no pitch changes, octave folding, free insertions, global shifts, beam search, or per-case threshold optimization. Alternatives are chronological and may be capped; record their kinds and fingerprints.

Only after candidate generation, score each against A1/A2. Select the best local candidate **for evaluation only**, independently for onset and onset+offset metrics. This oracle is a maximum over this limited candidate set, NOT achieved system accuracy, a global optimum, a deployable policy, or a trained selector. Keeping original ensures nonnegative local gain; that is tautological and not efficacy. Different metric maxima can select different candidates. Windows use onset-based membership, keep offsets uncut and forbid boundary edits; local matches near boundaries can differ from whole-recording matching. Do not combine local oracle scores into claimed whole-song F1. Empty-reference windows report coverage and predictions but no perfect oracle score. Raw data/predictions stay on the private runner.

vocadito has been repeatedly used for development. Results are **not independent held-out validation**. New final model selection, automatic correction, notation/PDF or human edit-cost claims are excluded.

### 2. Qwen4 output-constraint x decoding-recipe diagnostic

Same official Qwen3-4B Q4_K_M, pinned llama.cpp and native chat template as #243. One neural model only, CPU2threads, no external inference service. Two factors: schema enforcement present/absent, and former greedy decoding versus author-recommended non-thinking recipe (temperature0.7/top_p0.8/top_k20/min_p0/presence_penalty1.5). The second is a recipe bundle, not isolated sampler parameters. All other request content/max_tokens64/non-thinking template settings fixed.

Six nonmusical lookup cases (prior three plus three authored transfer cases), four independently crossed candidate-order/A-B label presentations. Greedy seed0, sampled seeds0/1. Total144 calls, shuffled in a fixed order. No best seed or best presentation selection. Same exact JSON parser for both schema arms; no output repair, retry, regex extraction or commentary stripping. Malformed/incomplete responses count explicitly against selection reliability. Preserve final answer text/finish reason/token usage for these owned synthetic controls; do not publish reasoning traces or user music. Gate24/24 per arm+seed; passing is only interface admission, not music competence. No new music efficacy score in this diagnostic.

Model-card reference: https://huggingface.co/Qwen/Qwen3-4B-GGUF . The prior greedy result is a tested setting, not proof that all Qwen/LLMs fail.

### 3. External data admission, not silently reused development data

Inspect original author-hosted Annotated-VocalSet record7061507 and VocalSet1442513 metadata. Only explicit permissive license metadata admits automatic annotation inspection. Original annotation ZIP identity is MD5 f4324592f5edebcb9e572c01531ac63b, <=500MB. Inspect bounded member names and column headings only; no audio download, note-array publication or model scoring yet. Separate performed measured F0 from score-intended pitch before a scorer is implemented. Pairing, annotation semantics and model training overlap require review; do not call loading a dataset external accuracy validation. NC/gated alternatives (TONAS/CSD/M4Singer) are not silently substituted.

Sources: https://zenodo.org/records/7061507 ; https://zenodo.org/records/1442513 ; https://www.mdpi.com/2076-3417/12/18/9257 . The annotation paper describes algorithm-assisted and manually checked labels and multiple boundary variants; it is not interchangeable with vocadito's two human annotations. Selection of evaluation records must be frozen before inference results.

## Runtime, evidence and limits

Standard ubuntu24 CPU runners, max2parallel,2threads. Per-job75min; actual inference timeout60min, Qwen40min, external admission12min. No GPU/model authentication/API fee/training. Requirements/model/scorer hashes, original WAV/annotation hashes and runtime versions recorded. Subsequent documentation pushes do not repeat experiments. PR-open/reopen or manual dispatch only; preserve failed/partial jobs.

Only explicitly named JSON metadata reports are uploaded. Original audio, notes, neural arrays, weights and inference logs remain private temporary files. No product promotion, complete production CI claim, or auto-merge. Qwen/LSTM/T5 generative task research is not substituted for measured note error reduction.

## Preflight before remote execution

28 local tests passed: original input immutability, candidate references absent, pitch/instrument/boundary/polyphony protection, matching accounting, explicit empty cases, oracle-vs-product separation, no incomplete macros, crossed label mapping, strict parser, and schema-only paired request equality. Python compile and YAML parsing passed. No local real-model inference or external data admission completed; actual results must come from Actions artifacts. Full repository CI is not claimed by these targeted tests.
