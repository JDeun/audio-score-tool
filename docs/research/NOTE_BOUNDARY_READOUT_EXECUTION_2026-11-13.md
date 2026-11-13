# #296 지속 raw-pitch 추가 분할 — 실행 명세

- 날짜: 2026-11-13 (Asia/Seoul)
- 이슈: [#296](https://github.com/JDeun/audio-score-tool/issues/296)
- 기준 main: `bccf69df86edde9176c62b3fa70d7055805ab9ca` (PR #295 병합)
- 사전 가설과 판단 기준: [기존 설계](NOTE_BOUNDARY_READOUT_PROTOCOL_2026-11-13.md). 이 문서는 구현·실행 계약을 추가하며 원래 설계를 수정하지 않는다.
- 이 문서를 포함한 코드·감사·테스트·workflow를 커밋한 다음 전체 40개/245개 성능 평가를 처음 실행한다. `protocol_head_revision`과 실제 checkout `source_revision`을 별도로 기록한다.

## 고정 대비

`gaussian_raw_hysteresis_split` 하나를 기존 `gaussian_exponent_1`(G)에 추가한다. 전체 Hz에 기존 `labels_from_hz(..., support=5)`를 한 번 적용하고, 양성 label 사이의 pitch 변화가 원래 G 부모 구간 내부이면서 실제 audio end보다 앞설 때만 자른다. 원래 G path와 모든 원래 경계를 보존한다. 각 자식에 원래 양성 raw MIDI median → `numpy.rint`, 실제 길이 clipping과 80ms 필터를 적용한다.

Raw-zero gate, 전역 시간 보정, pitch estimator 교체, 지속 길이 탐색, decoder 재추론을 추가하지 않는다. G 부모의 `original.prediction_index`는 기존 G 출력 순서를, 자식의 `prediction_index`는 새 출력 순서를 가리킨다. 원래 출력됐던 부모라도 모든 자식이 짧아지면 전체가 삭제될 수 있다.

## 실행 순서와 보존할 대조

1. 작은 소유 입력의 계약 테스트를 실행한다. 전체 synthetic grid의 성능은 freeze 전 확인하지 않는다.
2. 기존 245개 입력을 한 번 생성하고 기존 7개 예측과 공유 G 경로의 새 readout을 저장한다. **1,960개 event 파일을 hash 고정한 뒤에만 truth를 읽고 점수를 낸다.**
3. 원본 vocadito ZIP을 SHA/MD5/크기로 확인한다. 40개 WAV를 열어 동일 pYIN/기존 10개 arm을 실행하고 공유 G path의 새 arm을 더한다. **440개 event 파일을 저장·재검증한 뒤에만 A1/A2와 F0 reference를 읽는다.**
4. 기존 10개 arm과 기존 7개 synthetic arm의 projection을 별도 report로 저장한다. 이는 새 예측 뒤에 만들어지는 감사용 projection이며, 이전 runner를 먼저 정답까지 실행한 뒤 새 arm을 덧붙이는 흐름이 아니다.
5. 기존 독립 factor auditor로 400개 corpus 예측/440개 관측 배열을 확인한다. 새 독립 auditor가 모든 440개 corpus와 1,960개 synthetic prediction, 공유 path, raw hysteresis, parent/child trace, 직접 점수, 정답 집합, macro, bootstrap과 pruning 연관 집계를 재구성한다.
6. 이전 #295 원본 ZIP과 과학적 payload를 비교한다. 기존 400개 corpus/440개 배열, 1,715개 synthetic 예측/245개 입력/1,470개 path가 동일해야 한다. NPZ 컨테이너 bytes와 실행 시간은 달라도 내부 배열 dtype/shape/raw-byte SHA와 event bytes는 동일해야 한다.

누락·추론 실패·평가 실패를 분모에서 제외하지 않는다. 완결되지 않은 cohort에는 aggregate를 만들지 않는다. 빈 출력은 유지하고 F1=0으로 기록한다. Parity 실패는 성능 해석을 막는 실패로 남긴다. 실패 이후 소스를 수정해야 하면 실패 ZIP을 보존하고 새 frozen head와 별도 실행 identity로 기록한다.

## 평가와 진단의 구체적 정의

주 대비는 새 arm − G의 pitch+onset+offset F1이다. 기존 scorer와 원래 reference Hz, 파일별 8자리 F1을 그대로 유지한다. 40개 recording의 A1/A2 평균을 paired 단위로 `default_rng(296)`의 `(10000,40)` index 재표집을 수행하고 선형 2.5/97.5% quantile을 기술적 구간으로 보고한다. 파일 평균을 계산한 뒤 note 수로 다시 가중하지 않는다. 개선/악화/동률은 기존 수치 분해능인 ±`1e-8` 기준을 유지한다.

Onset/offset F1, precision/recall, 예측 수, 빈 출력, 40개 전부의 변화, A1/A2를 보존한다. 새 arm을 G와 runs 각각에 대해 onset-only 및 onset+offset maximum matching의 reference ID 집합으로 비교한다. `retained/gained/lost/neither`는 독립적으로 구한 집합의 교집합/차집합이며 점수 변화로 추정하지 않는다. A1+A2 pooled 수는 주석 판단의 합계이며 물리적 note 고유 개수가 아니다.

G/runs/실패 HMM/새 arm의 종료 오차는 각 arm의 **같은 onset-only matching pair**에서 `predicted offset − reference offset`으로 측정한다. Early/within/late는 기존 mir_eval의 거리 4자리 반올림과 `max(50ms, 20% reference duration)`을 사용한다. Quantile은 원래 pair 값을 모아 계산한다. 파일별 median을 평균내지 않는다.

Pruning 연관 손실은 G의 onset 또는 onset+offset match 중 새 arm에서 잃은 reference에 대해 G prediction이 속한 원래 parent를 찾는다. 다음 count를 함께 공개한다.

- 그 parent에 추가 cut이 있었는가.
- 그 parent에 80ms 미만으로 삭제된 child가 있었는가.
- 그 parent의 모든 child가 삭제됐는가.

이 세 항목은 중첩 가능한 기술적 연관이다. 단독 원인 또는 상호 배타적 오류 분류라고 주장하지 않는다. Parent/child 상세에는 실제 길이, 양성 raw 지원, median pitch, clipping, discard reason과 출력 index를 보존한다. 공개 진단은 개수·분포·hash에 한정한다.

합성은 기존 227 eligible, 15 ambiguity(동음 zero-gap 9개와 dropout 6개), silence 3개를 유지한다. 알려진 붙은 반음 6개 회복, 기존 G의 나머지 221개 성공 손상, 모든 case의 event/score를 보고한다. Zero-gap 동음처럼 입력에서 식별할 수 없는 경계를 truth metadata로 예측에 삽입하지 않는다.

## 저장 형식과 공개 범위

`run_note_boundary_readout.py`의 source inventory는 기존 #295 35개와 아래 12개를 합친 **47개**다: 새 script 4개, 새 test 4개, workflow, 원래 설계 문서, 이 실행 명세, #295 ZIP. 원래 35개 파일을 변경하지 않는다. Manifest partition 수정은 테스트 등록용이며 과학적 source inventory 밖에 둔다.

Corpus public schema는 `note-boundary-readout-v1`, synthetic public schema는 `note-boundary-readout-synthetic-v1`이다. Corpus 기존 row의 원래 필드는 그대로 유지하며 새 arm과 `readout`, private trace의 file hash, 주석별 aggregate diagnostics를 추가한다. 원래 열한 observation 배열은 그대로 저장한다. Synthetic은 기존 여섯 path 배열만 저장하며 새 arm이 G path identity를 공유한다.

Private 저장소에는 source WAV, reference CSV, observation NPZ, 모든 event, `readout-private.json`, `annotation-private.json`이 남는다. GitHub artifact로 올리는 파일은 아래 여섯 개뿐이다.

| 파일 | 내용 |
|---|---|
| `synthetic.json` | 245×8 결과, 소유 입력의 truth/event, 새 분할 진단 |
| `legacy-synthetic.json` | 기존 245×7 projection, 원래 결과와 exact parity |
| `vocadito.json` | 40×11 counts/hash/점수/분포; 실제 corpus event 시간·pitch 상세 제외 |
| `legacy-vocadito.json` | 기존 40×10 projection |
| `legacy-audit.json` | 기존 독립 auditor의 원래 10개 arm 검증 |
| `audit.json` | 새 독립 readout/annotation/synthetic/primary 검증 |

Corpus의 개별 parent/child 시간·median pitch, audio, reference, contour, state path를 공개하지 않는다. Private file은 hash로 연결한다. Artifact ZIP은 다운로드한 원본 bytes 그대로 저장하고 멤버 크기/SHA를 기록한다. 실행 준비 실패도 같은 6개 명시적 파일에 `not_completed` receipt로 남긴다.

## 자원과 결정 범위

Ubuntu 24.04, Python 3.11, CPU 2 threads, 최대 35분. NumPy 1.26.4, SciPy 1.13.1, librosa 0.10.2.post1, numba 0.60.0, soundfile 0.13.1, resampy 0.4.2, soxr 1.1.0, mir_eval 0.8.2를 고정한다. Workflow는 PR opened/reopened 또는 명시적 dispatch에서 실행하며 결과 문서만 추가하는 synchronize마다 실험을 재선택하지 않는다.

Onset macro 비감소와 offset macro 증가를 후보 검토의 최소 조건으로 삼되, 기존 정답 손상과 실제 match 수·pruning·파일별 악화를 함께 판단한다. 같은 40개와 245개를 재사용하는 개발 실험이다. 성과가 있어도 heldout, polyphony, 사용자 편집 비용, 같은 악보 복원을 입증하지 않으며 제품 기본값·자동 보정·모델 의존성을 바꾸지 않는다.
