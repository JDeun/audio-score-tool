# CPU symbolic postcorrection: admission before quality claims

Related #240 / #223 / #200. User-authorized execution after candidate research. This branch
adds only research scripts, owned fixtures, tests and a bounded workflow. It does not change
production inference, default models, user scores, or other-session PRs #236/#239. No auto-merge.

## Actual scope of this first run

- Rule baseline and **hand-set first-order duration Markov prior** on the same eight authored
  symbolic cases. This is not the trained Hiramatsu model, a reproduced paper, or a full HMM.
- Official Qwen3-1.7B Q8_0 and Qwen3-4B Q4_K_M: real CPU inference via pinned llama.cpp,
  same cases, two candidate permutations. Candidate ID or abstention only, not XML rewriting.
- MelodyT5: pinned upstream source, immutable HF LFS identity verified before loading,
  strict pretrained state loading, ABC representation and teacher-forced segmentation smoke.
  This does NOT measure transcription correction or qualify arbitrary ABC likelihood as music truth.
- Magenta mono_rnn: official GCS object generation and checksum frozen at admission, real
  bundle restore and one finite likelihood calculation without automatic pitch squashing.
  This is a legacy compatibility experiment, not a trained new LSTM or candidate-quality ranking.

Neural architecture scaffolding for MelodyT5 is upstream setup only: strict pretrained state
replacement is required before any forward evaluation. No random-initialized output counts.
Source URLs/revisions are in the scripts. Qwen model SHA/bytes are pinned from official LFS
pointers. Magenta uses generation-pinned author-host metadata on the first admission run;
this is not an independently signed attestation. Preserve that generation/SHA for later runs.
Code, model, corpus and downstream distribution rights remain separate; no bundled release.

## What the synthetic probe can and cannot show

Fixtures are deliberately small, **hand-authored observations** of sustained/repeated notes,
missed attacks, delayed attacks, syncopation, triplets and insufficient evidence. They contain
no copyrighted recordings and **are not outputs of an audio model**. The targets are held by
the scorer, removed from model input, and never read by the baselines. Candidate generation is
fixed, not reference-informed at runtime. The rule baseline is intentionally strong on these
simple cases; its score is not evidence of real-song ability. LLMs only see structured data.

Both candidate orders are executed. Report correctness, clean-case damage, abstention,
order consistency, per-call timing and peak RSS. Runtime failure/timeout/malformed output is
not a musical zero and prevents a complete summary. No API service, token, GPU, or training.
No model is promoted based on syntax-valid JSON. A finite likelihood is a runtime test only.
An abstention is not an error repair; the unanswered fraction must remain visible.

All times are exact rational quarter beats. The Magenta-like codec rejects thirds and
32nd-note positions rather than rounding them into its four-step-per-quarter domain. This
custom gate is independently tested; the real Magenta model gets only supported sequences.
The short MelodyT5 ABC fixture must roundtrip; the >256-patch fixture is used to detect the
known truncation boundary, never scored as preserved. Multi-voice, key-change, tie, transposing
instrument and expressive timing fidelity remain future admission checks.

## Limits and next gate

This workflow does not test raw AMT F1, real performance timing, full MusicXML/PDF output,
real-world edit time, or general musical intelligence. Models intentionally have different
Stage-0 tests, so their rows MUST NOT form a four-family accuracy leaderboard. The real
same-candidate comparison with both music models needs representation adapters and a
validated prior/acoustic/edit-cost combination after admission. No thresholds are selected
from these eight fixture outcomes. The familiar vocadito/five-song development data must
not be called new held-out evaluation. Existing source predictions are never overwritten.

Actions are capped at standard CPU runners, two threads per inference and 40/45 minutes.
The two model matrices can total four parallel model jobs; no hidden GPU or paid model API.
Only JSON receipts are uploaded, never weights, private logs, generated note arrays or audio.
Installation failures remain failed jobs even when the script was not reached. Subsequent
pushes do not repeat inference; only PR opened/reopened or explicit workflow_dispatch does.

## Local preflight at authoring

21 synthetic/reference-isolation/schema/codec tests passed. Model inference and remote CI
were not executed locally. The execution status must be read from the actual Actions run;
this document contains no invented result and does not close #240 or approve auto-correction.
