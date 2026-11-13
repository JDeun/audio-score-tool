# Gaussian note-state 경계 진단 — 실행 전 고정 프로토콜

- 날짜: 2026-11-13 (Asia/Seoul)
- 실행 이슈: [#293](https://github.com/JDeun/audio-score-tool/issues/293)
- 기준 main: `ddcbf4e6dc7df7c089c26efb3ef68bc156647978`
- 선행 연구: [가정별 실험 결과](NOTE_STATE_FACTORS_RESULTS_2026-11-13.md), [고정 프로토콜](NOTE_STATE_FACTORS_PROTOCOL_2026-11-13.md)
- 상태: 이 문서와 새 구현·독립 감사·테스트·workflow를 함께 commit한 뒤 최초 실행한다. 실행 head와 실제 Actions checkout SHA는 receipt에 기록한다. 실행 후 이 파일과 scientific source는 수정하지 않는다.

## 질문과 연구 범위

Gaussian exponent 1 조건(G)은 이전 HMM의 과도한 Silent 선택을 크게 줄였지만, pitch runs 대비 onset+offset 정답 매칭은 A1/A2 합계 980→807개로 감소했다. 동시에 macro F1은 22.149227%→24.270837%로 증가했다. 557 gained / 730 lost와 예측수 2,497→1,405를 함께 해석해야 한다. 합성 격자에서는 붙은 반음 전환 여섯 개가 한 음으로 합쳐졌다.

이번 연구의 목적은 **동일한 예측에서 종료 경계의 오차와 분할 구조를 조사하는 것**이다. 새로운 모델 조건의 성능 실험이 아니다. 기존 실제 음표·경로 파일은 공개 metadata에 없으므로 고정 코드를 다시 실행하고, 저장된 identity가 모두 같은 경우에만 진단한다. 새 pYIN 실행으로 복원한 배열이라는 사실과 이전 raw 배열 자체는 없다는 사실을 구분한다.

이전 24개 scientific source, 세 역사적 ZIP, 모든 실패 조건을 보존한다. 추출기, Gaussian exponent, 전이, 유성 prior, pitch 범위, timestamp, readout, 최소 길이, reference Hz와 scorer를 변경하지 않는다. 제품 기본값·의존성·자동 보정도 변경하지 않는다.

## 단계 1: 전체 frozen evidence 재현

이전 원본 artifact는 `note-state-factors-43344373779.zip`, 272,995 bytes, SHA256 `b20495c8936f8b4263daf2660fb57ba282264904d6b30dda076463cc6e3881f6`이다. ZIP member는 `synthetic.json`, `vocadito.json`, `audit.json`만 허용한다.

고정 runtime은 Python 3.11, NumPy 1.26.4, SciPy 1.13.1, librosa 0.10.2.post1, numba 0.60.0, soundfile 0.13.1, resampy 0.4.2, soxr 1.1.0, mir_eval 0.8.2다. 원본 vocadito ZIP은 58,492,257 bytes, MD5 `dea40fd18f14d899643c4ba221b33a46`, SHA256 `e0d6b99d3f9c594afe5ae5c4d7bdacebe569e53b809e90b89d1c771c4f9990e3`이다.

1. 수정하지 않은 `note_state_synthetic.py`로 245개 × 7개 조건을 모두 실행한다. 1,715개 예측을 저장한 뒤 authored truth를 평가하는 원래 순서를 유지한다.
2. 수정하지 않은 `run_note_state_factors.py`로 40개 WAV당 pYIN을 한 번씩 새로 실행하고 10개 조건을 모두 평가한다. 400개 예측 저장과 manifest 확인을 마친 뒤 처음으로 A1/A2 및 F0 reference를 연다.
3. 기존 `audit_note_state_factors.py`가 private 파일 전체를 다시 읽어 직접 mir_eval 점수, 7개 HMM 경로 readout, RMS, F0, 이전 baseline 재현과 집계를 감사한다.
4. 새 진단 runner가 이전 artifact와 아래 항목을 **정확히** 비교한다. 어느 하나라도 다르면 `replay_parity_failed`, 진단 aggregate는 없음, exit nonzero다.

| 대상 | 일치 조건 |
|---|---|
| Frozen source | 이전 24개 source의 원본 hash, 현재 파일 hash, replay report hash inventory |
| 실제 녹음 | 40개 원본 WAV·duration·80개 note reference·40개 F0 reference identity |
| Corpus 예측 | 400개 전체 arm 객체: event SHA256, 음표 수, A1/A2의 모든 metric·gain/loss ID |
| Corpus 관측 | 440개 배열의 dtype·shape·raw-byte SHA256, 모든 readout diagnostics |
| Corpus 집계 | 기존 aggregate, primary bootstrap, historical parity, prediction barrier와 manifest |
| 합성 | 245개 spec·eligibility·truth·alternative truth·입력 identity, 1,715개 전체 예측/점수, 1,470개 path identity, 전체 aggregate와 20개 analytic emission 행 |

실행 시간, host/platform, 새 commit SHA, NPZ 압축 container의 byte hash는 과거와의 동일성 비교 대상이 아니다. 현재 NPZ의 container hash는 현재 private 감사에서 확인하고, 역사적 동일성은 내부 raw 배열 identity로 판정한다. 이전 Python package 전체 목록 대신 고정된 수치 runtime을 기존 auditor가 검사한다. 이번 연구의 성공은 새 성능 상승을 뜻하지 않는다.

## 단계 2: 실제 녹음의 같은 onset 매칭 쌍에서 종료점 측정

모든 40개 녹음 × A1/A2를 포함한다. 상세 진단 조건은 `pitch_runs`, `gaussian_exponent_1`, `note_state_hmm` 세 가지이며, 나머지 7개 조건도 재현 receipt에 남긴다. Reference Hz는 원래 값, pitch tolerance는 50 cents이며 octave 차이를 허용하지 않는다.

각 조건과 주석자에 대해 onset-only 최대 matching을 **한 번 고정**하고, 그 동일 `(reference, prediction)` 쌍의 종료점 차이를 계산한다. 독립적인 offset matching에서 다른 예측이 선택되었다는 사실을 endpoint 변화로 오인하지 않는다.

- signed residual: `prediction offset − reference offset`; 음수는 조기 종료, 양수는 늦은 종료다.
- tolerance: `max(0.05 seconds, 0.2 × reference duration)`.
- early / within / late: mir_eval 0.8.2와 동일하게 절대 residual을 소수점 4자리로 반올림한 뒤 tolerance와 `<=` 비교한다. 범위 밖이면 부호로 early/late를 구분한다.
- tolerance excess: `max(0, abs(raw residual) − tolerance)`. 이 연속 값은 반올림하지 않는다. 따라서 matcher 기준 within이면서 raw excess가 극소 양수인 경우를 별도 count로 남긴다.
- residual, tolerance, excess, reference duration, prediction duration 각각 count, min, Q25, median, Q75, max, mean을 보고한다. Quantile은 정렬한 원표본의 선형 보간, mean은 원표본 합계/수다. 빈 표본은 count 0과 나머지 null이며 0ms로 꾸미지 않는다.

별도의 onset+offset 최대 matching도 원래대로 계산한다. 그 matching에 들어간 reference가 fixed onset pair에는 없거나, 다른 prediction을 쓰거나, fixed pair 자체는 offset을 통과하지 못하는 경우를 세어 assignment 영향을 표시한다. 후보 graph의 onset/offset edge 수와 후보가 두 개 이상인 reference/prediction 수도 기록한다. 이 후보 수는 가능한 최대 matching의 개수나 유일성 증명은 아니다.

각 A1/A2에서 G와 runs의 **offset-matched reference ID 집합**을 retained / gained / lost / neither로 나눈다. 네 집합은 전체 reference를 정확히 분할한다. 각 집합에 대해 G onset 미매칭 수와 fixed-pair endpoint 통계를 보고한다. Matching의 ID 변화는 관측상 지표이며 사람의 오류 원인 라벨이 아니다.

## 겹침, raw voicing, 최소 길이의 보조 진단

시간 구간의 교집합 길이가 **엄격히 양수**이면 overlap edge다. 두 구간이 끝점에서만 닿으면 edge가 아니다. Pitch를 조건으로 추가하지 않는다. Reference에 prediction이 여러 개 겹치는 수, prediction에 reference가 여러 개 겹치는 수, 겹침이 없는 수를 각 조건과 reference partition에 기록한다.

아주 작은 경계 오차도 두 reference와 overlap을 만들 수 있다. 이를 실제 merge/split이라고 확정하지 않는다. 보완적으로 prediction의 `[onset, offset)` 안에 reference onset이 두 개 이상 들어가는 prediction 수와 그 영향을 받는 reference 수를 보고한다. 이 규칙에도 새 허용 오차나 비율 threshold는 없다. 그 자체로 인과나 음악적 정답을 결정하지 않는다.

Raw support는 각 reference의 `[onset, offset)` 안에 있는 `t=i×0.01` 관측 중 `t<audio duration`인 프레임을 사용한다. Float 경계에 별도 fudge를 더하지 않는다. 다음 항목을 전체 reference 및 네 partition에 보고한다.

- raw voiced/unvoiced 프레임, unvoiced를 포함한 reference 수.
- reference window 안에서 양쪽 모두 raw voiced로 둘러싸인 내부 raw-unvoiced run 수. Clip 가장자리의 무성은 이 내부 gap에 포함하지 않는다.
- raw voiced인데 G가 Silent인 프레임과 해당 reference 수.
- raw unvoiced인데 G가 voiced인 프레임과 해당 reference 수.
- G의 decoded pitch segment를 재구성했을 때 원래 readout의 최소 80ms 필터에 버려진 segment와 양의 시간 overlap을 가진 reference 수, overlap edge 수 및 겹친 초.

Pruning은 기존 구현의 `duration < .08 − 1e−10` 판정을 그대로 진단하며 새로운 cutoff가 아니다. Raw support와 overlap 통계는 reference가 서로 겹치거나 A1/A2를 합치면 중복 집계될 수 있다. Corpus 전체의 유일한 프레임 수와 혼용하지 않는다. Zero-Hz가 실제 쉼인지 추적 실패인지는 이 분석만으로 판별하지 않는다.

## 단계 3: 전체 합성 경계의 raw 관측 → 상태 → 출력 비교

이전 245개 격자와 7개 조건을 모두 유지한다. Accuracy 대상 227개, 관측 모호성 15개, 전체 silence 3개를 분리하고 분모를 바꾸지 않는다. 합성 score는 새로 개선했다고 해석하지 않으며 이전 artifact와 같은 값을 보존한다.

Private 합성 배열·event 파일을 읽어 245개 F0, 1,470개 HMM path, 1,715개 event identity를 확인한다. Predictor를 다시 호출하지 않는다. Authored primary truth와 alternative truth의 각 onset/offset을 10ms 정수 frame에 놓고 같은 frame은 합친다. 각 경계에서 다음을 기록한다.

- 경계 전후 raw F0, 양쪽이 유성일 때 signed semitone 차이, clip 시작/끝 여부.
- 모든 조건의 해당 frame에서 emitted onset/offset 수와 그 경계를 가로지르는 event 수.
- HMM 여섯 조건의 전후 state, pitch-state, phase, decoded label 변화 여부.
- 가장 가까운 decoded-label 변화 및 phase 변화까지의 signed frame 거리. 동거리이면 더 이른 변화가 우선이며, 변화가 없으면 null이다. 거리를 pass/fail threshold로 바꾸지 않는다.

단음, 반복, pitch 변경, vibrato/drift, dropout, silence의 모든 case 행과 kind별 요약을 남긴다. 단음/반복/pitch-change는 원래 전체 격자 cell도 보존한다. 알려진 반음 여섯 개는 `kind=change, interval=1, gap=0`이라는 사전 정의 조건으로 읽는다. 나머지 pitch interval·길이·gap·clip 경계를 생략하지 않는다. Same-pitch gap=0 아홉 개와 dropout 여섯 개의 두 truth 해석을 유지한다.

## 집계, 독립 감사, 공개 범위

Corpus의 40개 개별 결과와 A1/A2별 집계를 모두 남긴다. 두 주석자를 합친 값은 **annotation judgments를 pooled한 기술 통계**다. 같은 물리적 음표의 독립 표본 수로 해석하지 않는다. Quantile은 모든 해당 pair의 원표본에서 다시 계산하며 녹음별 median을 평균내지 않는다. 기존 macro precision/recall/F1, 예측 수, 전체 녹음별 개선·악화, 빈 출력, bridging/pruning은 재현 receipt와 결과 문서에서 함께 보고한다. 새 inferential CI, p-value, 최적 subgroup/threshold 탐색은 하지 않는다.

새 auditor는 새 runner/diagnostic/model/scorer를 import하지 않고 직접 private evidence를 읽는다. 기존 strict parsing/hash 및 변경하지 않은 경로 readout 검증 helper는 재사용할 수 있다. 새 endpoint·partition·overlap·voicing·합성 경계 계산은 별도 코드로 재계산한다. Exact key inventory·hash·정수는 정확히 비교하고 float 집계만 작은 수치 차이를 허용한다. Contract tests는 실제 경계의 4자리 반올림, 빈 출력, 겹침/붙은 끝점, ambiguous matching, mutation, 누락 population과 실패 시 aggregate 억제를 검증한다.

Ubuntu 24.04, CPU 2 threads, 최대 35분의 별도 workflow에서 실행한다. GPU·학습·모델 credential·유료 추론을 사용하지 않는다. PR opened/reopened 또는 명시적 workflow dispatch만 scientific run을 시작하며 결과 문서 commit은 재실행하지 않는다. 실행 전 contract tests는 작은 authored 입력만 사용하고 전체 격자/corpus 결과로 설정을 고르지 않는다.

공개 artifact allowlist는 `synthetic.json`, `vocadito.json`, `replay-audit.json`, `diagnostics.json`, `audit.json` 다섯 개다. 실제 WAV·reference 본문·실제 개별 event 시간·full F0/path·private pair 상세는 공개하지 않는다. Authored synthetic truth/event/boundary는 공개할 수 있다. Corpus의 파일별/주석자별 잔차 분포와 count는 metadata로 공개한다. 누락/오류는 실패 receipt로 보존하며 완결 aggregate나 quality 승인으로 바꾸지 않는다. 원본 Actions ZIP는 그대로 checksum과 함께 보존한다.

## 결과 이후의 결정

진단 결과를 바탕으로 다음 실험에서는 note boundary 또는 readout 변경 **한 요인**을 별도 프로토콜과 issue에 실행 전에 고정한다. 이번 진단에서 실제 F1을 보고 threshold나 여러 변경의 조합을 고르지 않는다. 이전 G와 runs, 기존 실패 HMM, 여섯 반음 사례, 15개 모호성 조건을 다음 대조에서도 유지한다.

40개 vocadito는 반복 사용한 개발 데이터다. 이 연구는 full Tony 재현, Melodyne/Flex Pitch의 오디오 편집 음질, polyphonic 채보, [#281](https://github.com/JDeun/audio-score-tool/issues/281)의 같은 악보 복원, 미사용 녹음이나 사용자 편집 비용을 검증하지 않는다. 해당 검증 없이 제품 기본값이나 자동 보정을 적용하지 않는다.
