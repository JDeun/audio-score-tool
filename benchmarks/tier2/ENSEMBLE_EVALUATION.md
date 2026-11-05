# Tier 2 AMT ensemble reference evaluation

**Scope:** #56. This evaluates *independent, licensed MIDI references* against each AMT candidate and the conservative note-consensus result. Prediction-vs-prediction agreement is not a reference-quality metric.

## Inputs and execution

A Tier 2 corpus manifest with one independent reference MIDI per case, and two candidate prediction directories with `tier2-prediction-provenance.json` and `<case-id>.mid` files. Corpus/version and ordered case IDs must match. Candidate IDs must differ, even when the underlying runner is the same MT3-Infer executable.

```bash
uv run --frozen python scripts/evaluate_tier2_ensemble.py \
  /secure/tier2/manifest.json \
  --corpus-root /secure/tier2 \
  --first-root /secure/tier2/runs/yourmt3 \
  --second-root /secure/tier2/runs/mr-mt3 \
  --output-root /secure/tier2/ensemble-evaluation \
  --onset-tolerance 0.09 \
  --min-overlap 0.35 \
  --metric-onset-tolerance 0.05
```

This creates `ensemble-evaluation.json` and one consensus MIDI per case. Reported per-case information: source/reference SHA-256, source and consensus note counts, note precision/recall/F1, onset/offset MAE, instrument-aware precision/recall/F1, matched-note counts and the **consensus fusion** runtime. Each candidate's mean metrics and empty-result fraction are also included.

The tool does not execute AMT inference, transcribe raw audio, or measure human corrections; `model_inference_runtime_seconds` and `human_publish_metrics` are explicitly `null`. The value `commercial_baseline_approved` is always `false`. Compare human publish time and total edits via the existing Tier 2 benchmark reports and release quality approval protocol (#34).

## Failure and legal boundaries

- Every case needs an independent MIDI reference on the configured private corpus root; absent predictions or references fail before publishing a report.
- A candidate provenance mismatch or duplicate engine ID is rejected. Do not use two directories reporting the same engine identity to manufacture a comparison.
- Note overlap between candidate outputs is only a **consensus strategy**. It may improve precision while lowering recall; empirical gains must be demonstrated using genuine reference-annotated audio.
- Consensus and both base candidates are compared under one fixed onset tolerance. Aggregate values are averages of case-level metrics, not pooled note scores.
- The source audio and private references must remain outside the public GitHub repository/artifacts. Ensure the operator has lawful rights and an acceptable provenance trail; this tool does not certify ownership or redistribute media.
- Human publication time, MIDI export, multi-part MusicXML and commercial licenses remain separate acceptance gates. SheetSage2/MuScriptor weights with NC restrictions must never be treated as commercially cleared by this evaluation.

See [Tier 2 benchmark README](README.md) and issues [#34](https://github.com/JDeun/audio-score-tool/issues/34), [#56](https://github.com/JDeun/audio-score-tool/issues/56), [#57](https://github.com/JDeun/audio-score-tool/issues/57).
