# #296 보고서 projection의 immutable 설정 처리 수정

- 날짜: 2026-11-13 (Asia/Seoul)
- 이슈/PR: [#296](https://github.com/JDeun/audio-score-tool/issues/296) / [#297](https://github.com/JDeun/audio-score-tool/pull/297)
- 앞선 [수치 runtime 복구](NOTE_BOUNDARY_READOUT_RECOVERY_2026-11-13.md)는 그대로 보존한다.
- 이 추가 명세는 예측·평가 후 발견한 보고서 작성 결함의 수정과 별도 실행을 정의한다. 동일 head의 CPU 재배치 재시도로 취급하지 않는다.

## 두 번째 실행과 보존된 자료

[Run 43379624835](https://github.com/JDeun/audio-score-tool/actions/runs/43379624835), attempt 1은 frozen head `86c18a9eb3a1b2ba617a5daaa14a8c74a088fe82`, 실제 checkout `d455fea9bf67c1c9960d4e4a13eb2508469a7c40`에서 실행됐다. 실제 NumPy 1.26.4, Python 3.11.18과 AVX512F 활성 상태를 기록했다. Input-only 사전 검사 245개 입력/20개 analytic 행이 모두 정확히 일치했고, 합성 1,960개 예측·평가와 원래 7개 arm parity도 통과했다.

실제 corpus는 **40개 모두 prediction과 scoring을 완료**했다. 모든 440개 prediction은 첫 reference 접근 전에 저장됐고 scoring 후 manifest도 동일했다. 이후 legacy 보고서를 만드는 단계에서 `TypeError`가 발생했다. 완결 aggregate는 제거됐으며 private auditor는 실행되지 않았다.

Artifact `14016556224`를 [note-boundary-readout-43379624835-attempt-1.zip](receipts/note-boundary-readout-43379624835-attempt-1.zip)으로 보존한다. **579,798 bytes**, SHA256 `1c62896a6e6f3408d12fb82ddc42ec844bf8e5827dbe27fb5757e2db7d41383a`. 실제 `synthetic.json`/`legacy-synthetic.json`은 complete, `vocadito.json`은 failed, 나머지 3개 member는 not_completed이다. 상태나 원본 ZIP은 바꾸지 않았다.

저장된 metadata를 별도 읽기 코드로 대조한 결과, 이전 #295의 corpus **400개 event/440개 array/800개 annotation metric row**, 이전 source35개가 모두 같았다. Synthetic도 기존 **1,715개 event/245개 input/1,470개 path**와 전체 scientific payload가 같았다. 이는 공개 metadata의 비교이며 실행되지 않은 private audit를 대신하지 않는다. 새로운 후보의 성능을 골라 설정을 수정하지 않았다.

## 재현 가능한 오류 원인

`note_state_factors.FACTOR_SETTINGS`는 nested `_FrozenDict`로 구성되어 있다. 이 객체는 JSON 직렬화를 지원하지만, 실험 설정 변경을 차단한다. 다음 작은 호출만으로 실제 오류가 재현된다.

```python
copy.deepcopy(run_note_boundary_readout.frozen.FACTOR_SETTINGS)
# TypeError: experiment settings are immutable
```

새 runner의 `legacy_projection()`이 top-level report 값을 `deepcopy`하면서 이 보호 동작에 걸렸다. Archive에서 읽은 기존 테스트 fixture는 이미 일반 `dict`여서 결함을 드러내지 못했다. 실패 report에서 `factor_settings` 하나만 live `FACTOR_SETTINGS`로 되돌리면 같은 TypeError가 발생하고, JSON snapshot으로 값만 옮기면 projection과 기존 400/440 parity가 통과한다. 이 재현에는 새 모델·prediction·score 호출이 없다.

## 최소 수정과 새 freeze

Projection의 복사 경계 한 곳을 다음과 같이 바꾼다.

```python
result = json.loads(json.dumps(
    {key: report[key] for key in keys if key in report},
    allow_nan=False,
))
```

원래 immutable 설정과 변경 차단 코드는 유지한다. Report에 이미 저장 가능한 JSON 값의 snapshot을 만들 뿐, F0·HMM·readout·pitch·5프레임/80ms·matching·bootstrap을 바꾸지 않는다. Live immutable 객체를 주입한 회귀 테스트에서 projection 성공, 원래 설정 hash 불변, 기존 scientific payload 동일성을 확인한다.

이 문서와 두 번째 실패 ZIP을 source inventory에 더해 **53개**를 새 frozen head로 묶는다. 기존 #295의 35개 source와 앞선 두 실패 receipt는 그대로다. 전체 440/1,960 예측을 다시 생성하고, 이번 두 번째 실행의 모든 input/path/event identity도 결과 문서에서 비교한다. 최종 private audit가 성공한 새 실행만 완결 결과로 취급한다.

CPU 2 threads, Ubuntu 24.04, Python 3.11, 원래 pinned runtime과 35분 한도를 유지한다. 추론 전 수치 환경 불일치에 한해 사전 선언한 최대 3번의 순차 배치를 적용할 수 있다. 예측 이후 실패는 별도 원인과 새 frozen 실행 없이 자동 재시도하지 않는다. 모든 run/attempt ZIP을 구분해 남긴다.
