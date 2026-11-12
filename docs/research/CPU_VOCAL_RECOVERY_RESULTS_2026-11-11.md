# CPU vocal recovery results — partial completion, 2026-11-11

Related PR #239, #200 #214 #215 #172 #34. This report records the completed Basic Pitch experiment. YourMT3 recovery is still running at this report's authoring; no result for that task is inferred from the Basic Pitch result.

## Source and execution

- Workflow [42954128502](https://github.com/JDeun/audio-score-tool/actions/runs/42954128502), `CPU / basic_pitch_decode`, job130305067392: success.
- Experiment PR head `22b289baf40aa5073657c8b73a77eb12316b915b`; actual checkout `c4ea6148b38cb65b5e714cf984b23121246a09df`. These identify different Git objects. Subsequent `db6da51` removes one blank line between first-party imports only, without changing inference, scoring or settings.
- Same original vocadito v3 corpus, 40 recordings, both original-Hz A1/A2 annotations. Basic Pitch0.4.0, ONNX Runtime1.20.1 CPU, same verified pretrained asset as the earlier comparison.
- One neural inference per recording; five preregistered decoders receive independent copies of the SAME neural output. Default decoder replay exactly matches the initial event fingerprint; source audio and raw activation files are unchanged. No training, LLM, reference-driven pitch/time shift or per-recording winner selection.

## Primary results

Each cell is the equal-weight mean over40 recordings x2 annotators. Primary note matching: onset50ms/pitch50cents; offset condition additionally max(50ms,20% reference duration).

| Fixed arm | Pitch+onset F1 | Pitch+onset+offset F1 | Total predicted notes |
|---|---:|---:|---:|
| Default: onset0.5/frame0.3/min127.7ms/Melodia |49.102129%|31.583077%|2,086|
| Minimum note64ms only |48.797592%|29.024821%|3,125|
| Onset threshold0.65 only |54.192265%|37.257207%|1,783|
| Frame threshold0.5 only |44.435609%|27.453087%|1,493|
| No Melodia only |48.907887%|31.468929%|1,936|

Onset0.65 improves the two macro F1 metrics by **5.0901 and5.6741 percentage points** versus the unchanged default. For each metric,35 recordings improve and5 worsen after averaging the two annotators within each recording. Paired-recording bootstrap95% delta intervals are [+3.84,+6.30] and [+4.20,+7.15] percentage points. These exploratory intervals are NOT multiplicity-corrected significance or independent test-set evidence; the corpus has been repeatedly used for development.

Default note precision/recall macro is50.1381%/49.8629%; onset0.65 gives59.5524%/51.2110%. Shortening minimum duration gives41.4870%/61.0184%: it detects more annotated notes but also yields many additional predictions, reducing primary F1. Neural activations are fixed, but decoding can change segmentation; do not describe the higher-threshold arm as merely deleting a subset of original notes.

## Diagnostic interpretation

Default octave-sensitive50ms onset F1 is49.10%; allowing100ms gives59.91%. Folding pitch class at50ms gives49.23%, and onset-only matching at50ms gives56.10%. These are separate sensitivity probes, not corrected predictions or a mutually exclusive error decomposition. In this setting, octave folding alone barely changes the aggregate; onset precision and note segmentation deserve attention alongside pitch. No relaxed metric replaces the primary score.

## Verification performed

Artifact13825524844, `vocal-recovery-basic_pitch_decode-42954128502`, ZIP SHA256:
`6dc61e728c749ebfe8a51b3d4eea94026d18ca2cb6ec59c4e4ff734894cda3b0`.

Downloaded the ZIP and matched its digest against GitHub's artifact metadata. Verified40 distinct planned IDs, no failed cases, all five arms per case. Recomputed every primary macro from the40x2 rows; matched the report to floating-point tolerance. All40 source WAV and both annotation hashes equal the previous completed Basic Pitch baseline artifact. This checks metadata aggregation and provenance; public artifacts do not contain raw predictions for independent rescoring.

The experiment's recovery/scoring safety tests passed in both actual research jobs before inference. Ordinary CI initially failed on one import-formatting blank line; `db6da51` fixed it. CI42954413037 and Research Evidence Contracts42954413123 completed successfully at that commit. No model settings were changed to repair CI.

## Scope and current decision

This is solo-vocal raw note decoding, not the five separated acceptance songs, full multi-instrument audio, final notation/PDF or human correction cost. No product setting or default is changed; main and the other session's PR #236 are untouched. Basic Pitch should not be ruled out solely on its default-decoder result. The improved fixed setting remains a research candidate requiring separate data and end-to-end validation; no final model is selected here.

The YourMT3+Tiny four-arm experiment is separate and unfinished at this snapshot. Complete results must state its own40-case coverage, paired gains/losses and any unchanged or worsened metrics rather than implying that this Basic Pitch improvement transfers to YourMT3.
