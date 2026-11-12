# DSP octave hybrid — Basic Pitch completed; YourMT3 pending at this snapshot

PR #247 / #245 / #246. Standard CPU, no product/default/other-branch changes.
This snapshot records actual BP and signal receipts. YourMT3 results must be
reported from its own completed artifact, not inferred from this result.

## Execution and independent receipt audit

Run42992792292, original head81c7f1e811230ba2686f1994e600d3c58d02ccb1,
actual PR checkout d01cf5f1cab34ba7e917b1094a32475c7af6455c.
BP artifact13842388392, ZIP SHA256
`db694d9b5b7282152c97020a36eb79677e6befbb2532aa81a1586574b65a0300`.
Contains only basic_pitch.json and signals.json, not real media/predictions.

The downloaded ZIP digest matched GitHub metadata. All40 source and A1/A2 hashes,
archive and original scorer matched #239. Default/onset0.65 RAW event fingerprints
also matched #239 on40/40 respectively. Recomputed all row-to-macro arithmetic,
improved/worse counts, conditional anchor totals and count conservation. The
experimental library/runner source hashes match the locally tested files.
This is receipt/hash verification, not independent re-inference or raw rescoring.
33 local tests passed; remote lint/contract and signal steps passed as well.

## Basic Pitch paired note outcome: unchanged, zero applicable proposals

| Base decoder | Arm | Notes | Pitch changes | Onset F1 | With offset F1 |
|---|---|---:|---:|---:|---:|
| default | raw |2086|0|49.102129%|31.583077%|
| default | pYIN octave |2086|0|49.102129%|31.583077%|
| default | corroborated octave |2086|0|49.102129%|31.583077%|
| onset0.65 | raw |1783|0|54.192265%|37.257207%|
| onset0.65 | pYIN octave |1783|0|54.192265%|37.257207%|
| onset0.65 | corroborated octave |1783|0|54.192265%|37.257207%|

All40 recordings completed with both decoders and three arms. No per-recording
score changes. Since there were ZERO eligible octave proposals, real-recording
harmonic acceptance was not exercised. Zero harm here is not proof of safe
correction: nothing was changed. This does not rule out octave errors among
rejected/unstable/overlapping notes or other data. The test gives no positive
hybrid efficacy evidence and no real-proposal estimate of the harmonic gate.

| Fixed screening outcome | Default | Onset0.65 |
|---|---:|---:|
| short/drum |416|292|
| overlapping model events |282|229|
| insufficient voiced frames |24|17|
| low local voicing probability |235|199|
| unstable/fractional pitch |433|427|
| stable pitch agrees |693|619|
| stable disagreement other than one octave |3|0|
| octave proposed |0|0|

These are sequential screening categories, not confirmed music-error labels.
The onset0.65 setting is a prior development selection, not selected by this run.
The reproduced baseline benefit is NOT caused by the new octave selector.

## Voicing-mask diagnostic: fewer false alarms, too many missed voiced frames

This separate arm masks raw pYIN using probability, energy and period gates. It
is NOT applied to notes or used as a hidden replacement of octave-proposal input.
Equal recording macro on the full annotated timeline:

| Frame metric | pYIN raw | Masked |
|---|---:|---:|
| Raw Pitch Accuracy |80.528736%|58.503907%|
| Overall Accuracy |72.524536%|70.534870%|
| Voicing Recall |98.032028%|62.887775%|
| Voicing False Alarm |43.519268%|6.179035%|
| Predicted voiced fraction |79.318244%|43.524038%|

False-alarm reduction alone is not success. Many genuinely voiced frames are
removed; full-timeline pitch/overall metrics worsen. Do not promote this fixed
mask as a better F0 tracker. Do not report retained-frame-only agreement as whole
recording accuracy. No thresholds were adjusted after inspecting these results.

## Owned signal diagnostics: boundary hypothesis supported in controlled tones

Seven pure tones each tested with fmax880 and1760. The five tones from65.406Hz
through830.609Hz were within50cents at both ranges on the examined interiors.
The880Hz tone was tracked at440Hz with upper880, and880Hz with upper1760. The
932.328Hz tone was tracked at466.164Hz versus932.328Hz respectively. This is
controlled range sensitivity, not proof of the exact upstream implementation
cause or evidence that widening the range improves real songs. The corpus
continued to use55..880Hz; no post-result parameter change occurred.

Four designed wrong-octave controls (pure-tone upward/downward errors, dominant
second harmonic, missing fundamental with odd harmonic) were restored by the
hybrid. Correct220 and a real octave leap were unchanged. Silence/noise prevented
correction but their supplied note was not deleted: this pitch-only method is
not a silence note-removal algorithm.

Even-only440+880Hz produced a change from supplied220Hz to440Hz. That signal has
no evidence proving an intended220Hz source note. Count it as an ambiguity
illustration, not an unambiguous musical correction or a successful recovery of
hidden source intention. Controlled successes do not establish real-song gains.

## Decision and remaining work

BP gives no basis to deploy this hybrid; applicable proposal count is zero.
The voicing mask is not promoted because recall loss outweighs its alarm benefit
on the reported full-timeline metrics. Do not loosen gates on these40 recordings
merely to manufacture more edits. YourMT3 is separately in progress at this
snapshot. Keep #245 open and #247 draft; full product/notation/heldout/edit-cost
approval is not implied by successful execution or unchanged scores.
