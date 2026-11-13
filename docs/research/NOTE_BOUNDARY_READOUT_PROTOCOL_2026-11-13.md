# 지속 raw-pitch 경계로 G 구간 추가 분할 — 다음 실험의 사전 정의

- 날짜: 2026-11-13 (Asia/Seoul)
- 후속 이슈: [#296](https://github.com/JDeun/audio-score-tool/issues/296)
- 근거: [#293 / #295 경계 진단 결과](NOTE_BOUNDARY_DIAGNOSTICS_RESULTS_2026-11-13.md)
- 상태: **설계 고정, 아직 구현·실행하지 않음.** 다음 실행에서는 이 정의, 구현, 독립 감사, 테스트, workflow를 함께 frozen commit으로 묶고 그 head를 기록한다. 이번 문서에 신규 성능 결과는 없다.

## 질문

고정 Gaussian exponent 1 HMM(G)은 관측 유성 지원을 대부분 유지하지만, 같은 onset 매칭 쌍의 종료점 1,929건 중 1,122건이 늦다. Runs의 offset 정답 중 G가 잃은 730건은 onset 미매칭 436건과 onset 매칭 후 늦은 종료 294건으로 나뉜다. 붙은 반음 합성 여섯 개에서는 +1 semitone 입력 변화에도 HMM이 같은 Stable pitch state를 유지한다.

**질문:** G의 기존 경로와 유성 지원을 유지한 채, 이미 존재하는 raw-pitch hysteresis의 지속 변화점으로만 구간을 추가 분할하면 반음 경계를 회복하고 실제 onset/offset 정답을 늘릴 수 있는가? 기존 정답 손상과 자식 구간의 최소 길이 삭제를 반드시 함께 측정한다.

실제 436건의 onset 미매칭이 모두 병합 때문이라는 가정을 두지 않는다. 시간 겹침, 여러 reference onset 포함, raw gap과 pruning의 교집합은 운영적 설명이다. 이번 방법은 이미 제거된 유성 지원을 복원하거나 조기 종료를 연장하지 못한다.

## 유일한 변경: 기존 구간 내부에 추가 cut

새 arm 이름은 `gaussian_raw_hysteresis_split`이다. 기준선은 `gaussian_exponent_1`이다. 같은 pYIN 관측과 **정확히 같은 G state path**를 사용한다.

1. 원래 raw Hz 전체에 frozen `dsp_note_probe.labels_from_hz(hz, support=CHANGE_FRAMES)`를 한 번 적용한다. `CHANGE_FRAMES=5`는 이전 DSP 구현에 이미 고정된 값이며 이번 결과에서 선택한 threshold가 아니다. 함수가 확인한 변화점은 기존 구현대로 최초 증거 프레임으로 backdate된다.
2. 프레임 `k>0`에서 `label[k-1]>=0`, `label[k]>=0`, `label[k-1]!=label[k]`이면 후보 cut이다. Zero-Hz와의 경계는 새 cut 근거가 아니다.
3. G의 기존 readout과 동일하게 `phase != Silent`인 decoded pitch-label 구간을 만든다. 모든 기존 경계를 보존하고, 구간 **내부**에 있는 후보 cut만 추가한다. 부모의 프레임 범위가 `[begin, stop)`일 때 `begin < k < stop`이고 `k×0.01 < min(stop×0.01, audio_duration)`인 cut만 허용한다. 실제 audio end의 terminal 관측을 잘라 길이 0인 자식을 만들지 않는다. 경계를 지우거나 구간을 합치지 않는다.
4. 각 자식 구간에는 원래 raw-positive MIDI median→`rint` pitch, 실제 audio duration clipping, 양성 raw support 조건, 최소 80ms 필터를 동일하게 적용한다. 기존 prefilter 부모부터 처리해 부모·자식 및 pruning 분모를 보존한다.
5. 추가 cut으로 인해 각 자식의 median pitch가 달라지는 것은 같은 pitch 산정 규칙에 새 구간을 적용한 결과다. Pitch를 hysteresis label이나 decoded pitch-bin으로 직접 대체하지 않는다.

`notes_from_labels(raw_hysteresis ∩ G_voicing)`를 곧바로 호출하는 구현은 이 정의와 다를 수 있다. Raw-zero gate와 출력 pitch 산정법까지 같이 바뀔 수 있으므로, 부모 구간에 cut을 추가한 뒤 기존 readout 규칙을 적용한다.

유성 지원과 원래 G 경로는 바뀌지 않지만, 자식이 80ms 미만이면 최종 emitted coverage가 줄 수 있다. 기존 100ms 음을 50ms 두 개로 나누는 경우처럼, 부모는 남았을 상황에서 자식들이 모두 사라질 수 있다. 이를 숨기지 않는다.

## 변경하지 않는 항목

Acoustic frontend, pYIN 16kHz/2048/160 설정, Gaussian exponent 1과 나머지 emission/transition/initialization, pitch grid, Viterbi tie 정책, raw probability/RMS, minimum duration과 pitch 산정은 그대로다. Raw-zero gate, gap fill, voicing prior 변경, timestamp 이동, 일괄 offset 보정, 신규 pitch estimator를 함께 도입하지 않는다.

5프레임 대신 다른 지속 길이를 탐색하거나 80ms를 바꾸지 않는다. Reference를 읽어 cut을 추가·삭제하거나 결과가 좋은 조건을 선택하지 않는다. G의 state-pitch 경계는 이미 기준 readout에 포함되어 있으므로 새 방법이라고 다시 이름 붙이지 않는다.

## 전체 대조와 예측 barrier

- Corpus: 원본 vocadito 40개, A1/A2 모두. 이전 10개 arm을 그대로 재현하고 새 readout 하나를 추가해 **40×11=440개 prediction 파일**을 생성한다.
- Synthetic: 이전 245개 × 7개 arm을 그대로 재현하고 새 readout 하나를 추가해 **245×8=1,960개 prediction 파일**을 생성한다. 기존 227 accuracy-eligible, 15 ambiguity, 3 silence 분모를 유지한다.
- 원래 G 및 모든 이전 arm의 source, input, array, event identity를 #292/#295 원본 receipt와 비교한다. 이전 corpus 400개/440개 배열과 synthetic 1,715개/245개 입력/1,470개 경로가 달라지면 신규 대비 해석을 중단한다.
- Corpus의 모든 440개 prediction을 저장·hash 고정한 뒤 처음 reference를 읽는다. Synthetic도 모든 1,960개 prediction을 저장한 뒤 truth를 평가한다.
- 새 readout에 독립적인 HMM 추론을 추가하지 않는다. 하나의 고정 G 경로를 공유하며, source/path 동일성을 receipt에 남긴다.
- 누락·실패·빈 출력을 모두 보존한다. 빈 출력은 점수 0이며, 누락/실패 시 완결 aggregate를 내지 않는다.

원본 ZIP과 수치 runtime은 [경계 진단 프로토콜](NOTE_BOUNDARY_DIAGNOSTICS_PROTOCOL_2026-11-13.md)과 같다. 같은 40개 녹음과 245개 격자는 개발 자료의 재사용이며 새로운 heldout이라고 부르지 않는다.

## 사전 지정한 평가

### 실제 녹음의 주 지표

`gaussian_raw_hysteresis_split − gaussian_exponent_1`의 pitch+onset+offset F1 차이를 주 지표로 한다. 이전 scorer의 pitch 50 cents, onset 50ms, offset `max(50ms, 20% reference duration)`, 원래 reference Hz와 파일별 8자리 F1을 유지한다. 파일과 A1/A2를 동일 가중한 macro를 보고한다.

40개 녹음의 A1/A2 평균 차이를 paired 단위로 사용한다. 필요 여부를 실행 후 고르지 않도록, `default_rng(296)`, 10,000회, `(10000,40)` recording index 재표집, 선형 quantile 2.5/97.5%의 기술적 paired percentile 구간 하나를 사전 지정한다. 주석자 80개나 개별 note를 독립 표본으로 재표집하지 않는다.

Onset F1, precision/recall, 예측수, 실제 matched-reference retained/gained/lost, 40개 전부의 개선/악화, A1/A2 불일치, 같은 onset-only pair의 early/within/late와 signed residual도 함께 보고한다. Runs와 실패 HMM을 포함한 이전 10개 결과를 보존한다. Macro F1이 올라가도 실제 맞힌 reference 수가 줄었는지 별도로 밝힌다.

후보로 검토하려면 최소한 G 대비 offset macro 증가와 onset macro 비감소를 확인해야 한다. 이는 제품 채택의 충분조건이 아니다. 기존 정답 손상, onset/offset match 증감, per-file 악화와 pruning을 함께 판단한다. 성공 지표만 골라 전체 성공으로 부르지 않는다.

### 합성의 기전 확인

사전 정의한 `change` + `interval=1` + `gap=0` 여섯 조건에서 두 reference 음의 pitch/onset/offset 매칭이 회복되는지 기록한다. 이를 새 자료의 일반화 성공률로 해석하지 않는다.

동시에 기존 G가 맞힌 나머지 221개 eligible case의 손상과 전체 227개 F1을 보고한다. 원래 245개 전체의 길이·pitch interval·gap·clip 경계·vibrato/drift·silence를 보존한다. Same-pitch zero-gap 아홉 개와 dropout 여섯 개는 두 truth 해석을 그대로 유지하고 정확도 평균에서 제외한다. 입력으로 식별되지 않는 경계를 정답 metadata로 추가하지 않는다.

### 추가 분할의 비용

후보 raw-pitch 변화점 수, 실제 G 부모 내부에 추가한 cut 수, 부모와 자식 segment 수, child median pitch, 자식의 raw support와 clipping, 최소 길이 pruning 수·초, 부모가 기존에 출력됐으나 모든 자식이 삭제된 수를 기록한다. 기존 정답 손상과의 대응도 계산한다.

유성 경로 자체는 같다는 사실과 최종 emitted coverage가 같다는 주장을 구분한다. Emitted seconds, 빈 출력, raw bridging 및 새 pruning으로 줄어든 support를 모두 보고한다. 추가 cut이 없는 경우에는 원래 G event 객체·hash가 정확히 같아야 한다.

## 실행·감사와 판단의 한계

구현 전에 작은 소유 입력으로 다음 계약을 검증한다: 지속 pitch 변화의 backdate, 양성→양성 cut만 허용, zero-Hz 해석 불변, 기존 G 경계 보존, 추가 cut 없음의 완전 parity, child median/rint 동일 규칙, clip 경계, 짧은 자식 pruning과 분모 보존. 전체 합성/실제 성능으로 숫자를 조정하지 않는다.

독립 auditor는 저장된 G path와 raw observations에서 candidate cut 및 parent/child readout을 별도 구현으로 재구성한다. 모든 prediction 파일·reference·event hash, 직접 mir_eval 점수, subgroup 분모, macro 및 fixed bootstrap을 확인한다. 실제 녹음의 부모/자식 개별 시간과 median pitch 상세는 private에 두고 공개 artifact에는 counts/distributions/hashes만 남긴다. Public artifact는 metadata/owned synthetic으로 제한하고 원본 ZIP bytes를 그대로 보존한다.

CPU 2 threads, Ubuntu 24.04, Python 3.11, 최대 35분으로 제한한다. 준비 실패, 추론 실패, parity 실패도 receipt로 남긴다. Source freeze 후 scientific 파일을 바꿔 재실행해야 하면 이전 실패와 변경 이유를 먼저 보존하고 새 실행으로 구분한다.

이 실험은 raw pitch와 discrete note 경계의 관계를 다룬다. 실제 730개 offset 손실의 원인을 모두 합성 반음 병합으로 설명하거나, 이 추가 분할이 Melodyne/Flex Pitch의 분석 알고리즘이라고 주장하지 않는다. 미사용 녹음, 사용자 편집 비용, polyphonic 처리, [#281](https://github.com/JDeun/audio-score-tool/issues/281)의 같은 악보 복원 검증 없이 제품 기본값이나 자동 보정을 바꾸지 않는다.
