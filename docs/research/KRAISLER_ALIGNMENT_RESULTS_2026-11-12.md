# #275 / #276 — score correspondence completed with limited coverage

## Decision

**The fixed source-consistency procedure admits one of six recordings.** It
links **225 / 947 reference notes (23.7592%)** to notation at the primary 100ms
window. Only **137 / 947 (14.4667%)** retain the same unique identity at all
three fixed windows. Every admitted pair is in recording **19**.

This is correspondence coverage, not transcription accuracy. The other
**722** primary references remain unresolved, including **all previously
recorded gate match gains and losses**. The admitted subset therefore does not
explain the earlier tail-only benefit/damage by articulation. The preceding
[negative transfer result](KRAISLER_GATE_RESULTS_2026-11-12.md) is unchanged.

The experiment completed successfully; the method's limited admission is a
scientific outcome. Its time limits, global rejection rules and ambiguity
handling were not loosened after observing the result. This diagnostic checks
supplied-source consistency and does not establish independent acoustic truth,
written-rest accuracy, or automatic product quality.

## Fixed inputs and execution

The [protocol](KRAISLER_ALIGNMENT_PROTOCOL_2026-11-12.md) retained IDs **02, 19,
08, 12, 05, 06**, their 947 original violin note annotations, and the exact prior
gate matching receipt. Thirty original metadata members were verified: six each
of violin note CSV, shared beat CSV, violin XML, piano XML and piano Match.

