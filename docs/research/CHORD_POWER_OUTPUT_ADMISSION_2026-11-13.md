# Power-chord output admission and general harmony comparison

Related: #43, #53, #172, #200. Checked 2026-11-13.

The published LV-Chordia architecture cannot emit power-chord labels with its
`full` vocabulary. The vocabulary contains those labels, but the model's output
head and the decoder's range check exclude them. Increasing the dictionary size
therefore does not resolve the power-chord representation gap under investigation.

## Verified source and executable check

[LV-Chordia revision d8ab9ac](https://github.com/openmirlab/lv-chordia/tree/d8ab9ac99bce081bb79065d717f96e2c3b2099c8)
packages the original ISMIR 2019 system. It is a separate model from ChordFormer.
The repository and checkpoint manifest declare MIT; the five bundled checkpoint
hashes match that manifest. [The metadata receipt](CHORD_POWER_OUTPUT_ADMISSION_2026-11-13.json)
records source, vocabulary, checkpoint, runtime and check-script identities.

The relevant chain is:

1. [The class definitions](https://github.com/openmirlab/lv-chordia/blob/d8ab9ac99bce081bb79065d717f96e2c3b2099c8/lv_chordia/complex_chord.py)
   assign `power=7`; `Chord.to_numpy()` maps the twelve root-position `:5` labels
   to triad indices 73 through 84.
2. [The model](https://github.com/openmirlab/lv-chordia/blob/d8ab9ac99bce081bb79065d717f96e2c3b2099c8/lv_chordia/chordnet_ismir_naive.py)
   fixes `triad_limit=6`. Its triad head has 73 outputs, indexed 0 through 72.
3. [The decoder](https://github.com/openmirlab/lv-chordia/blob/d8ab9ac99bce081bb79065d717f96e2c3b2099c8/lv_chordia/extractors/xhmm_ismir.py)
   drops a label when a component index exceeds the corresponding probability
   head's range in `get_chord_tag_obs`.

An executable check instantiated the declared architecture without loading a
checkpoint or running a neural forward pass. It supplied one frame of uniform
probabilities with the actual head sizes `[73, 13, 4, 4, 3, 3]` to the real decoder.
All twelve power labels existed in the generated template pool, all were excluded
from the eligible output labels, and `C:maj` survived as a positive control. A
second execution reproduced these assertions. The import emitted a missing-ffmpeg
warning; audio loading was outside this check.

## ChordFormer source inspection

[ChordFormer revision 77bec51](https://github.com/mwaseemrandhawa/ChordFormer/tree/77bec5136503c406e34f223f2c9b013f24c80862)
also declares `triad_limit=6`, `power=7`, and the corresponding decoder range
check. Its `full` dictionary includes `C:5`, while its default `submission`
dictionary excludes it. This is a static source finding. The checked recursive
repository tree contained no `.sdict` checkpoint, and the release collection was
empty, despite the README describing bundled checkpoints. ChordFormer was not
installed or inferred in this admission check.

## Decision and limits

These exact pretrained architectures are not admitted as a direct fix for missing
power-chord output. A larger dictionary alone cannot add a missing trained output
class. The admission check assigns neither candidate a zero quality score or a
general rejection. LV-Chordia's subsequent general-harmony experiment is recorded
separately below; ChordFormer inference remains unperformed.

The guitar parts of an arrangement and the complete mixed recording can support
different chord descriptions. This capability check does not establish that every
major/minor label in an acceptance song is musically wrong. Whole-song chord
accuracy, independent reference coverage, final model selection and the five-song
publishing-quality gate remain open. No product setting, source, dependency or
automatic correction changed.

## Subsequent general-harmony CPU experiment

A separate protocol was recorded before audio inference. It tests whether the
same LV-Chordia ensemble improves general chord roots and no-chord coverage,
while preserving the failed power-capability result. The single `full` vocabulary
was fixed before outputs; no vocabulary sweep, source crop, stem input, beat
retiming, training or per-song setting changes were used.

All five complete original mixed WAVs completed with their existing source hashes,
using CPU, two threads and seed 0 per case. The official resident five-model
ensemble/API was used, with source and installed checkpoint hashes verified
against the pinned manifest. All five exited successfully without runtime fixes
or retries. Original inputs were rehashed after execution. The receipt records
113.85 seconds total, including load; this is not a controlled speed comparison
with SheetSage2. The official two-decimal segment outputs extend up to roughly
0.02 seconds beyond source duration and remain unmodified in the private JSON/LAB.

The public metadata retains input/output hashes and aggregate results, not the
musical events. The existing frozen SheetSage2 labels were compared directly with
the new labels, before any notation-grid projection.

### Partial root comparisons

| Reference and timing | S2 root agreement | LV-Chordia root agreement |
| --- | ---: | ---: |
| American whole-chart strict guitar/bass subset, drum fit | 62.4074% | 70.2906% |
| FANCY four community excerpts, authored endpoints | 76.6847% | 89.0472% |
| FANCY four community excerpts, nominal BPM | 76.8560% | 90.5762% |
| Me So Bad chorus, authored endpoints | 82.3601% | 85.9260% |
| Me So Bad chorus, nominal BPM | 80.2576% | 87.6744% |
| American two community excerpts, authored endpoints | 92.0036% | 92.1282% |
| American two community excerpts, nominal BPM | 92.1228% | 92.3203% |

Each percentage is matching-root duration divided by all supported reference
duration, including predictions of N in the denominator. The American whole-chart
subset covers only 42.73885 seconds where both authored rhythm-guitar parts share
a power set and the bass shares its root. N covers 1.14931 seconds of that subset
for S2 and 0.42082 seconds for LV-Chordia. These are arrangement-conditioned root
comparisons, not exact chord-quality agreement or whole-song WCSR.

The existing community-to-source timing projections were frozen before this model
comparison. Unsupported applied/substituted reference chords remain excluded and
counted. FANCY has a 15.623 ms overlap between authored excerpt observations; both
arms retain the same observations as separate excerpt weights, so the summed
reference duration is not unique source-audio coverage. No alignment was optimized
against either chord output.

The gains justify further chord-quality and cached-publication testing. They do
not select a final harmony provider: exact quality/extensions/bass, the two Korean
songs, final-grid damage, whole-song references and human correction cost still
need validation. This run did not add a product option or change defaults.
