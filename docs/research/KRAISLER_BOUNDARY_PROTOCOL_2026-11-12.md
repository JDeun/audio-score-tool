# #279 — original-waveform boundary and rest context: pre-execution protocol

This follow-up is declared before inspecting new waveform descriptors. It follows
the user's instruction to continue after [#278](https://github.com/JDeun/audio-score-tool/pull/278),
merged as `84fade231ebc89fefcb3f6a60f284b1e5a6cd575`. The same six recordings and
their previous outcomes have already been observed. This is an outcome-informed
development diagnostic, not a new held-out accuracy benchmark.

## Question and decision boundary

Can the original waveform provide observable context around annotated note
boundaries and the already supported written-rest ranges? Distinguish genuine
absence of digital energy, low but nonzero energy, a continuing same-pitch
neighbour, another overlapping note, and an observation without complete support.
Do not infer a physical release or written rest from an energy decrease alone.

The primary analysis covers **all 947 annotated onsets and all 947 offsets**,
plus **all 947 within-note midpoints** as an interior-control population. Midpoints
belong to the same notes and are not additional independent performances. Each
recording retains every reference, including unsupported or confounded windows.
The existing **36 instrument-wide written-rest intervals** remain the rest
denominator; #278's 18 projected / 18 unprojectable result is an immutable
historical baseline, not a target to improve by changing admission.

Four previously changed references are a selected explanatory watchlist, with
0-based indices fixed before this waveform study:

| Recording / reference | Historical matching observation | Interpretation boundary |
| --- | --- | --- |
| 02 / 14 | Onset loss in non-tail edits | Not an offset-only example; symbolic admission is unavailable |
| 19 / 294 | Offset-match gain on the final note | Local waveform context cannot recover its old prediction endpoint |
| 12 / 16 | Offset-match loss; another annotation of the same pitch starts at its offset | Energy alone may not separate the two annotated notes |
| 06 / 159 | Offset-match loss on the final note | Do not assume it has the same mechanism as 19 |

These indices are selected from previous matching outcomes. They cannot be used
as unbiased success examples or merged into a universal trimming explanation.
Saved receipts lack original prediction events and matching-pair identities.
No new inference is performed, so exact edited prediction endpoints and causal
attribution remain unavailable.

## Original sources and bounded acquisition

Use the unchanged source selection and manifests from #273/#274 and #275/#276:
KRAISLER v1.0, IDs **02, 19, 08, 12, 05, 06** in that order. Original dry violin
WAVs are **mono PCM16 at 44,100 Hz**, totaling **403.2338095238 seconds**. Decode
integer PCM as float64 / 32768, with no resampling, normalization, cropping,
channel replacement or time shift. Read every whole original recording.

Reuse the unchanged bounded audio and alignment loaders in separate private
directories. This deliberately permits the common metadata suffix to be fetched
twice, avoiding changes to either frozen loader:

| Acquisition | Maximum cold requests | Cold bytes |
| --- | ---: | ---: |
| Six audio members plus shared note/beat/violin-score metadata | 7 | 28,339,853 |
| Thirty alignment metadata members | 7 | 776,325 |
| **Combined** | **14** | **29,116,178** |

There are **36 unique original members**: six WAVs plus 30 metadata members.
The two loader receipts overlap in 18 metadata members; do not call the 54
member reads 54 independent sources. Report actual network bytes, HTTP ranges
and cache reuse separately. Require exact HTTP206 / Content-Range / length,
pinned directory and compressed-range identity, decompressed size, SHA256,
CRC and original WAV shape. This does not verify the complete 1.56GB archive's
published MD5.

