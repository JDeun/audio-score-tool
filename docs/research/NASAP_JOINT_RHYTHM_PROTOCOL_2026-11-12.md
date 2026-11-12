# Real voice/rest/measure joint decoding pilot — frozen before source evaluation

User-authorized continuation of #263/#249/#259. Parent #263 commit3c687aff0eadb23b645ce156fa1d764bc2c5a0ee. Keep DRAFT; no main/product/default/automatic score/other-session changes. CPU, no learned models, training, GPU, external API credentials or user audio.

## Question

On the SAME performed-note observations, does joint selection of note positions, durations and explicit rest gaps outperform independent selection under the SAME supplied score context? Separate hard structural constraints from rest-spelling preferences. Neither source duration is universally substituted for the other.

## Frozen source and coverage

Reuse exact #263 artifact13910660014, ZIP SHA256 a9fd6bb76b56ac0e7dc609e3dd9562326265571820d59cbab2edcf5833f99760; report SHA256 ef57078bf20bff35a56e2f35cada222fe05bea3d0754785781296531111d0890. Retain all12 planned IDs and5 prior nonadmissions. Rebuild the same7 source windows and all original observed notes; validate source observation hashes, all original source SHA256 and ALL SIX previous per-note result masks before new evaluation.

(n)ASAP CPJKU/asap-dataset@4097b45757bed854818cf87e77b92323ebf90615. Additional original MusicXML read only from this pinned revision, max4MB/file/40MB reader budget; compute byte SHA256. No whole dataset/audio/model downloads. Data CC BY-NC-SA4.0: retain attribution Foscarin et al., ISMIR2020, and Peter et al., TISMIR2023. No commercial-use permission or product bundling implied. Only our source code, derived outcome masks/counts and input hashes are published.

## Important privileged context and non-equivalent denominator

This is NOT automatic audio transcription. Both independent and joint arms receive the SAME annotated variable-tempo clock, correct quarter unit, two-bar boundaries, reference voice assignment, reference chord membership, and aligned complete note inventory. Chord membership includes which played notes share a written attack; therefore even an independent arm may improve relative to #263 because it receives extra context. Do NOT attribute that difference to joint decoding.

Within each admitted passage, identify full constant2/4,3/4,4/4 XML measures wholly inside the inherited beat8..40 window. Use consecutive non-overlapping pairs starting with the earliest eligible measure. Map repeat occurrences using XML note IDs plus publisher unfolded score coordinates, never guess a repeat traversal. Each voice is a separate block; max64 attempted blocks/source; do not replace unavailable blocks or search for better-performing excerpts.

Admission requires every expected sounding note in the voice/block to have a unique corresponding original performed note, equal-duration chord tones, no polyphonic overlap after chord grouping, and exact occupancy of the two bars by the original notes AND EXPLICIT XML rests. Exclude grace notes, ties crossing the outer block edge, unverified XML/CSV note semantics, ambiguous alignment and incomplete voice occupancy. Ties crossing the INNER barline are supported. These restrictions select well-aligned symbolic structure, not typical AMT mistakes; report every attempted block and rejection reason, participating sources and unique-note count. All numeric results are CONDITIONAL on this potentially small subset and must not be compared to #263's full1614-note score.

MusicXML parsing uses Fraction quarter durations; handle divisions, backup/forward, chord cursor semantics, explicit rests, and contiguous tied notes. No external DTD/entities resolution. Unfolded XML and score CSV pitch/duration must agree; never create ground-truth rests merely from observed silence. Adjacent explicit rests are merged for semantic interval comparison. If no supported blocks remain, report blocked rather than label a synthetic fallback as real data.

## Three paired arms x two endpoint representations

Representations: unchanged publisher sustain durations and original MIDI key-release durations, with identical original onsets, pitches and note IDs. Never use a reference-guided mixture.

All arms share the SAME group-level candidate lattice and unary costs:
- start candidates on1/48 quarter within +/-0.25quarter of the median observed chord attack;
- the inherited fixed duration vocabulary, gated log-duration observation loss with original GATES1/.75/.5/1.25, same fixed spelling penalties;
- mean squared start displacement with sigma0.10quarter;
- fixed metrical position penalty0 at multiples1/4quarter,0.15 at1/8,0.30 at1/12,0.50 otherwise;
- finite spellable note fragments across inner barlines and identical tie-fragment cost.
These are hand-set hypotheses, not calibrated probabilities or trained priors.

A) Independent: lowest unary candidate per attack group. Provided voice/boundaries/chord information is identical, but no joint non-overlap/rest constraint. It may create overlapping notes or unspellable rest gaps; report those violations.
B) Joint structure: exact dynamic program over successive end positions, no voice overlap, initial/intermediate/final gaps must be exactly spellable by rests and fill the two bars. No extra cost preferring fewer rests. This tests structural constraints beyond identical unaries.
C) Joint structure + rest notation: same DP plus0.20 times minimum rest-token spelling cost. This separately tests the rest-complexity preference. No other parameter change.

No note pitch/count edits or attack merging. All original performed seconds remain unchanged; only inferred notation coordinates change. Gold written start/duration/rest intervals are passed solely to evaluator, NOT the decoder. Context builder necessarily accesses score structure: disclose this rather than claiming a fully reference-free pipeline. Predictor receives performed observations and supplied topology/boundaries only. Swapping evaluator targets must not change its predictions.

## Metrics and controls

Primary: same-note exact written onset AND duration (inherited1/96-quarter tolerance). Separate onset and duration masks; fixes/damage against independent on paired completed blocks. Report lattice oracle coverage only as a reference-assisted diagnostic, not achieved accuracy. Same grid/radius across all arms.

Explicit-rest semantic interval precision/recall/F1, using original XML rest intervals and one-to-one tolerance matching. Report rest-free block counts, not100% rest accuracy for empty reference. No claim about graphical rest spelling. Check inner-bar crossing/required tie relation per note separately; no full exporter or engraving QA.

Structure validity = no voice overlap plus spellable rest partition. All-bar fill is a constraint check, NOT proof of original-score accuracy. Chords contribute concurrent notes once to occupancy, not sum of every chord tone. Correctness masks and ordered-ID digests permit independent aggregation/damage audit without distributing source scores.

Offline fixtures test chord/backup/forward, repeats ID binding, explicit rests vs missing markup, adjacent rest equivalence, internal tie vs same-pitch reattack, incomplete alignments, exact DP vs exhaustive enumeration, identical lattice unaries, infeasible states, and target-independence.27 new local tests pass BEFORE remote source evaluation. Pinned remote Ruff/tests remain authoritative.

## Stopping/interpretation

No threshold, input selection or weight changes after seeing real-data results. Infrastructure/parser bugs may be fixed only with disclosed regression tests and unchanged musical hypotheses. Successful execution with low coverage is not a broad success. Any gain under provided topology is conditional and must next survive inferred voice/chord grouping, automatically estimated clocks and actual AMT errors. Independent new compositions, mixed audio and editing-time/readability evaluation remain required. No promotion to production from this pilot.

MusicXML semantics consulted: https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/rest/ ; https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/chord/ ; https://www.w3.org/2021/06/musicxml40/musicxml-reference/elements/backup/ .
