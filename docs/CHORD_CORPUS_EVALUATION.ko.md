# Tier 2 코드·박자 다중 곡 평가 집계 (#58)

## 목적

기존 [참조 주석 변환기](CHORD_REFERENCE_INGESTION.ko.md)와 [두 후보 비교기](CHORDIFY_RESEARCH_WIKI.md)는 한 곡에 대해 `mir_eval` 지표를 계산합니다. `scripts/aggregate_chord_corpus.py`는 이 출력을 **곡 단위·데이터셋 단위로** 합산합니다. 원본 오디오 다운로드, Chordify 자동 수집, SheetSage2 모델 실행, 원본 오디오나 주석의 공개 업로드는 수행하지 않습니다.

## 사전 조건

- 권리와 녹음 버전을 확인한 **비공개** 저장소 외부 디렉터리에 파일을 보관합니다.
- JAMS/LAB은 `scripts/import_chord_reference.py`로 정규화하며, 참조 주석은 모든 시간 구간을 명시적 `N`을 포함해 빠짐없이 커버해야 합니다.
- 해당 녹음의 비교 예측은 `scripts/import_manual_chord_chart.py`와 SheetSage2 어댑터 출력에서 취득합니다. 세 파일의 `recording_sha256`와 `duration_seconds`가 같아야 하며, SheetSage2 예측도 동일한 녹음 식별 정보를 운영자가 확인 후 기록해야 합니다.
- 평가 세트는 `validation` 또는 `test`만 허용합니다. 동일 녹음의 중복 등록이나 train/test 분할 중복을 거부하지만, **이미 학습된 외부 모델의 훈련 데이터 포함 여부**까지 보증하지는 못합니다.
- `benchmarks/tier2/dataset-registry.json`에 출처별 `task`, `license`, `status`가 확인되어 있어야 합니다. `verify_upstream`, `planned`을 그대로 사용하면 평가를 거부합니다. 레지스트리의 상태나 라이선스는 저작권자의 권한을 대신하지 않습니다. 확인 없이 값을 변경해서는 안 됩니다.

## 입력 manifest

`/private/chord-eval/manifest.json` 예시입니다. `reference`, `manual`, `sheetsage2`는 `--corpus-root` 아래의 **상대 JSON 경로**입니다. 경로와 SHA-256은 반드시 실제로 확인한 값으로 교체합니다.

```json
{
  "schema_version": 1,
  "cases": [
    {
      "id": "licensed-song-01",
      "dataset_id": "casd",
      "split": "test",
      "recording_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "license": "CC-BY-NC-SA-4.0",
      "rights_reviewed": true,
      "reference": "references/song-01.json",
      "manual": "predictions/manual/song-01.json",
      "sheetsage2": "predictions/sheetsage2/song-01.json"
    }
  ]
}
```

이 JSON의 64개 `a`는 **예시 문자열**로 실재 녹음이 아닙니다. 레지스트리에도 실사용 전에 CASD의 정확한 권리 조건을 검토해야 합니다. `rights_reviewed: true`는 운영자의 확인 진술만 의미합니다. `reference`는 `dataset`, `license`, `rights_reviewed_by_operator_only: true`, `commercial_model_approved: false` 필드를 포함해야 합니다.

## 실행

```bash
uv run --frozen --with mir_eval==0.8.2 python \
  scripts/aggregate_chord_corpus.py \
  /private/chord-eval/manifest.json \
  --registry benchmarks/tier2/dataset-registry.json \
  --corpus-root /private/chord-eval/files \
  --output-json /private/chord-eval/report.json \
  --output-csv /private/chord-eval/report.csv
```

## 결과 및 해석

- **곡별:** 각 곡에 대한 수동 입력 후보와 SheetSage2 예측의 root·maj/min·thirds·triads·sevenths WCSR, beat/downbeat F1, chord boundary F1, no-chord recall, 입력 JSON 해시, 독립 주석자 수.
- **전체 및 데이터셋별:** 먼저 독립 주석자 점수를 곡 내부에서 평균하고, 이어 곡별 점수의 **단순 산술평균**(song-level macro)을 계산합니다. 20분 곡이나 주석자 4명인 곡이 짧은 곡 또는 1명 주석 곡보다 임의로 가중되지 않습니다.
- **불확실성:** 유효 곡 2개 이상인 지표에 한해 결정론적 1,000회 song bootstrap의 95% 구간을 기록합니다. 1개 이하인 지표는 구간을 `null`로 표시합니다. 주석이 없는 beat/downbeat 지표도 `0`이 아니라 `null`입니다. 작은 데이터셋의 bootstrap 구간은 유효성의 보증이 아닙니다.
- **검증 경계:** 녹음 SHA-256과 자료 출처의 독립적인 권리·정렬 검증은 `false`; `commercial_model_approved=false`; 모델 추론은 수행하지 않습니다. 수치가 만들어졌다는 이유로 출시 기준선을 통과한 것으로 간주하지 않습니다.

실제 허가된 여러 곡을 준비하고 동일 녹음의 독립 정답 및 데이터 분할을 검증하는 인수 작업은 이 코드와 별도로 #58/#57/#34에 남습니다.
