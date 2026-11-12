# #271 / #272 — bounded recovery of the one failed replay

The original [frozen protocol](AUDIO_GATE_ATTRIBUTION_PROTOCOL_2026-11-12.md)
and edit-selection/envelope modules remain unchanged. This addendum records an
execution guard repair; it does not select a musical method using partial scores.

## First attempt remains a failure

[Run 43178487837](https://github.com/JDeun/audio-score-tool/actions/runs/43178487837),
job 131048408057, head `f03152cef4e5e12e3beb8675b77ef005fe51d905`, checkout
`55b4fb57f29b6753e04319ab5e9d27bd80aa002d`, scored 39 of 40 cases. `vocadito_11`
failed the exact relative-gate scalar/count guard before its neural inference.
The full-cohort summary is null. The failed run is not relabelled successful.

Artifact 13925346757 is retained byte-for-byte as
`receipts/waveform-gate-attribution-incomplete-43178487837.zip` (50,470 bytes).
ZIP SHA256: `40df7f512ebf0680af7393ba0bf8c413dc9db716572803e162f74c9bfd4db388`.
Its only member, `report.json` (1,041,745 bytes), has SHA256
`3391f88dd327d0752cab62cc788d52321e5bf07c5ab28feffef695768675a088`.

An independent metadata audit checked the 39 completed rows, including 1,248
metric/mask/F1/transition identities, 156 exact raw/full control replays and 78
disjoint parent partitions. It did not compute a selected-source headline score
or replace the failed recording. This verifies metadata, not independent audio
inference or reconstructed note events.

## Diagnose without changing gate decisions

The original runner compared computed RMS/percentile decibel scalars with Python
`==`. Local source-only recalculation with the original checksum-pinned WAV,
NumPy 1.26.4 and SoundFile 0.13.1 reproduces all three historical scalars exactly
for vocadito_11, 1,299 frames and 143 quiet frames. This does not reveal the remote
runtime's actual mismatching values; the first guard did not record them. The
new guard therefore records actual/archived deltas and admits recovery ONLY if:

1. Total and quiet frame counts remain exact.
2. Reference, close and open levels differ by at most `1e-12` dB, with zero
   relative tolerance. Larger differences fail with a diagnostic.
3. Running the unchanged hysteresis/hold state machine on the CURRENT levels
   with the ARCHIVED close/open scalars produces a bit-identical FULL Boolean
   mask to the current gate. Even a tiny scalar difference that changes a single
   decision must fail.
4. Legacy/new RMS envelopes remain bit-identical for the recording, and all raw
   and full relative-soft prediction hashes/counts, F1 values, reference masks,
   transitions and occupancy still exactly replay #270 after inference.

The gate itself still uses its recomputed original thresholds; this verification
does not substitute archived thresholds into candidate generation. No gate
parameter, soft cost, edit classification, model, decoder, scorer or musical
candidate is changed. A numerical metadata allowance is not permission to alter
a gate decision or a note output. Until the recovery executes, the remote cause
remains a hypothesis rather than an observed floating-point diagnosis.

## Resume only the missing source

`--resume-incomplete` accepts only the exact retained ZIP and JSON above. It
checks the declared head/checkout, corpus/model/runtime/settings, 40 unique
planned identities and the single declared failed ID. Frozen components other
than runner orchestration must retain their original source hashes.

Copy all 39 successful case objects value-exact, including their original
timings, masks, hashes and metrics; do not rerun them or synthesize replacements.
Only vocadito_11 receives one new Basic Pitch CPU inference. The new report must
state the reused IDs, newly inferred ID, original failed row, prior run/head/
checkout and ZIP/report/source hashes, and planned/executed new neural passes.
Its top-level head describes recovery orchestration, not the execution origin
of the 39 inherited rows. Compute the complete aggregate only after all 40
fixed cases have passed. Compare reused rows directly with the preserved receipt
in the independent final audit.

The workflow has one branch-scoped recovery push trigger for its own file and
retains manual execution. Later documentation-only commits do not rerun models.
No successful experiment or product source/default is modified. All original
development-data, performed-gap-versus-written-rest and product-approval limits
continue to apply.
