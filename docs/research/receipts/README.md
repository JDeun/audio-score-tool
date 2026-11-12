# Durable waveform-gate experiment receipts

These ZIP files retain the **exact historical GitHub Actions artifact bytes**.
They preserve derived evidence after the remote artifacts expire; they are not new
experiments and do not change a historical result or its protocol.

| File | Run / artifact | ZIP bytes | Only allowed member | JSON bytes |
|---|---|---:|---|---:|
| `basic-pitch-decode-42954128502.zip` | [42954128502](https://github.com/JDeun/audio-score-tool/actions/runs/42954128502) / 13825524844 | 41,870 | `basic_pitch_decode.json` | 290,670 |
| `waveform-gate-rest-43172631193.zip` | [43172631193](https://github.com/JDeun/audio-score-tool/actions/runs/43172631193) / 13922463947 | 85,041 | `report.json` | 1,295,758 |

## Immutable identities

Baseline ZIP SHA-256:
`6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0`.
Baseline JSON SHA-256:
`dff293dc36a6642141cd235d8d958770e01d4bcd90f6f67c2ae0f82ae465309c`.

Waveform-gate ZIP SHA-256:
`ce7fb57fa4da65ee320f5c5e14e58d61d6a19bbccedd303143540de239a56325`.
Waveform-gate JSON SHA-256:
`e807cee43b21425738ae1fea206f61c86eeb4cbbfd4cfd113c4bb226cdf2461d`.

These are the digests recorded in the original
[gate protocol](../AUDIO_GATE_REST_PROTOCOL_2026-11-12.md) and
[completed result](../AUDIO_GATE_REST_RESULTS_2026-11-12.md). Do not recompress,
reserialize, edit or replace the files under these names. A later measurement
must receive its own receipt and identity.

## Contents and boundaries

The archives contain only JSON metadata: dataset/model/source fingerprints,
runtime settings, source IDs, scalar metrics and counts, per-reference binary
matching masks, edit counts, timing aggregates and provenance. They contain no
original WAV, MIDI, lyrics, score, event arrays, neural output arrays or model
weights. A model `weights` object records byte count and hashes, not weights.
Matching masks reveal which indexed reference outcomes matched; they do not
encode note pitches or event times.

The baseline records the original Basic Pitch decoding comparison. The gate
report records all 40 reused development recordings, two decoders, five gate
conditions and two human annotators. Performed-note gaps are not explicit
written rests. Neither these receipts nor a passing audit approves product
automatic correction or establishes independent generalization.

## Offline verification

From the repository root:

```bash
python -m scripts.audit_waveform_gate_receipts
```

The verifier checks exact ZIP sizes and SHA-256 digests before reading a single
allowlisted JSON member, then verifies its uncompressed size and digest. No
member is extracted. It rejects missing files, symlinks, modified archives,
incomplete or duplicate cases, changed provenance and inconsistent arithmetic.
It also checks the current bytes of the eight frozen historical source files.

The arithmetic audit covers 80 raw prediction count/hash replays, 320 baseline
metric replays and 1,600 reference-mask/F1/gain/damage identities. It verifies
source and model identity, complete arm/annotator coverage, note-count changes,
occupancy conservation and monotonicity, hard/soft containment, gain controls,
and the aggregate summary using the historical `summarize` implementation.
All numeric comparisons use absolute tolerance at most `1e-12`. Per-note F1
was historically rounded to eight decimal places; its reconstruction preserves
that rounding before comparison. The audit covers the two baseline decoder
arms reused by the gate experiment; it does not re-evaluate the baseline's
other decoding variants or bootstrap intervals.

This verifies stored receipt arithmetic, byte provenance and frozen code
identity. It does **not** download musical sources, rerun a model, independently
rematch predictions against annotations or reconstruct the underlying events.
The NPZ output-file hash can differ between original model executions; the
auditor instead checks the historical canonical event fingerprint and the
reproduced prediction-MIDI hash, as well as the reported raw metric values.

`load_receipts(repository_root)` returns the two hash-verified JSON objects for
further metadata analyses. `audit(repository_root)` also performs the arithmetic
and frozen-source checks. Downstream analyses must preserve the development-data
and annotation limitations of the original report.

## Completed attribution study and preserved failed attempt

The original two-receipt verifier above intentionally keeps its immutable input set.
The following additional ZIPs preserve the later study and its recovery chain:

| File | Run / artifact | ZIP bytes | JSON bytes | Outcome |
| --- | --- | ---: | ---: | --- |
| `waveform-gate-attribution-incomplete-43178487837.zip` | [43178487837](https://github.com/JDeun/audio-score-tool/actions/runs/43178487837) / 13925346757 | 50,470 | 1,041,745 | 39 scored, one failed, null aggregate |
| `waveform-gate-attribution-43179593722.zip` | [43179593722](https://github.com/JDeun/audio-score-tool/actions/runs/43179593722) / 13926136473 | 53,466 | 1,083,693 | 39 exact reused rows plus one new inference; complete 40 |

Both have exactly one `report.json` member. Failed ZIP SHA256:
`40df7f512ebf0680af7393ba0bf8c413dc9db716572803e162f74c9bfd4db388`;
failed JSON SHA256:
`3391f88dd327d0752cab62cc788d52321e5bf07c5ab28feffef695768675a088`.
Final ZIP SHA256:
`b66348c2d0be17874910f46659bdc25f2b0674bcbf9db9647ff857e8c75f6929`;
final JSON SHA256:
`90f0f8cd6dd891456e28ecbf98f7af5d58f377ceac1d1959e9ed0c22204b2eee`.

The [complete result](../AUDIO_GATE_ATTRIBUTION_RESULTS_2026-11-12.md) records the
independent 40-case arithmetic/provenance audit. This final report's current head
identifies recovery orchestration; its `recovery` field identifies the original
execution of the 39 reused case objects. The original failed run remains failed.
All four ZIPs contain derived metadata only, not original media, note events,
model outputs or weights. The frozen protocol and recovery addendum are unchanged.

## Completed KRAISLER transfer pilot

`kraisler-gate-43184102838.zip` retains artifact **13927279033** from
[CPU run 43184102838](https://github.com/JDeun/audio-score-tool/actions/runs/43184102838).
The [complete result](../KRAISLER_GATE_RESULTS_2026-11-12.md) covers all six
preselected dry violin recordings, two decoders and four arms, with no reference-
guided retuning or repeated vocadito inference. Tail-only's negative transfer and
all time-occupancy damage are retained.

- Exact ZIP: **16,111 bytes**; SHA256
  `ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e`.
- Sole member `report.json`: **155,591 bytes**; SHA256
  `e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754`.
- PR head: `faac53d0b9b63d8b8420e8fdb788dd3ec4cf4cda`; actual PR checkout:
  `7491b822c2d0d8cfe82193dea9c7135b91ebec2a`.
- Complete: six recording-level predictor calls, 48 scored conditions and 947
  reference notes. Six structural XML/beat audits remain explicitly unaligned.

This fifth receipt contains derived metadata only. Its dataset range/member
hashes do not claim to verify the complete source ZIP's MD5. The original
two-receipt verifier above is unchanged and does not claim to audit this new
receipt. No WAV, XML, source CSV, event arrays or weights are republished.

## Completed KRAISLER source correspondence

`kraisler-alignment-43201534121.zip` preserves artifact **13935537018** from
[CPU run 43201534121](https://github.com/JDeun/audio-score-tool/actions/runs/43201534121).
The [completed result](../KRAISLER_ALIGNMENT_RESULTS_2026-11-12.md) records all
six diagnostics, including 1/6 source-clock admission, 225/947 primary reference
correspondences, 137 stable correspondences, and unresolved matching transitions.
Completion does not mean every source was admitted.

- Exact ZIP: **25,366 bytes**; SHA256
  `6f8af87bef6fa8febc977e037130b520d05d0dab8df815e3684ae6239d475005`.
- Sole member `report.json`: **543,226 bytes**; SHA256
  `ec5048b11ede7364ca5c68e9f7fb6f4889ed818d881f502aa34726ba54335f7a`.
- Frozen head: `c209ac699add448873d0eb15761fbeae3feaccce`; actual checkout:
  `ff26548443286772df973340ea676bfef82442b3`; both tree:
  `7bcc3794a02bfb4990c08fc05e243ff111148cce`.
- Thirty original metadata members verified, seven HTTP ranges / 776,325 bytes,
  zero audio loads and zero new neural inferences. Previous gate masks and
  source identities remain unchanged.

Two derived post-run audit JSON files supplement the exact sixth ZIP:

| File | Scope | SHA256 |
| --- | --- | --- |
| [kraisler-alignment-audit-43201534121.json](kraisler-alignment-audit-43201534121.json) | Independent membership/conditional arithmetic, aggregates and input/code identity | `17cab647d54c1053ed9508574b51f9c1a2cbdc07f0b1eea77ae60279b96c8bfc` |
| [kraisler-alignment-postrun-audit-43201534121.json](kraisler-alignment-postrun-audit-43201534121.json) | Exact-tick reversal diagnostics, independent 19 pair reconstruction and rest/context checks | `0f3f093835936bc6fcff54645be8a6083151bee4d4d2e1fbf04738e7809e647a` |

These are verification summaries, not newly measured gate outcomes or modified
historical artifacts. No original XML/CSV/Match, event arrays or model weights
are included. The original two-receipt verifier above retains its frozen input
set and does not claim to audit this later study. All source-consistency and
annotation limitations remain explicit in the result report.

## Completed KRAISLER local timing and duration/rest ranges

`kraisler-expressive-43210425240.zip` preserves exact artifact **13939819598**
from [CPU run 43210425240](https://github.com/JDeun/audio-score-tool/actions/runs/43210425240),
attempt 1. The [completed result](../KRAISLER_EXPRESSIVE_RESULTS_2026-11-12.md)
records six completed diagnostics, 373/607 locally supported beat cells,
394/947 primary tempo20 pairs, 295 stable pairs, duration/rest ranges and
unchanged unresolved gate transitions. Coverage is not a model accuracy.

- Exact ZIP: **72,066 bytes**; SHA256
  `e51fae082cf3c97240a9746cf2ba2214923ce30555ae2f70130f6043cffd478f`.
- Sole member `report.json`: **1,546,689 bytes**; SHA256
  `32005007594058ee941fd367aab5cd0ad093cef130fc38a23f47912e36f580bc`.
- Frozen head: `18e358645fcec5c5314bb69f2725d9bc3be984f7`; actual checkout:
  `4a9f603d983eb0a576795bffd8e9f4fdb2254a77`; both tree:
  `7d16179315f8c62ef18f527db2c38fe942d550e1`.
- Thirty original metadata members verified, seven HTTP ranges / 776,325 bytes,
  zero audio loads and zero new neural inferences. All six historical global
  analyses, gate masks and source identities remain unchanged.

Two derived post-run audit JSON files supplement the exact seventh ZIP:

| File | Scope | SHA256 |
| --- | --- | --- |
| [kraisler-expressive-audit-43210425240.json](kraisler-expressive-audit-43210425240.json) | Independent standard-library provenance, partitions, conditional/aggregate arithmetic, duration count/sum means and rest decomposition | `5ac257612485c4512e67ad812798a507b9c9d1ce386a4f9ab5feee7e5272831c` |
| [kraisler-expressive-source-audit-43210425240.json](kraisler-expressive-source-audit-43210425240.json) | Independent local-clock, pair-identity, duration and interval reconstruction, reusing only frozen source parsers/eligibility and symbolic normalization | `123b51ded6e5336fb235e04d9ae69c16674545ddb9f2ecc3fb4b7f8be1fa51a4` |

Both audits passed. They are verification summaries, not independent acoustic
annotations, new gate outcomes or altered historical artifacts. The receipt's
`onset_residuals_pulse_fraction` values are dimensionless despite inherited
`_s` statistic key names; stable-scope residual statistics are explicitly not
computed. No original XML/CSV/Match, note-event arrays, audio or weights are
republished. The original two-receipt verifier above retains its frozen input
set and does not claim to audit this later study.
