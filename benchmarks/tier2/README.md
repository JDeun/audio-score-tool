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

## 엔진별 prediction 디렉터리

Tier 2 runner는 case id를 기준으로 다음 파일을 읽습니다.

```text
predictions/<case-id>.mid           # AMT prediction, 있으면 reference MIDI와 자동 평가
predictions/<case-id>.music.json    # meter/downbeat/chord/lyrics/SATB 등 추가 자동 지표
predictions/<case-id>.product.json  # 사람 수정량 / publish time / export 성공 여부
```

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

## 실행

```bash
uv run --frozen python scripts/run_tier2_benchmark.py \
  benchmarks/tier2/manifest.json \
  --corpus-root /secure/audio-score-tier2 \
  --predictions-root /secure/audio-score-tier2/runs/mr-mt3 \
  --engine-id mr_mt3 \
  --model-revision <exact-model-revision> \
  --runtime-revision <exact-runtime-revision> \
  --artifact-sha256 <64-hex-sha256> \
  --output /secure/audio-score-tier2/reports/mr-mt3.json
```

동일한 manifest/reference를 사용해 MR-MT3, YourMT3 등 후보별 prediction root만 바꿔 실행합니다.

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
- mean total edit actions
- mean time to publish
- successful export rate

## 원칙

1. 실제 audio는 Git에 넣지 않습니다.
2. 같은 manifest/reference로 candidate engine을 비교합니다.
3. engine revision, runtime revision, checksum을 결과에 기록합니다.
4. 사람이 수정한 양과 publish time이 최상위 제품 KPI입니다.
5. Tier 2 결과 없이 commercial default engine을 교체하지 않습니다.
