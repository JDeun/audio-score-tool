# #275 — KRAISLER source correspondence and conditional attribution

## Question and scope

The [completed frozen-gate study](KRAISLER_GATE_RESULTS_2026-11-12.md) found that
the vocal tail-only benefit did not transfer to six violin recordings. This
follow-up asks whether the supplied score, piano alignment and global beats
support a defensible correspondence between violin annotations and notation.
Only admitted correspondence may explain the already recorded gate match
gains/losses by articulation. This is an exploratory diagnostic of the same six
recordings, not a new held-out model evaluation.

IDs remain **02, 19, 08, 12, 05, 06**. The original gate, model, decoders,
thresholds and scorer remain byte-identical. No new neural inference, training,
audio download, fitted time shift, tempo scaling or gate tuning is planned.
The source parsers and rules below are frozen before the Actions execution and
before looking at articulation-conditioned gate outcomes.

## Inputs and provenance

- The original manifest's six violin note CSVs, six global beat CSVs and six
  violin MusicXML parts, with unchanged member hashes.
- Six author-supplied piano `.match` alignments and six piano MusicXML parts.
  Their central-directory entries, exact HTTP ranges, local headers, CRC32 and
  SHA256 are independently pinned in a supplementary manifest.
- The exact previous metadata ZIP `receipts/kraisler-gate-43184102838.zip`, SHA256
  `ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e`.
  Its sole `report.json` member has SHA256
  `e79ff94736b471da64638a93456ef4f1510750c843960ae924fc1f488ad2f754`.

Cold acquisition is seven bounded HTTP 206 requests, **776,325 bytes**: the
existing 666,965-byte metadata suffix plus six `.match` ranges totalling
109,360 bytes. There are 30 original metadata members and zero audio members.
Source media, XML/CSV/`.match` contents, score/performance event arrays and
model weights stay outside the repository and published artifact.

The source authors state that beats are shared between performers and manually
refined from piano alignment. A beat need not equal a violin onset. Some
performed chords differ from the written chord, and violin trills can be
represented by principal notes. Violin annotations themselves were derived
from score-to-audio alignment and reviewed; their offsets are less reliable
than onset/pitch. Consequently, source consistency is not independent acoustic
ground truth or an assessment of listening/editing quality.

## Symbolic parsing

Use exact rational quarter-note positions from MusicXML duration/divisions.
Track backup/forward, chord members, voice/staff, time-signature changes and
tuplets. A short first measure is a pickup and is not padded at its beginning.
Preserve a short final measure. Generate reproducible structural IDs because
the violin XML does not supply note IDs.

Collapse only explicit, contiguous same-part/pitch ties. Prefer the matching
voice/staff parent; if it is absent, allow exactly one contiguous same-part/pitch
parent across voice/staff and record that transition. Multiple possible parents
remain unsupported. Preserve grace, articulation and ornament flags.
Orphan/noncontiguous/open ties and unsupported
navigation or duration structure are explicit unsupported diagnostics.
Repeated sections are already expanded in the source, but the parser must
reject any remaining repeat/navigation structure it cannot establish.

Pre-execution source inspection identified explicit cross-voice ties in the
piano part. The parser was extended by the unique-contiguous-parent rule above
before any clock residuals or conditional gate outcomes were evaluated. This is
a source-grammar correction; the clock and correspondence thresholds below
were not changed. Grace-to-ordinary/noncontiguous tie ambiguity is not repaired.

Explicit rests are intersected with the complement of all sounding voices.
A rest in one voice is not instrument-wide silence. Uncovered score time is
reported separately, rather than being invented as a rest.

## Source clocks and admission

The piano `.match` parser must account for its score beat unit, whole-note
fraction durations, MIDI tick/clock conversion, and pickup numbering. Validate
its symbolic score positions/pitches/durations against the piano XML; retain
unsupported or unmatched rows as diagnostics. Grace/ornament rows do not
automatically become reliable beat anchors.

