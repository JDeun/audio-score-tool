# 모든 자식이 살아남는 분할만 승인하는 G 부모 보존 실험 — 사전 정의

- 날짜: 2026-11-13 (Asia/Seoul)
- 다음 이슈: [#298](https://github.com/JDeun/audio-score-tool/issues/298)
- 근거: [#296 / #297 완료 결과](NOTE_BOUNDARY_READOUT_RESULTS_2026-11-13.md)
- 상태: **설계만 정의했다. 구현·실행하지 않았으며 새로운 성능 수치는 없다.** 다음 실행은 구현, 독립 감사, 테스트, workflow와 전체 입력을 별도 frozen head로 고정한 뒤 시작한다.

## 질문과 이번 결과가 말해 주지 않는 것

지속 raw-pitch 경계로 G 구간을 나눈 #296은 합성 반음 여섯 조건을 모두 회복하고 이전 221개 성공을 보존했다. 그러나 실제 녹음의 offset-inclusive F1은 24.270837%에서 16.279944%로, onset F1은 57.225361%에서 35.916666%로 떨어졌다. 짧은 조각이 13개에서 1,682개로 늘고 출력 시간은 68.677875초 줄었다.

다음 질문은 **기존 readout이 삭제할 자식을 만드는 분할을 부모 단위로 거절하면, 원래 출력 시간 구간을 보존하면서 경계 회복과 정답 손상의 균형을 개선할 수 있는가**이다. 새로운 길이 threshold를 고르지 않고 기존 80ms 규칙의 적용 순서에 승인 조건 하나를 추가한다.

G의 offset 정답 중 잃은 506건 가운데 436건은 짧은 자식이 있는 부모와 연결됐지만, 이것은 공동 발생이다. 모든 자식이 삭제된 부모와 연결된 손실은 8건뿐이다. Guard가 436건을 회복한다거나 pruning이 모든 손실의 원인이라고 가정하지 않는다. 자식이 모두 80ms 이상인 잘못된 분할은 이 guard도 통과할 수 있다. 실제 raw pitch 변화점을 모두 vibrato라고 부르지도 않는다.

## 유일한 새 요인: 부모 단위의 전체 승인 또는 원본 복원

새 arm은 `gaussian_raw_hysteresis_parent_guard`다. 주 기준선은 `gaussian_exponent_1`(G), 보조 기준선은 #296의 `gaussian_raw_hysteresis_split`이다.

1. G의 모든 prefilter 부모를 기존 순서로 열거한다. 기존 raw-positive median/rint, 실제 audio duration clipping, positive raw support, 80ms 판정으로 원래 부모의 출력 여부와 원본 event를 얻는다.
2. 원래 출력되지 않은 부모는 계속 출력하지 않는다. 그 부모와 이유는 진단 분모에 남기지만 새 cut으로 되살리지 않는다.
3. 원래 출력된 부모에는 #296과 같은 전체 raw Hz의 `labels_from_hz(..., support=5)`와 같은 양성→양성 pitch 변화점, 같은 부모 내부·audio end 조건을 적용한다. 후보를 부모마다 재계산하거나 일부만 고르지 않는다.
4. 추가 cut이 없으면 원래 G event 객체를 그대로 출력한다. Cut이 있으면 모든 cut으로 자식들을 한 번에 제안하고, 각 자식에 원래 readout을 그대로 적용한다.
5. **모든 자식이 positive support, 양의 clipped duration, 기존 최소 길이 규칙을 통과할 때만 전체 분할을 승인한다.** 하나라도 실패하면 모든 제안 자식을 버리고 원래 G event 객체를 그대로 출력한다.
6. 일부 cut을 탐욕적으로 제거하거나 가까운 cut을 합치지 않는다. 순서를 바꿔 좋은 조합을 탐색하지 않는다. Floating-point 경계 처리는 현재 readout의 비교식과 완전히 같아야 한다.

원래 출력된 부모에서 승인한 자식들의 시간 구간 합집합은 원래 부모의 구간과 같아야 한다. 거절한 경우 원래 event bytes가 같아야 한다. 따라서 **최종 출력 시간 구간의 합집합 보존**을 계약으로 검증할 수 있다. 이는 부동소수점 합계의 bitwise equality, 자식의 median pitch, matched-reference 집합 또는 정확도의 보존을 뜻하지 않는다.

Acoustic frontend, pYIN, G path, emission/transition, voiced support, 5프레임 지속 조건, 80ms 규칙, raw-zero 처리, timestamp, pitch 산정, matching tolerance를 바꾸지 않는다. 이 조건을 제품 설정에 연결하지 않는다.

## 자료와 사전 고정할 새 입력

### 기존 자료의 정확한 재현

- 실제 vocadito 40개, A1/A2, 이전 11개 arm을 그대로 유지하고 새 arm 하나를 추가한다. **40×12=480개 예측**을 첫 reference 접근 전에 전부 저장하고 hash를 고정한다.
- 기존 authored 245개와 8개 arm을 그대로 유지하고 새 arm을 추가한다. 이 모집단은 **245×9=2,205개 예측**이다. 정확도 대상 227개, ambiguity 15개, silence 3개를 유지한다.
- #297 원본 receipt의 기존 corpus 440개 예측/440개 배열과 synthetic 1,960개 예측/245개 입력/1,470개 경로를 정확히 재현해야 신규 대비를 해석한다. 원래 35개 source와 #296의 frozen 53개를 수정하지 않는다.
- 기존 반음 여섯 조건과 기존 G 성공 221개를 각각 보고한다. 추가 cut 없음, 승인 거절 시 원래 G parity, 원래 short/no-support 부모의 부활 금지를 별도 검사한다.

### 추가 소유 스트레스 216개

기존 정수 MIDI 중심 ±0.3 modulation은 반올림 경계를 넘지 않는다. 다음 factorial 입력은 경계를 넘는 표현 변화와 인접 pitch 변화의 구분을 검사하도록 미리 정한다. 이 값들은 새로운 추론 threshold가 아니다.

| 축 | 사전 지정 값 |
|---|---|
| 기본 MIDI 중심 `b` | 45, 57, 69 |
| 중심 detuning `d` | −0.4, 0, +0.4 semitone |
| Modulation 진폭 `a` | 0.3, 0.6 semitone |
| Modulation 속도 `f` | 3, 6 Hz |
| 전체 유성 길이 `D` | 0.24, 0.48, 0.96초 |
| 시간 격자 | 10ms, 앞뒤 silence 각 0.10초, 시작 위상 0 |

각 조합을 아래 두 의도 조건으로 만든다. 각 조건은 3×3×2×2×3=108개이며 서로 평균을 합치지 않는다.

- **단일음 표현 조건 108개:** 유성 구간에서 `m(t) = b + d + a*sin(2*pi*f*(t-onset))`. Truth는 전체 유성 구간의 한 음이며 중심 Hz는 `440*2**((b+d-69)/12)`다. 중심 detuning을 truth에서 반올림하지 않는다.
- **인접 반음 조건 108개:** 같은 식에 유성 구간 중앙부터 +1 semitone를 더한다. Modulation 위상은 연속이다. Truth는 중앙 경계에서 나눈 두 중심 Hz 음이다. 두 반쪽의 길이는 각각 0.12/0.24/0.48초다.

Raw input을 생성하는 함수에 truth나 arm별 성공 여부를 넣지 않는다. Truth는 별도 저작 명세로 만들고 모든 예측 저장 뒤에만 scoring에 제공한다. 새 입력의 무성·유성 프레임, terminal sample과 실제 duration clipping은 실행 명세와 계약 테스트에서 정확히 고정한다. Float 생성 환경과 input hashes도 예측 전에 기록한다.

이는 **저작자가 정의한 표현/분할 의도**에 대한 스트레스다. 실제 F0만으로 사람의 의도를 언제나 식별할 수 있다는 가정은 하지 않는다. 기존 15개 ambiguity의 두 해석을 유지하고, 새로운 108/108과 기존 227개를 합쳐 하나의 일반 정확도로 표시하지 않는다. Detuning은 pitch 양자화와 경계 판단이 함께 작용할 수 있으므로 event 수·pitch 손상도 같이 보고한다.

전체 합성 예측은 **(245+216)×9=4,149개**다. 이 모두를 첫 truth 평가 전에 고정한다. 새 스트레스의 결과를 보고 진폭·길이·위상·threshold를 다시 선택하지 않는다.

## 지표와 손상 기록

주 지표는 `guard − G`의 pitch+onset+offset macro F1이다. Pitch 50 cents, onset 50ms, offset `max(50ms, 20% reference duration)`, 원래 reference Hz와 파일별 8자리 F1을 그대로 쓴다. 녹음과 A1/A2는 동일 가중한다.

Paired 단위는 40개 녹음의 A1/A2 평균 차이이고, `default_rng(298)`, 10,000회 `(10000,40)` 재표집, 선형 2.5/97.5 percentile을 고정한다. Onset F1·precision/recall·예측 수·모든 40개 개선/악화와 A1/A2를 함께 보고한다. `guard − unconditional split`은 보조 대비다.

최소 후보 검토 조건은 G 대비 offset macro 증가와 onset macro 비감소다. 이 조건만으로 제품을 승인하지 않는다. G와 기존 split 양쪽에 대한 실제 matched-reference retained/gained/lost와 같은 onset pair의 종료 오차, 합성 6/221 손상, 새 108/108 결과를 모두 제시한다. 매칭 재배정 때문에 특정 이전 손실이 반드시 회복된다고 해석하지 않는다.

진단은 다음 분모를 분리한다.

- 모든 기존 부모, 원래 emitted/non-emitted 부모
- Proposed cuts/children, short/no-support/clipped-duration으로 승인에 실패한 부모
- Accepted cuts/children, rejected parents, 원본 복원 event 수
- 제안 단계의 short child 수·초와 **최종 출력**의 pruning 수·초
- 원래/최종 출력 구간 합집합, 총 emitted seconds, empty outputs, raw bridging

거절한 제안의 short child를 실제 coverage 삭제량으로 세면 안 된다. 부모별 결과와 정답 손상 연결은 private trace에 남기고 공개에는 counts/distributions/hashes만 남긴다.

## 독립 검증, 실행과 제한

독립 auditor는 raw Hz와 기존 G path에서 전체 cut 집합, 부모, 각 자식의 readout 통과 여부, 전체 승인/복원을 별도로 재구성한다. 모든 event/reference hash, 직접 mir_eval score, 전체 모집단과 bootstrap을 확인한다. 추가 cut 없음 및 거절의 원본 event parity, 원래 non-emitted 부모 비복원, accepted-child interval union 보존을 계약으로 검사한다. 5-frame·80ms 경계의 양쪽, 실제 audio clipping, raw-zero, 두 개 이상의 cut을 가진 부모를 작은 소유 입력으로 검증한다.

CPU 2 threads, Ubuntu 24.04, Python 3.11, 기존 pinned numeric runtime, 최대 35분을 유지한다. 실행 전에 고정한 input-only exact preflight와 실제 CPU/runtime metadata를 남긴다. 실패하면 원본 ZIP을 먼저 보존하고 원인·새 head·별도 실행을 기록한다. 예측 뒤 생긴 실패를 같은 실행의 성공으로 바꾸지 않는다.

원본 metadata/owned-synthetic ZIP, 독립 감사, 전체 결과와 실패를 같은 PR에 커밋·푸시한다. 최종 head 검증 후 병합하고 실제 main의 CI·호환성·보안 검증을 PR에 기록한다. 이전 #297의 실패/완료 receipt와 알고리즘은 그대로 남긴다.

같은 40개 녹음은 개발 자료 재사용이고 새 216개도 저작 스트레스다. 미사용 실제 녹음, 편집 비용, polyphonic 처리나 [#281](https://github.com/JDeun/audio-score-tool/issues/281)의 공통 악보 복원을 입증하지 않는다. 이 설계를 Melodyne 또는 Flex Pitch의 비공개 알고리즘이라고 부르지 않는다.
