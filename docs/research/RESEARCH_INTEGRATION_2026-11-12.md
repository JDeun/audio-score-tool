# Research integration, 2026-11-12 — code inclusion is not product promotion

User requested consolidation after many stacked draft experiments. #266 integrates research scripts, regression tests and positive/negative result reports into main, while retaining main's application changes and protected verify gate. No src/desktop/pyproject.toml/uv.lock modification, automatic model switch, rest deletion or algorithm activation is intended.

## Included evidence families

- #239: CPU vocal recovery and Basic Pitch decoding (independent validation still needed).
- #241–#244: symbolic models, selection controls and vocal candidate headroom; includes negative Qwen/LSTM findings.
- #246–#248: pYIN/DSP pitch, octave and offset evidence; no blanket correction approval.
- #250–#251: measure-constrained notation and performed/notated duration pilots.
- #253–#258: drum events/audio, tempo-only patterns, multiwindow consensus and Beat This comparison. BPM, meter and downbeat are different metrics.
- #260–#261: half/double pulse units and time-preserving export; automatic convention selection remains unapproved.
- #262–#265: real aligned piano duration/endpoint ablations and joint rhythm decoding; provided clock/voice/chord context and limited coverage remain explicit.
- #267: DEVELOPMENT-only observed quiet-core preservation; rest benefit and normal-note damage are reported separately. #265 validation music is not reused for tuning.

Historical PR heads and their result files are the immutable evidence. Merge status is repository organization, not scientific acceptance. Reports with earlier wording 'keep draft/main unchanged' describe the experiment snapshot, not the user's later integration authorization. Issues #249/#259 remain open. Other-session product PR #236 is not part of this consolidation.

## Testing without changing the product runtime

CI runs all test files as an exhaustive, disjoint partition checked by scripts/run_ci_test_scope.py and its tests. Product tests run with uv.lock unchanged. The25 newly integrated research test files run in a temporary Python3.11 overlay with their numerical test dependencies. Neither suite is silently skipped; both must succeed in the same required python job. No learned-model or dataset downloads occur in these offline tests. Dataset/model inference is an explicit research workflow, not normal product CI.

Two immutable archival files contain import order that conflicts with the repository's I001 style rule: scripts/nasap_joint_rhythm.py and tests/test_nasap_joint_rhythm.py. Historical replay guards compare their literal bytes. Narrow nested Ruff exceptions preserve those two files only; every functional rule and all other files' import rules remain enabled. This is not a general lint downgrade, and avoids silently invalidating frozen evidence.

Research source datasets/checkpoints have independent license and redistribution terms. In particular (n)ASAP's CC BY-NC-SA4.0 data is not bundled here or cleared for commercial use. Only our scripts/tests, derived receipts and reports are integrated. Scores described as conditional notation accuracy are not full audio-to-score, rendering or user-editing-time approval.

## Acceptance boundary

Main merge requires the existing full verify gate, including product Python/frontend/Tauri checks as selected by CI, plus exhaustive research regressions. Main's existing #257 product fix must remain. Legacy research workflows are opt-in; do not automatically rerun long model studies simply because this archive is merged. Preserve source hashes and negative outcomes. Future product wiring requires its own held-out audio/notation and regression evidence.
