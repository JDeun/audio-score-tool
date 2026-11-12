# Frozen joint decoder on new compositions — preregistered follow-up

Related #249/#259/#264. Base #264 head f70581b72e037e44b156c1863fb8e8938e94341b.
Research only: no main merge, product/default/automatic-score/other-session changes,
GPU, learned models/training, paid APIs, external credentials or new audio inference.

## Question

Does the SAME joint voice/rest/measure decoder that improved conditional note
accuracy on five old compositions improve on genuinely different compositions?
Does its fixed rest cost preserve actual rests, rather than merely reduce gaps?
This is a frozen validation, NOT a rest-objective tuning experiment. A result on
new compositions does not remove the privileged input/context limitations.

## Immutable dependencies and source

Lock #264 artifact13911212291: ZIP SHA256
224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4;
report SHA256281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59.
Compare the four inherited script bytes against that artifact before execution:
nasap_joint_rhythm.py, nasap_keyoff_paired.py, nasap_duration_probe.py and
audit_nasap_duration_source.py. Decoder, lattice, parser, cost, evaluator and
source-clock logic remain unmodified. Existing tests are reused unchanged.

Official (n)ASAP source CPJKU/asap-dataset at
4097b45757bed854818cf87e77b92323ebf90615; metadata Git blob
f9b655ca92b3d88febab09763e7ed3b74c2c7878 and previous metadata SHA checked.
Attribution: Foscarin et al., ASAP, ISMIR2020; Peter et al., Automatic Note-Level
Score-to-Performance Alignments in the ASAP Dataset, TISMIR2023,
doi10.5334/tismir.149. CC BY-NC-SA4.0. This is isolated research evidence,
not commercial licensing clearance; no original musical data redistributed or
bundled into the product. Publisher annotation and parser limitations remain.

## Selection fixed BEFORE seeing new musical data

1. Exclude ALL twelve prior planned compositions, including old failures, using
   normalized composer+title, and shared XML/MIDI-score/folder paths. This excludes
   another performance or repeat-expanded variant carrying the same catalog work.
2. Also exclude Bach Fugue_bwv_846 and Fugue_bwv_848, inspected earlier for schema.
3. From robust_note_alignment=1 rows with required paths, sort by
   SHA256('nasap-joint-holdout-v1/'+midi_performance). Choose first24 unique
   compositions, at most3 per normalized composer; no shared score paths.
4. Persist all24 IDs and composer/title pairs BEFORE reading their note/beat/XML
   files. No score-based preselection, no outcome-guided replacement. Nonadmitted
   signatures, malformed/unhandled ties, missing alignments, budget limits and
   unavailable files remain in the full coverage denominator.

This is composition-disjoint relative to the previous study, NOT performer-disjoint,
not an independent dataset, not representative of pop/rock, and not necessarily a
standard dataset test split. No statistical-significance claim is planned.

## Same conditional experiment

Use inherited fixed annotated beat8..40 window and same admission: simple
constant2/4,3/4,4/4; consecutive two-full-measure voice blocks; complete unique
aligned note inventory, equal-duration chord groups, exact explicit XML occupancy,
no unsupported grace/external-edge tie structures. All restrictions are unchanged.
The restricted parser is NOT repaired to admit new successful cases in this trial.

All six arms receive the SAME supplied annotated beat clock, correct quarter unit,
bar boundaries, reference voice/chord membership and complete note inventory:
- publisher sustain and original key-release inputs, kept separate;
- independent note selection;
- joint structure (non-overlap plus spellable rest partition);
- joint structure + the PREVIOUS fixed rest-token cost.
No reference-guided best input/method selection. Raw performed timing/pitches and
note identity unchanged. Note/rest truth is for admission/context and evaluation;
actual target note values/rest locations are not passed to the decoder.

Known inherited constants:48ticks/quarter; onset radius0.25quarter; onset sigma0.10;
rest cost0.20; unchanged duration vocabulary, latent duration ratios and unary costs.
Unit inference, AMT errors, automatic voices/chords or audio beat prediction are
NOT tested. The same best-case structural context is given to every comparator.

## Outcomes and interpretation

Primary: exact written onset+duration using inherited1/96quarter tolerance,
compared on identical blocks. Retain note correctness masks, paired fixes/damage,
per-composition direction, micro and equal-composition means. Keep all unavailable
sources/blocks visible; if any arm lacks a block, provide an explicit all-six-arm
common-block comparison as well as coverage. Do not silently shrink denominators.

Co-primary safety concern: EXPLICIT XML semantic-rest precision/recall/F1 with the
same strict boundary tolerance. Rests absent in both reference and output have
undefined F1, not100%. Full measure sums and non-overlap are structural checks,
not proof of accuracy.

Additional descriptive diagnostics, computed from the SAME frozen predictions:
- overlap duration in quarter units between predicted and actual rest intervals;
- falsely silenced notated-note time and erased reference-rest time;
- inner-bar crossing TP/FP/FN/TN, not a negative-class-dominated agreement score.
These diagnostics do not replace exact rest F1 or introduce a new scoring loss.
They test whether boundary mismatch alone explains low exact-rest recovery.
No actual exporter/tie spelling, printed score, listening or editing-time claim.

If note gains repeat on new compositions but rest preservation deteriorates, record
that tradeoff and do NOT approve the rest-cost setting. Only the conditional
note-recovery hypothesis is supported, not full-score quality or deployment.
If gains disappear or are concentrated in one work, preserve that negative result.
No tuning on these new validation results. Any subsequent rest-objective changes
must use separately designated development data and a newly reserved evaluation.

## Execution

Standard Ubuntu CPU/Python3.11, pinned mido1.3.3, pytest8.4.2, ruff0.16.6;
read-only contents/actions permissions, no persistent credentials. One20min job.
Download only the small previous artifact and pinned individual dataset files.
Inherited max4MB/file and40MB total source-byte limits, in-memory caching only;
no full dataset/audio archive. Twenty new offline tests plus81 inherited tests
passed locally before real-data execution; remote checks remain authoritative.

Store source/protocol/code hashes, selection manifest, all statuses, per-block
masks/counts, rest occupancy and coverage. Upload only derived receipt and our code,
not original notes, XML, MIDI or audio. Report-only pushes must not retrigger
inference. Keep the PR draft and #249/#259 open regardless of outcome.
