# CPU symbolic choice follow-up results — completed, 2026-11-11

Related #243 / #240 / #223. Both Qwen jobs and the isolated mono_rnn follow-up
completed. Original preparation failure is retained. No product/default change,
main merge or automatic musical editing was performed.

## Execution and audit

- Original run42966855806, head `376c5b69aa4f53a203b533c3e2b2a7015775db1d`,
  actual PR checkout `e6268e24e8f846cc9a8f6017a356204c59d4cc32`.
- Qwen1.7B job130345944747 succeeded; artifact13832111443 ZIP SHA256:
  `5c19432f9b221da170870016db1120f86fda2a7bff08a74c4ab571d77efa8f7a`.
- Qwen4B job130345944708 succeeded; artifact13830699912 ZIP SHA256:
  `c83bcb832dcd731238c43b7e363764779e40cfb77ae1609df800854049142815`.
- Original mono job130345944364 failed **before inference**: separately installed
  pytest's exceptiongroup1.3.1 requires typing-extensions>=4.6, while TF2.12
  needs<4.6. Failed receipt artifact13831054597 is not a musical zero.
- Workflow-only fix `60c6dd1c2d9205be09e404308dcdf89e6cae3aa8` isolates TF in a
  separate virtual environment. Push reran only mono, not the Qwen jobs.
- Completed mono run42967218637, job130347118217, artifact13831872275 ZIP SHA256:
  `8a50ee6de6cf5fcd5f85dcb14bf99c22ecfe15f3e1f5d3ad6a6051b7c96c07c3`.
- All three downloaded ZIP digests were checked against GitHub metadata. All
  planned rows, label-to-content mappings, correctness flags, summaries and
  LSTM prior combinations were independently recomputed. This is metadata
  arithmetic/provenance verification, not independent re-inference or audio rescoring.
- All three script SHAs match the locally tested code:
  `20f9481a92f101f0c852a4913bcef1e7dce2679d12e0ea332fec1323ac596907`.
- All three fixture SHAs match Stage0:
  `df3b690e9b00cbd314beeb297d97028b769375cf18d3aab17f8eb16ac3922c4e`.
- 29 new local tests, remote lint and the 29 remote tests passed. Do not confuse
  this targeted validation with the repository's full product CI suite.
- The original workflow's overall failure still reflects the original mono
  preparation failure; do not relabel that entire run successful. Qwen jobs
  succeeded individually and the separate mono repair run succeeded.

## Qwen3-1.7B Q8_0 and Qwen3-4B Q4_K_M

Same official weights and llama.cpp revision as Stage0; native chat interface,
non-thinking JSON schema output, 24-tick integer times and no original marker.
List order and A/B labels are crossed independently. These interface changes
occur together, so changes versus Stage0 cannot be assigned to one factor.

| Diagnostic | Qwen1.7B | Qwen4B |
|---|---:|---:|
| Lookup controls: three cases x four presentations | 8/12 correct | 10/12 correct |
| Lookup cases correct under all presentations | 0/3 | 1/3 |
| Music: eight cases x four presentations | 14/32 correct | 16/32 correct |
| Music cases correct under all presentations | 0/8 | 0/8 |
| Cases with any content-choice disagreement | 8/8 | 8/8 |
| Clean music cases damaged in at least one presentation | 3/3 | 2/3 |
| Ambiguous music presentations correctly abstained | 0/4 | 3/4 |
| All music abstentions | 0/32 | 11/32 |

Both **fail the preregistered 12/12 instruction gate**. This is a completed
execution of a failed diagnostic, not a runtime failure or admission pass.
None of the 88 Qwen calls failed schema/completion validation; valid JSON does
not imply a correct content choice. The 32 presentations are correlated variants
of eight cases, not 32 independent musical examples.

### 1.7B label sensitivity

All 32 music presentations return label A. Changing list order while preserving
labels preserves the content selection; changing A/B labels changes the content
selection. This condition specifically exposes label sensitivity, not just a
list-order effect. All three normal examples can be damaged under label swapping;
first-order-only safety counts would conceal this.

### 4B mixed order/label sensitivity

Music output labels are A16/B5/abstain11. Every musical case changes content
selection under at least one label swap and at least one list-order swap. The
model correctly abstains in three of four presentations of the ambiguous case,
but abstains in eight determinate presentations as well. Two of three normal
examples receive a wrong edit in at least one presentation. Only the no-match
lookup control succeeds in all four presentations; each actual-match lookup
control has one error. Thus a superficially higher aggregate than 1.7B still
fails the required elementary selection reliability and cannot qualify automatic
postcorrection.

Neither tested configuration is suitable for product automatic correction.
These results do not prove all LLMs, all Qwen settings or unconstrained reasoning
lack musical competence. Before larger real-song evaluation, isolate structured
output constraints, decoding and input interpretation in nonmusical controls.
No score-driven protocol changes were made during this run, and no best
presentation/model setting is selected to inflate the result.

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

## Interpretation boundary and current decision

These are eight tiny authored symbolic cases with complete synthetic attack
observations, not actual audio or AMT output. The acoustic baseline already
solves the supported cases, so this suite has no headroom to establish a positive
LSTM gain. A supported-case 5/5 is not real transcription accuracy and does not
justify ranking mono_rnn above the Qwen configurations on different coverage.

No performance F1, whole-song notation quality, PDF readability or human edit
cost was measured. MelodyT5's task-aligned candidate-scoring question remains
open; its prior loading/forward success is not counted as correction efficacy.
It was not rerun merely to repeat admission. Markov remains the prior hand-set
baseline, not a newly trained HMM or a reproduced pretrained paper model.

The useful next gate is reliable candidate selection, not product integration:
Qwen needs a separately declared interface/constraint ablation that passes simple
controls; a music prior needs ambiguous/noisy development cases with real room
for improvement and protected ground truth. Those subsequent tests are not
claimed to have run here. Keep #240/#223 open and #243 draft. No weights, private
logs, user music or production settings have been published or modified.
