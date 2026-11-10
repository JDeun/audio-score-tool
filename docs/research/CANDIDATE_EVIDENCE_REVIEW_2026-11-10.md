# Additional candidate evidence review

## 검증 범위

추가 연구 #214/#215/#217–#221/#223과 [PR #216](https://github.com/JDeun/audio-score-tool/pull/216), [PR #222](https://github.com/JDeun/audio-score-tool/pull/222)를 현재 목표인 **원음·YouTube → 보컬 멜로디와 코드 → 최소 수정 PDF** 관점에서 검토했다. 새 모델 추론·기본값 교체·자동 음악 내용 수정은 하지 않았다.

- #216 [실행 42766852869](https://github.com/JDeun/audio-score-tool/actions/runs/42766852869)의 원본 metadata JSON을 확인했다. vocadito ZIP의 전체 SHA256과 완료된 모든 행의 원본 WAV·두 주석자 note CSV·F0 CSV hash를 실제 로컬 ZIP과 대조했다. Basic Pitch의 80개 주석자별 F1과 F0 후보별 40개 지표를 다시 평균내어 공개 macro와 일치함을 확인했다. 두 실험의 평가 script도 기록된 source revision의 SHA와 일치하고, 원래 note scorer SHA는 현행 파일과 동일하다.
- #222 [실행 42786032517](https://github.com/JDeun/audio-score-tool/actions/runs/42786032517)의 합성 피아노 3개, 박자 6개, 조건부 현 선택 6개 결과를 다시 집계했다. Beat This!/StringNet의 recording ID·audio/annotation SHA·원본 archive identity도 서로 같았다.
- 공개 artifact에는 원본 prediction MIDI/F0/NPZ가 없다. 따라서 **원시 예측에서 F1·F0 지표를 다시 채점한 것은 아니다.** GuitarSet 원본 ZIP/JAMS도 이번 로컬 검토에서 확보하지 않아 해당 source byte는 별도로 재검증하지 못했다. 정확한 구분과 artifact hash는 [검증 metadata](CANDIDATE_EVIDENCE_REVIEW_2026-11-10.json)에 남겼다.

## 완료된 측정과 미완료를 분리

### 보컬 note AMT

| 후보 / 조건 | 완료 | onset F1 | onset+offset F1 | 판정 |
|---|---:|---:|---:|---|
| Basic Pitch 0.4.0 ONNX CPU | 40/40 | 0.49102129 | 0.31583077 | 독립 채보 비교 후보 유지 |
| MR-MT3 / 이번 원격 비교 | 0/40 | N/A | N/A | 의존성 준비 실패, 0점 아님 |
| YourMT3+ / 이번 원격 비교 | 0/40 | N/A | N/A | 의존성 준비 실패, 0점 아님 |

MR/Your의 `mutagen` 누락을 해결한 같은 원격 프로토콜 결과를 기다려야 한다. 앞선 M4의 [Your/MR 보컬 평가](VOCADITO_VOCAL_BASELINES_2026-11-09.md)는 유효한 별도 실험이지만, 이번 빈 원격 행을 그 수치로 채워서 완성된 동일 실행 비교로 만들지 않는다. Basic Pitch의 최소 음 길이·pitch bend·악기 identity의 지원 범위도 독립적인 제한이다.

### 독립 F0 tracking

| 후보 / 40개 recording macro | Raw Pitch Accuracy | Overall Accuracy | Voicing False Alarm |
|---|---:|---:|---:|
| 제품 YIN | 0.62843586 | 0.68691592 | 0.19229621 |
| pYIN | 0.80528736 | 0.72524536 | 0.43519268 |
| torchcrepe tiny | 0.87981949 | 0.83174799 | 0.27491606 |

torchcrepe full은 **37/40**만 완료했고 전체 macro가 없다. 완료된 37개만 평균내어 다른 40개 후보보다 좋거나 나쁘다고 판정하지 않는다.

tiny는 우선 평가할 F0 검증 후보지만 **F0 정확도 ≠ 음표 채보 F1 ≠ 검수 경고의 precision**이다. YIN보다 높은 voicing false alarm도 확인된다. 다음 검사는 동일 AMT/현재 Revision의 음표를 고정한 채 경고의 precision·관측률·보류와 정상 음표 훼손 위험을 평가해야 한다. 모델이 만든 confidence를 보컬 존재나 정답 확률로 취급하거나 전곡을 자동 이조하지 않는다. #214의 제품 검증기 채택은 이 단계 뒤에 판단한다.

### 전문 모델의 별도 과제

| 후보 | 실제 측정 범위 | 다시 집계한 결과 | 현재 보컬+코드 목표에서의 결정 |
|---|---|---|---|
| Piano CRNN | 직접 생성한 합성 피아노 3개 | onset 0.96666667 / offset 포함 0.91527778 | 피아노 전용 추가 평가; 보컬 순위에 넣지 않음 |
| Basic Pitch / 같은 피아노 | 같은 3개 합성 입력 | onset 0.83830902 / offset 포함 0.04938272 | note duration·pedal·합성기 조건 검토 필요 |
| Rescored BiLSTM | 위 두 AMT 예측의 후처리 | 두 모델 모두 해당 F1은 전후 동일 | 이 실험만으로 자동 통합하지 않음; 모든 효과가 없다는 일반화도 금지 |
| Beat This! final0 | GuitarSet 원음 6개 | beat 0.69610333 / downbeat 0.61962895 | 박자 대체 ablation 후보; 해당 데이터는 학습에 포함되어 독립 일반화 근거 아님 |
| StringNet | 같은 6개, 정답 onset/pitch 제공 | 조건부 string accuracy 0.72818537, lowest-fret 0.16553957 | 기타 TAB 후속; audio→음표→TAB 정확도 아님 |
| BS/Mel-Band RoFormer, open-fret | 검토한 정확한 checkpoint의 출처/권리·가용성 gate 미충족 | 미실행 | 해당 checkpoint 보류. 전체 아키텍처가 CPU에서 불가능하다는 판정 아님 |