[CPU run 43201534121](https://github.com/JDeun/audio-score-tool/actions/runs/43201534121)
/ [job 131125918878](https://github.com/JDeun/audio-score-tool/actions/runs/43201534121/job/131125918878)
succeeded on its **first attempt**, completing on 2026-11-12 at 10:34:36 UTC /
19:34:36 Asia/Seoul.

- Frozen PR head: `c209ac699add448873d0eb15761fbeae3feaccce`.
- Actual checkout: `ff26548443286772df973340ea676bfef82442b3`, combining that head
  with main `21705cdd3095dc816d5569b8d044807fcbed1918`.
- Both commits have tree `7bcc3794a02bfb4990c08fc05e243ff111148cce`, independently
  checked against GitHub's commit objects.
- Cold acquisition: **7 HTTP 206 requests, 776,325 bytes, 30 verified members,
  zero cache hits**. The entire 1.56GB archive and its whole-archive MD5 were
  not verified.
- **Zero audio loads, model inferences, training runs or prediction changes.**
  The standard-library analysis used CPython 3.12.16. Contract tools were
  pytest 8.4.2 and Ruff 0.16.6.
- All six source analyses and their hashes were saved before the analysis
  runner consumed previous gate outcomes. Earlier integrity tests can read the
  already published baseline; this ordering concerns conditional analysis.
- The 14 inherited sources remained unchanged. Fourteen new source/protocol/
  workflow/test/inventory files were fingerprinted in the actual execution.
- Observed runner duration: 5.94s, including 5.27s preparation, 0.58s source
  analysis and 0.06s attribution. Package installation is excluded; this one
  observation is not a controlled speed benchmark.

## Admission has several distinct stages

Five piano Match files agree with the parsed piano XML inventory. Two produce
a strictly increasing median-onset clock. One passes the shared-beat admission
rules. Passing the first stage does not imply passing the later stages.

| ID | Violin references | Piano Match/XML structure | Piano clock / beat outcome | Primary pairs | Stable pairs |
| --- | ---: | --- | --- | ---: | ---: |
| 02 | 73 | Unadmitted grace/tie representation | Clock not admitted | 0 | 0 |
| 19 | 295 | Exact inventory agreement | Both clocks admitted | **225** | **137** |
| 08 | 203 | Exact inventory agreement | Non-increasing median piano onsets | 0 | 0 |
| 12 | 65 | Exact inventory agreement | Non-increasing median piano onsets | 0 | 0 |
| 05 | 151 | Exact inventory agreement | Beat support/residual limits failed | 0 | 0 |
| 06 | 160 | Exact inventory agreement | Non-increasing median piano onsets | 0 | 0 |
| **All six** | **947** | **5 / 6** | **1 / 6 beat maps admitted** | **225** | **137** |

All six violin XML parts parse without unsupported structure or uncovered score
time. Their explicit rest elements total **77**, but subtracting all pitched
voices and merging adjacent spans leaves **36 instrument-wide rest intervals**.
An XML rest element is not automatically a distinct whole-instrument silence.

### Why five recordings were not admitted

**02 — representation limit.** The source combines two grace attacks into
ordinary tied durations, while the conservative XML parser retains grace
duration zero and unresolved noncontiguous/tie structure. Two Match rows
disagree in duration; the full symbolic inventory has four unmatched XML
attacks and two unmatched Match rows. The method retains five unsupported XML
diagnostics. This is a parser/representation limitation, not a finding that the
authors' data is incorrect. Supported individual rows do not override failed
whole-source admission.

**08, 12, 06 — median onset order.** A separate post-run calculation used exact
MIDI ticks and rational medians, without importing the core clock/matcher.
The reversals are present in the source values, rather than floating-point
roundoff:

| ID | Adjacent score-position pairs | Strict time reversals | Equal-time pairs | Largest backward step |
| --- | ---: | ---: | ---: | ---: |
| 08 | 233 | 12 | 1 | 314.0625ms |
| 12 | 310 | 10 | 0 | 967.7083ms |
| 06 | 350 | 7 | 0 | 97.9167ms |

All seven 06 reversals occur between different voices/staves at adjacent
one-sixth-quarter positions. This association does not establish their musical
cause. The larger 08/12 exceptions especially require source MIDI/score and
audio review before being attributed to expressive timing. The
predeclared procedure rejects the whole nonmonotone clock and performs no
isotonic fitting, anchor removal or fitted time shift.

**05 — insufficient supported timeline and large residuals.** After the fixed
eligibility exclusions, the median clock has a largest anchor gap of 12 quarter
notes / 6.0922s. Only **53 / 80 beats (66.25%)** have supported interpolation,
below the required 90%. Supported residuals have median **19.5208ms**, p95
**426.3817ms** and maximum **539.0833ms**; the p95/max limits are 250/500ms.
No threshold was increased to admit it.

**19 — admitted, with residual uncertainty.** Its unique structural candidate
supports all **191 beats**. Piano-versus-global-beat absolute residuals have
median **13.1875ms**, p95 **127.2104ms**, maximum **434.4222ms**. Two ending
symbolic beats have no CSV rows and are not extrapolated. These two clocks
share source provenance and are not independent human annotations.

## Fixed-window correspondence coverage

A pair must be the same mutually unique same-pitch onset candidate under both
source clocks. Grace/ornament contexts are excluded uniformly. No nearest-note
tie-break, prediction-derived shift or best-window selection is used.

| Correspondence scope | Paired references | Coverage of all 947 | Unresolved |
| --- | ---: | ---: | ---: |
| 50ms sensitivity | 153 | 16.1563% | 794 |
| **100ms primary** | **225** | **23.7592%** | **722** |
| 200ms sensitivity | 236 | 24.9208% | 711 |
| Same pair at 50/100/200ms | 137 | 14.4667% | 810 |

All pairs above come from 19. Its primary within-recording coverage is
225/295 = **76.2712%**. Keeping all six recordings in the denominator prevents
that selected recording from being presented as whole-cohort coverage.

At 100ms, the remaining 70 references in 19 comprise 55 with no candidate in
one or both clocks, seven with multiple score candidates, and eight competing
for a score attack. A larger window can introduce ambiguity as well as admit
new pairs, so the stable intersection is smaller than the 50ms set.

## Conditional gate ledger: the informative transitions remain unresolved

Memberships were computed before reading the previous masks. Each scope
partitions all 947 references, including unresolved notes. Primary and stable
populations are:

| Class | Primary references | Stable references | Primary onset0.65 onset+offset matches, every arm |
| --- | ---: | ---: | ---: |
| Staccato family | 39 | 26 | 2 |
| Accent family | 6 | 4 | 3 |
| Mixed articulation | 4 | 3 | 0 |
| Unmarked | 176 | 104 | 43 |
| Tenuto / other marked | 0 / 0 | 0 / 0 | 0 / 0 |
| Unresolved | 722 | 810 | 239 |

The 225 admitted references have **48 onset+offset matches in every arm and
both decoders**. Their onset-only matches also remain unchanged: 124 for default
and 126 for onset0.65. All conditional matching gains/losses in the admitted
classes are zero; the primary and stable scopes retain every prior transition
in the unresolved class. This says nothing about unmeasured note-time damage
within a class: the previous public receipt does not retain per-event occupancy.

For onset0.65, raw/full/tail/non-tail still have 287 total onset+offset matches.
Full and tail each gain one and lose one, all unresolved here. The default
decoder similarly retains its 247 matches and gain/loss ledger. No prior F1,
prediction count, note endpoint or gate decision was changed by this analysis.

### The improved final note in 19

Independent raw-tick/CSV interpolation checked the single gained reference in
19, shared by both decoders' tail/full arms. Its onset differs from the global
beat projection by **155.7ms** and from the piano projection by **122.8917ms**.
Both exceed the fixed 100ms primary window. Its onset is inside both clocks'
support; the exclusion is a residual limit, not extrapolation failure.

The predeclared 200ms sensitivity admits it as an unmarked note. It remains
unresolved in the primary and stable scopes. This sensitivity observation is
not substituted for primary attribution, and it does not establish a general
articulation-dependent benefit. The damaged references in 12/06 remain outside
admitted source clocks.

The class figures are reference matching counts/recall. False-positive
predictions cannot be assigned to these reference-only classes, so no class F1
is reported. They are not an articulation detector benchmark.

## Written-rest context: a small supported interior

Only recording 19 has an admitted clock pair. Nine of its ten instrument-wide
rest intervals lie entirely inside both clocks' support; the last one extends
beyond the support endpoint. Across the entire cohort this is **9 projected
and 27 unprojectable intervals**, retaining all 36 in the accounting.

| Supplied-clock projection, 19 only | Projected duration | Overlap with annotated violin notes |
| --- | ---: | ---: |
| Global beats | 2.792900s | 0.170400s |
| Piano alignment | 2.991797s | 0.399488s |
| Shared interior, 100ms inward guard at both boundaries | **0.921344s** | **0.000000s** |

The two clocks differ at rest endpoints by up to **92.8917ms**. Their guarded
common interior avoids annotated notes in these nine intervals, but this is a
source-overlap observation. No audio was read and no prediction occupancy was
available, so it does not measure actual acoustic silence, gate rest recovery,
written-rest F1 or listening quality.

## Exact receipt and independent checks

Artifact **13935537018** is retained without recompression as
[kraisler-alignment-43201534121.zip](receipts/kraisler-alignment-43201534121.zip).

- ZIP: **25,366 bytes**, SHA256
  `6f8af87bef6fa8febc977e037130b520d05d0dab8df815e3684ae6239d475005`.
- Sole member `report.json`: **543,226 bytes**, SHA256
  `ec5048b11ede7364ca5c68e9f7fb6f4889ed818d881f502aa34726ba54335f7a`.
- Supplementary source-manifest SHA256:
  `ba062dc673f0ebb64c12a95c096144b3efb0975ab7e7be34be645359c3d6503d`.

The [independent metadata audit](receipts/kraisler-alignment-audit-43201534121.json)
uses the standard library without importing the correspondence/scoring/
aggregation helpers. It passed **24 membership partitions, 96 prior mask/F1
identities, 1,344 per-case conditional ledger rows and 224 aggregate ledger
rows**, plus coverage/rest arithmetic, 30 member hashes/CRC identities and all
28 measured/inherited code hashes. Numeric comparisons use at most 1e-12
absolute tolerance. It does not independently establish symbolic or acoustic
truth.

A separate [post-run source audit](receipts/kraisler-alignment-postrun-audit-43201534121.json)
reconstructed all 225 primary pair identities for 19 without the core clock/
matcher and obtained the identical pair hash. The frozen XML/Match parsers
supplied anchor eligibility; tick grouping, interpolation and correspondence
were recomputed independently. It checked raw XML tags and
mutual uniqueness for one example of each nonempty admitted category, verified
the three rejected clocks with exact ticks, and independently recomputed rest
projection aggregates (maximum discrepancy below 9e-15s). This source audit
also preserves the primary/sensitivity distinction for the final-note gain.
The two JSON audits are derived post-run checks, not replacements for the exact
Actions artifact. Neither contains original event arrays.

**195 new contract tests** passed locally and in the study workflow. The
[initial-head CI](https://github.com/JDeun/audio-score-tool/actions/runs/43201534025)
passed with **2,119 product tests / nine optional skips; 914 research tests /
one existing upstream warning; 200 product / 38 research files and zero
omissions**. Frontend E2E passed 69 tests. The PR's Tauri job was conditionally
skipped (`required=false`); required `verify` passed.
[Research Evidence Contracts](https://github.com/JDeun/audio-score-tool/actions/runs/43201533994)
also passed. Result/receipt-only updates require their own CI; current final-
head and main integration evidence is on [PR #276](https://github.com/JDeun/audio-score-tool/pull/276).

## Next research decision

The immediate limitation is verified local timing support, not a missing gate
parameter sweep. Preserve this complete 1/6 admission result. A subsequent
protocol should separately test local clock-support intervals and inspect
reversed anchor regions against the original source evidence. It must account
for rejected regions/notes and compare coverage against this frozen global
rejection baseline, rather than silently repairing or removing difficult cases.
The grace-to-ordinary tie representation in 02 is a separate parsing task.

Additional independently checked timing anchors are needed before treating the
remaining gate changes as written-rest or articulation effects. The 0.9213s of
guarded source-consistent rest interior in one recording is too narrow to claim
general rest correction. All six recordings remain observed development/
diagnostic material, and no product correction is activated by this integration.

Primary source context: https://zenodo.org/records/21082251 and
https://reference-global.com/article/10.5334/tismir.338?tab=article. Match format:
https://cpjku.github.io/docs/match/specification/. Source licensing/offset
limitations remain those documented in the frozen protocols.
