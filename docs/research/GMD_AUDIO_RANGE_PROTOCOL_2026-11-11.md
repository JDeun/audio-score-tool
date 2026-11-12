# GMD subset real-waveform onset feasibility — preregistered protocol

Research-only follow-up to #252/#253. Based on #253 head
\`94c085222c0becb86a59cc924f58075dce154e40\`.
No main merge, product edit, API credentials, training, GPU or paid model.

## Research question

After evaluating human-played drum **MIDI events** as idealized known role
inputs, can an untrained, fixed DSP band-energy/flux method detect actual kick/
backbeat events in the paired recorded **drum-kit WAV**? How much of the
separate meter/phase analysis survives detected instead of supplied events?
No mixed pop/rock recordings, no harmony instrument source separation.

## Source/rights and byte-bounded access

Original Magenta GMD v1.0.0 (CC BY 4.0, Google LLC, attribution required)
has ~4.76GB ZIP of aligned human MIDI + Roland TD-11 synthesized drum-kit
audio; an original 3.11MB MIDI-only archive includes exact dataset metadata.
Full ZIP SHA256 publisher value
\`21559feb2f1c96ca53988fd4d7060b1f2afe1d854fb2a8dcea5ff95cf3cce7e9\`.
We **do not download/check this whole archive**. Only range-read specific
ZIP members; require HTTP 206/Content-Range and enforce:
- remote full ZIP within 4–6 GiB; per HTTP range ≤10MiB;
- total bytes fetched ≤140MiB; each WAV compressed/uncompressed ≤55MiB;
- chunked deflate extraction with standard zipfile CRC verification;
- complete original \`info.csv\` SHA match across original MIDI-only and
  full ZIP, which protects metadata linkage but **not full ZIP integrity**.
- any unsupported byte range, absent member, excessive size, source mismatch
  or altered metadata is reported as **blocked/not evaluated**. Never fall
  back to downloading 4.76GB or replacing missing WAV with MIDI synth.

Select by **metadata only** before inspecting any audio: first up to two
SHA-ordered test 4/4 beat files 4–28s, one test 4/4 fill 4–15s, and one
validation 3/4 beat 4–165s. This limited exploratory selection is not
a representative genre/tempo benchmark. The 3/4 file is not test split.

## Fixed DSP hypothesis

Decode 16-bit PCM WAV; analyze only first 12 seconds.
Resample to 16k with scipy signal polyphase. At 1024 FFT/160 hop, compute
positive spectral changes in 45–210Hz (low) and 400–6000Hz (high), clip by
each band's 99th percentile, take union, use robust local peak threshold,
>=85ms refractory period. Assign low-dominant peaks to kick, others to
backbeat. This simple heuristic may confuse hi-hat/cymbals/snare; NO
pitch labels or MIDI events/metadata are available to the detector.

Use original corresponding MIDI kick35/36 and rim/snare/clap37-40 ONLY for
evaluation, not feature/threshold/peak selection. Peak times evaluated with
one-to-one ±50ms tolerance. Report micro/each-track precision recall F1,
false positives/negatives and both unconditional and role-aware counts.
Compare **given BPM+meter** phase on (a) original MIDI hits within excerpt,
(b) detected WAV peaks, separately. Supplied BPM and meter do NOT count as
automatic extraction wins; MIDI original tick0 is NOT independently annotated
acoustic downbeat.

Keep every preselected case including no detected peaks, no listed WAV or
unsupported format. Report a failure/status, never missing-as-zero.
No post-result tuning, adaptive thresholds per song, manual selection of
successful WAVs or claims that this proves full-band stems. Large WAV study,
3/4 test holdout, 6/8, time-varying beat, pickups and ambiguous phase remain
future tasks.

## Reproducibility and disclosure

CI installs fixed Python3.11, numpy1.26.4 scipy1.13.1, mido1.3.3, pytest8.4.2
and ruff0.16.6. CPU2threads. Workflow is one bounded PR-open research job.
Only JSON with member CRC/size/SHA, original ZIP SHA (metadata-only archive),
source HEAD/ranged byte counts, runtime, test status and scores may be uploaded.
Do not upload raw WAV/MIDI, other-song content or generated audio.
Abort range access early if the host rejects HTTP 206; no full-file fallback.
This is a research experiment; product model and automatic score remain unchanged.
