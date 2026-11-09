# Tier 2 Real-Music Benchmark

이 디렉터리는 실제 음악 기반 v1 품질 acceptance의 **manifest/reference/result contract**만 저장합니다. 저작권이 있는 원본 음원은 저장소에 커밋하지 않습니다.

## 입력

각 corpus item은 `manifest.json`에 다음을 기록합니다.

- stable case id
- category / genre / structure tags
- private/local audio locator
- reference MIDI/MusicXML locator
- license/ownership note
- expected meter / pickup / part metadata

`manifest.example.json`은 형식 예시입니다.

`user-acceptance.manifest.json`은 사용자가 최종 판정용으로 지정한 **Me So Bad / FANCY / American Idiot / 나의 노래(함부영) / 사건의 지평선(윤하)** 다섯 곡을 고정합니다. 확인된 영상·녹음 버전을 기록하고 미확인 출처는 임의로 선택하지 않습니다. 첫 범위는 보컬 멜로디·코드·선택적 가사를 포함한 Lead Sheet의 최종 PDF입니다. 원음과 독립 검수 정답은 Git 밖에서 준비하고 실제 바이트 SHA를 기록해야 합니다. 모델 후보·앙상블 조합을 계속 늘리지 않으며, 동일 입력과 기준의 검증 후 **단일 모델·체크포인트·runtime·설정**을 고정합니다. 현재 이 manifest는 선곡 기록이며 실측·정답 확보·품질 승인을 뜻하지 않습니다. 이 다섯 곡의 사전학습 포함 여부도 확인되지 않았으므로 held-out 일반화 근거로 사용하지 않습니다.

`private://reference/example.mid` 같은 locator는 `--corpus-root` 아래의 파일을 가리킵니다. 실제 audio/reference corpus는 Git 밖에서 관리합니다.

2026-11-09 사용자 지정 순서: 핵심 구현과 별도 개발·검증 corpus의 모델 선정을 먼저 진행하고, 단일 모델·체크포인트·runtime·설정을 고정한 뒤 위 다섯 곡으로 최종 인수 테스트를 실행합니다. 다섯 곡은 모델 선택이나 설정 튜닝에 사용하지 않습니다. 최종 판정에서 결함을 수정해 재평가하면 변경 이력과 재평가 사실을 남깁니다. 이는 사전학습 중복 여부가 확인된 held-out 평가라는 주장은 아닙니다.

## 엔진별 prediction 생성

실제 corpus를 선택한 AMT 엔진으로 실행해 case별 prediction을 생성합니다. **모델/runtime revision과 실제 배포 artifact SHA-256을 prediction 생성 시점에 고정합니다.**

```bash
uv run --frozen python scripts/generate_tier2_predictions.py \
  benchmarks/tier2/manifest.json \
  --corpus-root /secure/audio-score-tier2 \
  --predictions-root /secure/audio-score-tier2/runs/yourmt3 \
  --engine mt3_infer \
  --model yourmt3 \
  --model-revision <exact-model-revision> \
  --runtime-revision <exact-runtime-revision> \
  --artifact-sha256 <64-hex-sha256> \
  --device cpu \
  --output /secure/audio-score-tier2/runs/yourmt3/generation.json
```

`--engine`은 `mt3_infer`, `yourmt3`, `muscriptor`, `native`를 지원합니다. 실제 실행 가능 여부와 commercial usage 제한은 기존 transcription engine contract를 그대로 적용합니다. 각 case는 manifest의 audio locator를 반드시 가져야 하며, prediction은 `<case-id>.mid`와 `<case-id>.musicxml`로 저장됩니다.

생성 디렉터리에는 `tier2-prediction-provenance.json`도 자동 생성됩니다. 이 파일은 다음을 고정합니다.

- corpus version
- case id 목록
- engine id
- model revision
- runtime revision
- artifact SHA-256

평가 runner는 이 provenance를 읽어 report의 engine identity를 자동 결정합니다. 평가 시 revision/checksum을 사람이 다시 입력하지 않습니다.

## 엔진별 prediction 디렉터리

Tier 2 runner는 case id를 기준으로 다음 파일을 읽습니다.

```text
predictions/tier2-prediction-provenance.json     # prediction 생성 provenance
predictions/<case-id>.mid             # AMT prediction, 있으면 reference MIDI와 자동 평가
predictions/<case-id>.musicxml        # 생성된 편집 가능 악보
predictions/<case-id>.music.json      # 추가 자동/외부 지표(필요 시)
predictions/<case-id>.product.json    # 사람 수정량 / publish time / export 성공 여부
```

MusicXML이 있으면 runner가 다음 구조 지표를 자동 계산합니다.

- meter correctness
- pickup/anacrusis error
- part-count correctness
- chord accuracy: 독립 reference가 주석한 구간의 실제 초 단위 지속 시간으로 가중한 root/bass/pitch-class 정확도. 코드 반복 기입은 정확도에 영향을 주지 않으며, 전위·변경 시점·예측 조기 종료 오류를 반영
- lyrics alignment coverage: NFC 정규화한 가사 텍스트·절 번호와 onset 50ms 이내의 일대일 일치율. 글자/가사 개수 비율로 대체하지 않음
- SATB part-count / voice-order correctness where applicable

MIDI reference가 있으면 note/onset/offset/instrument metrics를 기존 canonical evaluator로 계산합니다.

위 코드·가사 지표는 각 MusicXML의 tempo map과 동일한 0초 원점을 사용하며, 정답을 보고 시간 이동·템포 보정을 하지 않습니다. 미표기 구간을 임의의 no-chord 정답으로 만들지 않고, 명시적 no-chord 기호는 평가합니다. 정답이 없으면 존재 여부만 보고하며 정확도를 채우지 않습니다. `annotation_metric_protocol`이 다른 과거 개수/순서 기반 보고서와 새 보고서를 섞어 모델을 선정할 수 없습니다.

## 별도 보컬 모델 개발 검증

