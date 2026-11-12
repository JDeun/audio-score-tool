# Real score–performance duration and unit pilot — fixed before evaluation

Related #259/#249/#261. Base #261 head 0dc3157f8bbc1fcb7307d53c80c73c52c00bcf39. Research-only isolated draft: no main, product defaults, automatic score changes or other-session branches. CPU, no learned weights/training/GPU/paid APIs/user recordings.

## Question and scope

Move beyond the 12 reused drum recordings and synthetic score fixtures. On actual human piano MIDI performances aligned note-by-note to written scores, test (1) whether allowing performed duration to differ from written duration improves note-value recovery, and (2) whether those performed durations help select half/normal/double pulse units without supplying reference written durations.

This is NOT audio transcription, beat tracking, automatic voice assignment, rendered notation or human editing-time evaluation. A privileged annotated beat clock is supplied to isolate rhythm interpretation. Half/normal/double pulse coordinates are constructed from that clock, not outputs of an audio detector. A positive score cannot approve the full audio-to-score pipeline.

## Sources and rights

Official (n)ASAP, CPJKU/asap-dataset commit 4097b45757bed854818cf87e77b92323ebf90615. Metadata Git blob f9b655ca92b3d88febab09763e7ed3b74c2c7878 must match before selection. Use publisher-exported parangonada_data/ppart.csv (human performance), part.csv (written score), align.csv (note alignment), and original performance beat TSV. Source paths/bytes/SHA256 are retained; no original MIDI, score, note arrays or audio are redistributed.

Attribution: Foscarin et al., ASAP, ISMIR 2020; Peter et al., Automatic Note-Level Score-to-Performance Alignments in the ASAP Dataset, TISMIR 2023. Dataset CC BY-NC-SA 4.0. This is isolated noncommercial research evidence, NOT commercial licensing clearance or authorization to bundle these data in a released product. Original publisher annotations/alignments have limitations and are not assumed infallible.

## Frozen selection and admission

Sort robust_note_alignment=1 rows by SHA256('nasap-duration-v1/'+midi_performance), take first12 with unique (composer,title), maximum2 compositions per composer. No replacement after failures. All12 planned IDs written before any source prediction. Source requests only pinned official raw GitHub HTTPS, at most4MB per file and40MB total.

Use annotated beats indices8..40 (32 beat intervals), not an outcome-selected excerpt. Support constant2/4,3/4,4/4 only. Other meters, beat irregularity bR, insufficient context, inconsistent exported clock coordinates or missing data remain unavailable in full coverage. Verify exported last_beat timestamps against TSV and constant integer quarter offset. Do not silently call compound beats quarter notes.

Predict using ALL positive performed notes wholly within the window, including unmatched notes. Score only unique robust alignment matches with matching pitch, positive written duration and score onset in the window. Report observed/matched/excluded counts. No pitch or note-count editing. Polyphony remains; reference voice is NOT used in the automatic arms.

## Fixed duration experiment (correct quarter unit provided)

All methods share original performed notes, annotated variable-tempo clock and a fixed vocabulary (powers-of-two durations1/16..8 quarters, dotted and triplet variants). All onset fits use1/48 of an observed pulse. Compare:
- literal nearest duration;
- log-duration fit plus a fixed compact-spelling prior;
- same fit with latent performed/written ratios1,.75,.5,1.25 and penalties0,.015,.030,.020;
- separate privileged voice diagnostic: same articulation fit, plus subsequent performed onsets grouped using REFERENCE voice membership. Voice labels are provided here; this is not audio-only inference.

Exact note-value/onset tolerance1/96 quarter; report macro and micro, onset+duration joint accuracy, gains and damage versus literal nearest. No claim these parameters are calibrated. No refitting after seeing results. MIDI duration is a performed key-event duration, not necessarily acoustic sustain under pedal.

The exported part.csv does not contain explicit MusicXML rests. The voice diagnostic uses possible gaps/overlaps as a preference, not known rest durations. Explicit rest accuracy, complete bar reconstruction and readable MusicXML/PDF remain UNMEASURED.

## Fixed unit-selection experiment

For EACH same real passage construct three observed pulse-coordinate scales whose true quarter-per-pulse is0.5,1,2. These are correlated controlled variants, not36 independent recordings. Only performance pitch/onset/duration and the observed pulse rate go into selection. Reference written note values are loaded only after blind predictions have been made.

Four selectors: keep unit1; broad120QPM preference; performed-duration likelihood plus fixed spelling prior; same with privileged voice grouping. Generate all three candidates and never pick a reference-assisted winner. Exact tied costs abstain. Report correctly chosen unit, wrong unit and abstention across all3 variants, eligible source count and full planned denominator. Do not equate convention agreement with physical-rhythm correctness.

Evaluation labels and alignment IDs are used only after automatic predictions. Recompute automatic results after loading voice labels and verify they remain unchanged. Keep physical observations immutable. Identical observations with different written conventions remain an identifiability control.

## Execution and reporting

Standard Ubuntu CPU / Python3.11; stdlib predictor/data code; pinned pytest8.4.2 and ruff0.16.6. Local29 offline tests pass before first real execution. Remote lint/compile/test then one bounded15min evaluation. All unavailable sources remain documented; no missing-as-zero average or claim that successful infrastructure implies scientific improvement. Only derived JSON receipt is uploaded. Source/code/protocol SHA256 plus settings and per-source counts retained.

A next gate is a broader independently selected performance set and an actual audio-derived clock, then real note/rest reconstruction. These outcomes cannot establish generalization to mixed popular songs, removal of AMT errors, or release readiness.