## 외부 기보 코드에서 얻은 두 개의 좁은 가설

모델 입력·raw AMT 이벤트·beat clock을 고정한 **기보 단계만의 ablation**으로 검증한다. 외부 코드/규칙을 현재 제품에 복사하거나 여러 모델 preset을 추가하지 않았다.

### Song2Sheet: ternary 격자 후보의 효과만 분리

고정 commit [`6aee2a2139b28af871f4c9a878b7e18650c38226`](https://github.com/kishormorol/song2sheet/tree/6aee2a2139b28af871f4c9a878b7e18650c38226)의 [`score.py`](https://github.com/kishormorol/song2sheet/blob/6aee2a2139b28af871f4c9a878b7e18650c38226/song2sheet/score.py)는 박별 시간 매핑 뒤 곡 전체의 16th/triplet-8th 격자 오차를 비교한다. 이는 셋잇단음표 검증에 참고할 수 있다. 다만 velocity 필터, early-pickup 제외, 최소 한 셀 길이 강제와 같은 onset의 병합도 있으므로 직접 이식하면 다른 음표·강약·재타격을 훼손할 수 있다.

**가설 S:** 현재 16th만 쓰는 해석과, 고정된 복잡도 비용을 가진 binary/ternary 후보 해석을 같은 입력에서 비교하면 정답이 ternary인 구간의 표기와 snap 오차가 개선될 수 있다. 먼저 소유한 합성 straight/triplet/mixed-bar 대조군에서 실제 tuplet·쉼표·타이·동음 재타격을 채점하고, 독립 기보 정답이 있는 실제 구간으로 확장한다. pitch·공통 beat clock을 바꾸지 않고 누락·추가·강제 연장·onset collision도 보고한다. triplet 격자 하나를 추가하는 것만으로 일반적인 짧은 장식음 문제가 해결된다고 가정하지 않는다.

### SwingScribe: 충돌 보호와 연주/표기 시각의 분리

고정 commit [`0a2d2ebb933d5ee190487a314a962d7355de394a`](https://github.com/elkayem/swingscribe/tree/0a2d2ebb933d5ee190487a314a962d7355de394a)의 [`quantize.py`](https://github.com/elkayem/swingscribe/blob/0a2d2ebb933d5ee190487a314a962d7355de394a/src/swingscribe/stages/quantize.py)는 beat별 후보 선택, 인접 beat 경계의 onset 충돌 보호, 표기와 연주 residual의 구분을 구현한다. 재즈 swing 추정이나 lag 규칙까지 pop/rock/CCM의 기본 규칙으로 옮길 근거는 없다.

**가설 W:** 각 beat에서 식별된 attack을 유지할 수 있는 최소 해상도를 고르고 이웃 beat와의 충돌을 거절하면, 현재 dominant-cell 해석이 버리는 짧은 이벤트와 재타격을 일부 보존할 수 있다. 소유한 합성 악구의 짧은 음·동음 재타격·경계 밀림·tempo 변화부터 시험하고, 유지할 수 없는 이벤트는 삭제 성공으로 숨기지 않는다. 더 많은 이벤트를 살렸다는 사실만으로 더 정확하다고 판정하지 않으며 실제 AMT 잡음 추가·정상 음표 훼손·표기 복잡도·사람 수정량도 비교한다.

원래 source seconds와 새 rational beat 위치/잔차를 별도 보존해야 한다. [`M5 문서`](https://github.com/elkayem/swingscribe/blob/0a2d2ebb933d5ee190487a314a962d7355de394a/docs/m5-quantize.md)의 중요한 경계처럼, 잔차까지 복원해 얻는 정확한 roundtrip은 보존 검사다. 현재 앱의 해석 격자→MIDI 2ms 일치 역시 기보·원곡 정확도 승인과 다르다. 검증된 SheetSage2 소스를 몰래 수정해 다른 격자를 같은 native 출력으로 표시하는 방식은 피한다.

## 현재 우선순위와 종료 조건

1. 원음 전체 보존을 전제로 같은 source의 MR/Your/Basic Pitch 비교를 완성하고, tiny를 **검수 보조 후보**로 음표 수준에서 검증한다. 원음·역할 매칭이 틀린 상태를 음정 보정으로 감추지 않는다.
2. 같은 AMT 음표를 유지한 Beat This!/기보 가설 S·W를 평가한다. 음표 인식 개선과 기보 해석 개선을 분리하고, 독립 정답·실제 수정 횟수/시간으로 최종 한 조합을 선택한다.
3. 피아노·TAB 전문 모델은 해당 기능 범위에서 후속 평가한다. 권리·weights gate 미충족은 실제 차단으로 남긴다. #223 LLM은 원음 근거에 제한된 제안/patch 비교 실험이 아직 없으므로 미실행 연구다. 기존 symbolic critic이나 논문만으로 자동 후보정의 효용을 승인하지 않는다.

이 검토는 추가 8개 연구 이슈의 전체 완료 조건을 충족하지 않는다. #214의 경고/보정 precision, #215의 stem/혼합·최종 악보 비교, #217의 외부 파이프라인 실측, #218의 실제 피아노, #219의 후속 기보 ablation, #220의 end-to-end TAB, #221의 checkpoint gate, #223의 실제 제한 LLM A/B가 남아 있다. 이슈는 해당 근거가 생긴 범위에서만 정리하며 최종 모델·출판 품질은 승인하지 않았다.