[run_vocadito_baseline.py](../../scripts/run_vocadito_baseline.py)는 Bittner et al.의 [vocadito v3](https://zenodo.org/records/5578807), CC BY 4.0, 원본 MD5 `dea40fd18f14d899643c4ba221b33a46`를 검증하고 40개 원음 모두를 동일 조건으로 채보합니다. 원래 Hz 음높이를 반올림하지 않고 두 독립 주석자 A1/A2 모두에 대해 onset 50ms/pitch 50cents, offset max(50ms, 20%)로 별도 평가합니다. 빈 예측은 0점, 실행 실패는 실패로 유지하며 전곡 완료 전 macro 점수·기본 모델 승격을 만들지 않습니다. 원음·예측·로그는 Git 밖에 저장합니다.

```bash
python -m scripts.run_vocadito_baseline \
  --archive /private/vocadito.zip --checkpoint-root /private/checkpoints \
  --model mr_mt3 --output /private/new-vocadito-mr-run
```

MR-MT3와 YourMT3+는 고정된 별도 runtime으로 같은 하드웨어에서 순차 실행합니다. 이는 단성 보컬의 개발 검증이며 혼합 팝 음원, 보컬 분리, 코드·박자·조성, 사람 수정량, 최종 5곡의 제품 인수와 구분합니다. 사전학습 중복은 미확인으로 기록합니다.

`product.json` 예시:

```json
{
  "manual_note_edits": 12,
  "manual_chord_edits": 3,
  "manual_measure_edits": 1,
  "manual_part_edits": 0,
  "manual_lyric_edits": 4,
  "manual_layout_edits": 2,
  "time_to_publish_seconds": 318.5,
  "successful_export": true
}
```

`total_edit_actions`는 위 edit count의 합으로 자동 계산됩니다. 직접 넣는 경우 계산값과 다르면 runner가 실패합니다.

## 사람 수정량 자동 계측

실제 앱에서 수정량을 재려면 먼저 해당 case의 telemetry 파일을 시작합니다.

```bash
uv run --frozen python scripts/start_tier2_edit_session.py case-001 \
  --output /secure/audio-score-tier2/runs/mr-mt3/case-001.product.json
```

그 다음 같은 환경에서 AudioScoreTool을 실행합니다.

```bash
export AST_TIER2_TELEMETRY_FILE=/secure/audio-score-tier2/runs/mr-mt3/case-001.product.json
```

Windows PowerShell에서는 `$env:AST_TIER2_TELEMETRY_FILE=...`을 사용합니다.

Telemetry는 명시적으로 이 환경변수가 있을 때만 활성화됩니다. 첫 번째 성공 mutation의 `song_id`에 session이 bind되며 이후 다른 곡의 수정은 무시합니다. 필요하면 `start_tier2_edit_session.py --song-id ...`로 미리 고정할 수 있습니다.

자동 분류:

- note insert/delete/pitch/duration/structure → `manual_note_edits`
- lyric-only PATCH → `manual_lyric_edits`
- chord PATCH → `manual_chord_edits`
- measure/signature mutation → `manual_measure_edits`
- publication layout PATCH → `manual_layout_edits`
- PDF/MIDI/MusicXML/파트를 모두 포함하는 성공한 최종 export → `successful_export=true`, `time_to_publish_seconds` 확정

HTTP 4xx/5xx 실패 요청과 MusicXML-only 같은 부분 export는 publish 완료로 계산하지 않습니다. `manual_part_edits`처럼 현재 별도 mutation endpoint가 없는 항목은 필요한 경우 검수자가 보완할 수 있습니다.

## 엔진별 평가 실행

```bash
uv run --frozen python scripts/run_tier2_benchmark.py \
  benchmarks/tier2/manifest.json \
  --corpus-root /secure/audio-score-tier2 \
  --predictions-root /secure/audio-score-tier2/runs/mr-mt3 \
  --output /secure/audio-score-tier2/reports/mr-mt3.json
```

runner는 `tier2-prediction-provenance.json`의 corpus/case 목록이 manifest와 정확히 일치하는지 검사하고, 그 provenance의 engine/model/runtime/artifact identity를 report에 그대로 사용합니다.

각 report에는 재현성을 위해 다음 corpus identity도 기록됩니다.

- `manifest_sha256`: 실제 manifest 파일 SHA-256
- `case_fingerprint`: ordered case-id 목록 fingerprint

동일한 `corpus_version` 문자열만으로는 후보를 비교할 수 없습니다.

## 후보 비교

두 개 이상의 report가 있으면 **corpus version + manifest SHA-256 + case fingerprint**가 모두 동일한지 확인한 뒤 baseline 후보 순위를 계산합니다.

```bash
uv run --frozen python scripts/compare_tier2_reports.py \
  /secure/audio-score-tier2/reports/mr-mt3.json \
  /secure/audio-score-tier2/reports/yourmt3.json \
  --output /secure/audio-score-tier2/reports/comparison.json
```

순위는 다음 순서를 사용합니다.

1. 모든 case 최종 export 성공
2. 평균 `time_to_publish_seconds`
3. 평균 `total_edit_actions`
4. 평균 note F1

비교기가 `recommended_engine`을 출력하더라도 `release_approved`는 항상 false입니다. #34의 provenance/license 검토와 사람이 결과를 승인해야 commercial baseline이 됩니다.

## v1 승인 evidence

실제 v1 tag 전에 candidate별 Tier 2 report 최소 2개와 comparison report를 `release/evidence/`에 metadata-only evidence로 보존하고 `release/v1-quality-approval.json`을 작성합니다. 실제 음원/reference asset은 저장소에 넣지 않습니다.

release gate는 다음을 다시 검증합니다.

1. source report SHA-256
2. source report schema와 corpus identity
3. source reports로 comparison 재계산
4. 저장된 comparison과 재계산 결과 동일성
5. 승인 engine의 model/runtime/artifact identity
6. commercial/default eligibility
7. #34 승인 metadata

## 출력

각 엔진 실행은 machine-readable JSON report를 남깁니다.

필수 모델 지표:

- note precision / recall / F1
- onset MAE / offset MAE
- instrument-aware F1
- meter / pickup / first-downbeat
- chord / lyrics / SATB metrics where applicable

필수 제품 지표:

- manual note/chord/measure/part/lyric/layout edits
- total edit actions
- time to publish
- successful export

summary에는 최소 다음 값이 포함됩니다.

- mean note F1 / instrument F1
- onset/offset error
- meter / pickup / part-count accuracy
- chord / lyrics / SATB applicable metrics
- mean total edit actions
- mean time to publish
- successful export rate

## 원칙

1. 실제 audio는 Git에 넣지 않습니다.
2. 같은 manifest/reference로 candidate engine을 비교합니다.
3. engine revision, runtime revision, checksum은 prediction 생성 단계에서 고정합니다.
4. 사람이 수정한 양과 publish time이 최상위 제품 KPI입니다.
5. Tier 2 결과 없이 commercial default engine을 교체하지 않습니다.
6. release comparison은 exact manifest identity가 다르면 실패합니다.

## 실험 후보 식별과 하이브리드 재현성

`run_tier2_matrix.py`는 각 후보의 `tier2-prediction-provenance.json`을 평가 **이전**에 생성합니다. 단일 AMT 실행 엔진이 `mt3_infer`라도 모델별 후보 ID(`yourmt3`, `mr-mt3`)는 달라야 하며, SheetSage2 보강 결과(`yourmt3+sheetsage2`)도 독립 후보입니다. 후보 ID는 **실험용**이며 승인된 제품 기본 엔진 ID를 의미하지 않습니다.

실험용 provenance에는 원본 `inference_engine` 신원과 모델/런타임/아티팩트 해시를 보존하고, `experiment.run_id`, UTC 기록 시간, 가능하면 `GITHUB_SHA`, 각 case의 MIDI/MusicXML SHA-256, 하이브리드인 경우 SheetSage2 events JSON SHA-256을 남깁니다. 이 파일을 생성할 때 corpus 버전과 **정렬된 case ID 전체**가 입력 manifest와 일치하지 않으면 실패합니다.

SheetSage2를 사용하는 하이브리드는 비상업 모델을 실행하기 전에 다음 변수를 정확히 고정해야 합니다.

```bash
export TIER2_SHEETSAGE2_MODEL_REVISION="<reviewed-checkpoint-revision>"
export TIER2_SHEETSAGE2_RUNTIME_REVISION="<reviewed-inference-runtime>"
export TIER2_SHEETSAGE2_ARTIFACT_SHA256="<64-hex-sha256>"
export AST_SHEETSAGE2_ADAPTER="<reviewed-executable>"
```

모델/런타임/아티팩트 중 어느 하나라도 누락되거나 SHA-256 형식이 틀리면 하이브리드 stage는 `blocked` 처리됩니다. `analysis.commercial_eligible=false` 및 `CC BY-NC 4.0`은 실험 결과에 명시합니다. 단독 AMT의 품질과 비상업 SheetSage2 보강 결과를 동일한 상용 후보로 취급하거나 자동 승격하지 않습니다.

각 stage의 원본 오디오와 비밀 토큰/로컬 절대 경로는 공개 artifacts에 넣지 않습니다. 이 기록은 **코드/실험 결과 출처 추적**이며, 외부 체크포인트 자체나 정식 저작권·재배포 허가를 검증했다는 뜻이 아닙니다. 실제 채보 품질 평가(#34)와 사용자 편집 시간/출판 성공 측정은 별도로 필요합니다.

## 저장된 실험 결과 무결성 검증

실험 결과를 다른 환경에서 사용하거나 #34 승인용 보고서로 전달하기 전에 파일이 원래 기록과 일치하는지 독립 검증하십시오. 원본 데이터셋과 동일한 manifest를 제공하면 corpus 버전과 case 순서도 확인합니다.

```bash
uv run --frozen python scripts/validate_tier2_experiment.py \
  --predictions-root /secure/tier2/runs/yourmt3 \
  --manifest /secure/tier2/manifest.json

uv run --frozen python scripts/validate_tier2_experiment.py \
  --predictions-root /secure/tier2/runs/yourmt3+sheetsage2 \
  --manifest /secure/tier2/manifest.json \
  --events-root /secure/tier2/runs/sheetsage2
```

검증기는 `tier2-prediction-provenance.json`의 필수 스키마, 실험 후보/실행 엔진 신원, 실행 ID, UTC 기록 시각, 체크포인트 SHA-256, 사례 목록 및 실제 MIDI/MusicXML/SheetSage2 이벤트 파일의 해시를 검사합니다. 하이브리드는 비상업 라이선스 표시와 events 경로가 필수입니다. 기록을 수정하거나 파일이 달라지면 오류와 비영(非0) 종료 코드로 차단합니다. 이 검증은 오디오 소유권 및 모델 권리 확인을 대체하지 않으며, 품질 지표를 만들어내지 않습니다.

실제 실행에서 `experiment.corpus_manifest_sha256`은 manifest의 **전체 바이트**를 고정합니다. 같은 `corpus_version`·case ID라도 오디오 locator나 reference 파일 경로가 변경된 manifest를 재사용하면 독립 검증이 실패합니다. 전용 self-hosted 러너는 검증된 `TIER2_MANIFEST_PATH`의 비공개 manifest를 그대로 사용해야 하며, 저장소의 공개 예시 경로로 대체해서는 안 됩니다.

## 도메인 데이터셋 오디오/MIDI 쌍 검증 (#59–#61)

`scripts/validate_tier2_dataset_pairs.py`는 Slakh2100/URMP, MAESTRO/ASAP/GuitarSet/GAPS, MusicNet-EM/드럼/베이스/RWC 팝 등에서 **운영자가 적법하게 확보한** 동일 녹음의 오디오·정답 MIDI 쌍을 로컬에서 검증합니다. 모델을 호출하지 않으며 파일을 공개 저장소에 복제하지 않습니다. 원본 `dataset-registry.json`에서 해당 데이터셋의 `status`가 `verified_for_evaluation`이고 라이선스가 해결된 경우만 대상으로 합니다. 기존 `planned`이나 `verify_upstream` 상태는 자동 승인되지 않습니다.

비공개 입력 JSON 예시:

```json
{
  "schema_version": 1,
  "cases": [{
    "id": "piano-001",
    "dataset_id": "maestro",
    "recording_id": "verified-global-recording-id",
    "split": "test",
    "rights_reviewed": true,
    "license": "CC-BY-NC-SA-4.0",
    "audio": {
      "locator": "private://audio/piano.wav",
      "sha256": "<ACTUAL_AUDIO_SHA256>"
    },
    "reference_midi": {
      "locator": "private://reference/piano.mid",
      "sha256": "<ACTUAL_MIDI_SHA256>"
    }
  }]
}
```

위는 **형식 예시**이며 실제 자료·SHA·권리 검토를 충족하지 않으므로 그대로는 실행 불가합니다. 데이터셋 레지스트리에 출처별로 정확한 `status/license`를 확인한 뒤 비공개 복사본에서 반영해야 합니다.

```bash
uv run --frozen python scripts/validate_tier2_dataset_pairs.py \
  /private/pairs.json \
  --registry /private/reviewed-dataset-registry.json \
  --corpus-root /private/corpus \
  --report /private/pair-verification.json \
  --tier2-manifest /private/tier2/manifest.json
```

검사 범위는 경로 탈출·심볼릭 링크 차단, 실제 오디오/참조 MIDI 파일 SHA-256, WAV 및 일반 압축 오디오의 메타데이터 길이, MIDI 구문 파싱, 동일 `recording_id` 또는 오디오 SHA-256의 train/validation/test 교차 누출 차단, 소스 라이선스 일치와 사용자 권리 검토 선언입니다. 결과는 **파일 경로 없는 메타데이터 보고서**와 저장소 밖에 보관할 Tier 2 manifest입니다. 악보 주석이 실제 오디오와 얼마나 정렬됐는지나 곡별 정답의 음악적 품질은 이 계약만으로 검증할 수 없습니다. 실제 샘플을 확보하고 독립 측정 결과를 제출하는 작업은 #59–#61/#34에 남습니다.

## 2026-11-05 — 실행 환경·실패·재시험 메타데이터 영수증 (#47)

모델 매트릭스 `scripts/run_tier2_matrix.py`는 이제 `summary.json`과 함께 **`execution-receipt.json`**을 원자적으로 기록합니다. 드라이런은 상태 `planned`/`blocked`만 기록하고 corpus/실제 실행이 존재한다고 주장하지 않습니다. 실제 실행에서 완료된 단계는 `tier2-prediction-provenance.json`(정확한 manifest SHA-256 및 출력 MIDI/MusicXML 해시 포함)과 후보 평가 보고서 SHA-256을 재검증한 뒤에만 `completed`로 수락됩니다.

영수증에는 실행 UUID, UTC 기록 시각, 매트릭스/manifest SHA-256, 순서가 있는 case fingerprint, 케이스별 운영자 선언 권리, Python/OS/CPU 수/요청된 연산장치, uv.lock SHA, 커밋(있는 경우), 단계별 실행 시간·상태, 실패 사유 SHA-256, 검증된 결과 보고서 및 원본 예측 provenance SHA-256이 포함됩니다. 실제 음원, 전체 로컬 경로, 원문 예외 문자열, 암호/토큰은 복제하지 않습니다. 따라서 실패 원문의 조사는 **비공개 CI 로그**를 사용해야 합니다. 이 영수증은 디바이스 메모리 사용량이나 GPU 실행 가능성을 직접 측정했다고 주장하지 않습니다.

완료 보고서를 변조하거나 manifest와 예측 아티팩트가 불일치하면 영수증 생성은 실패합니다. 실패·차단 뒤 다시 실행할 때 다음처럼 **이전 영수증의 corpus/matrix 신원이 동일한지 검증**하여 재시험 링크를 생성할 수 있습니다.

```bash
uv run --frozen python scripts/run_tier2_matrix.py \
  --matrix benchmarks/tier2/experiment-matrix.json \
  --manifest /private/tier2/manifest.json \
  --corpus-root /private/tier2 \
  --output-root /private/tier2/retest-02 \
  --retest-of /private/tier2/failed-run/execution-receipt.json

# No inference, verify and reconstruct receipt from an existing summary:
uv run --frozen python scripts/tier2_execution_ledger.py \
  --matrix benchmarks/tier2/experiment-matrix.json \
  --manifest /private/tier2/manifest.json \
  --summary /private/tier2/retest-02/summary.json \
  --output-root /private/tier2/retest-02 \
  --output /private/tier2/retest-02/revalidated-receipt.json
```

비모델 실행 기록 계약과 CI 테스트가 존재해도 적법한 다중 곡 corpus와 사람이 검토한 실제 품질 결과가 확보됐다는 의미는 아닙니다. 외부 권리 확인·실제 측정 지표·성능 승인 등은 #34/#47 후속 실증 조건으로 남깁니다.

## CocoChorales tiny: 공식 음원 + 정답 MIDI 페어링 (#154)

공식 [CocoChorales](https://magenta.tensorflow.org/datasets/cocochorales)는 **CC BY 4.0**으로 게시된 합성 4성부 앙상블 데이터셋이며, 공식 [파일 형식](https://github.com/lukewys/chamber-ensemble-generator/blob/master/data_format.md)에 따르면 한 트랙 폴더에 `mix.wav`, `mix.mid`, `metadata.yaml`이 함께 있습니다. 전체 데이터셋 대신 원본의 **tiny**만 소량으로 입수하고, 출처 버전·이용 조건·attribution·파일 해시를 사람이 확인해야 합니다.

`scripts/prepare_cocochorales_pairs.py`는 개발자 소유·검토된 트랙만 오프라인으로 읽습니다. WAV의 16kHz/16-bit PCM 특성과 길이, MIDI의 실제 note-on 이벤트와 시간, 입력 경로·심볼릭 링크·안전한 파일 크기 및 SHA-256을 검사합니다. 출력은 (1) 기존 `validate_tier2_dataset_pairs.py`가 읽을 **private:// mix WAV + mix MIDI** 페어링 JSON, (2) 경로·음원 바이트가 포함되지 않은 메타데이터 영수증입니다. 이 도구 자체는 모델 추론, 원본 데이터 다운로드, 라이선스 자동 승인, 참고 MIDI와 실제 오디오 정렬 정도의 독립 측정을 하지 않습니다.

```bash
# official tiny 자료는 먼저 수동 입수, 라이선스/출처/분할을 검토하고
# private/cocochorales/ 안에 각 track_id/mix.wav,mix.mid,metadata.yaml 배치
# 아래 example의 source_release_revision, rights_reviewed, track_id/split을
# 검토 후에만 수정. 예제 그대로는 유효한 출처가 아닙니다.
uv run --frozen python scripts/prepare_cocochorales_pairs.py \
  /private/reviewed-coco-selection.json \
  --corpus-root /private/cocochorales \
  --pairs /private/coco-pairs.json \
  --report /private/coco-pairs.pending.json
```

예제: [cocochorales-tiny.selection.example.json](cocochorales-tiny.selection.example.json). 공식 tiny 데이터의 실제 split, revision, 사용권은 자동으로 판정하지 않습니다. `rights_reviewed` 기본값은 `false`이고, 기존 `dataset-registry.json`에서도 CocoChorales는 **`status=planned`**입니다. 따라서 출처별 검토를 수행해 **별도의 사설 registry 사본**을 `verified_for_evaluation`로 승격하기 전에는 `validate_tier2_dataset_pairs.py`가 결과를 받아들이지 않습니다. 상용 MR-MT3 모델/실행 바이너리 재배포 허가와 데이터셋 CC BY 4.0 조건도 독립적으로 검토합니다.

대조군으로 #59 Slakh2100(합성 다중악기), #60 GuitarSet(실제 기타; JAMS 음표 이벤트 변환 필요)을 사용하고, MAESTRO/ASAP은 비상업 조건에 분리합니다. 특히 **ASAP 저장소 자체에는 오디오가 없고 별도의 MAESTRO 음원을 정렬해야** 하므로 `dataset-registry.json`의 `audio_included=false`로 수정했습니다. 본 코드는 실제 공식 CocoChorales 데이터쌍의 추론/품질 측정을 완료한 결과가 아닙니다. #154/#34에 남은 실측 사항을 추적합니다.

## Official CocoChorales tiny source integrity (#154)

The official `lukewys/chamber-ensemble-generator` format at commit `4647edbce6719fe907e17fcc072651def168eaa5` assigns track numbers 000001–192000 to train, 192001–216000 to validation, and 216001–240000 to test. `prepare_cocochorales_pairs.py` now rejects a track tagged with a contradictory split and checks the four SATB names/GM program numbers in each official `metadata.yaml`. No fixed audio/MIDI pair-count cap is imposed: larger selections remain subject to the archive, per-file and cumulative extraction-byte safety limits. The code does not infer a rights grant or upload audio.

Official dataset landing page: https://magenta.tensorflow.org/datasets/cocochorales (CC BY 4.0; attribution and changes notice apply). Source format: https://github.com/lukewys/chamber-ensemble-generator/blob/4647edbce6719fe907e17fcc072651def168eaa5/data_format.md. Real paired files must be obtained via the official tiny shard downloads and recorded with archive checksums, rather than inferring provenance from a lookalike folder or HF mirror.

### Official tiny single-shard audio+MIDI extraction (#154)

The upstream [tiny download script](https://github.com/lukewys/chamber-ensemble-generator/blob/4647edbce6719fe907e17fcc072651def168eaa5/data_download/download_cocochorales_tiny.sh) downloads many archives; do **not** run it just to obtain selected pairs from one shard. Instead, download exactly the explicitly chosen \`main_dataset/{train,valid,test}/1.tar.bz2\` from Google's official \`cocochorales_full_v1_zipped\` bucket to a private folder (never git), and verify the archive MD5 against the [official checksum list](https://storage.googleapis.com/magentadata/datasets/cocochorales/cocochorales_full_v1_zipped/cocochorales_md5s.txt). The offline tool below rechecks the fixed upstream MD5 and then extracts only the operator-selected \`mix.wav\`, \`mix.mid\` and \`metadata.yaml\` for any explicitly selected track IDs present in that shard, subject to bounded extraction size. All other shard members, including stems and synthesis data, are ignored. The archive may still be large, so check the remote file size/storage before downloading. No media is committed.

\`\`\`bash
uv run --frozen python -m scripts.extract_cocochorales_tiny \
  --archive /private/coco/shards/1.tar.bz2 \
  --selection /private/coco/tiny-selection.json \
  --output-root /private/coco/subset \
  --report /private/coco/shard-evidence.pending.json

uv run --frozen python -m scripts.prepare_cocochorales_pairs \
  /private/coco/tiny-selection.json \
  --corpus-root /private/coco/subset \
  --pairs /private/coco/pairs.json \
  --report /private/coco/pair-evidence.pending.json
\`\`\`

The operator selection must set \`source_release_revision=cocochorales_full_v1_zipped\`, \`rights_reviewed=true\`, and exact official track IDs/splits (global ranges specified above). \`1.tar.bz2\` is only one subset shard: selected tracks absent from it are refused; **do not substitute a Hugging Face mirror**. The resulting JSON records the checked original shard MD5+SHA-256, each selected WAV/MIDI SHA-256 and SATB instruments, with no source media, audio path, model weights, independent rights approval or benchmark numbers. The official CC BY 4.0 license requires attribution/changes notice; the model checkpoint's separate rights are not inferred.

### Actual AMT prediction scoring (paired-source proof required)

After the official pinned shard has been privately extracted and reviewed, validate the pair manifest against an **independently reviewed operator-local registry copy** with \`cocochorales.status=verified_for_evaluation\` (the bundled registry remains \`planned\` until real validation). Generate MT3 predictions with the existing \`scripts.generate_tier2_predictions\` runner and an exactly pinned model/runtime/checkpoint identity, using a Tier 2 manifest from \`scripts.validate_tier2_dataset_pairs\`.

Then run:

\`\`\`bash
uv run --frozen python -m scripts.score_cocochorales_tiny \
  --pairs /private/coco/pairs.json \
  --registry /private/coco/reviewed-registry.json \
  --source-proof /private/coco/shard-evidence.pending.json \
  --corpus-root /private/coco/subset \
  --predictions-root /private/coco/predictions \
  --output /private/coco/mt3-coco-score.pending.json
\`\`\`

The scoring command verifies case IDs, audio/reference SHA-256, split, rights-reviewed dataset registry, official shard source evidence, and actual Tier 2 prediction provenance. Results contain separate **note-onset F1**, **onset+offset F1** (50ms onset; offset tolerance max(50ms, 20% of reference note duration)), **instrument-aware onset+offset F1** (requires matching GM program), MusicXML part/note counts, explicit failures, and SHA-256 of the prediction files. Real \`generate_tier2_predictions\` now records per-case wall-clock inference seconds. Peak resident/GPU memory, human correction effort, and time to publish are explicitly **unmeasured**, not filled with synthetic values. This dataset is generated Bach-style SATB, not a proxy for real popular music. The tool never grants a model license or authorizes public redistribution.

### Pair-count limit removed (issue #154)

There is **no fixed four-pair/eight-media-file or 128-case limit** in the CocoChorales selection, private audio/MIDI extraction, pair validator, or scoring CLI. You may select as many tracks as are available in the exact reviewed official shard and fit the available private disk/runtime capacity. Each track contributes one WAV + one reference MIDI (plus small metadata). The score report records every selected case, not just a sampled subset.

Safety checks remain independent of track count: SHA-256 and official shard MD5 checks, a maximum 8 GiB compressed source archive, 8 GiB **cumulative selected uncompressed files**, 128 MiB per selected file, 100,000 archive members, strict path and symlink rejection, split/track identity checks, and rejection of duplicate/missing/incompatible references. These are resource and integrity bounds, not an arbitrary benchmark sampling policy. For datasets exceeding a single source shard or memory/disk budget, run multiple independent shard/corpus evaluations and aggregate them explicitly—never silently merge different train/test splits into one identity.

## Measured author-published CocoChorales example (research-only, #154)

For the first **real** score, the official [CocoChorales author demonstration](https://lukewys.github.io/cocochorales/) publishes a ZIP with unchanged mix.wav, mix.mid and metadata.yaml under the same track ID as the full dataset. The private sample preparation script pins the official GitHub Pages repository commit 7a0b15e7be365a6b062027c38ce0f8d57ed1d98a and the individual Git blob SHA-1/size, with a newly measured SHA-256 in the pending receipt. Neither the dataset ZIP nor its WAV/MIDI is republished.

The CocoChorales Real MR-MT3 Benchmark (research-only) workflow runs on a Linux CPU runner. It obtains the immutable author sample ZIP and independently pinned checkpoint, disables model network fallback during inference, uses the existing Tier 2 generator and scores note onset/offset and instrument-aware F1 against the author's original MIDI. CC BY 4.0 review is scoped only to this private sample; the committed dataset registry remains planned. Only score/hash/revision/attribution JSON is retained by GitHub Actions.

The four official examples all fall into the dataset **train** split. Results from them must not be interpreted as held-out model generalization, commercial quality acceptance, or cross-genre validation. Human edit time, full native memory peak, and model redistribution rights remain unmeasured/unapproved. Cite the original dataset creators and CC BY 4.0 license.

## 동일 역할 모델 전수 비교 계획 (#34, #43, #53, #55, #56)

`model-candidate-registry.json`는 현 프로젝트의 실제 후보와 외부 비교 후보를 **multi-instrument AMT / lead sheet / chord estimation / beat/downbeat** 역할별로 기록합니다. 새로 추가한 `scripts/plan_tier2_candidate_groups.py`는 개인/상용 계획을 분리해 라이선스·런타임 차단 사유만 출력합니다. 실제 모델 실행, 성능 순위 결정, 상업 재배포 승인을 **하지 않습니다**.

```bash
uv run --frozen python -m scripts.plan_tier2_candidate_groups \
  --role full_instrument_amt --usage-mode personal
uv run --frozen python -m scripts.plan_tier2_candidate_groups \
  --role full_instrument_amt --usage-mode commercial
uv run --frozen python -m scripts.plan_tier2_candidate_groups \
  --role chord_estimation --usage-mode personal
```

현재 AMT의 직접 경쟁 후보: **MR-MT3(4개 공식 train 예제 실측), YourMT3+ YPTF.MoE+Multi(합성 스모크), MT3-PyTorch(제품 어댑터 미연결·원본 소스 라이선스 미기재), MuScriptor small/medium/large(비상업 weights·인증/자원 차단), MIROS(원본 체크포인트·배포 라이선스·어댑터 미검증)**. 자체 Native는 학습 scaffold이며 실제 가중치가 없으므로 제품 기본 모델 선정에 포함하지 않습니다. MT3-Infer v0.2.0이 보고한 MT3-PyTorch 체크포인트 SHA-256은 MR-MT3와 동일하므로 **독립 학습 모델로 중복 계상하지 않고 어댑터 차이만** 검증해야 합니다.

화성/멜로디 분석은 **신형 SheetSage2와 구형 `sheetsage-infer`가 다른 모델**입니다. 현재 실험 매트릭스의 `sheetsage2`, `yourmt3+sheetsage2`, `mr-mt3+sheetsage2` 역사적 stage ID는 그대로 유지되지만, 이들 단계가 호출하는 실제 어댑터는 구형 SheetSage입니다. 해당 stage를 SheetSage2 품질 실측이라고 표시해서는 안 됩니다. Chordify는 수동 적법한 내보내기만 가능한 외부 서비스 비교 기준이며 정답 annotation이 아닙니다. Chordino/NNLS·ChordFormer는 chord 추정 연구 비교 후보, Beat This!는 beat/downbeat 연구 후보이며 모두 새로 측정·연결하기 전에는 `not_integrated` 또는 `research`로 표시됩니다.

**실험은 하나의 배치에서 수행하되, 동일 GPU에 여러 모델을 무작정 동시에 적재하면 추론시간/VRAM 비교가 왜곡**됩니다. 모델별 격리된 동일 사양 러너라면 병렬 실행하고, 단일 GPU라면 동등한 조건으로 순차 실행합니다. 같은 SHA-256 음원·독립 reference·split·metric tolerance·후처리에서 note onset/offset, instrument/part, 코드 WCSR, beat/downbeat 등 **해당 역할에서 비교 가능한 지표만** 비교합니다. 성능 1위는 라이선스 승인과 별개이며, 개인/비상업 winner와 상용 release 후보는 서로 다를 수 있습니다.

엔진 최종 승인에서는 `compare_tier2_reports.py`와 기존 #34 절차를 활용하되, **최종 편집 완료까지 필요한 사람 수정시간·작업 수, 모든 최종 export 성공 여부**를 중심으로 선정합니다. 적법한 held-out 다장르 reference corpus, 실제 모델 전체 실측과 법적 checkpoint/실행파일 배포권 검증이 완료되기 전에는 승자를 단정하거나 나머지 모델을 삭제하지 않습니다.

## Head-to-head MR-MT3 vs YourMT3+ using original paired author samples (#172)

The `CocoChorales Paired MR-MT3 vs YourMT3 (research-only)` GitHub Actions workflow now runs **both models as independent matrix jobs** on the same `ubuntu-24.04` CPU runner class. Each job retrieves the same **four pinned author-original CocoChorales** WAV/MIDI/metadata ZIPs by immutable Git commit and blob SHA and evaluates the actual notes against the same independent reference MIDI. Source timestamps, note F1 tolerances, metrics, MusicXML conversion, and sample order are identical. MR-MT3 and YourMT3 have genuinely different pinned model checkpoints and **different required Transformers versions**, so each model has its own environment. YourMT3+ specifically means the shipped `yourmt3` YPTF.MoE+Multi (noPS) adapter, not another YourMT3+ variant.

The YourMT3 checkpoint is downloaded privately from the original Hugging Face Space `mimbres/YourMT3`, immutable revision `5e66c1ea173a8186e0d20432b841d3180cc015b5`, `amt/logs/2024/mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops/checkpoints/last.ckpt`, **SHA-256 `ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25`**. The code rejects Git LFS pointer blobs and hash/size mismatches; the checkpoint is staged only outside Git under `MT3_CHECKPOINT_DIR/yourmt3/…/last.ckpt`. Model/source/MIDI and MusicXML bytes never enter public workflow artifacts.

For each candidate the private run writes a per-case provenance and `four-ensemble-score.pending.json` with onset/offset/instrument F1, predicted vs reference GM histograms, part counts, inference time, failure count, original media and reference SHA-256. The final `pair-and-compare` job rejects a different upstream source proof SHA, audio SHA, reference MIDI SHA, split or case count and produces **JSON-only** `head-to-head.pending.json`. The two candidate jobs may run concurrently on separate GitHub-hosted VMs, but CPU contention within one runner is avoided. Their hardware class is the same; exact CPU frequency/thermal conditions are not guaranteed equal, so latency comparisons remain approximate.

**This is an engineering A/B on four author-published *train-split* synthesized Bach-style ensemble examples, not an independent held-out/test benchmark.** The comparison emits a research-only ordering if all four pairs were scored; `commercial_default_selected=false`, `release_quality_approved=false`, `heldout_generalization_measured=false`. The YourMT3 upstream code repository's GPL-3.0 notice and Space/model checkpoint license/weights redistribution conditions remain separate legal review. Do not infer an authorized commercial runtime or remove other model implementations from a four-song result. The next production decision requires the held-out real-music Golden Set, equal editorial completion protocol, legitimate model/source redistribution rights, and human editing cost metrics.


## Reuse issue #154's official author sample for real MuScriptor CPU QA (#55)

The existing [CocoChorales author examples](https://lukewys.github.io/cocochorales/)
are **real files published by their authors**, with independent MIDI references
for each WAV. They have already been used in the [MR-MT3 vs YourMT3 paired
comparison](https://github.com/JDeun/audio-score-tool/actions/runs/42535843289).
A new YouTube URL is **not necessary** to execute the first genuine MuScriptor
small inference. Do not confuse this original-source engineering sample with
a held-out recording: the four author examples are all `train` split.

To run the gated small model, open [Actions → Tier 2 Actual Model Smoke
Tests](https://github.com/JDeun/audio-score-tool/actions/workflows/tier2-actual-models.yml)
and select **Run workflow** with:

- `muscriptor_source = cocochorales-author-train`
- `youtube_url` left **empty**
- Repository Variable `ENABLE_MUSCRIPTOR = true` deliberately configured for
  the research run
- Repository Secret `HF_TOKEN` securely configured for a Hugging Face account
  that has **explicitly accepted** the noncommercial MuScriptor small license

Never include the token in an issue, workflow input or commit. Missing
credentials or absent model-license access are **blocked/skipped, not a score
of zero**. Normal `pull_request` CI does not start this gated job.

The manual job downloads `string_track001010.zip` from exact upstream author
commit `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a`, verifies the pinned Git
blob and original `mix.wav`/`mix.mid` with the existing
`prepare_cocochorales_official_sample` source/rights checks, then privately
downloads MuScriptor small. Inference **clears `HF_TOKEN`**, runs the actual
AudioScoreTool MuScriptor engine with offline weights, and evaluates the MIDI
and MusicXML against the original reference using the same onset, onset+offset
and exact-GM instrument metrics as the MR-MT3/YourMT3 experiments.

Only `out/muscriptor/verification.pending.json` leaves the CI runner.
Its source/audio/reference/checkpoint/output hashes, F1, model runtime commit
and inference duration can be compared with earlier candidate results without
exposing model weights, original WAV, reference MIDI or predicted scores.
The receipt explicitly marks the sample as `dataset_split=train` and keeps
`checkpoint_revision_pinned_before_download=false`,
`redistribution_approved=false`, `heldout_generalization_measured=false`,
`release_quality_approved=false`. No human edit-time metric is fabricated.

The alternative `muscriptor_source=authorized-youtube` requires a separately
reviewed `youtube_url` and reports **N/A** for F1 because it lacks an independent
MIDI reference. The Tinashe example mentioned in [#57](https://github.com/JDeun/audio-score-tool/issues/57)
is a research candidate, not an authorized pinned media URI and reference-MIDI
pair. Do not silently substitute it for the original author audio.

This first gated run is only the small/CPU/author-train engineering gate.
Medium/large GPU or MPS, held-out real-genre quality, user edit-to-publish
time, independent checkpoint redistribution provenance, and platform packages
remain separate blockers (#55, #34, #29).

## Ground-truth evaluation of the *final MusicXML score* (#34, #154)

The earlier CocoChorales four-pair benchmark reported note/pitch/onset/offset
and instrument-aware F1 **from predicted MIDI**, but inspected MusicXML mainly
for structural validity and part count. A model can therefore score well in raw
MIDI while losing or changing playable notes when converting to sheet music.

The source-bound scorer now retains all historical raw MIDI metrics and adds:

- `score_musicxml_reference_fidelity.against_reference`: independent F1 for the
  final **MusicXML score**, interpreted as playable notes by the app's music21
  MusicXML→temporary MIDI converter, against the same pinned reference MIDI
- `score_musicxml_reference_fidelity.against_prediction_midi`: conversion
  fidelity between the final score and the model's own unmodified MIDI
- `score_part_count_absolute_error`: absolute difference between MusicXML
  parts and four original SATB voices; useful as a warning, not a true
  voice-assignment accuracy measure
- `score_musicxml_macro_successful_only` and
  `observed_musicxml_score_macro_by_candidate`: separately audited full-case
  model comparison; historical no-score reports use `null`, not zero

The temporary score round-trip MIDI is deleted after parsing and never enters
public artifacts. A MusicXML file that merely contains `<note>` tags but
cannot produce playable notes is a failed score, not a passed benchmark.
All comparisons use the same original WAV and independent source MIDI hashes.

**Interpretation:** This is a *playback-event proxy* for sheet similarity.
It measures pitches, note timing/duration and GM instrument assignment, but
does not score engraving layout, notation spelling, beaming, rests, staff
distribution or manual editing burden. music21 MIDI round-tripping itself
can quantize offsets and alter program mapping; compare against the raw MIDI
and investigate deltas before attributing every discrepancy to the model.
Author-supplied CocoChorales 4 tracks are **train** samples; held-out real
genre F1 and time-to-publish remain mandatory before choosing a release model.

### Reference-only codec calibration for the MusicXML score F1 (#34)

A final MusicXML score can receive a lower note F1 than the model's raw MIDI,
but the score evaluation itself reads XML via music21 and converts it back to
MIDI. That round-trip may change timing, quantization or instrument programs.
Do not attribute the entire difference to the neural model until this codec
effect is measured independently.

The [CocoChorales Reference MusicXML Roundtrip Control](https://github.com/JDeun/audio-score-tool/actions/workflows/coco-reference-musicxml-control.yml)
uses the exact four source-pinned **author train** samples from #154, extracts
the unchanged **reference MIDI** under the same source proof, converts the
reference MIDI → MusicXML → MIDI using pinned music21 10.5.0, and scores
its note-onset / onset+offset / strict GM instrument F1 against the original
reference MIDI. There is **no model** in this experiment. Control F1 below
1.0 quantifies the score codec's contribution under the current measurement
convention, not a model's error. The control is an additional baseline, not
an automatic correction factor to subtract from model F1.

Only metadata-only per-track JSON plus an explicitly four-case macro control
are uploaded; author audio/MIDI, interim MusicXML, and model weights remain
private. The report is not held-out, human edit-to-publish or commercial
release quality evidence.

## 2026-11-09 — 혼합음원 직접 채보와 Demucs 전 stem 채보 A/B

연구 runner [scripts.run_cocochorales_stem_ablation](../../scripts/run_cocochorales_stem_ablation.py)는 같은 원본 WAV·독립 reference MIDI에 대해 **혼합음원 직접 AMT**와 **Demucs가 추정한 모든 stem을 각각 AMT한 결과**를 비교합니다. 두 경로는 같은 AMT checkpoint·runtime·seed를 사용합니다. 기본 후보는 Demucs `htdemucs_6s`의 drums/bass/other/vocals/guitar/piano 6개 전부이며, `--separator htdemucs`로 4-stem 조건도 별도 실행할 수 있습니다. 원본 전체 길이를 사용하며 trim·시간 정렬 탐색·낮은 에너지 stem 제외·정답에 따른 stem 선택을 적용하지 않습니다.

분리 실행은 [scripts.separate_benchmark_stems](../../scripts/separate_benchmark_stems.py)가 담당합니다. Demucs 4.0.1, shifts 1, PCM16/rescale과 Python·NumPy·Torch seed를 고정하고, 새 비공개 디렉터리에서 정확한 4/6개 출력의 SHA-256·sample rate·channels·frames·길이를 검증합니다. 선택한 공식 checkpoint의 실측 SHA-256과 공식 prefix, 모델 YAML, runtime/options를 기록하며 이미 존재하는 분리 결과는 재사용하지 않습니다. 고정 seed가 서로 다른 기기·runtime의 비트 단위 동일성을 보장하지는 않습니다.

아래는 저장소 루트에서 실행하는 최소 예시입니다. `/private/amt-env`에는 [실험 workflow](../../.github/workflows/cocochorales-stem-ablation.yml)와 같은 모델별 고정 환경을 설치하고, 원본 corpus·검증된 pairs/registry/source-proof·정확한 AMT checkpoint는 미리 비공개 경로에 준비합니다. 작업 디렉터리와 report 파일은 새 경로여야 합니다.

```bash
# 분리 helper만 실행: 진행 로그는 stderr, 검증 metadata는 stdout.
TORCH_HOME=/private/coco/torch-cache /private/amt-env/bin/python \
  -m scripts.separate_benchmark_stems \
  /private/coco/corpus/audio/source.wav /private/coco/separation-inspection \
  --model htdemucs_6s --device cpu --seed 0 \
  > /private/coco/separation-proof.json

# 동일 author sample의 mix/stems A/B를 실제 실행하고 평가.
TORCH_HOME=/private/coco/torch-cache /private/amt-env/bin/python \
  -m scripts.run_cocochorales_stem_ablation \
  --pairs /private/coco/evidence/pairs.json \
  --registry /private/coco/evidence/reviewed-registry.json \
  --source-proof /private/coco/evidence/source-proof.pending.json \
  --corpus-root /private/coco/corpus \
  --work-root /private/coco/ablation-run-001 \
  --checkpoint-root /private/coco/checkpoints \
  --model mr_mt3 --separator htdemucs_6s --device cpu \
  --output /private/coco/reports/mr-mt3-case.json
```

[전용 scorer](../../src/audio_score_tool/stem_ablation.py)는 stem별 **raw note multiset의 합집합**을 초 단위 시간축에서 평가합니다. MIDI를 병합·재직렬화하거나 중복 음을 제거하거나 GM 프로그램을 바꾸지 않습니다. onset F1, onset+offset F1, instrument-aware onset+offset F1마다 독립적인 **최대 일대일 이분 매칭**을 사용합니다. onset 허용치는 50 ms, offset 허용치는 `max(50 ms, reference 음 길이의 20%)`입니다. 중복 예측도 각각 예측 음 수에 포함됩니다.

유효한 빈 MIDI는 **0개 음 예측**으로 평가에 포함합니다. 한 stem이라도 분리·추론·검증에 실패하면 separated 경로는 incomplete이며, 성공한 stem만 골라 완성 결과로 집계하지 않습니다. `--aggregate`는 동일 모델·분리 설정·측정 계약의 case report를 받아 네 공식 예제의 완전한 비교 여부를 확인합니다. 불완전한 실행은 JSON에 실패를 남기고 비영 종료 코드를 반환합니다.

현재 범위는 upstream 저자가 공개한 **train split의 4곡**입니다. held-out 일반화, 원본 정답 stem 대비 SDR, 최종 MusicXML/PDF 품질, 사람 편집 시간은 측정하지 않습니다. WAV·분리 stem·reference/prediction MIDI·모델 weights는 저장소와 공개 artifact에 포함하지 않고, CI에는 검증된 JSON metadata만 남깁니다.

구현과 실행 추적: [PR #195](https://github.com/JDeun/audio-score-tool/pull/195), [CI run 42584934707](https://github.com/JDeun/audio-score-tool/actions/runs/42584934707). 두 모델 모두 네 곡의 양쪽 경로가 완료됐습니다. 이번 조건에서 onset+offset macro F1은 MR-MT3 **43.91% → 28.92%**, YourMT3+ **67.41% → 16.62%**로 낮아져 전체 악보의 직접 채보 기본 경로를 유지합니다. 원본 자료의 범위, 다른 지표, 처리시간, 모델 간 분리 WAV 바이트 차이와 해석은 [실험 보고서](../../docs/research/MIX_VS_STEMS_ABLATION_2026-11-09.md), 원본 metadata는 [영구 증거 JSON](../../docs/research/MIX_VS_STEMS_EVIDENCE_2026-11-09.json)에 기록했습니다.
