# Actual vocal error headroom — partial execution snapshot, 2026-11-11

Related #244/#243/#240/#239/#200/#215. Standard CPU only. Product settings,
main and other-session PRs unchanged. This is an auditable partial snapshot,
not an all-model result or an independently held-out benchmark.

## Execution identity and checks

Workflow42985648061, Basic Pitch job130406050293 succeeded. Experiment head
`431c55833a753c59fd3a3d8297090846e759edf3`; actual PR merge checkout
`6865433bf31a13415fe03d3be78f483330d0b1dd`. Later documentation commits are
not the revision used for inference.

Downloaded artifact13839472716 (`error-headroom-basic_pitch-42985648061`).
ZIP SHA256 `84a81c4cc24498b785989ddad1acb23ac0841387201795840868c30d06753664`.
Report SHA256 `5346c547c36ca99a37ed1e02380d526fadd536e6c723af1f5eafc3291c76c608`.
Verified the ZIP hash against Actions metadata,40/40 planned recordings, both
arms and both annotations, count conservation in the ordered residual matching,
all candidate-kind mappings and arithmetic. Macros and per-window oracle gains
were recomputed from the receipt. This is metadata/provenance verification,
not independent re-inference or raw-audio rescoring. Twenty-eight targeted
protocol tests passed locally and in the completed Basic Pitch job; this is
not the full product CI suite.

## Full-recording primary metrics: reproduction only

| Fixed Basic Pitch decoding | Pitch+onset F1 | Pitch+onset+offset F1 |
|---|---:|---:|
| Default |49.102129%|31.583077%|
| Previously chosen onset0.65 |54.192265%|37.257207%|

These reproduce the previous development result with unchanged weights and
scoring. They are not an accuracy improvement from the new candidate generator.
The40 original vocadito recordings have been repeatedly used for development;
this result does not establish external generalization.

## Local candidate headroom: evaluation oracle, NOT achieved correction

Sampling without reference access produced118 complete four-second windows,
with236 window-annotation pairs. All windows had multiple candidate alternatives;
none reached the17-candidate cap. The candidates are keep or a single
reference-free onset/split/merge edit; pitch, instrument and protected boundary
notes are not changed. References enter only after all candidates are generated.

| Local window diagnostic | Default decoder | Fixed onset0.65 |
|---|---:|---:|
| Windows with positive onset-F1 headroom under BOTH annotators |75/118|49/118|
| Local onset F1 before candidate choice |48.3645%|53.5086%|
| Reference-selected local onset-F1 maximum |52.2723%|56.6811%|
| Local onset-F1 headroom |+3.9079pp|+3.1725pp|
| Local onset+offset F1 before candidate choice |30.9173%|36.3487%|
| Reference-selected local onset+offset-F1 maximum |36.6913%|41.2872%|
| Local onset+offset-F1 headroom |+5.7740pp|+4.9385pp|

These are **separate per-window, per-annotator and per-metric maxima selected
using truth at evaluation time**. They are neither a deployable selector nor
whole-recording F1, and different metrics can select different candidates.
They bound only this limited one-edit candidate set, not all achievable future
improvement. Nonnegative headroom is guaranteed by keeping the original and is
not itself proof of efficacy. A1/A2 can prefer different edits even in a window
with positive headroom for both; this does not establish consensus on one edit.

For onset0.65, best-improving onset candidates across236 annotated windows
were51 merges,37 onset edits and29 splits. These are correlated diagnostic
window-times-annotation counts, not117 independent confirmed musical errors.

## Ordered residual matching counts

Counts below sum BOTH annotations; the same predictions are evaluated twice.
Categories are assigned by fixed-priority residual maximum matching. Priority
can change associations. Do not read them as human-confirmed causal labels.

| Category | Default | Onset0.65 |
|---|---:|---:|
| Full pitch/onset/offset match |1258|1384|
| Remaining pitch/onset match with offset mismatch |739|675|
| Remaining same pitch within150ms |686|520|
| Remaining octave discrepancy within50ms |2|3|
| Remaining other pitch discrepancy within50ms |222|206|
| Unmatched reference |1206|1325|
| Unmatched prediction |1265|778|
| Total reference events across annotations |4113|4113|
| Total predictions counted twice |4172|3566|

The unmatched rows do not automatically mean insertion/deletion causes; they
can include combined timing/pitch/segmentation errors. This analysis does not
identify instrument-confusion errors or replace primary strict F1.

## Remaining jobs at this snapshot

YourMT3 is running the actual40-recording experiment; Qwen4 has completed
runtime preparation and is executing the bounded144-call nonmusical interface
ablation. External-corpus admission is queued behind the max2parallel limit.
No results are inferred for those jobs from Basic Pitch. Read their own final
receipts and job outcomes before updating this snapshot.

External Annotated-VocalSet/VocalSet work is intentionally **metadata/license/
annotation-schema admission**, not a completed independent accuracy validation.
Original-audio pairing, annotation semantics and training overlap still need
review before evaluating the frozen Basic Pitch0.65 setting on that corpus.

## Current decision

Actual development inputs contain some better one-edit candidates. This makes
reference-free candidate selection a measurable next question, but it does not
show that any rule, LLM or music model can choose those candidates reliably.
No automatic editor, product model selection, notation/PDF acceptance or human
editing-time improvement is approved here. Keep #244 draft and quality issues
open. Raw recordings, annotations, predictions, weights and private logs were
not uploaded; only explicitly scoped metadata receipts are public.
