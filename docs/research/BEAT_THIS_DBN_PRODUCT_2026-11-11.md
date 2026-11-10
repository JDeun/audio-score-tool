# DBN clock: one product Job and clone deletion

At tested source `9ffdcef7b4d4bdf2a0090ebfca2fce0385d678cd`, one complete Me So Bad upload and Job used new SheetSage2, Demucs, YourMT3, torchcrepe tiny and BeatThis DBN inference. No YouTube audio was downloaded again. The whole source was retained without cropping; all recorded source, checkpoint, driver and wrapper hashes remained unchanged.

The Job created 564 raw notes, selected 564 and exported 550 attacks, omitting 14 selected notes. Selection used the single-part bypass, not an acoustic multipart choice. The interpretation-to-export guard passed within 2 ms; this is not an original-song accuracy measure.

The source contained 14 no-chord intervals. The resulting canonical XML and published XML each contained 6 no-chord marks, and PDF text contained 6 N.C. marks. The displayed approximate tempo and UI clock were both 100.00 BPM; 351 hidden-clock checks agreed within 1.05e-12 seconds. The observed tempo is not asserted to be the original-song tempo.

A subsequent actual Job deletion in an isolated clone preserved the Song revision, source audio and exports. All 53 preserved evidence files passed manifest checks, including DBN logits/decoded clock and receipt, Tiny observation/receipt, and original predictions. The original producer Job remains intact.

The [metadata](BEAT_THIS_DBN_PRODUCT_2026-11-11.json) includes the producer, audit and clone deletion report hashes, along with exact code, checkpoint and output hashes.

This run covers one recording. Meter support remains conditional. Original-song accuracy and commercial quality remain unverified.

Commit `95533d3` keeps every raw downbeat detection in the interpretation. The analysis uses detections that match the selected bar phase. A mixed-phase fixture verifies that the first analysis downbeat is a selected first beat. The five cached recording clocks had zero incompatible detections. The focused beat and recipe group passed 20 tests with FFmpeg available. The product Job above ran before this change.
