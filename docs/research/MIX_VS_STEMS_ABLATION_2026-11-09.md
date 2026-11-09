# 혼합 음원 직접 채보와 분리 stem 채보 비교 — 2026-11-09

상태: **두 모델 모두 네 곡의 양쪽 경로 실행·출처 연결·집계 검증 완료.**
이번 조건에서는 전체 stem을 각각 채보해 합친 경로가 직접 혼합 음원 채보보다
세 종류의 macro F1 모두 낮았다. 전체 악보의 기본 경로는 직접 채보로 유지한다.

## 질문과 비교 범위

같은 채보 모델에 혼합 음원을 바로 넣는 것과, Demucs가 추정한 모든
stem을 각각 채보하는 것 중 어느 방식이 음표를 더 정확하게 인식하는가?
현재 전체 악보의 기본 처리 방식을 바꾸기 전에 이 차이를 측정한다.

이 실험은 **채보 모델 출력의 음표 정확도**를 비교한다. 제품의 기타+보컬
조립기에서 수행하는 대표 파트 선택, 코드 추론, MusicXML/PDF 변환은
적용하지 않는다. 정상적으로 음표를 0개 예측한 stem도 결과에 포함한다.

## 실행 근거

- 구현: [PR #195](https://github.com/JDeun/audio-score-tool/pull/195).
- 실제 비교 실행: [Actions #42584934707](https://github.com/JDeun/audio-score-tool/actions/runs/42584934707).
- 실행 PR head: `0b29d98dca01ed29c4ee528b9a0bb9ff4aecb6b9`.
  실제 Actions checkout의 merge SHA는
  `1c06610de5ec2742c6b97572b9df20a309329502`이다.
- 원본: CocoChorales 저자 공개 샘플 저장소 commit
  `7a0b15e7be365a6b062027c38ce0f8d57ed1d98a`의 네 ZIP.
  원본 Git blob/크기, 추출한 WAV와 정답 MIDI의 SHA-256을 검증한다.
- 곡: `string_track001010`, `brass_track049013`,
  `woodwind_track097010`, `random_track145011`.
- 네 곡 모두 upstream **train split의 합성 악기 앙상블**이다.
  실제 보컬이 있는 대중음악 또는 held-out 평가 자료가 아니다.

| 구성 | 고정 조건 |
| --- | --- |
| MR-MT3 | `mt3-infer==0.2.0`, Transformers `4.57.6`, 프로그램 보존 bridge |
| YourMT3+ | 같은 mt3-infer, Transformers `4.44.2`, YPTF.MoE+Multi (noPS) |
| 공통 AMT | Torch/Torchaudio `2.7.1` CPU, seed 0, Torch 2 threads, 자동 모델 다운로드 금지 |
| 분리 | Demucs `4.0.1`, `htdemucs_6s`, shifts 1, rescale, PCM16, seed 0 |
| 입력 구간 | 검증한 원본 WAV 전체. trim, 시간 이동, 정답 기반 정렬 없음 |

AMT 체크포인트는 기존 [동일 원본 모델 비교](COCOCHORALES_MRMT3_YOURMT3_HEAD_TO_HEAD_2026-11-09.md)와 같은
독립 검증된 SHA-256을 사용한다. Demucs는 공식 manifest의
`5c90dfd2-34c22ccb.th`를 사용하며, 보고서에 실제 바이트의 전체 SHA-256과
공식 공개 SHA-256 prefix `34c22ccb`를 구분해 기록한다.
실제로 사용한 파일의 전체 SHA-256은
`34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd`이다.

## 실험 방법

1. **직접 채보:** 혼합 WAV → 해당 AMT 모델 → 예측 MIDI의 모든 음표.
2. **분리 후 채보:** 같은 WAV → Demucs 6개 stem → 같은 AMT 모델로 각각
   채보 → 각 MIDI를 원래 tempo에 따른 초 단위 음표로 읽어 multiset 합산.

모든 `drums`, `bass`, `other`, `vocals`, `guitar`, `piano`를 포함한다.
에너지 기준 stem 선택, GM 악기 이름 강제, 중복 제거 또는 정답 파트 선택을
하지 않는다. 여러 stem에서 같은 음을 검출하면 예측 중복으로 남고,
실제로 정답에도 중복이 있는 경우를 제외하면 precision을 낮춘다.

독립 MIDI 파일들을 다시 직렬화해 합치지 않는다. 동일 GM·피치의 겹친
음표가 MIDI 채널의 note-on/off 대응 때문에 다른 길이로 변하는 문제를
피하고, 분리 효과만 비교하기 위해서다.

정상적인 빈 MIDI는 0개 예측으로 측정한다. stem 하나라도 추론에 실패하면
분리 경로 전체를 불완전으로 기록하며, 성공한 stem이나 곡만 골라 평균을
내지 않는다. 네 곡의 양쪽 경로가 모두 완료되어야 macro F1을 계산한다.

### 지표

- **Onset F1:** 같은 pitch이며 시작 오차가 50ms 이내인 음표.
- **Onset+offset F1:** 위 조건과 함께 종료 오차가
  `max(50ms, 정답 음 길이의 20%)` 이내인 음표.
- **Instrument-aware F1:** 위 조건과 함께 GM 악기 identity도 일치한 음표.

각 지표에 독립적인 최대 일대일 매칭을 사용한다.
방법 식별자는 `maximum_bipartite_one_to_one_note_events_v1`이다.
앞선 Coco 연구의 greedy matcher를 조용히 대체한 재계산이 아니라,
이번 실행에서 양쪽 경로에 동일하게 적용한 새 비교 방법이다.
이전 표의 숫자와 비교해 변화를 주장하지 않는다.

## 실측 결과

8개 직접 채보와 48개 stem 채보를 모두 완료했다. 각 모델에서 네 곡의 양쪽
경로가 모두 성공했고, 실패한 stem/곡을 제외한 부분 평균은 없다.
[원본 집계·출처 증거와 독립 검토 기록](MIX_VS_STEMS_EVIDENCE_2026-11-09.json)에
metadata를 보존했다. 원본 음악·MIDI·모델 바이트는 포함하지 않는다.

MR-MT3의 [metadata artifact](https://github.com/JDeun/audio-score-tool/actions/runs/42584934707/artifacts/13658809102)를 내려받아 ZIP SHA-256
`5c8f5a5e564f0a93ad47b7a60a47c64e6fc51c5c3e00e2298d9197b450e81626`을
대조했다. 네 개 case 보고서로 집계를 다시 계산한 결과가 원본 aggregate와
일치했고, source proof와 원본 WAV/MIDI, 분리된 stem과 AMT 입력의 해시 연결도 확인했다.
이는 공개된 metadata의 독립 대조이며, 비공개 예측 MIDI를 다시 채점한 것은 아니다.

### MR-MT3

| 지표 | 혼합 음원 직접 채보 | 6개 추정 stem 채보 | stem 경로 변화 |
| --- | ---: | ---: | ---: |
| Onset F1 | 65.21% | 47.83% | −17.38%p |
| Onset+offset F1 | 43.91% | 28.92% | −14.99%p |
| GM 포함 onset+offset F1 | 22.72% | 8.41% | −14.31%p |

곡별 F1의 비가중 macro 평균이다. 네 곡 각각에서도 세 F1 모두 하락했다.

| 곡 | 직접 onset+offset F1 | stem onset+offset F1 | 직접 예측 음 수 | stem 예측 음 수 |
| --- | ---: | ---: | ---: | ---: |
| String | 58.97% | 28.29% | 125 | 301 |
| Brass | 40.37% | 30.83% | 129 | 177 |
| Woodwind | 41.23% | 26.02% | 123 | 141 |
| Random | 35.09% | 30.55% | 180 | 242 |

정답은 네 곡 합계 408음이다. 예측 음은 **557 → 861**로 54.6% 늘었지만,
시작 시각까지 일치한 음은 **313 → 298**, 종료 시각까지 일치한 음은
**210 → 184**, 악기까지 일치한 음은 **106 → 59**로 줄었다.
Onset macro precision은 57.43% → 36.36%, recall은 76.58% → 73.20%였다.
추가 예측의 원인이 중복, 분리 누출, 다른 오인식 중 무엇인지는 이 metadata만으로
확정하지 않는다. 일부 곡에서 회수한 정답 음이 늘어도 전체 F1 개선으로 이어지지는 않았다.

24개 stem 모두 정상 채보 결과로 집계되었다. 그중 7개는 유효한 빈 MIDI였다.
이는 모델의 음표 예측이 0개라는 관측이며, 해당 오디오가 완전 무음이었다는 뜻은 아니다.

### YourMT3+

YourMT3+의 [metadata artifact](https://github.com/JDeun/audio-score-tool/actions/runs/42584934707/artifacts/13659648656)도 내려받아 ZIP SHA-256
`143c0e14056c3bf1fa6fa924aade7667796184586c8a14a59d446d82f410a57e`을
대조하고, 네 case의 집계를 재계산했다. 결과는 원본 aggregate와 일치했다.

| 지표 | 혼합 음원 직접 채보 | 6개 추정 stem 채보 | stem 경로 변화 |
| --- | ---: | ---: | ---: |
| Onset F1 | 83.44% | 22.54% | −60.90%p |
| Onset+offset F1 | 67.41% | 16.62% | −50.79%p |
| GM 포함 onset+offset F1 | 4.38% | 1.69% | −2.68%p |

| 곡 | 직접 onset+offset F1 | stem onset+offset F1 | 직접 예측 음 수 | stem 예측 음 수 |
| --- | ---: | ---: | ---: | ---: |
| String | 80.72% | 15.75% | 114 | 1,059 |
| Brass | 60.00% | 18.70% | 71 | 435 |
| Woodwind | 72.64% | 17.43% | 107 | 595 |
| Random | 56.28% | 14.59% | 94 | 731 |

24개 stem 모두 성공했고 유효한 빈 MIDI는 없었다. 총 예측은 **386 → 2,820**으로
약 7.31배 늘었다. Onset 일치는 334 → 346으로 소폭 늘었으나, onset macro
precision이 **86.29% → 13.11%**로 떨어졌다. Onset macro recall은
81.23% → 84.67%였다. 더 많은 정답을 회수한 효과보다 추가 오탐의 영향이 컸다.
종료 시각까지 맞춘 음은 271 → 263, GM까지 맞춘 음은 14 → 20이었다.

Onset과 onset+offset F1은 네 곡 각각에서 하락했다. GM-aware F1은
random에서 0 → 1.435%로 개선됐고 string·woodwind에서는 0을 유지했다.
따라서 모든 모델의 모든 곡에서 모든 지표가 하락했다고 표현하지 않는다.

### 처리시간

| 측정 범위 | MR-MT3 네 곡 합계 | YourMT3+ 네 곡 합계 |
| --- | ---: | ---: |
| 혼합 음원 직접 AMT | 125.48초 | 134.47초 |
| stem별 AMT | 624.84초 | 1,113.33초 |
| Demucs 분리 | 40.79초 | 66.87초 |
| 분리 + stem AMT | 665.63초 | 1,180.20초 |
| 직접 채보 대비 배율 | 5.30배 | 8.78배 |

각 모델은 양쪽 경로를 동일한 CPU runner에서 실행했다. MR의 string
piano stem 한 번에 271.05초가 걸린 큰 편차가 있다. 각 시간에는 프로세스
시작과 모델 로드가 포함되며, 일반적인 모델 연산속도 비율로 확장하지 않는다.

### 모델 간 입력 동일성의 범위

두 모델의 원본 WAV·reference MIDI·source proof 해시는 동일하다.
Demucs checkpoint·seed·옵션·runtime identity도 동일하다. 다만 각각의
runner에서 생성한 **24개 분리 WAV 파일의 SHA-256은 모델 간에 모두 달랐다.**
각 모델 내부에서는 분리 출력과 AMT 입력 해시가 모두 일치한다.

따라서 이번 결론은 각 모델 내부의 직접/분리 경로 비교이다. 두 모델에
byte-identical stem을 공유한 별도 모델 간 비교라고 표현하지 않는다.
WAV 헤더와 PCM 파형 중 무엇이 다른지는 metadata로 측정하지 않았으며,
고정 seed만으로 기기 간 바이트 동일성을 주장하지 않는다.

## 제품 판단과 검증

현재의 **6개 추정 stem 전체 → 동일 다악기 AMT → 원본 음표 합산**을
전체 악보의 기본 경로로 채택할 근거가 없다. 이번에는 기본 직접 채보
경로를 유지하고, 연구 runner와 실측 증거를 추가했다.

후속 분리 경로는 악기·보컬 대상 선택, 불필요한 예측 억제, stem 간
중복 처리 등을 각각 별도 조건으로 비교해야 한다. 어떤 처리도 정답 악기나
음표를 입력으로 사용해서는 안 된다. 기타+보컬/Lead Sheet처럼 선택한
역할만 만드는 제품 모드의 품질은 그 역할에 맞는 별도 정답으로 평가해야 한다.

- 관련 로컬 회귀 테스트: **104 passed**.
- [정규 CI #42584934768](https://github.com/JDeun/audio-score-tool/actions/runs/42584934768):
  Python **1,729 passed / 4 skipped**, 브라우저 E2E **62 passed**.
- 실제 실험 run: 두 모델 **4/4 complete pairs**, 전체 **success**.
- 초기 workflow run #42584706683은 job-level `runner.temp` 참조 오류로
  모델 추론 전에 실패했다. 실행 step의 환경으로 이동한 후 위 run에서
  재검증했고, CLI 실패 코드 및 잘린 MIDI의 실패 증거 보존도 반영했다.

## 해석의 한계와 다음 평가

- 이 네 train 샘플로 보컬·팝·록·힙합 또는 보지 않은 곡에 대한 일반화
  성능을 입증할 수 없다. 특히 Demucs의 분리 범주와 클래식 4성부 악기는
  일대일로 대응하지 않는다.
- 정답 stem → AMT 대조군은 이번 실행에 없다. 따라서 채보 결과의 차이는
  측정하지만 분리 자체의 SDR이나 오류 원인을 단정하지 않는다.
- MusicXML/PDF의 표현·가독성, 악보 편집 시간, 출시 품질은 측정하지 않는다.
- 후속으로 Slakh·URMP의 정답 stem 및 음표 주석을 연결하고, 보컬이 있는
  실제 음악은 MUSDB/Moises 계열의 분리 정답과 별도의 음표 정답을 준비해야 한다.
- Chordify 공개 CASD 및 Isophonics/Billboard/ChoCo의 코드 주석은
  [#58](https://github.com/JDeun/audio-score-tool/issues/58)의 별도 평가 축이다.
  코드 WCSR과 악기별 음표 F1을 하나의 정확도 숫자로 합치지 않는다.

원본 음원·stem·MIDI·모델 파일은 공개 artifact에 포함하지 않는다.
이 실험은 상용 모델 배포 승인이나 제품 기본 경로 변경을 자동으로 수행하지 않는다.