Source: [official release](https://zenodo.org/records/21082251),
[author paper](https://doi.org/10.5334/tismir.338). Retain the research-only
use and non-redistribution boundary recorded in the prior source protocol.
Do not publish original WAV/crops, XML, Match, annotation/event arrays,
spectrograms, prediction events or weights. Publish derived summaries and hashes.

## Frozen gate replay

Compute the original relative gate with the **same**
`audio_gate_attribution.rms_envelope` sample-domain cell-count implementation
and `audio_gate_rest.gate_levels`. Use original mono samples in the same
single-channel array shape as the historical runner. Keep 20ms RMS, 10ms
cells, reference percentile95 minus30dB, 6dB hysteresis and 60ms hold unchanged.

After all six new analyses are saved, require exact equality to #274 for each
recording's reference/close/open dB scalars, frame count, quiet-frame count and
quiet-mask SHA256. A replayed gate mask is a property of that procedure; it is
not independent validation that a region is musically silent. No edit selector,
prediction matching or model score is rerun.

## Separate spectral descriptor

Use a fixed, reference-conditioned descriptor, not an inferred pitch or endpoint:

- Symmetric Hann (`numpy.hanning`) **2048 samples**, hop **441 samples**.
- Frame starts are 0,441,882,...; end=start+2048 must be inside the original
  audio. No zero padding or partial trailing frame. FFT chunks are 256 frames.
- One-sided rFFT power: multiply interior bins by two, DC/Nyquist by one, then
  divide by `2048 * sum(Hann**2)`. Its full-spectrum sum obeys windowed Parseval
  energy. PCM full scale is the dBFS reference, not calibrated acoustic SPL.
- Analysis band: bin centers **80 through 8000 Hz**, inclusive.
- For the annotated MIDI pitch, form bands around harmonics1..8 whose centers
  are at most8000Hz. Each band is the outer hull of true +/-50cents and
  +/-one FFT-bin radius, intersected with analysis bins. Use their union so a
  bin is never counted twice. The finite width does not contain all Hann leakage.
- Let H be the target harmonic-vicinity power and B the analysis-band power.
  A window reports mean(H), mean(B), `sum(H)/sum(B)`, and dBFS computed **after**
  averaging linear power. Do not average individual frame ratios or dB levels.

H is conditioned on the source annotation. Coarse spectral resolution,
harmonically related notes, vibrato, bow noise, overlapping notes and room/mic
response can affect it. Call it harmonic-vicinity energy/concentration, never
pitch confidence, audibility, a physical key/bow release, or a calibrated
probability. It is a different descriptor from the gate but not independent
ground truth.

## Fixed boundary windows and context

At each onset, offset and midpoint, compare **[-100,-20]ms** and
**[+20,+100]ms** relative to that annotation position. A spectral frame's entire
2048-sample support must fit within its requested window. Merely fitting its
center is insufficient. These windows usually contain three or four complete
frames; they are sparse fixed observations, not a continuous endpoint search.

The entire requested interval must lie inside the audio. Do not clip it to gain
admission. Record unavailable windows and zero complete frames explicitly.
Power0 remains0; undefined logarithms or ratios are null. Count separately
both-positive, zero-to-positive, positive-to-zero, both-zero and unavailable
transitions for target and total power. A null dB delta must not conceal an
exact-zero release or an unsupported observation.

Primary numeric descriptors are after-minus-before target/total dBFS,
concentration change and frozen gate-quiet fraction change, with before/after
levels retained. A negative difference is descriptive; no threshold labels it
as a correct release. Gate window occupancy uses continuous intersection with
original gate cells, including partial cells.

Context is derived from unchanged note annotations. For each +/-100ms hull,
retain same-pitch and other-pitch neighbour flags and exact window coverage by
the current note, other notes and annotation-uncovered time. Overlapping notes
are unioned before duration accounting. Use mutually exclusive strata in this
priority order:

1. Any other **same-pitch neighbour** intersects the hull.
2. Otherwise, any **other-pitch neighbour** intersects the hull.
3. Otherwise, the current note is **too short to cover its expected side(s)**.
4. Otherwise, **isolated annotation context**.

For onset, the expected sounding side is after; for offset, before; for midpoint,
both. The neighbourhood includes the excluded guard. Floating interval-context
comparisons use1e-12 seconds solely for arithmetic roundoff. Annotation isolation
does not establish acoustic isolation or completeness of the annotations.

Report all three populations and their strata; never discard ambiguous notes
to improve a cohort average. Within-recording summaries include type7 quantiles,
count and sum. Cohort means are pooled by the number of defined observations,
not unweighted recording means. Keep undefined counts. Do not average recording
medians into a cohort median, and do not report independent-sample confidence
intervals for overlapping windows or the same six performers/recordings.

## Existing rest ranges, now with waveform context

Reconstruct #278's unchanged local clocks and exact range rules. Compare the
complete public source projection with frozen `rest_range_context`, including
unsupported intervals, collapse counts, guard statistics and annotation overlap.
After all analyses, compare the full expressive diagnostic with the exact #278
receipt. No source anchor, guard, onset pairing or symbolic value is adjusted.

For envelope, core and boundary-uncertain interval unions, report continuous
seconds of frozen gate quiet/active and split each by annotated-note overlap /
uncovered-by-annotations. Preserve all of these conservation relations:

- Core + uncertain = envelope, including each annotation subset.
- Quiet + active = region duration.
- Annotated overlap + uncovered = region duration.

No intervals are clipped or extended. Projection outside the original waveform
fails the study instead of inventing coverage. Report broadband spectral power
only for full frames inside a region; a short region may have duration without
a complete frame. Spectral frame counts do not partition like continuous time:
a frame can fit the envelope while crossing the core/uncertain boundary. Count
those frames explicitly. Pool spectral power by full frames, not interval dB
means. Neither gate-quiet nor annotation-uncovered time is acoustic rest truth.

## Controls, provenance and execution

Separate authored controls are fixed before the real waveform study: hard
tone-to-zero, a sustained same pitch across a nominal boundary, a nonzero
low-amplitude tail (0.05 amplitude multiplier), a two-semitone detuned tone,
and seeded noise. They verify descriptor behaviour, not human listening or
real-data recognition accuracy. Additional contracts cover a0.01-amplitude
tail that is nonzero while the frozen gate is closed, context ambiguity,
sample-boundary leakage, exact waveform scaling, and conservation failures.

Use CPU Python3.12 / **NumPy1.26.4**, pytest8.4.2 and Ruff0.16.6, two numerical
threads, no GPU, model download, authentication, training or inference.
Record all **37 inherited literal byte pins** and the **11 new measured files**,
including this protocol, workflow, four modules, four test files and extended
research inventory. The inventory is intentionally extended, not falsely
claimed byte-identical to its old version.

Save all six public analyses and their canonical hashes before first opening
either historical receipt. Retain each complete expressive analysis privately
and require exact reproduction of #278. Verify all36 source member identities
and the six gate replays. Only after all baseline checks succeed, attach the
old2decoder/4arm/2metric saved-mask transitions for the fixed watchlist. The
union of changed references must equal the four declared indices. Never mutate
new analyses or historical masks during this attachment.

Frozen historical inputs:

- `kraisler-gate-43184102838.zip`:16,111 bytes, SHA256
  `ba88b9bda70d4a560a3d05c85ea5301d2e8ff98ea81746d676a1c6695898e10e`.
- `kraisler-expressive-43210425240.zip`:72,066 bytes, SHA256
  `e51fae082cf3c97240a9746cf2ba2214923ce30555ae2f70130f6043cffd478f`.

The Actions run starts on PR opening/reopening or manual dispatch, not on
synchronization, documentation-only completion or main merge. Retain source
head, actual checkout/tree, run/attempt, runtime and acquisition provenance.
Public components are at most1MB and the report at most8MB; private exception
logs remain outside artifacts. Preserve preparation and per-case failures.
Only all six complete analyses, baseline checks and watchlists permit the
planned-cohort summary. Keep the exact artifact ZIP beyond temporary retention,
then independently audit arithmetic and selected source reconstructions.

## Interpretation and subsequent decision

Completion establishes a reproducible waveform diagnostic and the original
gate's replay, not improved F1, corrected annotations, verified acoustic
silence, actual swing detection or automatic notation correction. Existing
negative gate-transfer findings and unresolved score correspondences remain
unchanged. Strong harmonic evidence after a boundary may motivate independent
listening/source review; weak evidence can reflect expression or noise limits.
Neither observation is a license to move endpoints or relabel a written rest.

Source offsets are less reliable than onsets/pitch, as stated by the dataset
authors. The beat/piano source clocks are related. Any subsequent articulation
or swing-aware selector needs separately declared calibration and held-out
validation; this reused development cohort is not such a validation set.
