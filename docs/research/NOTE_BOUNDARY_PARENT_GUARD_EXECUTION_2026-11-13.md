# #298 G 부모 보존 guard — 실행 명세

- 날짜: 2026-11-13 (Asia/Seoul)
- 이슈: [#298](https://github.com/JDeun/audio-score-tool/issues/298)
- 관리 우산: [#36](https://github.com/JDeun/audio-score-tool/issues/36), [프로젝트 완성도와 인수 기준](../PROJECT_COMPLETENESS_2026-11-13.ko.md)
- 기준 main: `97cb7b4263d1cc49ec8f4b6045f0e8ed9128d96e` (PR #297)
- 사전 가설: [부모 보존 protocol](NOTE_BOUNDARY_PARENT_GUARD_PROTOCOL_2026-11-13.md). 원래 문서의 설계 시점 상태를 유지하고 이 문서에 구현·실행 계약을 추가한다.
- 이 명세·코드·감사·계약 테스트·workflow·입력 manifest를 커밋한 후 전체 성능 평가를 처음 실행한다. 이 문서는 성공 결과 보고서가 아니다.

## 유일한 새 추론 요인

`gaussian_raw_hysteresis_parent_guard`를 기존 11개 corpus arm과 8개 synthetic arm에 추가한다. 원래 G path·raw Hz·5-frame hysteresis와 80ms readout을 그대로 사용한다.

1. 모든 prefilter G 부모를 열거하고 원래 출력 여부와 원래 Note 객체를 확인한다.
2. 원래 출력되지 않은 부모를 되살리지 않는다. 해당 부모도 진단 분모에 남긴다.
3. 전체 raw Hz에서 양성 label 사이의 pitch 변화점을 한 번 만든다. 원래 emitted 부모 내부이며 clipped audio end보다 앞선 cut을 모두 제안한다.
4. 추가 cut이 없으면 원래 G Note 객체를 그대로 쓴다. Cut이 있으면 모든 자식을 동시에 만든다.
5. 자식 전부가 기존 positive support·clipping·duration·80ms readout을 통과하면 전부 승인한다. 하나라도 실패하면 제안 전체를 버리고 원래 G Note 객체를 그대로 쓴다.

일부 cut을 제거해 더 좋은 조합을 찾지 않는다. Threshold, estimator, path, 전역 timing, pitch 산정, raw-zero 처리를 바꾸지 않는다. 원래/거절 부모의 직렬화 event bytes와 객체 재사용을 작은 계약 테스트로 검사한다. 승인 자식은 원래 부모의 시간 구간 합집합을 보존해야 한다. 인접 구간을 정규화한 endpoint를 비교하며 floating 합계의 bitwise 일치를 요구하지 않는다. 구간 보존은 pitch·정답 match·F1 보존을 뜻하지 않는다.

## 자료와 입력 사전 확인

### 기존 cohort

- Corpus: 같은 vocadito 40개, A1/A2. **40×12=480** event 파일을 전부 저장·hash 확인한 후 첫 정답을 읽는다.
- 기존 synthetic: 같은 245개, 9개 arm. 기존 227 eligible, 15 ambiguity, silence 3개를 분리한다.
- #297 원본 ZIP: `note-boundary-readout-43381098932-attempt-1.zip`, **775843 bytes**, SHA-256 `f34e88d2b5023df5762fba46b4149167265efbd24a837d30500375b30cd5758f`.
- 원래 440 corpus event/440 관측 배열, 1,960 synthetic event/245 raw input/1,470 path identity와 원래 점수·과학적 진단을 정확 재현한다. 측정 실행 시간, runtime/source provenance, NPZ container bytes는 별도로 기록하며 raw 배열 dtype/shape/bytes를 대조한다.

### 새 소유 입력 216개

Protocol의 b/d/a/f/D grid를 그대로 사용한다. Iteration은 kind(`single_expression`, `adjacent_semitone`) → b(45/57/69) → d(−.4/0/.4) → a(.3/.6) → f(3/6) → voiced frames(24/48/96)이다. 각 kind는108개이며 ID는 `stress_<kind>_001`부터 `108`까지다.

- `hz` 길이는 voiced frames +21.
- `[10, 10+voiced_frames)`만 유성, 앞뒤 silence interval은 각각10프레임.
- 실제 duration은 `(voiced_frames+20)*0.01`초.
- 마지막 index는 duration 시점의0Hz sample이며 추가 오디오 interval이 아니다.
- Modulation 시간은 유성 구간의 local integer frame×0.01초이고 위상은0.
- 인접 반음의 +1 변화는 유성 frame 절반부터이며 modulation 위상은 이어진다.
- Truth는 별도 저작 명세에서 만들며 fractional center `b+d`를 반올림하지 않는다.

[입력 전용 manifest](NOTE_BOUNDARY_PARENT_GUARD_NUMERIC_INPUTS_2026-11-13.json)는 추론/정답 평가 없이 만들었다. 생성 runtime은 Python3.12.14/NumPy1.26.4이며 실제 환경과 CPU dispatch 정보를 기록했다. 실제 trial은 Python3.11의 고정 runtime에서 **기존245 입력/20 analytic 수치와 새216 입력의 exact identity**를 모두 확인한 뒤 모델/decoder를 실행한다. 환경 metadata가 같다는 이유로 입력 동일성을 가정하지 않는다.

모든 **461×9=4,149** synthetic prediction을 고정한 뒤 첫 truth scoring을 한다. 작은 소유 계약 테스트와 입력 hash 생성은 freeze 전에 가능하지만 전체 cohort의 성능을 미리 보고 입력·threshold·위상을 선택하지 않는다.

## 예측·평가·projection 순서

1. 고정 소스의 Ruff와 작은 계약 테스트를 실행한다.
2. 입력 preflight 후4,149 synthetic prediction을 저장·hash 고정하고 truth scoring을 수행한다. #297의245×8 projection과 exact parity를 확인한다.
3. 원본 corpus ZIP의 SHA/MD5/크기를 확인한다. 40개 WAV에서 한 번의 pYIN과 원래 path를 공유해480 prediction을 먼저 저장한다. 이후 A1/A2/F0 reference를 읽는다.
4. 원래 11-arm readout report와 원래10-arm factor report를 새 실행의 projection으로 만든다. 과거 runner를 먼저 정답까지 실행한 뒤 신규 arm을 추가하는 방식이 아니다. Live immutable settings는 JSON snapshot으로 투영하며 deepcopy하지 않는다.
5. 원래 factor auditor, 원래 readout auditor, 새로운 guard auditor를 순차 실행한다. 추가 case/private JSON 파일은 이전 auditor가 사용하는 기존 cohort/array 집합에 섞지 않는다.
6. 누락/빈 출력/실패를 유지한다. 실패 cohort에는 aggregate를 남기지 않고 원본 실패 ZIP을 보존한다.

## 고정 지표와 손상

주 대비는 guard−G의 pitch+onset+offset macro F1, 보조 대비는 guard−unconditional split이다. 원래 reference Hz, pitch50cents, onset50ms, offset max(50ms, reference duration20%), 파일별8자리 점수를 유지한다. 녹음과 A1/A2는 동일 가중한다.

각 녹음의 A1/A2 평균 차이40개에 `default_rng(298)`의 `(10000,40)` bootstrap index를 적용하고 선형2.5/97.5 percentile을 보고한다. 이 reused development cohort의 기술적 구간이며 최종 미사용 성능 추정으로 부르지 않는다. Onset/offset F1·precision/recall·예측 수·빈 출력·모든40개 변화와 A1/A2를 함께 보고한다.

G와 split 양쪽에 대해 onset-only 및 onset+offset maximum matching의 reference ID 교집합/차집합으로 retained/gained/lost/neither를 계산한다. 각 arm의 같은 onset-only pair 안에서 predicted offset−reference offset과 early/within/late, pooled quantile을 계산한다. Arm 사이 pair 모집단이 달라질 수 있으므로 평균 오차 감소를 같은 음표의 개선으로 표현하지 않는다. A1+A2 count는 주석 판단의 합계다.

원래 G 및 split match가 속한 G 부모와 guard의 승인/거절/추가 cut 없음, 제안 short child, 원본 복원 여부를 private trace로 연결한다. 공동 발생 count는 인과 관계나 상호 배타적 오류 원인으로 간주하지 않는다.

진단은 다음을 분리한다.

- 모든 원래 부모와 원래 emitted/non-emitted 부모.
- 제안 cut/child와 rejected parent, 제안 단계의 short/no-support/clipped-duration 실패.
- 실제 승인 cut/child, 원본 복원 event, 최종 pruning.
- 원래/최종 정규화 interval union과 총 emitted seconds, raw bridging, 빈 출력.

거절된 제안의 짧은 자식을 실제 삭제 시간으로 계산하지 않는다. 최종 구간 합집합이 원래 G와 같아도 matching 손상을 숨기지 않는다.

Synthetic은 기존227/15/3, 알려진 반음6개/기존 G 성공221개, 새 single108/adjacent108을 각각 보고한다. 새 저작 truth는 의도 조건이지 실제 F0에서 사람의 모든 의도를 식별할 수 있다는 증거가 아니다. Note 수·pitch 손상을 별도 표시한다. Pitch를 무시한 timing-only 진단은 pitch-aware 정확도와 별도 이름/분모로 보고한다. 별도 one-to-one timing matching은 pitch-aware matching과 다른 pair를 배정할 수 있다.

후보 검토의 최소 조건은 **G 대비 offset macro 증가와 onset macro 비감소**다. 이 조건을 만족해도 기존 정답 손상, 합성 스트레스, 수정 비용과 제품 인수는 별도로 필요하다.

## 소스 고정과 독립 감사

원래 #296/#297의53개 frozen source를 수정하지 않는다. 새4개 scripts, 대응4개 tests, 새workflow, 원래 guard protocol, 이 실행 명세, 원본 #297 ZIP, 새 입력 manifest를 더한 **66개**를 고정한다. 연구 test manifest 등록과 프로젝트 관리 문서는 과학적 source inventory 밖이다.

새 auditor는 guard 구현을 호출해 expected를 만들지 않는다. Raw Hz와 원래 G path에서 부모·global hysteresis·제안 child·전체 승인/복원·최종 event를 독립 재구성한다. 원래 non-emitted 비복원, fallback bytes, 승인 interval union을 확인하고 모든 event/reference hash, 직접 mir_eval, 전체 cohort, match 집합/endpoint/pruning 분포/seed298 bootstrap을 대조한다. 이전 두 auditor의 receipt도 원본 report hash로 연결한다.

공개 receipt 재감사는 metadata와 소유 synthetic에 한정된다. 실제 corpus private event/parent/annotation trace의 전체 재검증은 실행 중 독립 auditor가 수행한다. Hash만으로 reference 접근 순서를 증명한다고 주장하지 않으며 frozen 코드와 barrier 계약 테스트를 함께 남긴다.

## 저장과 자원

원본 다운로드 ZIP을 재압축하지 않고 그대로 커밋하며 각 member 크기/SHA를 기록한다. 업로드 대상은 다음8개뿐이다.

| Member | 내용 |
|---|---|
| `synthetic.json` | 신규461×9, 소유 truth/event와 진단 |
| `legacy-synthetic.json` | 기존245×8 projection |
| `vocadito.json` | 신규40×12 counts/hash/점수/분포 |
| `legacy-vocadito.json` | 기존40×11 projection |
| `legacy-factor-vocadito.json` | 기존40×10 projection |
| `legacy-factor-audit.json` | 기존10-arm 독립 감사 |
| `legacy-audit.json` | 기존11-arm readout 독립 감사 |
| `audit.json` | 새guard 독립 감사 |

Actual corpus WAV/reference CSV/NPZ/event/pitch·time 상세/private parent·matching trace는 업로드하지 않는다. 실행 준비가 실패해도8개의 명시적 `not_completed` receipt를 남긴다.

Ubuntu24.04, Python3.11, CPU2threads,35분 제한, NumPy1.26.4/SciPy1.13.1/librosa0.10.2.post1/numba0.60.0/soundfile0.13.1/resampy0.4.2/soxr1.1.0/mir_eval0.8.2를 유지한다. 실제 runtime/CPU features와 protocol head/PR merge checkout을 각각 기록한다. CPU 기능을 강제로 끄거나 켜지 않는다.

Input-only preflight 불일치가 **어떤 model/decoder 예측보다 먼저** 발생한 경우에 한해 동일 frozen head의 최대3개 순차 runner placement를 허용한다. 모든 실패 ZIP을 보존하고 실제 입력 동일성이 성립한 첫 placement를 사용한다. 예측/점수 이후의 실패를 성공한 결과가 나올 때까지 재시도하지 않는다. 소스 수정이 필요하면 원인을 기록하고 새 frozen head로 별도 실행한다.

Workflow는 PR opened/reopened 또는 명시적 dispatch에서 실행한다. 결과 문서의 synchronize마다 성능 실험을 다시 선택하지 않는다. 최종 head의 일반 CI를 확인하고 병합한 뒤 실제 main의 CI/호환성/보안 결과를 PR에 남긴다. 제품 소스·기본값·모델 의존성을 변경하지 않는다.
