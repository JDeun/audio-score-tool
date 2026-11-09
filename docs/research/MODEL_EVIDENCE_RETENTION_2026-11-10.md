# Model observations survive Job cleanup

The five actual SheetSage2 output workspaces from the previous product run were
cloned into an isolated application directory. No new inference or musical
correction was performed. The original private source workspaces remain intact.

Each clone was ingested through SongStoreV2, deleted through the actual
`DELETE /api/jobs/{id}` route, then opened through a new SongStoreV2 instance.
All five retained the original input SHA, canonical MusicXML and 32 allowlisted
model/clock files each. Every preserved file passed SHA-256 validation after
deletion. [Metadata-only receipts](MODEL_EVIDENCE_RETENTION_2026-11-10.json)
identify the execution commit and source recordings without publishing music.

The immutable Song-owned snapshot includes raw SheetSage2 ABC/vocal MIDI,
playback/beat/key/chord observations, pinned model identity, initial score,
and the pipeline's crop/clock context. Selected MT3 stem MIDI/XML are included
when present. New official SheetSage2 runs also record runtime versions,
adapter SHA, device, seed and preset; old runs are not retroactively labelled
as having recorded runtime data. Existing scores can be backfilled while their
Job workspace still exists. Historical/direct imports without declared model
outputs explicitly report unavailable evidence.

Bounded copies are staged then renamed atomically. Missing required model
observations, symlinks, out-of-Job paths, oversized files, failed copies and
corrupt snapshots prevent deletion. Both individual deletion and bulk cleanup
apply the same preservation check. User edits never replace model observations.

Validation: 13 targeted preservation/deletion regressions passed; 28 combined
preservation/native-notation tests passed; full local suite 1,859 passed and 5
skipped because optional mir_eval was unavailable. Ruff and diff checks passed.
This is a storage/reproducibility fix, not an improvement in transcription accuracy.

Remaining: octave-sensitive product verification, acoustic lead selection,
full-song reference/correction-cost assessment and final model approval.
