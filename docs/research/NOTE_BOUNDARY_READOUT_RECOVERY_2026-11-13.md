# #296 수치 실행 환경 사전 검증과 별도 재실행

- 날짜: 2026-11-13 (Asia/Seoul)
- 이슈/PR: [#296](https://github.com/JDeun/audio-score-tool/issues/296) / [#297](https://github.com/JDeun/audio-score-tool/pull/297)
- 원래 [사전 설계](NOTE_BOUNDARY_READOUT_PROTOCOL_2026-11-13.md)와 [첫 실행 명세](NOTE_BOUNDARY_READOUT_EXECUTION_2026-11-13.md)는 역사적 snapshot 그대로 보존한다.
- 이 문서는 첫 실패 이후, 별도 recovery commit과 실행을 위한 추가 계약이다. 피치 분할·예측·평가·bootstrap 조건은 변경하지 않는다.

## 첫 실행을 보존한다

[CPU run 43377739964](https://github.com/JDeun/audio-score-tool/actions/runs/43377739964), attempt 1은 head `b64b0bd521c9c6433a581f876f6afe7b654edeb5`, 실제 checkout `3491c1b305519515921ee1f88de6f1b401a56e08`에서 실행됐다. 549개 계약 테스트는 통과했다. 합성 245×8=1,960개 예측을 저장한 뒤 평가까지 진행했지만, 원래 7개 arm의 scientific payload exact parity에서 실패했다. 이후 실제 corpus 다운로드·추론과 두 독립 감사는 실행되지 않았다.

원본 artifact `14015650109`는 [note-boundary-readout-43377739964.zip](receipts/note-boundary-readout-43377739964.zip)으로 보존한다. **173,771 bytes**, SHA256 `522db7f66bea3dc6b05774c6dd1a82d450b6edfc076a4f7d79230de026f9e7bc`. 실패 synthetic report에는 모든 prediction/hash/평가 행과 barrier 기록이 남고 aggregate/comparisons는 null이다. 나머지 5개 member는 `not_completed`이다. 성공한 것처럼 상태나 ZIP 내용을 고쳐 저장하지 않았다.

## 정확히 무엇이 달랐는가

#295 원본과 비교한 28개 차이는 **18개 input array SHA와 analytic emission 표의 10개 float 값**뿐이다. 기존 1,715개 event SHA, 1,470개 state path SHA, 모든 기존 arm 진단·개별 점수·재계산 aggregate는 같다. Input dtype과 shape도 같다. 첫 실패는 후보 성능의 성공 또는 실패로 해석하지 않는다.

입력 차이는 `change_195`–`198`, `change_207`–`210`, `change_219`–`222`, `vibrato/drift_234`–`239`에 있다. 예를 들어 MIDI46 구간의 116.54094037952248Hz를 +2 ULP, 즉 약 `2.842170943040401e-14`Hz 바꾸면 `change_195`의 실패 SHA를 정확히 재현한다. Hash 기준을 완화하지 않는다.

[수치 진단 원본](receipts/note-boundary-readout-numeric-diagnosis-2026-11-13.json)은 실제 probe 코드, 각 결과의 hash, 전체 245개 input identity, 20개 analytic 행과 모든 차이를 보존한다. 동일 로컬 NumPy 1.26.4에서 프로세스 시작 전 `NPY_DISABLE_CPU_FEATURES`만 바꿨다. Decoder·event 생성·성능 scoring 호출은 0회였다.

| 로컬 dispatch 설정 | #295 input 차이 | #295 analytic 차이 | 첫 실패 payload와 차이 |
|---|---:|---:|---:|
| 기본 | 0/245 | 0개 필드 | 입력18 + analytic10 |
| AVX512F 제외 | 18/245 | 10개 필드 | **0** |
| AVX2와 FMA3 제외 | 0/245 | 0개 필드 | 입력18 + analytic10 |
| AVX512F·AVX2·FMA3 제외 | 18/245 | 10개 필드 | **0** |

이 통제 비교는 **AVX512F dispatch 제외가 실패의 수치 차이를 완전히 재현한다**는 증거다. 첫 Actions host는 CPU feature를 기록하지 않았으므로 실제 host 모델이나 feature 상태를 직접 관측했다고 주장하지 않는다. 첫 workflow 로그는 NumPy 1.26.4/SciPy 1.13.1/Python 3.11.18 설치를 확인한다. 버전 pin만으로 bit identity가 보장되지는 않았다. 로컬 probe의 Python은 3.12.14이며 원격 실행의 Python과 구분한다.

NumPy 1.26 공식 문서는 import 시 CPU 기능을 확인해 kernel을 선택하고 환경 변수로 기능을 제외하는 동작을 설명한다: [runtime dispatch](https://numpy.org/doc/1.26/reference/simd/build-options.html#runtime-dispatch), [global state](https://numpy.org/doc/1.26/reference/global_state.html). 지원하지 않는 기능을 강제로 켜거나 AVX512F를 끄는 방식으로 원본 데이터를 맞추지 않는다.

## Recovery에서 추가하는 계약

1. **입력만 있는 manifest** [NOTE_BOUNDARY_READOUT_NUMERIC_INPUTS_2026-11-13.json](NOTE_BOUNDARY_READOUT_NUMERIC_INPUTS_2026-11-13.json)을 고정한다. 원래 #295의 case ID, audio duration, 245개 input identity와 analytic 20행만 포함한다. Truth/event/path/score/spec 필드는 없다. SHA256은 `e5349cfb3a65e076fab607287b69e71c9e4298157614160439128e00b6b14428`이다.
2. Synthetic runner는 실제 Python/NumPy/module 경로, 수치 라이브러리 버전, CPU feature/dispatch와 관련 환경 변수를 기록한다. 원래 버전 pin을 실제 실행에서도 확인한다.
3. **어떤 decoder나 prediction도 부르기 전에** frozen `observations()`로 245개 입력을 준비하고 analytic 20행을 계산한다. Input-only manifest와 모두 정확히 일치할 때만 진행한다. 같은 준비된 배열을 예측에 사용하며 다시 생성하지 않는다. 사전 검사에서 reference/truth/event를 읽지 않는다.
4. 불일치이면 candidate 점수 없이 실패한다. 환경 관측과 input/analytic 차이, 모델 호출 0이라는 단계 기록만 남긴다. 독립 auditor는 성공 실행에서 manifest를 #295 원본과 대조하고 실제 input/analytic identity 및 preflight receipt를 확인한다.
5. Corpus도 수치 환경을 기록한다. 원래 corpus 400개 event와 440개 array의 exact parity는 그대로 요구한다. 합성 preflight 통과만으로 실제 pYIN 재현을 가정하지 않는다.

초기 47개 source inventory에 위 manifest, 이 recovery 문서, 첫 실패 ZIP, 수치 진단 JSON을 추가해 **51개**를 새 frozen head에 묶는다. 기존 #295의 35개 source는 여전히 바꾸지 않는다. 초기 head와 recovery head를 구분하고 각각의 source map을 보존한다. 구현 변경은 관측·사전 검사·실패 기록과 독립 감사 계약에 한정한다.

## 실행 횟수와 결과 선택 방지

새 frozen head에서 CPU 2 threads / Python 3.11 / Ubuntu 24.04 / 최대 35분의 원래 한도를 유지한다. Hosted CPU가 같은 수치 결과를 지원하지 않아 **추론 전 사전 검사에서만** 실패한 경우, 같은 head에서 최대 3번의 순차적 CPU 배치를 허용한다. 매 배치는 독립 run/attempt identity와 원본 artifact를 남긴다. Artifact 이름에 run attempt를 포함해 이전 실패를 덮어쓰지 않는다.

첫 compatible 환경에서 전체 cohort를 한 번 실행하고 그 결과를 보고한다. Candidate F1, reference match, threshold 또는 유리한 결과로 환경을 선택하지 않는다. 사전 검사를 통과한 뒤 실패하면 원인을 별도로 기록하며 이 환경 배치 규칙으로 무조건 재시도하지 않는다. 세 배치에서 원본 bit 재현을 얻지 못하면 실험은 미완결로 보고하고 수치 runtime 재현 문제를 별도 과제로 남긴다.

제품 기본값·자동 보정·의존성은 변경하지 않는다. 재사용한 개발 자료라는 한계와 #281의 공통 악보 복원 과제도 그대로다.
