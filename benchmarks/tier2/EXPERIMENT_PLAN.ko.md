# Tier 2 모델 실험 실행 계획 (2026-10-23)

## 목적 및 검증 가능한 가설

**실측 전에는 모델 순위나 성능 개선을 주장하지 않는다.** 동일한 실음원, 정답, 후처리, 하드웨어 조건에서 AMT 후보를 비교한다.

- H1: YourMT3 계열과 MR-MT3 계열의 note onset/offset, 악기 분리, MusicXML 완성도는 장르에 따라 차이가 난다.
- H2: SheetSage2의 chord/beat/key/melody 결과를 **보조 주석**으로 제공하면 기본 AMT 단독보다 사람의 악보 수정 시간이 줄어든다. AMT 전체 대체 가설이 아니다.
- H3: MuScriptor의 개인·비상업 비교 결과는 상용 기본 엔진 승격 근거로 사용할 수 없다(CC BY-NC 관련 제약 확인 필수).

## 실행 전 확인

1. 소유하거나 명시적 평가 권한이 있는 음원과 reference MIDI/MusicXML을 저장소 밖에 준비한다. 공개 CI에는 원본 음원을 업로드하지 않는다.
2. `benchmarks/tier2/manifest.example.json`을 참고해 **실제** `manifest.json`을 만든다. piano, guitar, pop/CCM, rock, hip-hop/R&B, choir, ensemble, noisy/live, tempo/meter change, pickup을 포함하고 장르별 결과를 따로 보고한다.
3. 각 모델의 정확한 revision, runtime revision, artifact SHA-256, 라이선스, 다운로드/실행 조건을 기록한다. 실행 불가능한 후보는 성능 0점이 아니라 **blocked + 오류 로그**로 기록한다.
4. 모델별 GPU/CPU, OS, 메모리, 실행 시간, peak RSS/VRAM, 추론 실패율을 별도 기록한다. 다른 하드웨어 간 절대 지연을 직접 비교하지 않는다.

## 첫 실행: 기존 엔진을 기준선으로

```bash
uv sync --frozen
uv run --frozen python scripts/generate_tier2_predictions.py \
  benchmarks/tier2/manifest.json \
  --corpus-root /secure/audio-score-tier2 \
  --predictions-root /secure/audio-score-tier2/runs/yourmt3 \
  --engine mt3_infer --model yourmt3 \
  --model-revision <PINNED_MODEL_REVISION> \
  --runtime-revision <PINNED_RUNTIME_REVISION> \
  --artifact-sha256 <64_HEX_SHA256> --device cpu \
  --output /secure/audio-score-tier2/runs/yourmt3/generation.json
uv run --frozen python scripts/run_tier2_benchmark.py \
  benchmarks/tier2/manifest.json \
  --corpus-root /secure/audio-score-tier2 \
  --predictions-root /secure/audio-score-tier2/runs/yourmt3 \
  --output /secure/audio-score-tier2/reports/yourmt3.json
```

위 명령은 **실제 corpus, 설치된 모델, 정확한 revision/checksum이 있을 때만 실행 가능**하다. `--device cpu`는 최소 재현성 확인용이며 실시간 성능을 보장하지 않는다. `--engine` 지원 값은 `mt3_infer`, `yourmt3`, `muscriptor`, `native`이다. MR-MT3는 실제 등록된 모델/런타임 구성과 연결됐는지 먼저 검증한다. SheetSage2는 현재 이 AMT runner의 엔진 선택지가 아니므로 별도 격리 PoC로 평가하고 AMT 결과와 무리하게 같은 형식의 다중 악기 F1을 비교하지 않는다.

## 비교 및 통과 기준

동일 corpus manifest SHA-256, case fingerprint, reference, 후처리 설정을 사용하고, 엔진별 동일한 사람 편집 프로토콜을 적용한다. 비교 스크립트:

```bash
uv run --frozen python scripts/compare_tier2_reports.py \
  /secure/audio-score-tier2/reports/yourmt3.json \
  /secure/audio-score-tier2/reports/other-candidate.json \
  --output /secure/audio-score-tier2/reports/comparison.json
```

