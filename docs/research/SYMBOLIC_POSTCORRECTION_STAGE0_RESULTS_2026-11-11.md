# Symbolic postcorrection Stage 0: actual CPU receipts, 2026-11-11

Related #240 / #223, admission PR #241, runtime-repair PR #242. This is a review of the completed original workflow, not a new audio transcription experiment. Product code, automatic editing, defaults, main and other-session #236/#239 are unchanged.

## Provenance and audit

Original [workflow 42960526211](https://github.com/JDeun/audio-score-tool/actions/runs/42960526211): PR head `8fa7b5bf0af6cc6377f77393a63f4d70a9001b2d`, actual checkout `c630d85d4288133e9041e5aef17aecc2535d3e11`. The two Git objects have different roles. Qwen and the baselines used the same script SHA256 `fb14493554e0d8c2e4029ea803bbb4c9fcabf2822448d0b518c4f28a758179df` and fixture SHA256 `df3b690e9b00cbd314beeb297d97028b769375cf18d3aab17f8eb16ac3922c4e`.

Four artifact ZIPs were downloaded, their SHA256 digests checked against GitHub metadata, and their JSON read. For all four choice arms, eight unique planned IDs, complete rows and matching fixture identity were verified; each summary was recomputed from individual metadata rows. This is aggregation/provenance verification, **not an independent re-run of model generation or raw-response rescoring**.

| Artifact | ID | ZIP SHA256 |
|---|---:|---|
| symbolic-baselines | 13829410537 | `ed0385932d21300f17fa2c6664851aca1dbb41bdccc8cc2def10ec2e237a882b` |
| symbolic-qwen17 | 13828599866 | `59ab6fb9358c69573f79f39646835f0e312f1b54df332a15897aae735ea2af6a` |
| symbolic-qwen4 | 13829395999 | `97848224f1b702e52458c968351eb694d119ea122e7c51619b814cae1d2b01f4` |
| symbolic-runtime-melodyt5 | 13829535166 | `837068d666909ebc8e340d15ed8b9740b61b4dc514a8a4b63bf075acacc577c8` |

## Eight authored symbolic cases: selection only

These are **hand-authored observations, not recordings, not AMT predictions and not a held-out musical corpus**. Each local candidate window is one quarter-note beat, with a short fixed preceding-duration context; it is not the eventual 2–4-bar context evaluation. Four cases need repair, three preserve a normal input and one requires abstention. Candidates and exact synthetic attack information were designed together; the simple cost baseline is expected to do well. It is not an independently trained benchmark.

Each arm was called with both candidate orders (16 calls, **not 16 independent musical examples**). The original report's `choice_correct`, damage and abstention fields describe the **first order only**. `order_disagreements` separately compares first and reversed choices after mapping back to source candidates. The report does not retain the reversed choice itself, so do not claim a zero collateral-damage rate across both orders.

| Arm | First-order correct / 8 | First-order normal cases changed / 3 | First-order abstentions | Candidate-order disagreements / 8 |
|---|---:|---:|---:|---:|
| Deterministic synthetic attack-cost baseline | 8 | 0 | 1 | 0 |
| Same cost + **hand-set** first-order duration Markov prior | 8 | 0 | 1 | 0 |
| Qwen3-1.7B Q8_0 | 3 | 0 | 0 | 2 |
| Qwen3-4B Q4_K_M | 3 | 0 | 0 | 8 |

Both Qwen arms chose the original candidate in all first-order cases, repairing none of the four faulty examples and failing the deliberate abstention case. A calculated always-keep-original baseline would therefore also score 3/8 on this first order. This is a diagnostic, not a separately executed model. The 4B outcome changes for every reversed order, indicating severe order sensitivity in this particular prompt/decoder configuration. Do not treat the first-order normal-case damage column as safe automatic editing.

Both Qwen jobs executed successfully with verified official weights and pinned CPU llama.cpp. Syntax-valid constrained JSON and successful runtime do **not** establish useful reasoning or music correction. These small non-thinking/short-output probes do not disprove the usefulness of all LLMs, other prompts, longer context or other models. Neither Qwen setup is approved for production correction on this evidence.

The hand-set Markov prior is not a pretrained HMM, the 2021 paper's model, or a learned music LM. Its equal output to the rule baseline establishes no added value from the prior.

## MelodyT5: admission passed, correction quality not measured

The actual pretrained checkpoint loaded with strict state matching. Checkpoint SHA256 `930d96ecb6a663ef8e504e0885e940a676cb3d4fe36c6513b96f00db233435cd`, 1,357,746,623 bytes, HF revision `22c7d8f51fc3f69f2e272c00fe44d50df2b0e38f`; source revision `9fc0e7dd02ba10a77b46f9d4a669451f17885fbc`.

Short ABC representation roundtrip passed, long-input truncation was detected, and a bounded teacher-forced segmentation forward produced finite loss 1.3325202465. This is **not a candidate-ranking score, correction F1, or proof of improved notation**. The original upstream segmentation task concerns symbolic segmentation and is not an audio note-onset detector. No random-initialized output was counted as pretrained success.

## Melody RNN: original dependency preparation failed

Original job `130325788439` stopped before weights/inference: `note-seq==0.0.5` requires protobuf>=4.21.2 while the workflow pinned protobuf3.20.3. TensorFlow CPU2.12.1 accepts a compatible 4.25.x release. #242 isolates a corrected CPU runtime and runs **only mono_rnn**, leaving successful Qwen/MelodyT5 runs intact. Its status must be read from its own workflow receipt, not inferred from this report.

The first repair attempt additionally found the requested jaxlib0.4.13 wheel absent from the current package index. Its failed job/metadata is preserved; the compatible CPU0.4.18 pair is a separate subsequent attempt. Dependency failures are not musical zeros. There is no LSTM correction-quality result at this snapshot.

## Next gate, not a result claim

Before larger real-song tests: add non-musical candidate-ID instruction controls, retain both permutation choices and their correctness/damage, and verify prompt/template/grammar behavior. Keep the observed negative first result rather than tuning silently on it. Next compare music specialists on genuinely common representable candidate sets with a fixed acoustic/edit-cost combination, reference-free candidate generation and an independent validation split. The eight fixtures and a finite model loss cannot approve real AMT correction, MusicXML/PDF readability or human editing-cost gains. #240 stays open.