At a coincident score quarter, use the median performance onset of eligible
piano anchors. The resulting clock must be strictly increasing: do not repair
it with isotonic fitting, delete conflicting anchors to improve admission, or
extrapolate beyond its observed range. Interpolation support is limited to
adjacent anchors separated by at most **4 quarter notes and 3 seconds**.

Construct symbolic beat positions from the score and meter: denominator-note
beats for simple meters, dotted beats for compound meters such as 6/8. A pickup
uses the terminal portion of its nominal measure. Compare the supplied beat
CSV to contiguous symbolic beat sequences with exactly matching downbeat and
meter patterns. Cross-check piano/violin measure positions and lengths.

A candidate beat-to-score sequence is admitted only when:

1. At least **90%** of its beat positions have supported piano-clock times.
2. Absolute beat-versus-piano timing residuals have median **<=100ms**,
   95th percentile **<=250ms**, and maximum **<=500ms**.
3. Exactly one structural candidate passes. Multiple passing candidates are
   ambiguous; no candidate is selected using violin notes or gate outcomes.

Report every structural candidate and its rejection reasons within a bounded
candidate budget. No threshold is relaxed in response to low coverage.

## Violin correspondence and conditional ledger

The primary window is **100ms**. Independently build same-MIDI onset candidate
relations using the admitted global-beat clock and the piano clock. Admit a
pair only if both clocks give the same mutually unique reference/score pair.
Do not use a nearest-neighbour tie-break, dynamic time warping, note offsets,
gate predictions or F1 to resolve ambiguity.

Report fixed **50ms and 200ms** sensitivity windows, and the intersection of
pairs unchanged across all three windows. Do not select the best observed
window. Grace events, ornaments such as trill/tremolo, and principal attacks
at the same symbolic instant as a grace event are excluded from strict
articulation attribution. Their exclusions remain in the coverage ledger.

Primary labels partition every reference note into staccato, tenuto, accent,
other marked, mixed articulation, unmarked, or unresolved. Unresolved notes
remain in every denominator and gain/loss conservation check. Membership
bitmasks and aggregate counts are publishable derived metadata; original
event arrays are not.

Within the analysis runner, only after correspondence and memberships have
been constructed may the previous immutable match masks be consumed for
attribution. Earlier contract tests may read the already published baseline
receipt to verify integrity; they do not calculate conditional outcomes or
choose correspondence rules. For both decoders and all four
arms, report matching counts and gained/damaged reference notes within each
class. Class counts must sum to the unchanged previous whole-recording counts.
These are conditional match/recall ledgers: false positives cannot be assigned
to these reference-only classes, so do not manufacture class F1.

## Written-rest context

Project only instrument-wide explicit rests whose entire intervals lie inside
both clocks' interpolation support. Compare endpoint differences and report
overlap with the source's violin note union as a source-consistency diagnostic.
Also report the conservative shared interior after a fixed **100ms** boundary
guard on each clock. Omitted/unprojectable rests remain counted.

No prediction occupancy arrays are available in the prior public receipt.
This experiment therefore does not measure gate written-rest accuracy, silence
F1, or actual articulation-gap recovery. It determines what score context can
be admitted for subsequent work.

## Execution, failure and completion

Run on CPU with the standard library; use pinned pytest/ruff only for contracts.
The runner requires all six sources and validates the previous artifact and
source identities. Always preserve a bounded failure receipt. A source may
finish as structurally unadmitted, with every reference unresolved; that is a
scientific result, not permission to substitute another recording.

Publish all six diagnostics, fixed-window coverage, matching conservation,
source hashes, runtime/checkout identity, code/protocol hashes and limitations.
Independently check aggregate arithmetic and selected private correspondences.
Complete final-head CI before merging and check actual main CI afterwards.
Research integration does not activate an automatic correction in the product.

Primary sources: https://zenodo.org/records/21082251,
https://reference-global.com/article/10.5334/tismir.338?tab=article,
https://cpjku.github.io/docs/match/specification/.
