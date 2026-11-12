# #271 / #272 — waveform-gate edit attribution: completed CPU evidence

## Decision

The relative-soft pilot's gain is not explained entirely by deleting or splitting
predictions. Keeping ONLY its already-selected trailing-offset trims preserves
all onsets and note counts yet improves onset+offset F1 on the same 40 development
recordings. For the onset0.65 decoder, raw 37.2572% becomes tail-only 37.5350%
(+0.2778 percentage points), versus 37.6995% for the full policy.

Tail-only is a useful candidate for subsequent independent validation, not an
approved automatic correction. Its nine edits gain 11 annotator-specific matched
outcomes with zero lost matches and no per-annotator recording F1 regression,
but additionally remove **0.205 seconds of annotated-note time**. A tolerance-
based matching score can conceal boundary damage. The central written-rest versus
articulation question remains unresolved.

## Same-input results

All 40 original vocadito IDs completed, two unchanged Basic Pitch decoders,
four predeclared intervention arms and A1/A2. These are 40 reused DEVELOPMENT
recordings, not 640 independent samples or a new holdout. All 80 raw and 80 full
relative-soft predictions replay their historical count/hash and complete
annotator metrics/masks/occupancy. No threshold, soft cost, model, decoder,
candidate classification or scorer was tuned after outcomes.

F1 is averaged equally across recordings and the two annotators. Values below
measure performed notes, not published-score accuracy.

| Arm | Default onset F1 | Default onset+offset F1 | onset0.65 onset F1 | onset0.65 onset+offset F1 |
| --- | ---: | ---: | ---: | ---: |
| Raw | 49.1021% | 31.5831% | 54.1923% | 37.2572% |
| Full relative-soft | 49.2404% | 31.9991% | 54.3454% | 37.6995% |
| Tail-only | 49.1021% | 31.8482% | 54.1923% | 37.5350% |
| Complementary non-tail | 49.2404% | 31.7336% | 54.3454% | 37.4215% |

Tail-only's onset F1 is exactly raw for every case/annotator. Its default-decoder
offset gain is +0.2651pp; its onset0.65 gain is +0.2778pp. Full gains are +0.4160pp
and +0.4423pp. F1/matching effects are nonlinear; these arm deltas are NOT an
additive causal-contribution percentage and are not a post-hoc per-file ensemble.

### Edit attribution, onset0.65

| Arm | Changed parents | Tail / delete / split | Output notes | Offset matches gained / lost | Recordings better / worse / equal |
| --- | ---: | --- | ---: | --- | --- |
| Raw | 0 | 0 / 0 / 0 | 1,783 | 0 / 0 | 0 / 0 / 40 |
| Full relative-soft | 20 | 9 / 9 / 2 | 1,776 | 14 / 0 | 9 / 0 / 31 |
| Tail-only | 9 | 9 / 0 / 0 | 1,783 | 11 / 0 | 5 / 0 / 35 |
| Complementary non-tail | 11 | 0 / 9 / 2 | 1,776 | 3 / 0 | 5 / 1 / 34 |

There were no selected single-fragment onset trims in this sample. Non-tail
therefore means the selected deletions and splits here. The default decoder has
one additional deletion: full 21 changed parents (9 tail, 10 delete, 2 split),
2,086 to 2,078 notes; tail-only retains 2,086. Match gains/losses sum A1/A2
outcomes and are not counts of distinct physical notes across annotators.

The final column averages A1/A2 per recording. Individual results are also
retained: tail-only improves 4/40 A1 and 5/40 A2 recordings, worsens none in
either decoder. The complementary arm worsens one recording for BOTH annotators.
The full policy's averaged zero regressions still hides an A1 regression.

### Concrete disagreement retained: vocadito_7, onset0.65

| Arm | A1 onset+offset F1 | A2 onset+offset F1 |
| --- | ---: | ---: |
| Raw | 0.35955056 | 0.38095238 |
| Full relative-soft | 0.35555556 | 0.40000000 |
| Tail-only | 0.35955056 | 0.40476190 |
| Complementary non-tail | 0.35555556 | 0.37647059 |

This separates the harmful split from the offset benefit in the same recording.
It does not justify selecting whichever arm each ground-truth annotation likes.

## Time occupancy prevents a false zero-damage claim

Same inherited 10ms time grid, cropped between first and last annotated notes.
Totals are in seconds, averaged across A1/A2 totals, not quarter-note units.
Reference scope contains 547.0624 seconds of note time and 212.3500 seconds of
non-note time. All comparisons below use onset0.65 and the same raw control.

| Arm | Wrongly covered reference gap | Wrongly unoccupied reference note | Gap time restored vs raw | Additional note time removed vs raw |
| --- | ---: | ---: | ---: | ---: |
| Raw | 32.175s | 101.7024s | 0 | 0 |
| Full relative-soft | 30.480s | 101.9874s | 1.695s | 0.285s |
| Tail-only | 31.470s | 101.9074s | 0.705s | 0.205s |
| Complementary non-tail | 31.185s | 101.7824s | 0.990s | 0.080s |

