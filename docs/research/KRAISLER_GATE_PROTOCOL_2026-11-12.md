# #273 — frozen gate transfer to KRAISLER: pre-execution protocol

This protocol is fixed before neural inference or gate-result inspection. It
continues the completed #271/#272 edit-attribution study, merged at
`1c9514e30e2aac92ba6857e67a940dc48b6a03e6`. Research integration is authorized;
successful execution and required CI will precede this follow-up PR's merge.

## Question and controls

Does the unchanged gate's selected tail-only correction retain any benefit on
new actual violin recordings outside the 40 vocadito development recordings?
Report gains AND harm, including unchanged matching with lost note time.

Use the unchanged Basic Pitch 0.4.0 ONNX CPU asset and its default/onset0.65
decoders. One recording-level prediction call supplies both decoders; the model
may process multiple neural windows internally within that call. For
each decoder, retain raw, full relative-soft, tail-only, and non-tail-only arms.
The soft selector runs once per parent and its choices are partitioned exactly
as #272. No new thresholds, costs, candidates, models, fitting, learned alignment,
reference-guided selection, per-file winning-arm choice, or vocadito rerun.
F1 differences are not additive causal contribution percentages.

The new runner checks SHA256 of all eight inherited gate/model/decoder/scoring
source files before execution. RMS is still 20ms/10ms, relative level is the
95th percentile minus 30dB, hysteresis 6dB and hold 60ms. All soft edit costs and
minimum fragment length remain unchanged. Runtime pins match the prior study.

## Source and selection fixed before results

Official KRAISLER v1.0, Kim, Park, Lee, Kwon, Won and Nam (2026):
https://zenodo.org/records/21082251 and https://doi.org/10.5334/tismir.338.
The release contains 20 classical duet excerpts by a professional violinist and
pianist, recorded in acoustically isolated rooms. Use the original close-miked
VN dry recording only, never studio/hall variants or accompaniment mixtures.

Rank two-digit IDs 01–20 by SHA256(`waveform-gate-kraisler-v1/` + ID). Select the
first six in that order: **02, 19, 08, 12, 05, 06**. The remaining IDs are not
evaluated here. Retain every planned ID without outcome-, score-, instrumentation-
or annotation-quality-based replacement. Evaluate each whole original WAV;
there is no chosen excerpt, onset-based crop, gain normalization or time shift.
The selected WAVs are 63.2338095, 67.5, 74, 48, 72.5 and 78 seconds respectively,
403.2338095 seconds total, below the fixed 150s per-file admission ceiling.
Six recordings are not 48 independent samples; they share performers
and collection. This is new-to-gate data, not a verified pretraining-disjoint
benchmark or a broad violin population estimate.

Mono refers to the WAV channel count. Some selected scores contain double stops,
multiple voices, grace notes and meter changes. Do not replace them or claim all
six performances are musically monophonic. The gate and Basic Pitch can produce
overlapping notes; the evaluator preserves these and scores occupancy by union.

## Bounded verified source acquisition

Official archive URL:
https://zenodo.org/api/records/21082251/files/KRAISLER.zip/content

Archive size 1,558,287,213 bytes; published MD5
`22f6f51e9c356c1ea8f591d85603fd73`. Retrieve only the pinned ZIP directory and
selected member ranges. Require exact HTTP 206/Content-Range/length, pinned
directory identity, local-header consistency, decompressed size, ZIP CRC and
individual SHA256. The manifest freezes exact member identities and the selection
algorithm. Original audio/notes/beat CSV/MusicXML bytes are unmodified. Do not
claim a full archive download or full archive MD5 verification from range reads.
Cache reuse, when present, requires the exact member digest; a fresh CI run starts
without a source cache. The six compressed audio members total 27,672,480 bytes.

The release labels itself CC BY 4.0 while its description also states a
noncommercial restriction. Restrict this work to research evaluation; do not
claim commercial rights or redistribute raw media, MusicXML, annotations, MIDI,
prediction events, neural arrays, or weights. Publish only code, provenance,
hashes, counts, match masks and aggregate/damage metadata. Credit the authors.

## Reference and evaluation boundary

Violin CSV columns are onset seconds, offset seconds, integer MIDI pitch, and
velocity (the release fixes velocity to 127). Validate finite nonnegative starts,
positive durations, valid pitches and the source timeline. Convert the provided
MIDI pitch to Hz without transposition/tuning search, and reuse the existing
50ms onset / 50-cent pitch / max(50ms,20% duration) offset matching scorer.
Retain valid empty predictions as zero; retain overlapping reference notes.

The source annotations were generated with score-to-audio alignment and then
manually refined. The authors explicitly warn that offsets are less reliable
than onsets and pitch. This is accuracy against those annotations, not proof of
the exact physical endpoint. Preserve that uncertainty in conclusions.

All eight prediction sets per recording are constructed before labels are
parsed for scoring. No reference CSV, score, beat map, rest, articulation, title,
composer or instrument identity enters the model, gate or edit selector.

Primary evidence is per-recording and macro onset/onset+offset F1 for all four
arms and both decoders. Also report output counts, edit operations, matched
reference outcomes gained/lost, and per-recording improved/worsened/equal counts.
Require tail-only to preserve every parent onset, pitch/identity, order and note
count; its onset F1 must equal raw exactly. Match masks permit independent metric
arithmetic, but do not substitute for re-matching private source events.

Time occupancy uses the unchanged 10ms grid and first-to-last reference-note
scope. Report sums of reference-note/gap time, wrongly unoccupied note time,
wrongly covered gap time, restored gap time and additional note time removed.
Here there is one annotation per recording, with no A1/A2 averaging. Matching
and duration damage must both be reported, including negative or zero effects.

Primary aggregate is available only for all six unique planned IDs, both
decoders and four complete arms. Preserve every failure and return incomplete
with null aggregate otherwise. Do not summarize a successful subset as the
planned cohort. Source/preparation failures produce a failure receipt.

## Score/rest admission audit, separate from performance-note accuracy

The official release provides repeat-expanded VN MusicXML and global beat CSV.
It provides explicit note-ID alignment for piano, not the violin CSV's rows.
Violin CSV has no MusicXML IDs; global beats also need a validated score-position
mapping, especially with pickup bars, compound meter and meter changes.

Inspect XML rest elements, articulation tags, chords, voices, grace notes and
meter declarations, together with beat structure. This is a structural audit.
It does not create a verified violin score-to-audio mapping. **Do not report
written-rest precision/recall or treat every performed gap as a written rest.**
If this audit fails for a case, retain its diagnostic separately; it does not
select or discard the primary performed-note evaluation. Correct matching of
notated rests versus articulation remains a subsequent alignment/admission task.

## Execution and decision rule

CPU-only GitHub Actions with two threads, no training or external credentials.
Exactly six planned recording-level inference calls. Freeze protocol/source hashes in the receipt
and retain the completed artifact beyond temporary Actions retention. The model
run happens on PR opening; report-only updates and main merge do not rerun it.

Report all outcomes. A positive macro result on six excerpts is preliminary
transfer evidence, not product approval; a zero/negative result limits the
vocal-development finding. Any note-time harm prevents a zero-damage claim.
No automatic score correction, notation-quality, listening-quality or human
editing-time improvement is approved by this study. Future rest validation
needs verified violin note/beat-to-score alignment before scoring written rests.
