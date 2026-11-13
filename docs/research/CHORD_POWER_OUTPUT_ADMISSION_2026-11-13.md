# Power-chord output admission

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
class. Their general chord-recognition accuracy remains unmeasured here; neither
candidate receives a zero quality score or a general rejection.

The guitar parts of an arrangement and the complete mixed recording can support
different chord descriptions. This capability check does not establish that every
major/minor label in an acceptance song is musically wrong. Whole-song chord
accuracy, independent reference coverage, final model selection and the five-song
publishing-quality gate remain open. No product setting, source, dependency or
automatic correction changed.
