# Development-only rest-evidence ablation after #264/#265

Related #249/#259; consolidation #266 is separate from production approval.
Use ONLY the original #264 development cohort, not the #265 validation music.
No audio/model inference, GPU, training, metadata provider, score auto-edit or runtime-default change.

## Frozen source and comparison

Original development artifact13911212291/run43144673880 ZIP SHA256224dd43e067bdfbb87d1e0ef9c1af48baaf5ccd385c259c388ab69f543fd55e4; report281bad7ffb899a1e0ce67a148c832cb56cb7ddd377aa0e94c0abddaf19664b59. Same12 source statuses; only prior5 completed works/38 blocks/655 notes are attempted. Previous exclusions remain excluded; no replacement. Prior byte-hashed original source and XML, decoder/parser code and all6 per-block control masks/rest counts must reproduce. Same privileged beat clock, quarter unit, bar boundaries, voice/chord membership and complete aligned note inventory remain supplied. This is NOT an automatic audio or voice-inference experiment.

Keep old independent / joint_structure / joint_rest_cost for both CSV-sustain and MIDI-key-release unary inputs. Add two fixed hypotheses to the same rest-cost decoder:
1. soft evidence: add8.0 cost per quarter-unit where a notated note covers a candidate quiet core;
2. hard evidence: reject note candidates covering any quiet core; no legal path means unavailable, never silently fall back to an unprotected output.

## Quiet evidence — no target rest labels

Use both observed endpoint representations, always available in this paired diagnostic. Union their sounding intervals in the supplied voice/chord block. Retain only INTERNAL unoccupied intervals of at least0.25 quarter units; trim1/16 quarter from each edge. Lead/trailing silence at crop boundaries is not used. Longer pedal sustain vetoes a key-only gap. Inputs remain unchanged. This is performed-event quiet evidence, not a proven intended rest; a staccato articulation can still create a misleading gap. No unseen waveform rest detector is claimed. New arms have additional paired-endpoint evidence; do not attribute differences solely to a new search algorithm.

Same candidate generation and unary costs as #264. Soft adds a fixed cost; hard prunes the same lattice. Both use exactly the old rest-partition DP. Zero evidence must reproduce the old rest-cost prediction/cost exactly. Tests check physical identity, zero-evidence identity, no target arguments, bad inputs, hard-infeasibility and exact search versus exhaustive enumeration. Local113 inherited/new tests passed before real evaluation; remote pinned checks pending.

## Reporting and decisions

10 arms per block (6controls+4new). Report exact onset/duration/pair counts and masks, paired fixes/damage against the rest-cost control, explicit XML rest interval P/R/F1, true-rest overlap, false-rest time and erased-rest time. Audit candidate evidence overlap with true rests ONLY after predictions. Report common-arm denominators and hard-guard unavailability; do not drop failed blocks from total coverage. A good note score is not complete-score correctness. No post-result weight/gap threshold adjustments or selection of whichever arm wins per piece.

This is a new DEVELOPMENT hypothesis motivated by prior failures, not independent validation. Do not reopen #265 musical inputs or tune against its failure example. Positive development results would still require a separate predeclared evaluation. No rendered score/PDF/listening or editing-time claim. All source/music arrays stay on runner; only derived masks/counts/hashes and our code are uploaded.

Dataset: (n)ASAP CPJKU/asap-dataset@4097b45757bed854818cf87e77b92323ebf90615. CC BY-NC-SA4.0, attribution Foscarin et al.(ISMIR2020), Peter et al.(TISMIR2023). No commercial data-use clearance or data bundling implied. Keep quality issues open. Bounded20min CPU Actions; source reads via existing4MB/file40MB budget; no external credentials beyond read-only same-repository Actions artifact access.