# CPU symbolic choice follow-up results — partial snapshot, 2026-11-11

Related #243 / #240 / #223. Qwen1.7B and mono_rnn are complete in this snapshot;
Qwen4B is still running and has no inferred result here. No product/default change.

## Execution and audit

- Original run42966855806, head `376c5b69aa4f53a203b533c3e2b2a7015775db1d`,
  actual PR checkout `e6268e24e8f846cc9a8f6017a356204c59d4cc32`.
- Qwen1.7B artifact13832111443 ZIP SHA256:
  `5c19432f9b221da170870016db1120f86fda2a7bff08a74c4ab571d77efa8f7a`.
- Original mono job failed **before inference**: separately installed pytest's
  exceptiongroup1.3.1 requires typing-extensions>=4.6, while TF2.12 needs<4.6.
  The failed receipt remains artifact13831054597; it is not musical zero.
- Workflow-only fix `60c6dd1c2d9205be09e404308dcdf89e6cae3aa8` isolates TF in a
  separate virtual environment. Push reruns only mono, not the Qwen jobs.
- Completed mono run42967218637, artifact13831872275 ZIP SHA256:
  `8a50ee6de6cf5fcd5f85dcb14bf99c22ecfe15f3e1f5d3ad6a6051b7c96c07c3`.
- Both downloaded ZIP digests were checked against GitHub metadata. All planned
  rows, label-to-content mappings, correctness flags, summaries and LSTM prior
  combinations were independently recomputed. This is metadata arithmetic and
  provenance verification, not independent re-inference or audio rescoring.
- Both script SHAs match the locally tested code:
  `20f9481a92f101f0c852a4913bcef1e7dce2679d12e0ea332fec1323ac596907`.
- Both fixture SHAs match Stage0:
  `df3b690e9b00cbd314beeb297d97028b769375cf18d3aab17f8eb16ac3922c4e`.
- 29 new local tests, remote lint and the 29 remote tests passed. Do not confuse
  this targeted validation with the repository's full product CI suite.

## Qwen3-1.7B Q8_0

Same official weights and llama.cpp revision as Stage0; native chat interface,
non-thinking JSON schema output, 24-tick integer times and no original marker.
List order and A/B labels are crossed independently. These interface changes
occur together, so changes versus Stage0 cannot be assigned to one factor.

| Diagnostic | Result |
|---|---:|
| Lookup controls: three cases x four presentations | 8/12 correct |
| Lookup cases correct under all presentations | 0/3 |
| Music: eight cases x four presentations | 14/32 correct |
| Music cases correct under all presentations | 0/8 |
| Clean music cases damaged in at least one presentation | 3/3 |
| Ambiguous music presentations correctly abstained | 0/4 |

The **12/12 instruction gate fails**. All 32 music presentations return label A.
Changing list order while preserving labels preserves the content selection;
changing A/B labels changes the content selection. Thus the new musical result
specifically exposes label sensitivity, not just a generic list-order effect.
The normal-case damage overlooked by first-order-only summaries is now visible.

This setting is unsuitable for product automatic correction. It does not prove
all LLMs, all Qwen settings or unconstrained reasoning lack musical competence.
Before larger real-song evaluation, isolate output constraints, sampling and
input interpretation in nonmusical controls. No score-driven protocol changes
were made during this run, and no best presentation is selected for the result.

## Pretrained mono_rnn conditional prior

Checkpoint generation1551832452804604 and SHA256
`69308e573f8be84aea3870146039d22f212aeb3767b08c19cd5b58dff7fec873` unchanged.
The #242 adapter validates codec/manual next-event logsum and identical batches.

| Combination on the five supported cases | Correct choices |
|---|---:|
| Acoustic/edit cost only, prior weight0 | 5/5 |
| Same + pretrained LSTM prior weight0.01 | 5/5 |
| Same + pretrained LSTM prior weight0.1 | 5/5 |

The five comprise four determinate cases and one case correctly abstained for
missing evidence. No additional gain is observed. Cases04/06/07 (off-grid start
or thirds) are explicitly unsupported, not rounded, omitted from a claimed full
score or assigned musical zero. Coverage is 5/8.

The prior can conflict with the authored attack evidence: in probe01 it prefers
two half-quarter notes over the target sustained note (-1.2009 vs -2.5883
conditional loglikelihood); in probe05 it prefers the full-quarter note over the
target syncopation (-2.5883 vs -5.2616). The acoustic cost prevents these wrong
choices at both preregistered weights. This supports keeping an acoustic guard;
it does not estimate the general effectiveness of music LSTMs.

## Interpretation boundary

These are eight tiny authored symbolic cases with complete synthetic attack
observations, not actual audio or AMT output. Four presentations are correlated
variants, not four independent songs. The acoustic baseline already solves the
supported cases, so this suite has no headroom to establish a positive LSTM gain.
No performance F1, whole-song notation quality, PDF readability or human edit
cost was measured. MelodyT5's task-aligned candidate-scoring question remains
open; its prior loading/forward success is not counted as correction efficacy.

Keep #240/#223 open and #243 draft. No weights, private logs, user music or
production settings have been published/modified. Qwen4 must be reported from
its own completed artifact, not guessed from the 1.7B result.
