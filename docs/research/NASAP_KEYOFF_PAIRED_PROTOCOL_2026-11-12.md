# Fixed-cohort key-release versus publisher sustain duration

Authorized continuation of #262, related #259/#249. Base94aa494dc1badad843014767a2dfdc46eee32a60. Research-only draft, no main/product/default/automatic score changes or other-session modifications. CPU, no training/learned models/GPU/paid API. Do not repeat unit-selection experiments in this study.

## Question and locked controls

Does changing ONLY the observed endpoint representation improve written-duration recovery? Compare publisher-exported duration (often pedal-adjusted) versus raw MIDI note-off at identical onsets and pitches. Neither input is assumed equal to the written score. Original performances, window, note IDs, clock, targets, vocabulary, predictor costs and tolerance remain unchanged.

Use immutable #262 Actions43138389279 artifact13908396922 ZIP SHA2568aae98a772c0a6494ba243ebe0f123d0a3de7e1d4d44108dd5f61cb7ebf170b8, report SHA256ad4ab109f11850ab270bc43310e328d7e5cb9f5f8894af2e6e1975b5e2e6cd4e, source-audit SHA256dc244b40827e34516b8659208175887d76e5464540ffc2cc47a45c6ef42cd09d.

All12 planned source IDs stay in coverage; carry forward the five previously unsupported windows without replacement. Attempt the same seven previously admitted passages,1,702 observations and1,614 aligned evaluation notes. This is paired development evidence chosen after the prior input-semantics finding, NOT a new independent holdout.

Official CPJKU/asap-dataset@4097b45757bed854818cf87e77b92323ebf90615. Every requested original source must match the prior report/source-audit SHA256. Verify inherited predictor SHA256881a0a7544745d5fe50317ca81bca8ea05adce510bbfb2facc46405c65ffa973 and original MIDI-parser Git blob a61a9283daf2c815dbe762e481e1e008f8d2d5a0. No inference changes.

## Admission and invariants

Reconstruct previous CSV-selected observation set exactly before reading score labels. Match each CSV onset/pitch/channel to exactly one original MIDI note within2ms, with one-to-one assignment. Keep CSV onset and pitch fixed; key-duration arm changes its endpoint to the matched physical note-off. Reject ambiguous/unavailable or out-of-clock endpoints for the whole passage, NOT silently dropping notes or clipping. Record onset mapping residual separately.

Use the SAME provided beat clock and quarter origin from #262 (annotated indices8..40). This is privileged-clock MIDI-to-notation evidence, not an audio detector. No new notes become eligible merely because raw key durations are shorter. Confirm exact original observation fingerprint and counts. After predicting, load identical part.csv/align.csv targets and reproduce the prior three CSV method scores before interpreting new results.

Original MIDI parser preserves tempo changes and per-track/channel reattacks; tests cover multiple tracks and tempo messages, ambiguous matches and out-of-window note-off. Original global MIDI note rows are not republished.

## Six arms

Input csv_sustain/key_release x unchanged literal/spelling/articulation. Use imported #262 fit(), VOCAB and evaluation tolerance1/96 quarter (+existing numerical epsilon). No voice information, no costs tuned, no beat-unit inference, no metrical-grid adjustment, no changed source cohort. Every method must preserve note IDs/pitch/onset/attack count; onset predictions must be identical across six arms.

Primary: same-note written-duration accuracy and paired corrected/damaged counts for key_release versus csv_sustain per method. Report passage-equal macro and note-equal micro, onset+duration, correct counts, loss counts, better/worse/equal passages. Also compare articulation against spelling WITHIN the same representation; do not credit input improvements to algorithm changes.

Secondary descriptive stratification: notes with CSV duration >key-held by10ms versus others, frozen before reference inspection. No automatic per-note choice of whichever input matches truth. No p-value/generalization claim on seven correlated passages.

## Preflight representation/metric checks

After freezing predictions, calculate exact vocabulary coverage (1e-7) and evaluation-tolerant coverage (1/96), onset-grid representability and candidate pair ceiling. Unsupported true values remain in full denominator. Do not enlarge vocabulary after seeing their count.

Diagnostic-only: feed true written onset/duration to the unchanged literal quantizer. It must preserve all representable values within the same tolerance; report unsupported values rather than claiming universal identity. This is NOT a new model result. Check variable-tempo seconds->quarter->seconds roundtrip at every original onset/endpoint. This validates coordinate arithmetic, not truth of annotated beats or note alignment.

Retain per-case ordered-ID digest plus correctness/representability bit masks, without raw pitches, onset/duration arrays or original musical source content. This allows independent aggregate and paired-damage recomputation from the output. No product MusicXML/PDF, explicit rests/ties or human editing-time metrics here.

## Execution / decisions

Standard CPU Ubuntu, Python3.11, mido1.3.3/pytest8.4.2/ruff0.16.6. Local runtime has no network access; definitive tests and source execution run in GitHub Actions. Normal ephemeral actions:read token only fetches the old same-repo artifact; no provider credentials. Bound file reads using inherited4MB/file40MB-total reader. No private user audio. Artifact contains derived JSON and this experiment's own source/test code only, not original musical files.

Before PR execution parameters and protocol are committed. If source hash/representation/replay fails, report failure/partial coverage without a new success claim. No changing scientific settings to get a better score. Large paired gain implies representation matters under the provided clock, not that key-off is automatically inferable from audio. Little gain means move to actual voice/rest/measure context rather than keep fitting these seven passages.

Data license is CC BY-NC-SA4.0. Retain attribution to Foscarin et al., ASAP (ISMIR2020) and Peter et al., note-level ASAP alignments (TISMIR2023); no raw redistribution or commercial-use clearance is implied. Do not describe a commercial product as licensed merely because this evaluation is labelled research. Keep product integration blocked pending rights review and independent audio/notation evaluation.
