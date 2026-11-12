# Bar-sum articulation and synthesized-wave accent follow-up — completed CPU run

Issue #249; draft PR #251, stacked on draft #250. **No product/default, main,
existing research branch, user audio, GPU, API, credentials, training or automatic
correction was changed.** This is an authored **symbolic** notation experiment with
synthetically rendered other-part audio, not real AMT or real downbeat recovery.

## Reproducible execution and verification

- First PR-open run \`43025819793\` failed in regression tests before study
  evaluation: a single-case aggregator test encountered an empty profile group.
  Corrected that bookkeeping guard, not any scoring/model parameters.
- Successful Actions run [43026055229](https://github.com/JDeun/audio-score-tool/actions/runs/43026055229),
  job \`130540926877\`: pinned Python3.11 + numpy1.26.4, Ruff, compile,
  **43 regression tests passed** (old21 + new22), and all 72 planned
  combinations with 6 arms completed. Research Evidence Contracts is separate.
- Exact experiment script checkout \`b660e51ad3f06de9d2db412c3caeac7f7bad7659\`
  (the PR merge checkout for the successful run), while the branch head was
  \`9e7b7d85c0e2557b700cbfd102fa46048be294b0\`; these are distinct objects.
- Artifact \`13856823217\` ZIP SHA256
  \`0552ec694707e5795acd4aad9f33333b193e6f434443f332821c7cf5faac3d09\`.
  Sole report.json SHA256
  \`4030bc18a26f7524779709e2d8c3b685629a78d6906bc6a68034e7ff7e54e4eb\`.
  Digest matched GitHub Actions metadata. Independently checked 72 unique
  planned IDs, each 6 arms/scored, per-case note-id metrics, reported means,
  phase correct/wrong/abstained arithmetic, and 978 observation count.
- The **48 old-profile original baseline scores match #250's stored receipt
  exactly** for all four notation metrics. Report contains source hashes
  and fixed gate hypotheses, not audio/weights/user songs.
- Receipt arithmetic and provenance were checked; this does **not** mean
  new real-audio re-inference, professional music proofreading, or human edit
  time measurement was performed.

## Known-phase written onset+duration recovery

Each case has **correct pitch, note count/attack identity, meter, BPM/beat unit**.
Three duration fractions were permitted: sounding/notated = 1.0/0.75/0.5 with
fixed edit penalties 0/.09/.17. The correct bar phase was provided to BOTH
methods; phase quality is not part of this table.

| Recovered notation metric, case-equal mean | Existing #250 joint+notation | + latent sounding-duration gates |
| --- | ---: | ---: |
| Exact written onset AND duration | **38.5602%** | **46.4787%** |
| Exact written onset | **73.2289%** | **73.1474%** |
| Exact written duration | **47.0931%** | **56.0837%** |
| Exact rest interval F1 | **23.0724%** | **25.0994%** |
| Bar/voice structural validity | **72/72** | **72/72** |

Exact onset+duration: +7.9184 percentage points on these 72 correlated cases.
Changes: **34 improved, 6 worsened, 32 equal**. By note ID, **93 previously
wrong pairs became exact, while 13 previously correct pairs became wrong**.
The twelve completely clean cases stayed 100% exact in both versions.

| Profile (12 phrases per profile) | Old note-pair exact | + gate candidates |
| --- | ---: | ---: |
| clean |100.00%|100.00%|
| timing jitter |44.18%|46.62%|
| earlier staccato60% gate |4.44%|25.94%|
| weak/flat accent + jitter |53.62%|50.94%|
| new mixed gates |20.08%|28.96%|
| new variable short gate |9.03%|26.41%|

**Main result:** modelling sounding vs written duration meaningfully recovers
some staccato/mixed durations, but error and damage remain significant.
The prior synthetic staccato failure motivated the gate candidates: this is
an *informed research modification*, NOT an unbiased test of a calibrated model.
The 24 new generated variants still reuse the same 12 authored phrases. The
improvement was **not** achieved by knowing an individual note's true gate.

## Unknown downbeat / pickup phase

Phases were NOT passed to these four arms. The last two use a waveform-derived
bass transient strength extracted from a **known-phase generated percussion
waveform**. Ground-truth phase was used to synthesize the wave only, not
passed directly as a downbeat label to the selector. This is an easy controlled
source, not recorded band/polyphonic audio.

| Unknown-phase selector | Correct /72 | Wrong /72 | Abstained /72 | True phase retained |
| --- | ---: | ---: | ---: | ---: |
| old, no accent |1|5|66|39|
| + gate, no accent |0|5|67|39|
| old + audio-derived synthetic accents |**40**|20|12|49|
| + gate + same audio-derived accents |38|21|13|47|

The synthetic audio feature is informative compared to no accents, but has
**many wrong or ambiguous phase assignments**. In this controlled setting,
the articulation model actually lowers the correct-phase count from 40 to38
on the same audio evidence. Do NOT interpret a conditional success rate
over decided cases as whole-input accuracy, and do not call the waveform
synthesis a deployed downbeat detector. Nontrivial phase identifiability
and pickup ambiguity remain.

## Interpretation and next gate

1. Duration articulation is the more promising correction target; **not**
   a final notation engine. Keep raw performed timing and note IDs unchanged.
   A fixed gate lattice still cannot uniquely distinguish an articulated
   quarter from eighth+rest when the sounding waveforms coincide.
2. Next, obtain a verified *real* aligned score–performance dataset, with
   a reference for both performed note times and written durations plus
   role/voice/tempo/pickup. ASAP is a candidate for rights review (its data
   license is CC BY-NC-SA and its domain is classical polyphonic piano). No
   dataset was downloaded/admitted in this experiment.
3. Test actual **audio-derived** beats/downbeats with imperfect stems and
   varied tempi. Don't treat known phase or synthetic bass accents as real
   source features. Include held-out tunes, pickup/no-pickup, rest and
   strong/weak beat variations.
4. The **sounding duration** observation model needs calibration on permitted
   development performances; compare a stronger baseline and quantify clean
   note damage under this new representation. Then check final
   MusicXML/PDF rest/tie/tuplet readability and measured editing time.
5. Keep this PR draft, #249/#200/#34 open; do not adopt any automatic
   duration, rest or downbeat edits on product input. No claim of improvement
   to the earlier real vocadito note F1 or mixed-source audio-to-score accuracy.
