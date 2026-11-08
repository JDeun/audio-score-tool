# Music Dataset Survey: Hugging Face and Authoritative Sources (2026-10-23)

## Decision
Use **two separate benchmarks**: (A) chord/beat estimation and (B) audio-to-MIDI multi-instrument transcription. Hugging Face is a distribution channel, not proof of licensing or ground-truth quality. Do not train and test on overlapping recordings, including repackaged datasets.

## Chord / beat / harmony
| Dataset | Source | Audio included? | Annotation | Conditions / recommendation |
|---|---|---|---|---|
| CASD | https://github.com/chordify/CASD | No | 50 Billboard songs × 4 experts, JAMS chords | CC BY-NC-SA 4.0; excellent for inter-annotator chord evaluation; acquire matching audio separately |
| Isophonics | https://isophonics.net/datasets | Not generally redistributable | chords, beat, key, segmentation | Verify source-specific licensing and recording alignment |
| Billboard | https://music-ir.org/mirex/wiki/2025%3AAudio_Chord_Estimation | No generally open commercial audio | chord reference | respect MIREX splits; potential CASD overlap |
| ChoCo | https://github.com/smashub/choco | No | >20K pieces' harmonic annotations/metadata | heterogeneous licensing; not an audio benchmark without pairing |
| GuitarSet | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | Yes (repackaged) | guitar JAMS, pitch and some harmony-related annotations | upstream CC BY 4.0 as reported by aggregator; confirm upstream files |

## Audio/MIDI aligned transcription
| Dataset | Hub / authoritative source | Audio and MIDI | License and evaluation suitability |
|---|---|---|---|
| Slakh2100 Redux | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 ; https://zenodo.org/records/4599666 | rendered mixtures, stems, MIDI | upstream CC BY 4.0 reported; strongest initial multi-instrument benchmark; synthetic instruments domain shift |
| MAESTRO v3 | https://magenta.tensorflow.org/datasets/maestro | aligned piano audio and MIDI | CC BY-NC-SA 4.0; piano only |
| GuitarSet | https://github.com/marl/GuitarSet | guitar audio + JAMS | CC BY 4.0 per aggregator; guitar-specific |
| URMP | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | chamber ensemble stems, MIDI/score | verify upstream conditions; limited production-music transfer |
| MusicNet-EM | https://zenodo.org/records/7793404 | classical audio + aligned MIDI | inspect source LICENSE.txt before use |
| MDB Drums++ | https://huggingface.co/datasets/xavriley/MDBDrumsPlusPlus | drum audio + hits | per-source terms; percussion-only |
| ENST-Drums | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | drum audio + hits | research/source terms; percussion-only |
| IDMT-SMT-Bass | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | bass audio + MIDI | research/source terms; bass-only |
| RWC Popular Music | https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2 | recordings and external annotations | CC BY-NC 4.0 reported; verify provenance and source terms |
| ASAP | https://github.com/fosfrancesco/asap-dataset | classical piano aligned MIDI, audio references | source-specific licensing; piano only |
| GAPS | https://huggingface.co/datasets/xavriley/GAPS | guitar audio/MIDI/score | source-specific terms |

## Hub collection: MIMuT Data v2
https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2
Aggregator claims **13 source datasets, 82,046 files, ~151 GB**, not 82K songs. Hub metadata license is **other**; underlying source datasets have **different licenses**. Never treat entire collection as uniformly CC-licensed. Avoid bulk downloading to GitHub-hosted CI.

## Recommended staged implementation
1. Metadata-only registry with task, source, license, rights, splits, download mode, estimated size, and source-specific reference formats.
2. Minimal local smoke set: CASD JAMS annotations only (no audio), small Slakh sample, small GuitarSet sample; store source IDs/hashes, not source media.
3. Chord evaluation: `mir_eval.chord` WCSR and multi-annotator CASD scoring; use same exact reference recording.
4. AMT evaluation: onset/offset note F1, instrument-aware metrics, per-class/drum metrics, real vs synthetic domain shift.
5. Cross-dataset validation: held-out source split, training overlap audit, hardware latency and memory.
6. Explicitly keep NC sources outside commercial-training or redistribution pipelines.

## Caveats
No exhaustive Hugging Face search or automatic license audit is claimed. Dataset card claims are provisional until verified against original publishers. Repackaged files may have different provenance and terms. Some listed corpora have no usable audio; do not imply that downloading their annotations yields a ready-to-run audio benchmark.

## Sources
- https://github.com/chordify/CASD
- https://huggingface.co/datasets/J1mmymm/MIMuT_Data_v2
- https://github.com/ismir/mir-datasets/blob/master/mir-datasets.yaml
- https://github.com/smashub/choco
- https://magenta.tensorflow.org/datasets/maestro

## 2026-11-05 — metadata-first 소량 Hub shard 수집 계약 (#62)

`scripts/ingest_hf_dataset_subset.py`는 실행 전에 **명시적으로 지정된 파일 목록**과 라이선스·용량·SHA-256·split 중복을 검사합니다. 기본 실행은 네트워크나 디스크에 접근하지 않는 계획/검증 모드입니다. `--fetch`를 직접 입력해야만 파일을 다운로드합니다. 전체 Hub 데이터셋을 열거하거나 ~151GB 수집본을 자동 다운로드하지 않습니다.

