# #271 — frozen waveform-gate edit attribution (development follow-up)

Base main `7dd5c6ce0b18fda023403d92fba981867a1f0202`. The prior #270 study is
complete. This protocol is committed before measuring the NEW intervention arms.
CPU only, existing public vocadito and Basic Pitch 0.4.0 ONNX weights, two threads;
no GPU, training, LLM, paid API or external model credentials. Product defaults
and automatic score correction are outside this experiment.

## Question and fixed interventions

The prior relative-soft condition increased onset0.65 onset+offset F1 from
37.2572% to 37.6995%, but its 20 changed source events included nine deletions
and two splits. A higher F1 can result from removing predictions or changing
onsets/counts. How much benefit remains when only the already-selected,
count-preserving trailing-offset corrections are allowed?

Use the SAME 40 reused DEVELOPMENT recordings, both original decoders (default
and onset0.65), both annotators A1/A2, and the unchanged relative gate and soft
selection objective from #270. Compute the existing soft proposal ONCE for each
parent note, without reference inputs. Partition those fixed choices:

| Arm | Applied choices |
| --- | --- |
| raw | None |
| relative_soft | All original relative-soft choices |
| tail_only | Only one retained child with identical onset, pitch, channel, program and drum flag, and a strictly earlier offset |
| non_tail_only | The complementary selected edits: deletion, splitting or a moved onset |

Unchanged parents stay unchanged in every arm. A child with BOTH a moved onset
and an earlier offset belongs to `non_tail_only`. This is a conservative partition
of the previous policy, not a newly optimized offset proposer. Do not generate
extra candidates, recalibrate cost/thresholds or select a winner using truth.
The two changed-parent sets must be disjoint and their union must reconstruct
`relative_soft` exactly in original parent order. `tail_only` preserves note
count, pitch and every onset, so its onset F1 must equal raw exactly.

F1 is nonlinear and matching can interact across notes. Do NOT sum arm deltas
into percentages of causal contribution. Compare each arm against the same raw
control and report full-vs-tail differences directly. This is a post-result
mechanism diagnostic on a development set, not an independent generalization
test or evidence that any method recognizes engraved rests.

## Exact replay before comparison

The old artifacts contain metadata and hashes, not reusable raw event/model
arrays. Regenerate Basic Pitch ONNX inference once per recording and share its
arrays across both existing decoders. Explicitly report that model inference was
repeated. Check the full original corpus and per-file audio/annotation hashes,
model identity, all 80 raw prediction fingerprints/counts, all 80 original
relative-soft fingerprints/counts, and the corresponding scores, match masks and
occupancy against #270. The raw scores also retain the earlier #239 baseline.
Any mismatch fails the case and suppresses a complete-cohort aggregate.

All arms for a recording are frozen before its note annotations are read.
Annotations enter only the inherited 50ms/50cent onset scorer, the
max(50ms,20%-duration) offset scorer, and evaluation cropping. No F0, lyrics,
tempo, bar/voice information or score labels enter the selector. The evaluator
rejects drum predictions here: the inherited vocal F1 excludes drums whereas
its mask builder does not, so mixed inputs would have inconsistent populations.
Basic Pitch's frozen vocal predictions are non-drum.

## Frame-boundary repair, separate from the music hypothesis

The archived `rms_envelope` uses floating `ceil(duration / .01)`. At exact hop
multiples such as 70ms it can generate an extra zero-width final cell, causing
`mask_intervals` to reject valid audio. Keep that historical file byte-identical.
A new envelope computes the count by exact rational/sample-domain ceiling, then
uses the same edges/RMS arithmetic and gate settings. Test exact-hop and
one-sample-adjacent lengths at several rates. For ALL 40 historical WAVs require
bit-identical valid edges and RMS levels against the archived function. Therefore
the repaired boundary handling cannot silently change this ablation's input.
No claim that the completed old study was affected by this new-input bug.

## Reporting and completeness

Two decoders x four arms x 40 recordings x two annotators = 640 scored conditions,
not 640 independent sources. Keep all 40 IDs and failed cases; a missing/duplicate
ID, missing arm or failed replay suppresses the aggregate. Empty predictions are
scored as zero, never dropped. Report:

- Recording/annotator-equal onset and onset+offset F1; both annotators separately.
- Matched-reference gains/losses and source-event edit categories/counts. These
  two annotators' matching outcomes are not distinct physical notes.
- Better/worse/equal recordings with the A1+A2 mean AND each annotator separately.
- Total note count and changed parents per arm.
- Annotated note time removed and reference non-note time recovered, averaged
  across A1/A2 totals, in seconds. Zero matching loss is not zero time damage.
- Per-file masks/counts/hashes and scores to allow independent receipt arithmetic.

Use inherited 10ms occupancy evaluation between first/last annotated notes.
These labels describe performed notes and gaps, not written rests or staccato.
No nASAP joint decoder, polyphonic separation, MusicXML/PDF readability or user
editing-time evaluation is performed. No training-overlap guarantee is inferred.

## Durable evidence and execution

Preserve the exact metadata-only ZIP bytes of artifacts 13825524844 and
13922463947 in `docs/research/receipts/`, with original ZIP/member SHA256 and an
offline integrity/arithmetic verifier. The new workflow reads these committed
receipts and does not depend on expiring Actions artifact download URLs.
Archive the new derived report after completion too. Original WAV, reference
notes, MIDI, predictions and weights remain in the runner's private temporary
directory. Published metadata must not contain those arrays or raw media.

An opt-in PR-open/manual CPU workflow runs contracts, checks retained receipts,
downloads the same checksum-pinned vocadito corpus, then runs the four fixed arms.
It does not rerun on later documentation pushes. Normal repository CI still runs
the exhaustive product/research test partition. Keep the PR draft until results
are audited; code inclusion and product quality approval are separate decisions.

Source attribution: Bittner, Pasalo, Bosch, Meseguer Brocal and Rubinstein (2021),
https://zenodo.org/records/5578807. Related #269, #249 and #259. Independent
score-aligned mono stems with written-rest versus articulation labels remain the
next data requirement; this development ablation does not replace that gate.