The default decoder's tail-only restores the same 0.705s but removes an additional
0.225s of annotated-note time (full 0.305s, non-tail 0.080s). Tail-only avoids
deletions/splits and observed F1 regressions; it does NOT dominate all metrics or
eliminate boundary loss. No universal safety or real written-rest claim follows.

## Execution, failure preservation and exact recovery

Original [run 43178487837](https://github.com/JDeun/audio-score-tool/actions/runs/43178487837)
failed the replay guard for vocadito_11 before that recording's neural inference.
The other 39 cases completed with exact historical raw/full controls. Its null
aggregate and failure receipt remain unchanged. Head `f03152cef4e5e12e3beb8675b77ef005fe51d905`,
actual PR checkout `55b4fb57f29b6753e04319ab5e9d27bd80aa002d`.

The bounded [recovery run 43179593722](https://github.com/JDeun/audio-score-tool/actions/runs/43179593722)
succeeded, job 131052048356. Head AND actual push checkout:
`5426e7f1a0dfb5c8662f35b9d08996b44085ce2b`. It reused all 39 successful case objects
value-exact and performed exactly **one** new neural inference, for vocadito_11.
Across the two attempts each recording received one completed inference for this
study. The first attempt remains failed; the second completes the combined fixed
cohort with explicit per-batch provenance.

Remote recovery observed reference-level difference `3.552713678800501e-15` dB;
the actual close/open thresholds differed by exactly zero. All 1,299 frame
decisions matched the archived-threshold state machine, with 143 quiet cells.
Thus the old strict scalar equality would reject this metadata-only roundoff
despite identical thresholds, gate decisions and musical outputs. The guard now
permits at most 1e-12 scalar difference ONLY with exact full-mask parity and exact
event/metric replay. The change does not tune the gate or establish which CPU
instruction caused the numerical difference. See the frozen
[recovery addendum](AUDIO_GATE_ATTRIBUTION_RECOVERY_2026-11-12.md).

The independent zero-width RMS-cell bug at exact hop multiples was repaired in
the new envelope. All 40 historical waveforms retain bit-identical new-versus-
legacy envelopes; none of this ablation's outcomes derives from that repair.
No archived scientific source file was modified.

## Durable receipts and independent audit

Final artifact **13926136473**, 53,466 bytes, retained in
`receipts/waveform-gate-attribution-43179593722.zip`.

- ZIP SHA256: `b66348c2d0be17874910f46659bdc25f2b0674bcbf9db9647ff857e8c75f6929`.
- Sole `report.json`, 1,083,693 bytes, SHA256:
  `90f0f8cd6dd891456e28ecbf98f7af5d58f377ceac1d1959e9ed0c22204b2eee`.
- Failed-attempt ZIP/report identities remain in the recovery addendum and
  [receipt index](receipts/README.md). Historical #239/#270 ZIPs are retained too.

A separate standard-library audit, without experiment aggregation helpers,
verified the Actions ZIP digest, 40 unique completed sources, exact 39-row reuse,
one new pass, 1,280 metric/mask/F1/transition identities, 160 raw/full control
replays, 80 disjoint parent partitions and 19 executed-source hashes. It rebuilt
all means, per-annotator regressions and occupancy totals within 1e-12 absolute
arithmetic tolerance. The receipt contains no raw audio, MIDI, source events or
model arrays. Hash/mask arithmetic cannot independently rematch source notes,
reconstruct event streams or prove listening/notation correctness. Full event
identity and gate-mask parity are protected by the frozen execution and contracts.

147 local and remote new/recovery contract tests passed; measured code lint and
compile checks passed. A separate full-CI failure exposed an old test asserting
exactly 25 research files. The follow-up changes that assertion to verify actual
manifest membership, no duplicate/overlapping files and exhaustive discovery;
it does not skip tests or alter runtime dependencies. All nine scope tests pass
locally. Final-head repository `verify` status is tracked on
[PR #272](https://github.com/JDeun/audio-score-tool/pull/272), separately from this
successful scientific run. Historical CI failures are preserved.

## Next research decision

Carry frozen tail-only forward as a conservative candidate alongside raw and
full controls on separately reserved data. Do not calibrate thresholds on these
40 reused recordings and call it untouched validation. A score-aligned mono stem
set with explicit written-rest versus articulation labels is still needed before
connecting this gate to nASAP rhythm decoding or claiming final-score improvement.
Mixed/separated audio, inferred voices, MusicXML/PDF readability and human editing
time remain unmeasured. Product/default/automatic correction is not activated.

Source attribution: Bittner, Pasalo, Bosch, Meseguer Brocal and Rubinstein (2021),
https://zenodo.org/records/5578807. Protocol and limitations remain tied to
#271, #269, #249 and #259.
