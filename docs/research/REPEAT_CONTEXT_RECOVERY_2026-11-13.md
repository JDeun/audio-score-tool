# Repeat-context report recovery — unchanged predictions and compact metadata

Execution [#286](https://github.com/JDeun/audio-score-tool/issues/286),
[PR #287](https://github.com/JDeun/audio-score-tool/pull/287). This recovery extends
the [frozen protocol](REPEAT_CONTEXT_PROTOCOL_2026-11-13.md) without changing its
population, source selection, inference, truth, evaluation arithmetic or byte
limits. Commit the recovery implementation, tests and this record before the
official recovery run. Preserve the failed original artifact under its own name.

## What the first execution completed and where it failed

Original [CPU run 43256776331](https://github.com/JDeun/audio-score-tool/actions/runs/43256776331),
attempt1, used scientific head `cbcf97e0dc7fbd56bc3052e3f8daa30475b36cad` and tree
`5cccebbe6b4aa5342790feae9183b1be36505134`. Actual PR checkout was
`357c7531fd3d10364c515b8a45a0607bea30afa4`, with the same tree and parents
`b7561cc64e2a595ba9d99cbaf1cf2170f00ae2ee` /
`cbcf97e0dc7fbd56bc3052e3f8daa30475b36cad`.

It completed **all1,520 predictions and1,520 preservation checks** and then loaded
all four evaluation sources. It retained265,464,728bytes of private prediction
JSON. Its final public state is **`evaluation_failed`**, with `evaluation=null`
and `summary=null`; it is not relabelled successful.

| Original receipt | Exact identity |
| --- | --- |
| Artifact |13962156613 |
| ZIP |`repeat-context-incomplete-43256776331.zip`,361,958bytes |
| ZIP SHA256 |`cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e` |
| Only member |`report.json`,2,842,632bytes |
| JSON SHA256 |`568898b9c1f1fb6d5d2671e1805305eaa2939b2d1580175f0e2d6fc43e16c559` |

The public failure reported a `ValueError` at evaluation. A local diagnostic
replay reproduced **every original input and complete prediction file hash**,
passed the frozen prediction validator, and completed the unchanged evaluator.
It then reproduced `combined public metadata exceeds the report budget` at
`run_repeat_context._check_report_budget`.

The original public encoder indents every nested JSON level. A diagnostic
assembly with short placeholder source-receipt metadata already measured
33,531,531bytes as a whole pretty-printed report, exceeding the32,000,000byte
report limit and the guard's2,000,000byte failure reserve. That assembly's
standalone evaluation was28,676,772bytes, below the30,000,000byte evaluation
limit. The same semantic assembly encoded without indentation measured
16,508,270bytes as a whole report. These are diagnostic lower-bound sizes, not
the final source-complete recovery artifact's sizes or an accuracy claim.

An independently implemented model replay separately matched all1,520 input
hashes and all1,520 complete prediction hashes, including independent generation
of the new1,028 authored inputs. Its3,070 checks include the30 frozen source
hashes. Source-only independent parsing completed303,812checks, and original
receipt verification completed6,240checks. Those initial audits explicitly do
not claim that the failed original contains completed evaluation metrics.

## Recovery boundary

The repair is **public JSON serialization**. Keep every semantic evaluation
field, candidate decision, count, float, mask, cohort, limitation and source
receipt. Do not remove difficult cases, reduce output diagnostics, change the
model, widen any gate, choose a different phase, or retune the repeat prior.
Canonical JSON object key order is not a scientific variable.

The original selector, generator, source adapters, evaluator, runner, original
workflow, manifests and frozen protocol remain unchanged. The research test
inventory gains only the recovery contract file: verify the old inventory from
the frozen commit and report the expanded current inventory separately. Every
other original measured file must still match the first artifact's SHA256.
The failed original ZIP is an additional immutable recovery dependency.

Preserve the old pretty encoder for private input and prediction files. Public
metadata uses `json.dumps(..., sort_keys=True, separators=(",", ":"),
allow_nan=False)` plus a final newline. The byte checks apply to those actual
compact bytes. **The30MB evaluation,32MB public report,1MB metadata-component,
4MB private-case and512MB private-total limits stay unchanged.** Keep the2MB
reserve for bounded failures when attaching a complete public report.
The original standalone pretty-evaluation and summary component guards must also
pass; these are stricter than their compact sizes in this repair. Only the final
combined report's whitespace causes the declared recoverable failure.

The new recovery runner calls the unchanged original runner once with an explicit
evaluation dependency wrapper. The wrapper enters only after the original runner
has saved all predictions and loaded all four evaluation sources. It verifies
the original/current/private-file identities before calling the unchanged
evaluator once, and captures that returned semantic object privately. There is
no global monkeypatch and no duplicate scoring call. The original pass is allowed
to hit its known serialization-budget failure; recovery must verify that exact
failure condition, complete inference, preservation and all loader flags. It must
not treat an arbitrary source, inference, validation or evaluation error as a
formatting failure.

Before publishing any recovered score:

1. Verify exact original ZIP/member sizes, hashes, complete ordered1,520-case
   ledger, frozen commit/source identity, original failure stage and null summary.
2. Verify current scientific bytes against the original frozen receipt, handling
   only the administrative inventory extension as declared above.
3. Reproduce all planned observations and predictions with the original code
   and save them privately. The original runner still loads references only
   after every prediction is frozen. At wrapper entry, before scoring, verify
   **every input and complete prediction file SHA256 against both the original
   artifact and the recovery execution ledger**. Preserve original event identity,
   order, onsets, velocities and supplied span.
4. Keep the same source selection, canonical targets, four loader order and
   acquisition budget. No extra data selection or reference reload is needed.
   Record verified network transfers and cache hits as in the original runner.
5. Run the unchanged evaluator once and capture its result. After the original
   pass reports the exact known budget failure, validate preservation and the
   public metadata boundary again, enforce compact byte budgets and save the
   complete four-cohort result. Keep the original pretty-component evaluation
   hash definition and separately record actual compact report bytes/hashes.

The official recovery has its own workflow/run/artifact identity and source
commit. It references the failed original explicitly. No copied or guessed
metric can substitute for the evaluator. Any replay, source, shape, hash,
serialization, preservation or budget failure retains the planned population
with null aggregate results. No silent retry or selection among successful
subsets is permitted.

## Validation and interpretation

Small recovery contracts must show that compact and old pretty serialization
parse to equal JSON, retain every value, reject nonfinite numbers, preserve the
original private-file encoding, retain size limits and private-field filters,
and fail on changed source/input/prediction identities. They must exercise the
known-budget-failure recovery and reject unrelated failures. They are execution
contracts, not new model-performance tests.

The recovery workflow runs CPU-only with the same pinned dependencies and a
bounded wall time. It uses a **push** event limited to the existing
`research/repeat-context-20261113` branch and the four recovery implementation,
test, workflow and protocol files. Push path filtering evaluates the new push;
PR-wide changed-file filtering would also include earlier recovery files on a
later result-only update and is not used; see the official
[GitHub diff comparison rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#git-diff-comparisons).
Thus a later result-document commit
does not silently rerun the science. Save the exact ZIP
and report; verify all1,520 original/recovery hashes and independently audit
source, model and derived metric arithmetic before marking the PR ready.
The final-head repository checks and post-merge actual-main checks remain
required. The original failed attempt remains part of the permanent result.

This technical recovery adds no evidence about an accent model, inferred beat
clocks, written durations/rests or full notation. All scientific limitations and
four separate denominators from the frozen protocol remain in force.
