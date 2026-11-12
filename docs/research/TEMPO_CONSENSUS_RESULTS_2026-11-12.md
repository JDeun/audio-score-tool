# Completed tempo-only consensus and alias abstention study

Issue #252 / draft PR #256, stacked on #255. No main merge, product/default edits,
automatic score changes, user audio, API calls/credentials, GPU or training.
This measures BPM from repeated rhythmic activity, NOT bar starts or notation.

## Execution and independent receipt audit

- Actions https://github.com/JDeun/audio-score-tool/actions/runs/43118256045
  succeeded for MIDI job130851753828 and audio job130851754335. Pinned install,
  Ruff, compile and21 unit tests passed before each actual evaluation.
- Experimental head4658a7e5c1ef29eabf51140ae0e249ec78e767cb;
  actual PR merge checkout7e7354cb705e5abcb34de56573e2df45aa642d40.
- MIDI artifact13899093469 ZIP SHA256
  77c5ee752eb49ce52cbf435d8ee03cab537aee8c6776ee21e04c1faa2efbedfe;
  report JSON f484d0b911910fa222205fffc764430597db017c9e956e54b5e7656c28391964.
- Audio artifact13898608944 ZIP SHA256
  50d1e8173a95883adb40c7fa7ff706e23e4fa8c0df0ed0584a14103de978d744;
  report JSON b63efe6ef6b3baa10ba4f3a7ce0b3c724373cf167e1a1cd9809dba55375da587.
- ZIP digests matched Actions metadata. Recomputed all1976 MIDI method evaluations
  and128 audio evaluations, every grouped numerator/denominator, conditional
  precision, coverage, half/double, top3 recall, correction/loss and paired context
  counts independently from the JSON rows. These repeated evaluations are NOT
  independent recordings. All166 MIDI and16 WAV planned cases completed.
- New core, runner, tests and protocol hashes exactly match locally tested files.
  Earlier source/observation hashes match on all134 reused MIDI and12 reused WAV
  recordings. The old baseline's BPM, status and top3 BPMs exactly reproduce #255;
 183 MIDI candidate confidence scores differ by at most1.11e-16 (floating point),
  no ranking/metric changes. WAV candidate scores match exactly. Per-input runtime
  replay also checked the earlier original _acf_curve implementation.
- Audio fetched78,189,118 bytes in42 strict206 range requests, below140MiB budget.
  Full5.11GB ZIP was not downloaded or SHA-verified; metadata linkage/memberCRC/SHA
  checked. Raw source WAV/MIDI/envelopes were not published.
- This is an independent provenance/arithmetic audit, NOT a second raw-audio
  inference run or musician review. Full product CI is outside this research check.

## Fixed comparison, without reference BPM

The prior method ALREADY averaged8s windows every4s. New consensus aggregates
normalized4/8/12s score curves with per-scale median/mean and equal scale weights.
Both use the SAME broad120BPM preference, not the song's tempo. Also apply the
SAME selective policy to both: enough informative windows/scales, stable winner,
adequate margin and no similarly strong half/double rival. No post-result tuning.

All predictors receive rhythmic envelopes ONLY: no nominal BPM, meter, downbeat,
reference event labels (for WAV) or recording name. Nominal correct=within4%;
half/double values remain errors. Conditional accuracy cannot conceal abstention.

## Real drum-kit WAV, same first up to24s

GMD is human drumming recorded from a Roland sound module, not full-band mixes.
12 files are reused from #255; four disjoint validation4/4 beat files are new to
this experiment. Related exercises/performers may overlap, so this is not a
representative composition/performer-independent benchmark. One reused file is
3/4 validation; never claim official-test3/4 coverage.

| Input representation | Cohort | Old mean8 correct | New consensus correct |
|---|---|---:|---:|
| detected hit timing, roles ignored | reused12 |7/12|8/12|
| detected hit timing, roles ignored | new validation4 |1/4|1/4|
| detected hit timing, roles ignored | combined16 |8/16|9/16|
| continuous spectral flux, no hit classification | reused12 |6/12|7/12|
| continuous spectral flux, no hit classification | new validation4 |3/4|3/4|
| continuous spectral flux, no hit classification | combined16 |9/16|10/16|

