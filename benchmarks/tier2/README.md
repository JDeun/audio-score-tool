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

`private://reference/example.mid` 같은 locator는 `--corpus-root` 아래의 파일을 가리킵니다. 실제 audio/reference corpus는 Git 밖에서 관리합니다.

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
- chord accuracy/coverage where applicable
- lyrics alignment/coverage where applicable
- SATB part-count / voice-order correctness where applicable

MIDI reference가 있으면 note/onset/offset/instrument metrics를 기존 canonical evaluator로 계산합니다.

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
