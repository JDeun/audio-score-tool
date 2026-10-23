# SheetSage inference integration (research-only)

The executable in `scripts/sheetsage_infer_adapter.py` integrates **SheetSage**
through the independently packaged `sheetsage-infer` API. It does **not**
implement the newer SheetSage-A2S/HookKern architecture; these are distinct
models and must be reported separately in benchmarks.

## Setup

Install `sheetsage-infer` and `music21` into a dedicated Python environment
that can access the selected SheetSage weights. Run the adapter once to
download and verify model assets before scheduling a benchmark.

```bash
python -m pip install sheetsage-infer music21
AST_USAGE_MODE=research python scripts/sheetsage_infer_adapter.py \
  input.wav output.lead_sheet.json
```

For the Tier 2 matrix, set:

```bash
export AST_USAGE_MODE=research
export AST_SHEETSAGE2_ADAPTER="python scripts/sheetsage_infer_adapter.py"
```

The adapter emits timed chord symbols, beat anchors, and meter. Harmony
fusion preserves the AMT notes and annotates MusicXML. The adapter does not
replace an actual end-to-end model evaluation. The SheetSage weights and
associated assets are **CC BY-NC-SA**, so this integration must not run
in commercial mode or be represented as a commercial-ready dependency.

**Benchmark naming:** The current matrix retains historical `sheetsage2`
stage identifiers for compatibility, but runs using this executable must
be attributed to **SheetSage (sheetsage-infer)** in the final report, not
SheetSage-A2S. A native HookKern adapter requires independent implementation
and validation.

The matrix runner uses the executable only if the event JSON is missing.
For reproducible comparisons, preserve the exact model checkpoint SHA256,
runtime version, and event JSON artifacts.