핵심 제품 KPI는 (1) 모든 최종 악보 export 성공 (2) time_to_publish_seconds (3) total_edit_actions 이다. Note F1, onset/offset, 악기별 F1, meter/downbeat/pickup, chord accuracy, peak RAM/VRAM, RTF는 원인 분석 지표로 함께 기록한다. **비교 가능한 실제 결과가 없으면 엔진 선정 결정을 보류**한다. 연구 모델의 비상업 라이선스를 상용 제품 사용 승인으로 해석하지 않는다.

## 현재 실험 상태

- 계획과 기존 runner/manifest 인터페이스 확인: 완료
- 권한 있는 실제 음원 corpus 및 reference 확보: 미확인
- 라이선스가 확인된 실제 곡 및 동일 reference를 이용한 Tier 2 비교 추론: 미실행
- 모델별 결과와 제품 KPI 비교: 미실행

연계 이슈: #34 (Tier 2), #43 (SheetSage2), #47 (실험 provenance).

## 2026-11-05 CI 스모크 실험 기록 (실제 음악 품질 측정 아님)

- Actions [실행 #41976831365](https://github.com/JDeun/audio-score-tool/actions/runs/41976831365): **합성된 자체 코드 음원**으로 YourMT3 추론 명령이 완료되고 MIDI/MusicXML을 생성했지만, 파싱한 악보는 **1개 파트 / 0개 음표**였다. 따라서 end-to-end 품질 성공이나 note F1 달성으로 간주하지 않는다.
- 동일 실행에서 MR-MT3는 `T5Block.forward() got an unexpected keyword argument 'past_key_values'`로 중단됐다. 사용된 `transformers==4.44.2`의 T5Block 시그니처는 `past_key_value`(단수)인 반면 MR-MT3 wrapper는 복수형을 전달한다.
- 시험용 환경을 `mt3-infer[torch]==0.2.0` + `transformers==4.57.6`으로 고정하고 로드 시 T5Block 시그니처를 검사하도록 수정했다. **수정 전후의 실제 추론 성공 여부와 정확도는 별도로 확인해야 한다.**
- 여기 기록된 합성 스모크 결과는 장르별 실음원 corpus, 독립 reference MIDI, 계측된 사람 편집 시간에 대한 어떠한 대체도 아니다. 모델 성능 순위와 v1 상용 기본 모델 결정은 계속 보류한다.

### 2026-11-05 SheetSage2 hybrid 실추론 레이블 호환성

- AMT 단독 작업은 YourMT3 및 MR-MT3 모두 실행 완료. YourMT3 합성음원 악보에는 음표가 **0개**, MR-MT3에는 **2개**였음. 실행 성공을 품질 통과와 혼동하지 않는다.
- [실험 #41978284123](https://github.com/JDeun/audio-score-tool/actions/runs/41978284123) 하이브리드에서 Harte 레이블 `C:aug`를 music21 기본 표기로 전달해 실패한 사례를 확인함. 알려진 Harte 품질만 명시적으로 대응하고, 지원하지 않는 변형은 오류로 유지하는 정규화와 회귀 테스트를 추가함.
- YourMT3에는 `transformers==4.44.2`, MR-MT3에는 `4.57.6`을 각각 고정하여 T5 API 충돌을 격리함. 현재 실제 음원의 화성 정확도 및 수동 수정시간 평가는 별도이다.

### Hybrid provenance guard (2026-11-05)

Matrix experiments must produce a candidate-specific `tier2-prediction-provenance.json` before evaluation. `yourmt3`, `mr-mt3` and their SheetSage2 augmentations may use the same base MT3-Infer runner but **must not share a report candidate ID**. The source AMT identity and checksums are preserved; the analysis checkpoint/runtime SHA-256 and every case's event-file SHA-256 are explicit. If pins or case identity are absent, evaluation is blocked instead of fabricating a completed benchmark. For the workflow implementation and tests see issue #47.
