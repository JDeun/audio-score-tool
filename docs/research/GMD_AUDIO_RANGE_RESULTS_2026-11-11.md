# GMD actual drum-kit WAV onset extraction — completed bounded research

Issues #252, #249; draft PR #254 stacked on draft #253.
**No production/default changes, no main merge, no user songs, API keys, GPU or training.**

## Study provenance

- First PR-open Actions 43038839287 failed at Ruff (unused imports and import ordering); it did not run the waveform study. Later code-only cleanup resolved the errors.
- Successful CPU Actions: https://github.com/JDeun/audio-score-tool/actions/runs/43039476056
- Successful inference head: d11ec69985ed3b9b1b0abd7b1ca79d9eedafe1b1. The report's source_revision 8ce0c5b6fd3e5ba9cfd927545ba5175c1105b5a9 identifies the **PR merge checkout**, not the head commit.
- Artifact ID 13863673852, ZIP SHA256 9be7f5e8e61dc5798726495dd17faab88425c18701c7fc1bacb1b22b088dc1e3.
- Report JSON SHA256 ebaed3f2d923c81078657d1928ef367ac6204f3d44b8c81fdd13ee42fd6935c6.
- Verified artifact digest against GitHub Actions metadata, 4/4 planned IDs and scored status, per-case match counts, individual F1 and micro totals. This is a receipt audit, not independent re-inference of original WAV.
- Publisher MIDI-only archive SHA256 651cbc524ffb891be1a3e46d89dc82a1cecb09a57c748c7b45b844c4841dcc1e verified, source info.csv SHA256 3e17eef2f18012c0160c183ad5b106964eb429876cceb1eee1b746def4e6b11b matched between MIDI-only and ranged full ZIP.
- Full original ZIP size reported by HEAD: 5,111,599,714 bytes. **Not downloaded, full ZIP SHA256 NOT verified**; only selected members read and ZIP CRC validated.
- Read **27,857,470 bytes in 18 strict HTTP 206 range requests**; rejected any non-range fallback.

## Paired audio and human MIDI comparison

Original human performance was played on MIDI drum kit; audio is its recorded Roland
synthesized sound, not a live full-band track. The simple low/high spectral
novelty detector received no true hit roles, beat metadata or MIDI annotation
during waveform analysis. MIDI timestamps and roles were used ONLY for subsequent
one-to-one ±50ms onset matching. There are four **selected** excerpts, NOT a
representative release-quality benchmark. One 3/4 excerpt is validation-split,
not independent test.

| Metric | 4/4 test: 3 excerpts | 3/4 validation: 1 excerpt | pooled: 4 excerpts |
| --- | ---: | ---: | ---: |
| Kick truth / predicted / matched |32 / 49 / 29|11 / 12 / 11|43 / 61 / 40|
| Kick onset micro F1 |71.60%|95.65%|**76.92%**|
| Snare/rim/clap truth / predicted / matched |51 / 58 / 33|22 / 20 / 20|73 / 78 / 53|
| Backbeat onset micro F1 |60.55%|95.24%|**70.20%**|
| Any kick/backbeat truth / predicted / matched |83 / 107 / 65|33 / 32 / 31|116 / 139 / 96|
| Class-agnostic onset micro F1 |68.42%|95.38%|**75.29%**|

The counts include the **hard 4/4 fill** with no MIDI kicks: audio detects 12
low-frequency events that are false kick positives under this role mapping.
Therefore pooled F1 hides major role confusion. No threshold changes were made
after seeing these data. A perfect role separation model was not assumed.

For 4/4 test excerpts, all three phase decisions ABSTAINED even after supplying
the nominal BPM and 4/4. The 3/4 validation excerpt generated phase2.0 beats
from both extracted audio events and MIDI events; **this is not nominal tick0
phase and is not a verified musical downbeat truth**. It may reflect rhythmic
phase ambiguities or dataset conventions. Thus good audio onset F1 **does not**
suffice to solve bar-phase or pickups.

## Decisions and next verification

- **Feasibility**: Strict range-only extraction succeeded without fetching the
  4.76GiB archive. A limited signal-processing detector recovered many actual
  drum-kit transients in this tiny selection.
- **No production approval**: Not an accurate full-band kick/snare source
  separator, not validated for snaps or 6/8, half/double time, tempo changes,
  meter changes, silent intro, mixed pop song, BPM metadata availability,
  correct first downbeat, MusicXML/PDF, or human correction time.
- Before coupling to the bar-sum rhythm resolver, measure realistic demixed
  drums from licensed mixed recordings, compare an audio beat/downbeat model
  with explicit BPM/meter metadata and quantify false first-beat corrections.
- Provider metadata must be exact-recording matched and only used after
  validating permissions/API key/link obligations. GetSongBPM and Spotify
  are NOT called by this experiment. The GMD info.csv is supplied catalog data.
- Keep PR #254 DRAFT and related issues open; no automatic changes.
