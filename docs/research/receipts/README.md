# Durable waveform-gate experiment receipts

These ZIP files retain the **exact historical GitHub Actions artifact bytes**.
They preserve derived evidence after the remote artifacts expire; they are not new
experiments and do not change a historical result or its protocol.

| File | Run / artifact | ZIP bytes | Only allowed member | JSON bytes |
|---|---|---:|---|---:|
| `basic-pitch-decode-42954128502.zip` | [42954128502](https://github.com/JDeun/audio-score-tool/actions/runs/42954128502) / 13825524844 | 41,870 | `basic_pitch_decode.json` | 290,670 |
| `waveform-gate-rest-43172631193.zip` | [43172631193](https://github.com/JDeun/audio-score-tool/actions/runs/43172631193) / 13922463947 | 85,041 | `report.json` | 1,295,758 |

## Immutable identities

The [completed frozen-boundary diagnosis](../NOTE_BOUNDARY_DIAGNOSTICS_RESULTS_2026-11-13.md)
preserves `note-boundary-diagnostics-43370790419.zip` from
[run 43370790419](https://github.com/JDeun/audio-score-tool/actions/runs/43370790419),
artifact 14012856593: **631,149 bytes**, SHA256
`43b439e665eb470ec1b24179697cc99d2733fecb6122d1da6a77125d8e3ccf31`.
Its exact five members are `synthetic.json` (2,847,165 bytes), `vocadito.json`
(1,625,622 bytes), `replay-audit.json` (282,759 bytes), `diagnostics.json`
(8,483,795 bytes), and `audit.json` (765,544 bytes). The old private replay audit
passes 42,867 checks and the new independent private boundary audit 208,855.
The separate `note-boundary-postrun-audit-43370790419.json` is 9,145 bytes,
SHA256 `02e5f32a52118fda64f0bc937c8d73d6d4908684dba82e4e5f41f09b1a921c86`,
with 209,349 public metadata/owned synthetic checks. It does not reconstruct
unpublished actual-event residuals, pooled quartiles or full synthetic paths.
The ZIP retains unchanged scientific outputs and new endpoint/overlap summaries,
including owned synthetic truth/events and local boundary-state samples; no
actual WAV/reference/event arrays or full private F0/path arrays are published.

The [completed factor diagnosis](../NOTE_STATE_FACTORS_RESULTS_2026-11-13.md) preserves
`note-state-factors-43344373779.zip` from [run 43344373779](https://github.com/JDeun/audio-score-tool/actions/runs/43344373779),
artifact 14001615849: **272,995 bytes**, SHA256
`b20495c8936f8b4263daf2660fb57ba282264904d6b30dda076463cc6e3881f6`.
Its only members are `synthetic.json` (2,847,165 bytes), `vocadito.json` (1,625,637 bytes)
and `audit.json` (282,759 bytes). The original private-file audit passes 42,867 checks.
`note-state-factor-postrun-audit-43344373779.json` (180,997 bytes; SHA256
`8b58d7d5b40c6c52630842cbb14d46ed0b10df99b6732a0a8233909315fd9399`)
records 125,891 independent metadata and owned-synthetic assertions. This ZIP includes
**owned authored synthetic truth/prediction events**, but no actual recording events,
WAVs, annotation contents or full private F0/path arrays. The primary improvement does
not approve a product default; offset match losses and six merged controls remain visible.

The [completed note-state comparison](../NOTE_STATE_HMM_RESULTS_2026-11-13.md)
preserves `note-state-hmm-43336542480.zip` from
[run43336542480](https://github.com/JDeun/audio-score-tool/actions/runs/43336542480),
artifact13996459905: 73,141 bytes, SHA256
`46ea77a90750172a905750599db3b419f09d70d165ef0be221e0004b8cd61b26`.
Its only members are `vocadito.json` (709,930 bytes) and `audit.json` (15,062 bytes).
The separate `note-state-postrun-audit-43336542480.json` records independent
metadata/provenance verification of the downloaded ZIP. The study is negative;
successful execution and audit are not a quality approval.

The note-state follow-up also preserves `dsp-note-baseline-42989661618.zip`
from [run 42989661618](https://github.com/JDeun/audio-score-tool/actions/runs/42989661618),
artifact13841810951: 27,672 bytes, SHA256
`6bc477457a89403c7bb18f331d862555f4d963db4a227472bb19d63644d39541`.
Its only members are `synthetic.json` (12,284 bytes) and `vocadito.json`
(162,070 bytes). They contain the original metadata, not raw F0 or note arrays.
The [note-state protocol](../NOTE_STATE_HMM_PROTOCOL_2026-11-13.md) uses this
unchanged archive for historical baseline parity before accepting its comparison.

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
matching masks, edit counts, timing aggregates and provenance. Except for the explicitly owned synthetic events and boundary samples in the factor/boundary studies above, they contain no
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

## Completed KRAISLER original-waveform boundary audit

`kraisler-boundaries-43222529760.zip` preserves exact artifact **13944769055**
from [CPU run 43222529760](https://github.com/JDeun/audio-score-tool/actions/runs/43222529760),
attempt 1. The [completed result](../KRAISLER_BOUNDARY_RESULTS_2026-11-12.md)
records all six original WAVs, 947 onset/offset/midpoint populations, frozen
gate replay, unchanged rest projections and four selected historical watchlists.

- Exact ZIP: **111,438 bytes**; SHA256
  `ead70a5ea7d5826d24d3ac470b9e5d154004c332ffea678dbc9b82c8a9ff42fd`.
- Sole member `report.json`: **813,260 bytes**; SHA256
  `9177964bff5d848610a6ae93f2a509f0cb4a3608ca86df9ff53f35760668feba`.
- Frozen head: `116a68599c9358dc0dc9d8590edbfb1f696307b4`; actual checkout:
  `9a812a6262b4be398ab245af207890af6cf7f60c`; identical tree:
  `a36f8b3ba364da6d9a7b3c31604a44f4cc516446`.
- 36 unique original members, 14 HTTP206 ranges / 29,116,178 bytes, six original
  PCM16/44.1kHz WAVs totaling 403.23381s. No new model inference. All six prior
  gate scalars/masks and full expressive analyses reproduced exactly.

Two derived audit JSON files accompany this exact eighth ZIP:

| File | Scope | SHA256 |
| --- | --- | --- |
| [kraisler-boundaries-audit-43222529760.json](kraisler-boundaries-audit-43222529760.json) | Standard-library provenance/arithmetic, original annotation-context memberships, all case/cohort statistics, rest conservation and historical transitions | `f2b413b424964145bb840a7c828cc520fb05df004a9fe64bb9bbde5e0b029009` |
| [kraisler-boundaries-source-audit-43222529760.json](kraisler-boundaries-source-audit-43222529760.json) | Independent PCM/RMS/gate/FFT and full-window/context reconstruction, rest support/interval/frame masks; frozen symbolic parsers reused explicitly | `ebc582dcc5b7e08ce7ba4edeb36695d980991159bc0d73544d4d02060d2f8116` |

Both passed. The second audit independently checks all 2,841 source probes,
5,682 side windows, 12,185 selected FFT frames and 40,324 gate cells. Numerical
comparison tolerances and observed differences are explicit in its metadata;
it does not claim bitwise equality of all floating probe hashes or acoustic
ground truth. These are derived verification summaries, not original source
event/waveform/spectrogram arrays. The original two-receipt verifier above
retains its frozen input set and does not claim to audit this later study.

## Completed common-rhythm / expressive-performance pilot

`performed-rhythm-invariance-43236100984.zip` preserves exact artifact
**13951958071** from [CPU run 43236100984](https://github.com/JDeun/audio-score-tool/actions/runs/43236100984),
attempt 1. The [completed result](../PERFORMED_RHYTHM_INVARIANCE_RESULTS_2026-11-12.md)
reports 480 authored onset-score cases, four identical-observation controls and
40 actual GMD performances. All 524 inference and input-preservation checks
completed before evaluation. Scientific completion does not establish common
written-score recovery.

- Exact ZIP: **273,834 bytes**; SHA256
  `7dad622b5ed1106691a5c10c387ef810b286cf49ce2bceaac920d0bdf45cd2af`.
- Sole member `report.json`: **4,169,391 bytes**; SHA256
  `30b839ab832780789eb9d4e77632d3679cd9efac2a031f40357e9080b4b4b723`.
- Frozen head: `d56738e77a9d058de430e2f20b07bd238c544ef9`; actual checkout:
  `4a167f7ac2c2eb97fe1e393ca195d947a0da61fe`; both tree:
  `6fda55f0a3194f0fcc96366b9527a1466feb5e1f`.
- Cold source acquisition: one HTTP request / 3,260,318 bytes, complete source
  ZIP SHA256 and 41 member hashes verified. The 40 fixed windows retain 10,818
  attacks; 675 source attacks outside the window are explicitly counted.

This receipt contains derived metadata, fingerprints, fit/decision summaries,
pair distances, retrieval outcomes and source provenance. It contains no raw
MIDI, event arrays, complete prediction arrays, audio or model weights. Hashes
of indented JSON files and compact content fingerprints are separately named.
Independent model and source/arithmetic audit summaries accompany it; they do
not alter the immutable Actions ZIP or measured scientific files. The original
two-receipt waveform verifier retains its frozen scope and does not claim to
audit this study.

| Independent audit | Bytes | SHA256 |
| --- | ---: | --- |
| [Model reconstruction](performed-rhythm-invariance-model-audit-43236100984.json) | 10,822 | `8d776215fe61c14c9486d559dcbdaa43edf6a828c984b309c568793fc90ff403` |
| [Source and arithmetic](performed-rhythm-invariance-source-audit-43236100984.json) | 70,819 | `0c2cd62a4c204919c57fe790def7c84613413c4cb7c2d18b7d8816534fbfeac7` |

Both audits pass with zero maximum numeric difference. The first reconstructs
all 524 input/prediction files byte-for-byte and the full model-derived pair
metrics without project helpers. The second independently decodes original
SMF bytes without mido and verifies every reported admission and aggregate.
Their limits remain explicit: common-groove labels are not written-score truth,
provided clocks are not audio-inferred, and reproducing arithmetic does not
prove the adequacy or generalization of the model.

## Completed repeat-context study and report-only recovery

The [completed result](../REPEAT_CONTEXT_RESULTS_2026-11-13.md) retains both
execution artifacts without recompression or replacement:

| Exact ZIP | Run / artifact | Bytes | SHA256 |
| --- | --- | ---: | --- |
| [Original failed receipt](repeat-context-incomplete-43256776331.zip) | [43256776331](https://github.com/JDeun/audio-score-tool/actions/runs/43256776331) / 13962156613 | 361,958 | `cf11f4757ae756878b108ab7b89a49a90db71b5c9fa04803a79f00d1c9e4f93e` |
| [Official recovery receipt](repeat-context-recovery-43261359821.zip) | [43261359821](https://github.com/JDeun/audio-score-tool/actions/runs/43261359821) / 13963788382 | 1,519,299 | `d77222eef446dbe9f24caa4b733139c59f2f06b96c8dcaf461dba34c3caa8528` |

Both ZIPs contain only `report.json`. The original member is 2,842,632 bytes,
SHA256 `568898b9c1f1fb6d5d2671e1805305eaa2939b2d1580175f0e2d6fc43e16c559`;
the compact recovered member is 16,524,883 bytes,
SHA256 `b64985586ec5f0340a61b45bce99107bccfd60d50bd3d19491e0f524c699bf93`.
The original remains `evaluation_failed`, with null evaluation and summary.
The recovery reproduces every original input/prediction file hash before the
unchanged evaluator and preserves all 1,520 planned cases in four separate
cohorts. Public JSON whitespace is the only report repair.

The original [model](repeat-context-model-audit-43256776331.json) and
[source](repeat-context-source-audit-43256776331.json) audit receipts retain
their prediction/source-only scope. The result document links the later
evaluation audits and their explicit independence limits. These verification
receipts do not establish musical generalization, successful common-score
recovery, audio beat inference, duration/rest accuracy or product readiness.

| Recovery verification receipt | Scope | SHA256 |
| --- | --- | --- |
| [Independent authored evaluation](repeat-context-recovery-evaluation-audit-43261359821.json) | 248,070 checks; all 1,512 authored input/prediction hashes reproduced before independent scoring; maximum numeric difference 0 | `ff743bb0f2030bfcdb638fc60e3ef70caa4fc53041c80624f4bed761f48367c1` |
| [Public real-mask and source-continuity arithmetic](repeat-context-real-receipt-audit-43261359821.json) | 36,971 checks; exact source receipt chain, all actual target/paired denominators and context aggregation; no private tick reconstruction in this script | `a2edf832fd1be2dda944da280b6d46b874f7517d34e769e899605af4b7baee43` |
| [Actual source replay and independent target/pair evaluation](repeat-context-real-replay-audit-43261359821.json) | 5,259 checks; 49 exact source members, eight full input/prediction replays and all real pair categories independently rejudged | `80b3189536a3a9df4daf3a52a25516c989c2978af1615af7a32e48c8d525ddde` |
| [Audit negative controls](repeat-context-recovery-audit-negatives-43261359821.json) | Rejects modified archive bytes and a modified summary count | `fe4dbe28b52694c755fbcd1b25baa47346ef9c8d165bc043ea3e20e411bc8a96` |

The authored [audit script](../../../scripts/audit_repeat_context_recovery.py)
has SHA256 `088c53e149917fb6bb8b58ea218d278c169247ab82b3e399a64612327f3283a2`;
the public real [audit script](../../../scripts/audit_repeat_context_real_receipt.py)
has SHA256 `072e0ea098c96c8399e4d70fddfa7af524474f2f72e0394f5a393f9dc76dcbf5`.
The actual [replay script](../../../scripts/audit_repeat_context_real_replay.py)
has SHA256 `d0593d3c77072ac0f143418793ccc148c7b966752a740a9b7e17660c6f3d802e`.
Their independence boundaries and reproduction commands are described in the
result report. Verification does not add a new scientific trial or modify the
original artifact.
