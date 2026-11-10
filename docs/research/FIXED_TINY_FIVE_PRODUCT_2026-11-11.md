# Fixed Tiny five-song product evidence — 2026-11-11

Five frozen source recordings were first available as cached references. A new isolated product run at `7a07c88b9c4f1267431d2daf372c7b3acbd8b602` then performed SheetSage2, Demucs, torchcrepe tiny and YourMT3 inference for all five; it did not download YouTube audio again. The driver exited successfully and all five exports completed. Nine source files, five model weight files and the driver were verified unchanged by the run.

The run produced **2,902 raw notes across all parts**, selected **2,813 notes**, and exported **2,693 attacks**. The existing grid omitted **120 selected notes**; those omissions require review and are not proof of transcription errors. The export fidelity guard compares the interpreted grid with the exported MIDI; it does not measure original-song accuracy.

| Case | Raw all parts | Selected | Exported | Omitted | PDF pages | Elapsed s | Job created UTC | Job complete UTC | Fidelity max ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |
| tinashe-me-so-bad | 564 | 564 | 545 | 19 | 5 | 396.854 | 2026-11-10T17:25:14.498661+00:00 | 2026-11-10T17:31:50.854828+00:00 | 0.0089 |
| twice-fancy | 732 | 710 | 695 | 15 | 7 | 440.056 | 2026-11-10T17:32:34.757971+00:00 | 2026-11-10T17:39:54.310915+00:00 | 0.0208 |
| green-day-american-idiot | 311 | 311 | 308 | 3 | 9 | 376.076 | 2026-11-10T17:40:43.816337+00:00 | 2026-11-10T17:46:59.642511+00:00 | 0.0030 |
| ham-boo-young-my-song | 613 | 605 | 551 | 54 | 5 | 549.068 | 2026-11-10T17:47:49.225858+00:00 | 2026-11-10T17:56:57.764707+00:00 | 0.0010 |
| younha-event-horizon | 682 | 623 | 594 | 29 | 7 | 582.449 | 2026-11-10T17:57:42.708541+00:00 | 2026-11-10T18:07:24.677376+00:00 | 0.0033 |

Two single-part results used the single-part bypass; they do not claim acoustic part selection. Tiny selected among multiple parts on Fancy (index 1), 나의 노래 (index 0), and 사건의 지평선 (index 2).

The selected MIDI files were byte-identical to the previous five-song run in all five cases. Compared with the prior current-main exports, all 2,693 final events retained the same pitch, program, drum flag, onset and offset, with zero measured timing difference. This is a regression check: adding Tiny did not improve these score events. Four final MIDI files were byte-identical. The fifth contained one additional key-signature event; its voice track was identical and its metadata track matched after excluding key signatures.

A subsequent clone-only Job deletion check passed for all five, retaining 258 evidence files. Every preserved manifest entry was rechecked against the cloned file and the corresponding original Job file; source audio and exports also matched their recorded hashes. The original QA workspace remained intact.

Fresh validation is **pending**; no result is claimed here. The exported PDF page counts above use this run’s publication settings and are not a comparison with previews made under other settings. Neither the original-song transcription nor commercial quality is approved.

## Receipts and hashes

| Case | Source audio SHA-256 | Job receipt SHA-256 | Tiny runtime receipt SHA-256 |
| --- | --- | --- | --- |
| tinashe-me-so-bad | `f39788b3075e9117661481470289c6e79ce25171f7a256936a2167bdae49fd65` | `00c9e0f77621529b9118259d872ffbb481dd564cf265fec7043fee919e46ca80` | `2fe96e493885d44c2c936fcac110faf2b08ddb9b07f1af61f94d0e501bebea17` |
| twice-fancy | `5e1b5613b3863ea3babd2dc22bc9fa8ba62deb2ae44d48c8885f832ab56f01ec` | `3ffb37e3c2a5fe2a1c742ae6a41ff87c822db7d960751e878747fcf313cbffdb` | `62c5cfe63f19b6e5ddb349628c572682789fe7c84fa02ca71579486869cf1286` |
| green-day-american-idiot | `aedb875ba145c1f5cd21a0a86713d11dff1de9701512b8f1c7e4a40fa4fdf680` | `5616e71c591b6fde66e4fec4564c37a81d3ba059b79868c7737b6cbafe3ccc38` | `4a4abf25d81a29ec5a57ea8c25c9b2a8555edaef99810bec074e9ff537bdc734` |
| ham-boo-young-my-song | `871118a06f5021b94f6e56c9066fca50670582f5e530bcee9290e2db270d8ac7` | `48ef5b3b74cbdb45092d8e53a178eb00f5e7c7dda431eb8bc151b92ccec94a62` | `560018bb35b2b66aabdedeb97e4ed9f48fbbf0b36ba267734394a1ea4e247049` |
| younha-event-horizon | `2d84bd77253c96851db8bde4cd76de0b7bf7101cf07f79ff8dbf2d03f1d23dce` | `d7672d47610be469ebe76f3823132db14b0fdcef6bd1b470b23bb441e6075a50` | `34902c641043652b8399b15aed9e7209ec1506527cf963fbe52dfb598e12420a` |

Product report SHA-256: `949c15b6821bc62d16dbd5405da1f5862ac878742cf2ab36ad70478ebb80a8e8`. Clone deletion report SHA-256: `c5888162e90073e4ffa97d5a1bd6bd24c27ed0217222ce4fd7773e4b322a39c1`. The [metadata JSON](FIXED_TINY_FIVE_PRODUCT_2026-11-11.json) includes the source, model, driver, prediction and export hashes.
