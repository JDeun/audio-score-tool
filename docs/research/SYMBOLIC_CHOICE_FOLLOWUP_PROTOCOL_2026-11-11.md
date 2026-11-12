# CPU symbolic choice follow-up — 2026-11-11

Related #240 / #223 / #241 / #242. This experiment continues the successful
runtime admission, not production deployment. Parent is #242 head
`5e9c771da3f60fd01e318ed50e978a7d24e4c468`. No main merge, product inference,
private songs, default engines, automatic edits, external paid API or training.

## Why this run

Stage 0 scored the first of two presentations; alternate presentation choices
were only reflected in an inconsistency count. That is insufficient to assess
clean-case damage across orders. This run stores **every mapped content choice**
and its correctness, with list order and A/B labels varied independently (2x2).
The four presentations of a case are correlated, NOT four independent songs.

The eight existing cases are authored synthetic symbolic observations, not
recordings or actual AMT/Tiny/beat output. Their baseline is deliberately easy.
A perfect score cannot establish a real-song benefit. The settings below are
fixed before the new output is viewed; no post-hoc per-case winner selection.

## Qwen diagnostic condition

Use the same officially pinned Qwen3-1.7B Q8_0 and Qwen3-4B Q4_K_M weights,
llama.cpp commit and CPU two-thread execution as Stage 0. New condition uses:

- Native `/v1/chat/completions`, Jinja chat template, `enable_thinking=false`
  plus `/no_think`, constrained JSON A/B/abstain, temperature 0/seed 0.
- Exact integer ticks (24/quarter) instead of fractional strings; no original
  flag, target field, category or fixture ID in model inputs.
- Three NONMUSICAL marker-lookup controls (first match, second match, no match)
  and eight same musical cases, each in four presentations: 44 calls per model.
- A 64-token cap and 180-second request timeout. Invalid schema, non-stop finish
  and runtime failures are NOT abstentions or correct answers.

This changes several input/transport factors together. A difference from Stage 0
cannot isolate the template, representation or original-marker effect. It is a
preregistered alternative interface diagnostic, not a single-factor efficacy
claim. Native structured-output support is described in pinned llama.cpp
`tools/server/README.md`; Qwen's official model card describes non-thinking mode.

Record all presentation choices, prompt hashes, usage/time and complete group
summaries. The instruction gate requires all 12 lookup presentations correct.
Music probes are still recorded after a failed gate for diagnosis, but must not
be promoted to a music-ability conclusion. Any clean case damaged in any order
counts as damaged. The original eight cases are not held-out development data.

## Learned mono_rnn prior on the same representable candidate subset

Use the successful #242 scoring adapter with unchanged upstream graph and
encoder, official bundle generation `1551832452804604`, 13,997,590 bytes and
SHA256 `69308e573f8be84aea3870146039d22f212aeb3767b08c19cd5b58dff7fec873`.
Every call retains independent next-event logsum and duplicate-batch checks.

Both candidates must be represented exactly at four steps/quarter. Unsupported
thirds and 32nd positions are reported, NOT rounded, transposed or assigned zero.
The prefix is the existing four half-quarter context notes at pitch 60. Candidate
conditional log likelihood is logP(prefix+candidate)-logP(prefix), four time
steps per candidate regardless of note count. Compare unchanged acoustic cost
plus original-edit cost with fixed prior weights 0, 0.01 and 0.1. No acoustic
observations means abstain in ALL conditions. These three weights are sensitivity
arms, not fitted parameters; all results must be reported, not only the winner.

The fixture acoustic rule already solves the supported subset, so this can find
regressions/prior conflicts but cannot demonstrate superiority on real ambiguous
performances. This is a learned LSTM prior, not the prior hand-set Markov model.
No directly comparable headline leaderboard is formed across unsupported cases.

## Explicitly deferred

MelodyT5 previously passed loading and a segmentation forward probe. Its learned
segmentation task concerns phrase/breath marking, not arbitrary AMT split/merge
repair. We do not silently interpret that task loss as a validated unconditional
music prior or rerun its same admission test and claim progress in accuracy.
Task-aligned candidate likelihood validation remains a separate follow-up.

Longer multi-bar contexts, real audio errors, MusicXML/PDF, human editing time,
independent corpus and statistically defensible generalization all remain open.
Performance with the tested quantized Qwen settings is not all LLM performance.

## Execution/evidence policy

One Actions matrix, maximum two jobs concurrently, 45 minutes/job, CPU only,
no model credentials or training. New PR opened/reopened or explicit dispatch
runs it; ordinary documentation pushes do not repeat inference. Only JSON
receipts leave the runner; weights, private logs and model/source material do
not. Preparation failures remain failed jobs with an explicit failure receipt.

29 new local protocol tests and Python compile passed before PR creation.
No real pretrained inference was executed locally; model conclusions require
actual Actions receipts and their source/checkpoint identities. No auto-merge.
