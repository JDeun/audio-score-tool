# Tempo-only multi-scale agreement and selective output — frozen protocol

Related issue #252; continuation of draft #255 at d953ad962463699c4647cc4923aa13094324cfbc.
Research only: no main merge, product/default changes, user songs, API credentials,
paid APIs, GPU, training, or alteration of other sessions' branches.

## Question and causal separation

The user's hypothesis concerns BPM from recurring rhythm, NOT finding the first
beat of a bar. Previous #255 already averages 8-second ACF windows every 4 seconds.
Do not advertise merely adding windows as a new method. Compare robust agreement
across fixed 4/8/12-second scales, and explicitly measure uncertainty/half-double
aliases independently of meter, downbeat or notation accuracy.

Four frozen methods on the SAME envelope and same broad prior centered at120:
1. Original mean8 ACF + prior120. Exact earlier score/top3 replay on EVERY input.
2. New consensus: normalize informative windows by peak; average median and mean
   of normalized score curves within each scale (weights .5/.5), then average
   scales equally. Apply the SAME prior once. A window is informative if its
   maximum unweighted score >=.12. All windows, including excluded weak windows,
   stay in diagnostics. This parameter is a hypothesis, not calibrated confidence.
3. Original mean8 + the shared selective policy below.
4. Consensus + that IDENTICAL selective policy. This prevents attributing the
   benefit of simple abstention to the consensus algorithm.

Selective policy: >=3 informative windows in >=2 scales; >=60% scale-balanced
local winner support within4%; competitor separation>=8%; relative top gap>=.08;
no 0.5x or2x rival within4% whose score is >=.85 of the best. Otherwise return
BPM=null with reasons, retaining a DIAGNOSTIC winner/candidates only. Abstention
is never counted as correct and no target BPM/meter/phase is passed to any selector.
Both always-output and selective results are recorded: correction, damage,
coverage, accepted-only precision, correct/all-planned, half/double and other errors.
No post-result threshold selection or reference-guided candidate reranking.

## Recordings and context

GMD v1.0.0, Google LLC, CC BY4.0. Official MIDI-only ZIP SHA256
651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e.
All source/observation/script/settings hashes and individual predictions are
retained as metadata; original MIDI/WAV/envelopes are runner-private.

MIDI: all original129 test + five non-test3/4 reused DEVELOPMENT/REGRESSION cases;
add up to32 validation4/4 files, ordered by SHA256('consensus-midi-v1/'+id), excluding
all previous12 audio IDs. Do not call this a performer/composition-independent test.
Same first24s, kick/backbeat and kick/backbeat/hat inputs separately. Role identity
is GIVEN in MIDI. For every file whose observed MIDI duration >24s, also score
first min(60s,length) with both methods; this is a separate paired context-length
ablation on an eligible subset. Do not pretend long context helps shorter files.
MIDI tempo events are used to convert ticks to observed seconds, not as BPM input.

Audio: same previous12 files from #255, plus up to4 validation4/4 beat files12–40s
ordered by SHA256('consensus-audio-v1/'+id), disjoint by recording ID. First24s;
same detected-hit train AND continuous unclassified spectral flux. Known MIDI
roles, nominal BPM, meter, phase and file identity never reach audio predictors.
These are recorded sound-module outputs of human drumming, not full-band mixes.

Reused vs added cohorts, representations, beat/fill, denominators and long-context
subsets remain distinct. Validation files may share performers or exercises with
earlier data; no claim of broadly independent generalization.

## Bounded original source access

Reuse #254/#255 strict HTTP206 reader and fixed140MiB total budget. Check full vs
MIDI-only info.csv hash, individual memberCRC/SHA, ZIP identity/byte count. Never
fall back to downloading5.11GB or synthesize a replacement for blocked WAVs.
Preflight all selected compressed bytes+conservative request overhead against
budget before inference; retain every blocked/failed selected ID. Full ZIP SHA
cannot be verified by subset range retrieval; do not claim otherwise.

## Validation / publishing

21 local algorithm tests on installed numpy2.3.5/scipy1.17.0 passed; this is NOT
pinned remote or real-data evidence. Remote Python3.11 numpy1.26.4 scipy1.13.1,
mido1.3.3, pytest8.4.2 and Ruff0.16.6. Two standard CPU jobs/max2parallel,
25min/job, no models. No librosa call is needed for these four compared methods.
Only exact JSON reports uploaded; filenames/hashes/metrics are not source media.

Every case must pass immutable-input and earlier baseline-replay guards. Summary
failure/missing IDs cannot be reported as complete. Primary success: nominal BPM
within4%; half/double remain errors. Top3 recall is a separate oracle diagnostic.
Selective precision must ALWAYS be paired with coverage and all-input counts.
No automatic tempo or score modification is authorized by these findings.
Keep #252/#249/#34 open. After this comparison, test licensed real mixes and
separated drums, established beat models, and permitted exact-recording metadata
as separate experiments rather than hiding them in this algorithm-only ablation.
