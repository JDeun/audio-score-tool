# Chordify: Competitive Research & Benchmark Protocol (2026-10-23)

## Executive findings
Chordify is a **chord-and-beat-aligned play-along product**, not a full multi-instrument AMT engine. Its official technical explanation describes spectrogram inputs, separate deep neural networks for automatic chord recognition and beat/downbeat tracking, and time-aligned chord display. Its paid MIDI exports contain **chord notes, not full instrumentation**. AudioScoreTool should benchmark **harmonic transcription independently from note transcription**, while distinguishing chord-only MIDI from full-song MIDI.

## 2026-11-09 — 현재 연구 연결 상태

관련 연구 이슈는 모두 **open**이며, 아래의 기존 조사·구현 이력과 실제 corpus 실측 완료 여부를 구분합니다.

- [#58](https://github.com/JDeun/audio-score-tool/issues/58): CASD·Isophonics·Billboard·ChoCo의 코드 annotation 확보와 녹음 정렬·이용 조건 검증.
- [#53](https://github.com/JDeun/audio-score-tool/issues/53): Chordify와 SheetSage 계열의 동일 녹음 기반 실제 비교. [수동 코드 입력기](../scripts/import_manual_chord_chart.py)와 [비교 CLI](../scripts/compare_chord_playalong.py)는 연결되어 있으며, 정당하게 확보한 다중 곡의 실측이 남습니다.
- [#57](https://github.com/JDeun/audio-score-tool/issues/57): 실제 음악 corpus와 독립 reference 확보·검증. URL이나 후보 곡 이름만으로 평가용 음원·정답 쌍이 준비된 것으로 간주하지 않습니다.

[Chordify 공식 CASD](https://github.com/chordify/CASD#overview)는 **50곡 × 4명 전문가의 코드 참조 주석**을 JAMS/Harte 형식으로 공개합니다. 원본 음원·분리 stems·개별 음표 정답 MIDI는 제공하지 않으며, 이 공개 주석 집합을 현행 Chordify 서비스의 **전체 학습 데이터**라고 확정할 근거도 없습니다. 여러 전문가의 주석을 유지하는 [CASD importer](../scripts/import_casd_annotations.py)를 통해 코드 평가에 사용하고, 녹음은 별도로 확보해 동일 버전·시간축을 확인해야 합니다.

**코드 WCSR과 full-score note F1은 별도 지표입니다.** CASD는 시간 구간별 화성 주석을 평가하는 근거이며, 전체 악기 음표의 pitch/onset/offset/GM 평가에는 독립 note MIDI가 필요합니다. 새 [혼합음원 대 분리 stem AMT 실험](research/MIX_VS_STEMS_ABLATION_2026-11-09.md)은 후자의 연구이며, #53의 Chordify 코드 정확도 실측을 대체하지 않습니다.

### 공개 원본 주석 가져오기 확인

공식 CASD commit `f9f8f7d4542f7cd75c0c29fe867da89f350ea7b1`의 원본 JAMS 세 개를 내려받아 pinned tree의 Git blob/크기와 SHA-256을 확인했다. 기존 `extract_casd()`와 엄격한 `_jams()` 구간 검증이 모두 통과했으며, 원본 metadata의 길이를 그대로 사용했다. [검사 결과와 원본·코드 해시](research/CASD_ANNOTATION_IMPORT_2026-11-09.json)는 metadata만 기록한다.

| 원본 | metadata 길이 | 전문가 수 | 전문가별 구간 수 | 가져오기 / 전체 시간 구간 검증 |
| --- | ---: | ---: | --- | --- |
| `jams/12.jams` | 218.8초 | 4 | 454 / 454 / 454 / 454 | 통과 / 통과 |
| `jams/92.jams` | 243.0초 | 4 | 605 / 605 / 605 / 605 | 통과 / 통과 |
| `jams/1012.jams` | 291.6초 | 4 | 617 / 617 / 617 / 617 | 통과 / 통과 |

총 12개 전문가 그룹의 6,704개 구간을 보존했다. 검사한 주석은 0초부터 원본 metadata 길이까지 누락·겹침·범위 초과 없이 이어졌다. 이는 **세 원본 파일의 구조·시간 구간 호환성** 확인이다. 음원을 내려받거나 녹음 해시를 임의로 만들지 않았으며, 음원 매칭·Harte 라벨 의미·모델 정확도는 검증하지 않았다. 실제 녹음 기반 #53/#58 인수 조건은 계속 남는다.

## Verified sources
- Technology and architecture: https://chordify.net/pages/technology-algorithm-explained/
- Beat/downbeat tracking: https://chordify.net/pages/algorithm-summer-bootcamp/
- Current feature overview: https://chordify.net/pages/chordify-app/
- MIDI export behavior: https://support.chordify.net/hc/en-us/articles/360002164538-How-to-use-Premium-features
- Melody transcription limitation: https://support.chordify.net/hc/en-us/articles/360002272998-Which-instruments-can-I-use-with-Chordify
- CASD multi-annotator chord references: https://github.com/chordify/CASD
- MIREX 2025 chord-estimation evaluation: https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation
- MIREX 2025 results/baselines: https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation_Results

## Product decomposition
| Capability | Chordify | AudioScoreTool target | Verification |
| --- | --- | --- | --- |
| YouTube play-along | Yes | URL -> audio -> transcription -> synchronized editor | E2E |
| Chord recognition | Yes | SheetSage2 plus alternative ACR baseline | WCSR, root, maj/min, sevenths |
| Beat/downbeat | Yes | Time-aligned bar/beat grid | beat F-measure, downbeat F |
| Key/BPM | Exposed | Exposed | key accuracy, tempo error |
| Chord diagrams | Guitar, piano, ukulele, etc. | Future UI | UX |
| Loop/speed/transpose | Paid practice features | Future UI | UX |
| Chord-only MIDI | Paid | Distinguish from full instrumentation | MIDI content |
| Full multi-instrument MIDI | Not offered | YourMT3/MR-MT3/MuScriptor | note F1 |
| Sheet music | Chord chart, not full lead/melody lines | MusicXML multi-part score | notation quality |

## Scientific validity
1. Chordify outputs are **competitor predictions, not ground truth**. Compare model-to-model agreement separately from annotated accuracy.
2. Use CASD/JAMS multiple references to measure annotator ambiguity; consider MIREX/Isophonics reference sets, license and split provenance.
3. Use `mir_eval.chord` weighted chord symbol recall (root, maj/min, thirds, sevenths), segmentation and no-chord handling. Normalize chord labels into a common Harte representation; report unsupported-label rate.
4. For beat/downbeat use `mir_eval.beat` and independent annotated beats; tempo tolerance and half/double-tempo ambiguity need explicit reporting.
5. For AMT use note onset and onset+offset F1, instrument-aware F1, duration and runtime; use manually verified MIDI/reference, not chord-only exports.
6. Report confidence intervals across **songs**, not frames; separate genre, production density and vocals; avoid inferring performance from one Tinashe track.
7. Chordify research reports substantial human disagreement (CASD): a single reference may not represent unique musical truth.

## Experimental protocol
- Input: authorized audio from the **same exact recording and time window** for every model. Track SHA256, duration, sample rate, source ID, download policy, model/weights/runtime revisions, CPU specs and execution time.
- Candidate AMT: YourMT3, MR-MT3, MuScriptor small/medium/large as feasible.
- Harmony: SheetSage2, Chordify manual export (when legitimately available), and Chordino/NNLS baseline.
- Hybrids: YourMT3+SheetSage2, MR-MT3+SheetSage2, MuScriptor+SheetSage2.
- Ensemble: YourMT3+MR-MT3 consensus (precision-first), plus union and confidence-aware variants only after ground-truth measurement.
- Pipeline gates: successful download/ingest, MIDI and MusicXML validity, no duplicated notes, valid chord timeline, successful rendering and synchronized playback.
- **Never label a smoke test as a benchmark score**. A model can produce files and still transcribe incorrectly.
- Copyright: do not commit or publish commercial source audio; avoid public artifacts containing source audio; use appropriately licensed/authorized test recordings.

## Gaps and prioritized implementation
P0: fix Actions package import, actual model CLI compatibility, and GitHub hosted runner execution; retain full logs.
P0: make source ingestion work on real video URLs without relying on synthetic audio; persist only derived metrics by default.
P0: fix hybrid dependency/CLI contract; test end-to-end output and musical timing.
P1: add Chordify-vs-SheetSage2 normalized chord event importer and `mir_eval` scoring.
P1: create human-annotated multi-song test set; use CASD and other licensed datasets.
P1: MuScriptor authenticated inference on CPU small, MPS/CUDA medium/large, gated by accepted HF license.
P1: compare AMT ensemble consensus against single-model recall/precision.
P2: chord-aligned player, diagrams, loop, tempo, transpose, editable chord grid.
P2: cost/latency/accuracy Pareto analysis on GitHub Actions CPU and optional GPU.

## Limitations
No public official Chordify inference API or model weights were verified in this investigation. Do not automate scraping, assume Chordify results are reference annotations, or claim its algorithm can be reproduced from the high-level description. The exact commercial production model architecture and accuracy are undisclosed.

## CASD feasibility and alternative corpora (verified 2026-10-23)
- CASD **is usable for noncommercial research** under **CC BY-NC-SA 4.0**, with attribution and share-alike requirements on adaptations. Repository: https://github.com/chordify/CASD ; license: https://github.com/chordify/CASD/blob/master/LICENSE.md .
- CASD contains 50 Billboard songs, four expert chord annotations per song, JAMS/Harte format. **It does not distribute the copyrighted source audio**. Acquire matched audio separately and verify recording/version/time alignment and rights.
- CASD can measure chord recognition but **cannot evaluate full instrument note-level AMT**. Use independent MIDI-aligned audio corpora for AMT.
- `scripts/import_casd_annotations.py` converts JAMS to per-annotator intervals, preserving all references; requires no network at runtime.
- Isophonics (https://isophonics.net/datasets): annotated chord/key/beat datasets; original commercial audio not automatically licensed.
- ChoCo (https://github.com/smashub/choco): large harmonically annotated symbolic/audio-aligned metadata collection, not a turnkey audio dataset.
- ASAP (https://github.com/fosfrancesco/asap-dataset): classical piano MIDI/audio-alignment and beats, better for AMT than pop harmony.
- Hugging Face hosts community datasets but presence on HF **does not imply permission to redistribute commercial recordings**. Inspect each dataset card, actual audio availability, license and alignment; prefer authoritative source when available.
- 2026 MIREX ACE guidelines (https://music-ir.org/mirex/wiki/2026%3AAudio_Chord_Estimation) prohibit Billboard 2013 test material for training, validation or model selection in the competition; maintain split provenance if seeking MIREX-comparable results.

## 2026-11-05 — 수동 주석 비교 도구 (#53)

이 프로젝트는 **Chordify 인증 세션, 비공식 API, 웹 스크래핑을 구현하지 않습니다**. 사용자가 적법하게 확보하고 직접 작성한 시간 정렬 CSV를 받아 비교용 이벤트로 정규화합니다. 다음은 공식 Chordify CSV 포맷이라는 주장이 아닌 **AudioScoreTool 수동 입력 계약**입니다.

- `chords.csv`: `time_seconds,chord` 헤더와 시간 오름차순 코드 행(예: `0,C`, `2,Am`, `3.5,N`)
- 선택 `beats.csv`: `time_seconds,kind` 헤더, `kind`는 `beat` 또는 `downbeat`
- 원본 오디오 SHA-256과 재생 길이는 운영자가 지정하며, 파일 바이트가 원본과 실제 일치하는지 이 도구가 직접 검증하지 않습니다.
- 인식 불가능한 코드 품질·전위는 추측하지 않고 오류로 처리합니다.

```bash
uv run --frozen python scripts/import_manual_chord_chart.py \
  /private/chords.csv /private/manual-events.json \
  --beats-csv /private/beats.csv \
  --duration-seconds 120 \
  --recording-sha256 <ACTUAL_64_CHAR_RECORDING_SHA256>

uv run --frozen --with mir_eval==0.8.2 python scripts/compare_chord_playalong.py \
  /private/independent-reference.json \
  /private/manual-events.json \
  /private/sheetsage-events-with-audio-identity.json \
  /private/chord-comparison.json \
  --output-csv /private/chord-comparison.csv
```

독립 참조 JSON은 `recording_sha256`, `duration_seconds`, `annotators[{index,intervals[{start,end,label}]}]`를 필수로 포함하고, 선택적으로 `beats`와 `downbeats`를 포함합니다. SheetSage2 JSON에도 **동일한** `recording_sha256` 및 `duration_seconds`가 있어야 합니다. 서로 다른 녹음·길이의 결과를 섞으면 실패하며, 결과의 오디오 신원과 이용권 보증은 여전히 사람이 확인해야 합니다.

결과 JSON/CSV에는 독립 주석 기반 root, maj/min, thirds, triads, sevenths WCSR과 beat/downbeat F1, 화성 분할 boundary F1, no-chord 구간 재현율이 포함됩니다. 두 예측 간 일치율은 `inter_model_agreement_not_accuracy`로 **별도 분류**합니다. 주석 출처·오디오 정렬이 검증되지 않은 값은 상용 모델 품질 근거로 사용할 수 없습니다. 설치된 기본 앱에 `mir_eval`을 강제하지 않고 선택형 벤치마크 CLI에서만 임시로 사용합니다. 합성 테스트와 실제 합법적 다중 곡 벤치마크는 구별하며, 실제 곡의 평가 결과가 없으므로 #53의 실증 인수 조건은 남습니다.