Do NOT compare the new16-case rate with the old12-case rate as if matched data.
The improvement on reused12 is ONE recording under both representations, not
several independent successes. No added-validation case changed its BPM.

Concrete source drummer7/session3/86: nominal93, old detected182 ->new93;
old continuous184 ->new93. But drummer7/session3/73 also has nominal93:
detected182 ->64, changing a half/double error into an ordinary error, NOT a fix.
Detected16: half/double6->4, ordinary2->3, correct8->9. Merely reducing the
half/double count exaggerates improvement unless all error types are shown.

## Selective output did not reliably improve audio safety

| Input/method | Accepted /16 | Correct /16 | Wrong accepted | Abstained |
|---|---:|---:|---:|---:|
| detected / old |16|8|8|0|
| detected / consensus |16|9|7|0|
| detected / old + selective |11|7|4|5|
| detected / consensus + selective |11|7|4|5|
| continuous / old |16|9|7|0|
| continuous / consensus |16|10|6|0|
| continuous / old + selective |10|6|4|6|
| continuous / consensus + selective |9|5|4|7|

For consensus detected input, accepted precision7/11=63.64%, coverage11/16=68.75%,
correct/all16=43.75%. This is not an accuracy increase to63.64% over all inputs.
For consensus continuous input, accepted precision5/9=55.56% is LOWER than
unfiltered10/16=62.5%; the guard rejects correct answers while still accepting
wrong ones. Do not enable this uncalibrated confidence/abstention rule in product.

## MIDI known-role diagnostic, first up to24s

Role identity is supplied by MIDI note numbers. This is not drum extraction
accuracy. BPM metadata is used only AFTER predictions; MIDI tempo map is needed
to convert ticks to observed seconds.

| Cohort, kick/backbeat | Files | Too short | Old correct | New consensus correct |
|---|---:|---:|---:|---:|
| reused official test4/4 |129|42|57|59|
| new validation4/4 |32|17|6|7|
| reused non-test3/4 |5|0|1|1|

All short clips stay in denominators. In test129, old -> consensus repairs2
recordings with no formerly nominal-correct loss. New32 repairs1 with no loss.
The other role representation including hats remains in the full receipt;
these role-specific outcomes must not be selectively mixed into an oracle model.

Test129 consensus selective:55 estimated,46 correct,9 wrong,32 abstained,
42 too short. Accepted precision46/55=83.64% with coverage55/129=42.64%; only
46/129 receive a correct answer, fewer than the unfiltered59/129. Distinguish
risk reduction from improved all-input correctness.

## Longer observation is a separate paired comparison

Only recordings actually longer than24s enter this comparison; same IDs, role
input and model under24s vs min(60s,source length). Not a comparison of different
sets of easy/long files. It is MIDI evidence, not new longer WAV analysis.

| Eligible source cohort | N | Old correct24 ->up to60 | Consensus correct24 ->up to60 |
|---|---:|---:|---:|
| reused official test |66|47 ->50|49 ->51|
| new validation4/4 |10|6 ->7|7 ->7|
| reused non-test3/4 |5|1 ->0|1 ->0|

For test66, old repairs4 and loses1 correct; consensus repairs3 and loses1.
Longer context is mildly useful here, not uniformly so. Selective consensus on
that SAME66 instead changes41 ->37 correct (one gained, five lost), illustrating
that longer context and aggressive agreement filters can conflict.

## Decision

Multi-scale agreement is a modest research improvement, not a solution to nominal
beat-level ambiguity. Current prior still sometimes confidently prefers a wrong
half/double or other metrical rate. Do not replace the product BPM policy or
activate the selective gate based on these limited results.

Keep the exact successful/failed hypotheses and source versions; do not keep
changing thresholds on these cases and relabel them independent tests. Next
priorities are a same-input established beat/tempo-model comparison, then licensed
mixed music versus separated drums, and optionally authorized exact-recording
metadata for non-oracle reranking. None of this demonstrates improved note F1,
barline/pickup recovery, MusicXML/PDF readability or reduced human editing time.
Keep #256 draft and #252/#249/#34 open; no automatic changes.
