# Same-input established beat model vs DSP BPM inference — preregistered CPU study

Issue #252; stacked on draft #256 at fc307315d45cc3d3d6be6fca6c0255e58dece66e.
User requests the next experiment. BPM from rhythmic repetition is the target;
no meter/downbeat inference is required or scored. No main/production edits,
other-session changes, user audio, GPU, training, API keys or paid services.

## Training overlap and the fair comparison boundary

Beat This! final0/small0 were trained on all considered data except GTZAN,
INCLUDING Groove MIDI. They are NOT used as the primary model here. The original
paper v1.0 `groove_midi/8-folds.split` is content-bound by Git blob
0ff7d0954194060597b027c29c2332f894b32aca. Exact GMD audio path is mapped to its
annotation stem. Only a mapped file can select its corresponding `foldN` model.
Upstream dataset.py uses `split.part == self.fold` for validation and the rest
for training; `no_val` must be explicitly false in checkpoint metadata. Any
unmapped source, mismatch, absent metadata or download failure is unavailable,
not secretly run through final0 or counted as incorrect BPM. Keep all planned
inputs in the coverage report and report pairwise comparisons on the identical
admitted subset. Absence from a manifest is not proof of no training overlap.

Validation files can have been used for model selection and related exercises,
performers or compositions may cross folds. This is FILE-held-out validation,
NOT a composition-independent or untouched test of generalization. The 16
source recordings have also been examined in earlier DSP research.

## Frozen inputs and methods

Use EXACT #256 16 WAV files, first min(24s,duration), mono16k float32, same
original archive members/checksums and prior preprocessing. The committed
input receipt stores only IDs, source hashes/cohorts/durations, not true BPM.
Reuse `plans(rows,'audio')`; assert plan/hash/duration identity before any model.
No replacement of inaccessible files by easier recordings. Already drum-kit
recordings (Roland sound module played by humans), NOT full pop mixes/stems.

Unmodified paired baselines: mean8/prior120 and multi-scale consensus/prior120
on (a) detected-hit train and (b) continuous multiband spectral flux. Previous
exact-baseline replay remains enabled. No selective-confidence gate and no new
DSP tuning. Four fixed DSP results; never choose the best per song.

Model: Beat This! source b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c, CPU float32,
Audio2Beats, dbn=False (published minimal postprocessing). Select one checkpoint
ONLY by original validation fold, not results. Ignore returned downbeats. Convert
predicted beat times to BPM as 60/median(diff(beats)); require >=4 finite strictly
increasing beats within the same excerpt and >=4s context. No alias folding,
clipping towards120, truth correction, tempo prior or per-file decoder selection.

Download up to8 required fold checkpoints from official public HTTPS, max90MiB
each and720MiB total. Record actual SHA256/size BEFORE inference and validate
fold/no_val metadata via torch.load(weights_only=True). Published checkpoint
checksums were not independently supplied: hashes attest observed bytes rather
than a claimed pre-existing vendor integrity signature. No weights uploaded.
Code and published weights MIT per upstream, which separately warns about
training-source rights. This research is not a commercial-release legal approval.

## Measures and attribution

Primary nominal BPM within4% on the SAME admitted inputs. Report half/double,
other wrong, insufficient beats, nonadmission, full planned denominators, and
paired corrected/formerly-correct-lost cases. Top candidates are not oracle
success. Report both reused12 and new-to-previous-study4 cohorts, neither is an
untouched test now. Correct BPM does not prove notes/score or first bar accuracy.

No reference BPM, meter, identity or annotation enters model call/beat-to-BPM
conversion. References are attached after all algorithms finish. Fold membership
is used only to determine which checkpoint excluded the file during training.
Report runtime/load time/model hashes/source hashes and all failures. Do not
retune after results. GMD CC BY4.0: Google LLC, Groove MIDI Dataset v1.0.0.

Original MIDI ZIP SHA256 651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e.
WAV strict HTTP206 range reader remains140MiB total; max10MiB/request,55MiB/member.
Compare source info.csv across archives, validate member CRC/size/hash. Full5.11GB
archive is not downloaded or checksum-verified. Only JSON evidence, no source
WAV/MIDI/features/models, leaves the runner. Fold manifest is metadata only.

Pinned Python3.11/numpy1.26.4/scipy1.13.1/mido1.3.3, torch/torchaudio2.7.1+cpu,
einops0.8.1/rotary-embedding-torch0.8.6/soxr0.5.0.post1. One bounded CPU25min job,
2threads, explicit CPU, frozen test+compile+Ruff before inference. Research
workflow on opened/reopened only: documentation pushes do not retrigger work.

## Sources

- https://github.com/CPJKU/beat_this/blob/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c/README.md
- https://github.com/CPJKU/beat_this/blob/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c/beat_this/dataset/dataset.py
- https://github.com/CPJKU/beat_this_annotations/blob/v1.0/groove_midi/8-folds.split
- https://magenta.tensorflow.org/datasets/groove
