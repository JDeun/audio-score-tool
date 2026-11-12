# GMD drum-event tempo/meter and external metadata eligibility — fixed research protocol

Issue #252; related #249/#200/#219/#34. Stacked on draft #251 commit
\`6282321f9f58a49948e1167ae3d54865199c50cb\`.
**Never auto-merge, alter main/default models, access user files, obtain API
credentials, train, or claim audio-first model correctness.**

## Why this experiment

User proposes combining online per-recording BPM/meter metadata with periodic
kick and snare/rim/clap/snap observations to solve tempo, 3/4 vs 4/4 and bar
phase, then feed trustworthy observations to the earlier constrained notation
inference. These are different tasks and each needs an honest denominator.

## Metadata vendor audit (documentation and mock contracts, NOT live calls)

- GetSongBPM: \`tempo\` and \`time_sig\` (beta) are described in the search/song
  response; requires an API key AND a backlink. We lack granted API credentials.
  No live GetSongBPM calls or assertion of actual track coverage.
- Spotify: audio features include estimated \`tempo\`/\`time_signature\`, but
  access to new third-party use cases was restricted Nov 27, 2024; new
  Development Mode also has 2026 limitations. Do not treat Spotify as an
  accessible default provider without authorized access.
- MusicBrainz: useful to disambiguate recording, ISRC, release/artist metadata,
  not a guaranteed BPM/time-signature endpoint. Noncommercial web service
  access is free subject to user-agent/rate rules; business-use terms differ.
- AcousticBrainz: frozen historical extracted BPM records, stopped collection
  in 2022, coverage/continued API availability uncertain; not a current
  per-song authoritative meter provider.
- Exact recording/version linkage is REQUIRED before accepting a provider value.
  Neither identical song title nor a different live/remaster recording is
  sufficient. The study uses original GMD \`info.csv\` as **ground truth supplied
  metadata**, not an external provider response. A synthetic mismatch must be
  rejected, and a deliberately false meter must be flagged or abstained.

## Measured data

Official Google Magenta Groove MIDI Dataset v1.0.0, MIDI-only ZIP, SHA256
\`651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e\`,
licensed CC BY 4.0 (retain attribution). Official \`test\` split only, deterministic
hash-ordered first up to 24 3/4 and 48 4/4 tracks; include beats and fills.
Report true available 3/4 and 4/4 counts; NO 3/4 inference claim if none or
too few. No trainer or metadata-driven per-case best arm. Missing/failing cases
are not scored as zero or silently excluded.

This is a **real human drummer MIDI performance** (velocity and timing), but
NOT recorded audio processed by a kick/snare classifier. Note numbers identify
percussion roles for the algorithm in an idealized condition; we do not
claim robust extraction through bass, guitars, or vocals. Roles: kick MIDI35/36,
snare/rim/side-stick/clap37/38/39/40; no standard GM snap class, so actual
snap detection is untested. Hi-hat notes22/26/42/44/46 are catalogued but
not directly used as downbeat proof. Original MIDI tempo messages are needed
to convert MIDI ticks to real seconds, **not supplied to the blind estimator**.
Reference bar-1 origin is MIDI tick0 (dataset alignment convention), not an
independent human-labelled acoustic downbeat.

## Fixed comparison matrix

1. **Event-only**: Infer BPM in 60..200 step2 and meter 3/4 or4/4 with frozen
   cyclic kick/backbeat/whole-bar-repetition scoring and phase at 1/4-beat
   resolution. Neither meter nor BPM metadata is passed to the estimator.
2. **Metadata BPM given**: same event roles, but BPM is the exact recording's
   official supplied value. This measures meter/phase ONLY; trivial tempo
   recovery by supplying the truth is NOT improvement.
3. **Metadata BPM + meter given**: both are supplied from official \`info.csv\`.
   Only phase is inferred; do not report metadata-supplied meter as an
   automatically estimated correct meter.
4. Conflict and missing-provider control: nonmatching recording version
   is rejected; deliberately wrong supplied meter is marked as conflicted or
   uncertain rather than silently promoted. The controller is diagnostic,
   not an automatically approved metadata override.

All arms share exactly the same timing/role input. No time signature change,
rubato, 6/8, 12/8 or >1 tempo segment claim; changed signatures/tempos are
explicitly unsupported. Actual pop genres can have many other patterns.
Half/double-time tempo matches are reported separately, **not redefined as
exact successes**.

The fixed templates are intentionally narrow examples of 4/4 kick1/3 &
snare2/4 and 3/4 kick1 & backbeat2/3. They may fail with syncopation, four
on the floor, no drums, three-against-four, electronic patterns, fills,
and backbeat substitution. Built-in phase abstention is mandatory for
symmetrical 4/4 kick1/3-snare2/4, where a half-bar shift is observationally
indistinguishable. 3/4/4/4 are preferred tested candidates, **not exclusive
pop-music truth**.

## Evidence, metrics and future stage

- Recording counts and coverage by meter/beat_type and actual official split.
- Absolute BPM within4%, half/double alias separate; meter correct/wrong/
  abstained; bar origin phase correct/wrong/abstained only when exact tempo
  and meter also correct. No false denominator shrink.
- Synthetic toy 3/4/4/4, backbeat role, initial rest and ambiguous phase unit
  tests are **not** real MIDI/audio accuracy claims.
- Pairing/source/checkpoint-free runtime/protocol hashes, ZIP checksum,
  all attempted cases, failure types, per-class counts, metadata mismatch
  diagnostics. Do not upload raw MIDI/audio/sampled drum waveforms.
- No optimal thresholds fitted to these same test split results; changes
  after measured failure require a *new* explicitly tracked development
  experiment. No claims of representative 3/4 performance without coverage.
- Real-audio detection MUST be measured separately using a rights-cleared
  subset of original GMD WAV or other aligned drums. The full WAV archive is
  4.76GB and explicitly not downloaded here. Audio detector error, timing
  drift, drums absent, pickups, variable BPM/meter, 6/8, genre coverage,
  MusicXML/PDF and time-to-publish remain open. A conditional beat/meter
  prior is useful only if the model accuracy and abstention are documented.

## External documentation

- GMD: https://magenta.withgoogle.com/datasets/groove
- GetSongBPM: https://getsongbpm.com/api
- Spotify restriction: https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
- Spotify 2026 access: https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security
- MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
- AcousticBrainz: https://musicbrainz.org/doc/AcousticBrainz