예제 파일: [hf-subset.example.json](../benchmarks/tier2/hf-subset.example.json). 안전을 위해 이 예제는 **권리 미검증 / revision 000... / 예시 SHA**이므로 원본 그대로는 다운로드할 수 없습니다. 이용 전에 사람이 원저작자 약관을 검토하고 실제 dataset repository, 정확한 40자 commit, 소스별 사용권, 소량 파일 크기와 SHA, 녹음·분할 정보를 모두 교체한 뒤에 `rights_reviewed: true`로 설정해야 합니다.

```bash
# Offline validation, does NOT download any bytes:
uv run --frozen python scripts/ingest_hf_dataset_subset.py \
  /private/verified-subset.json --private-root /private/datasets

# Explicitly download at most 8 selected files, 32MiB per file, 64MiB total:
uv run --frozen python scripts/ingest_hf_dataset_subset.py \
  /private/verified-subset.json --private-root /private/datasets \
  --fetch --report /private/subset-receipt.json

# Noncommercial sources cannot enter this mode:
uv run --frozen python scripts/ingest_hf_dataset_subset.py \
  /private/verified-subset.json --private-root /private/datasets \
  --fetch --commercial
```

각 shard는 다운로드 **이전** Hugging Face 서버에 파일 길이를 조회하고 예상 길이와 일치하지 않으면 중단합니다. 다운로드 후 실제 바이트 SHA-256 검증, 안전한 private-root 이동, 기존 파일 불일치 시 덮어쓰기 거부를 적용합니다. `recording_id` 및 선택 `audio_sha256`을 기준으로 train/validation/test 간 같은 녹음 중복을 거부합니다. 파일은 git 작업공간 바깥에만 저장되며 CI 테스트는 소유한 합성 바이트로 네트워크를 모킹해 실행합니다.

**중요한 제한:** `rights_reviewed: true`는 운영자의 검토 진술이지 자동 라이선스 인증이 아닙니다. Hub 메타데이터와 실제 저작권 상태는 다를 수 있습니다. 다운로드 가능성 ≠ 학습·상업적 이용·재배포 허가이며, 파일명/녹음 식별자만으로 모든 복제·리마스터·데이터셋 간 누출을 잡을 수도 없습니다. 실제 허가된 샘플과 상위 저작권 검증, 악보/음원 정렬 인수시험은 #59–#62에 남습니다.

## 2026-11-08 — 원자적 파일 반영 및 동일 split 중복 검증

선택한 모든 shard에 대해 서버 크기와 기존 파일 SHA-256을 선검사한 후, 하나의 임시 디렉터리에서 검증합니다. 여러 파일 중 하나라도 잘못되면 새 파일은 최종 private dataset 경로에 반영되지 않습니다. 정상 확인된 전체 파일만 덮어쓰기 없는 하드링크로 반영하며, 도중 오류 시 새로 생성한 파일만 롤백합니다. 임시 다운로드 cache는 자동 삭제합니다.

같은 녹음에 속한 여러 주석 파일은 하나의 recording으로 집계합니다. 동일 audio SHA-256이 다른 source/recording identity에 반복되면 split이 같더라도 중복으로 차단합니다. SHA가 제공되지 않은 서로 다른 녹음의 실제 동일성은 별도로 검증해야 하며 자동으로 판정했다고 주장하지 않습니다. 수집 보고서는 저장소 밖에만 기록할 수 있고 모든 라이선스·외부 출처 승인은 여전히 운영자 검토가 필요합니다.

## 2026-11-08 — CocoChorales tiny 페어링 계약 (#154)

공식 [Magenta CocoChorales](https://magenta.tensorflow.org/datasets/cocochorales)는 CC BY 4.0의 4성부 합성 앙상블 오디오와 정렬된 MIDI를 제공하며 [`main_dataset/<ensemble>_track######/mix.wav` 및 `mix.mid`](https://github.com/lukewys/chamber-ensemble-generator/blob/master/data_format.md) 형태로 같은 트랙의 정답을 얻을 수 있습니다. `scripts/prepare_cocochorales_pairs.py`는 **검토된 tiny 로컬 1~16트랙**의 WAV/MIDI/metadata를 안전하게 검사하고 SHA-256 결속된 private:// pair manifest를 만듭니다. 저장소에는 샘플 음원·MIDI를 커밋하지 않으며 실제 official tiny 파일이 입수되기 전에는 `status=planned`을 유지합니다.

추가로 ASAP 저장소는 MIDI/MusicXML과 음원 매핑을 제공하지만 오디오 자체는 별도 MAESTRO에서 가져와야 합니다. 즉 ASAP dataset registry의 `audio_included`는 `false`, license는 `CC-BY-NC-SA-4.0`으로 정정했습니다. GuitarSet은 실제 기타 녹음+JAMS/이벤트, Slakh2100은 합성 mix+MIDI이므로 세 데이터를 같은 음질·권리 조건이라고 취급하지 않습니다. 원본 파일과 HF 미러가 다르면 원본 출처를 기준으로 우선 검토합니다.
