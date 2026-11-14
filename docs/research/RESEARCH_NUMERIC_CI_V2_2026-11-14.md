# #302 연구 CI 수치 환경 적합성 v2

- 날짜: 2026-11-14 (Asia/Seoul)
- 이슈: [#302](https://github.com/JDeun/audio-score-tool/issues/302)
- 기준 main: `33ec72a76c53c1bd17f3c2f2170ca504c23aeb3a`
- 변경 범위: CI 관측·입력 적합성·mutation 검사. 새 음악 성능 실험이 아니다.

## 결론과 남은 범위

원래 66개 frozen 파일과 exact 비교는 그대로 두고 **별도 v2 CI 적합성 계약**을 추가했다. 기존 입력 245개, 새 stress 입력 216개, analytic 20행을 현재 프로세스에서 다시 만들고, 독립 auditor의 stress 재생성 216개도 확인한다. 입력이 다른 환경은 구체적인 ID·dtype·shape·SHA와 함께 부적합으로 남는다. 전체 연구 테스트는 그 환경에서도 모두 실행하며, 환경 부적합이나 진단 오류를 성공 상태로 바꾸지 않는다.

이 변경은 **수치적으로 다른 host를 모두 같은 입력으로 만드는 해결책이 아니다.** 로컬 호환 환경에서 기존 exact 검사와 모든 mutation의 의도된 실패 위치를 확인했고, 비호환 환경의 입력 차이를 재현했다. 원래 실패한 원격 host의 CPU가 기록되지 않았으므로 해당 host의 직접 원인 판정은 남아 있다. 실제 PR/main의 실행 환경과 최종 CI 결과를 따로 확인하기 전 #302를 완료로 닫지 않는다.

## 원래 실패 기록

[main CI 43393032958, attempt 2](https://github.com/JDeun/audio-score-tool/actions/runs/43393032958/attempts/2)의 [Python job 131782169433](https://github.com/JDeun/audio-score-tool/actions/runs/43393032958/job/131782169433)은 연구 테스트 `2439 passed / 1 failed`였다. 실패는 다음 입력 재생성 검사다.

```text
tests/test_audit_note_boundary_parent_guard.py::test_both_input_only_manifests_bind_original245_and_new216_without_inference
ValueError: independent_stress_input_regeneration: boolean mismatch
```

실제 job 로그는 연구 overlay에 **CPython 3.11.16**을 선택했음을 보여 준다. 앞선 제품 의존성 설치의 `numpy==2.5.3` 로그는 연구 subprocess가 실제 import한 NumPy 버전을 입증하지 않는다. 그 subprocess의 NumPy 경로·build·runtime·CPU dispatch는 원래 로그에 없다. 추가 재시도로 성공 host를 찾지 않는다. #298의 원본 과학 결과와 후보 기각 판단은 유지한다.

## 별도 입력 전용 진단

[진단 receipt](receipts/research-numeric-ci-v2-diagnosis-2026-11-14.json)은 실제 실행한 두 프로세스의 환경, 모든 불일치 identity, analytic 차이, 최대 차이를 보존한다. 일치하는 수백 개 identity와 중복된 독립 stress 불일치 행만 생략한 projection이며 raw audio·truth·prediction·score는 없다.

| 관측 환경 | 기존 245개 입력 차이 | 새 216개 입력 차이 | analytic 필드 차이 | 적합성 |
|---|---:|---:|---:|---|
| native dispatch | 0 | 0 | 0 | compatible |
| 별도 진단 subprocess에서 AVX512F 제외 | 18 | 207 | 10 | incompatible |

두 프로세스는 같은 **Python 3.12.14 / NumPy 1.26.4 / AMD EPYC 9V74**를 사용했다. NumPy extension SHA도 같다. 독립 auditor가 만든 216개 stress 입력의 불일치 기록은 authored generator의 불일치 기록과 모두 같았다. 이 로컬 입력 진단은 원격 CPython 3.11 CI나 원본 과학 실행으로 보고하지 않는다.

기존 입력에서는 518 sample, 새 stress에서는 2,326 sample이 달랐다. 최대 차이는 두 군 모두 **2 ULP / 1.1368683772161603e-13 Hz**다. 수치 차이가 작더라도 exact SHA 계약을 통과시켜 주지 않는다. 첫 기존 불일치 `change_195`는 dtype `<f8`, shape `[85]`를 유지하면서 SHA가 달라졌다. 첫 stress 불일치부터 전체 목록과 양쪽 hash는 receipt에 있다.

이 비교는 **해당 NumPy 연산 경로의 dispatch 민감성**을 재현한다. 원래 실패한 원격 host가 실제로 AVX512F를 지원하지 않았다고 확인한 결과는 아니다. 진단 코드만 명시적으로 별도 subprocess의 기능을 제외한다. CI plugin과 원래 과학 workflow는 CPU 환경 변수를 변경하지 않는다.

## 구현 계약

1. `scripts/research_numeric_qualification.py`가 실제 import된 NumPy/Python 경로·버전, extension SHA, `show_config()` build, `show_runtime()` 결과, CPU 모델·feature·dispatch를 입력 생성 전에 기록한다. runtime 관측 오류도 별도 metadata로 보존한다.
2. [별도 source manifest](RESEARCH_NUMERIC_CI_V2_FROZEN_SOURCES_2026-11-14.json)는 원본 #298 receipt의 66개 source SHA와 원본 ZIP identity만 담는다. 원래 frozen 파일이나 manifest를 갱신하지 않는다. source가 다르면 입력 생성 전에 부적합이다.
3. 입력 전용 manifest와 **동일한 exact 비교**를 적용한다. dtype·shape·duration·hash를 모두 비교하고 첫 불일치와 전체 불일치 ID를 기록한다. 비교 tolerance는 없다.
4. `scripts/research_numeric_pytest_plugin.py`는 연구 overlay 내부, 테스트 수집·실행 전에 적합성을 관측한다. compatible일 때만 긍정 preflight와 7개 mutation의 구체적인 오류 label을 검증한다. 선행 환경 실패를 mutation 검증 성공으로 세지 않는다.
5. 부적합 환경에서도 원래 research 파일을 전부 실행한다. 테스트 선택·skip·xfail을 추가하지 않는다. 기존 검사가 실패하거나 v2 적합성이 실패하면 CI가 성공하지 않는다. 이 계약 때문에 앞으로도 부적합 hosted runner에서는 CI가 실패할 수 있다.
6. CI는 성공·실패 모두 `research-numeric-qualification-<run>-attempt-<attempt>` artifact에 JSON을 보존한다. 기존 product 명령·dependency lock·과학 workflow·threshold·scorer는 바꾸지 않는다.

## 검증

로컬 NumPy 1.26.4 환경에서 v2 테스트, CI scope 테스트, 원래 parent-guard 관련 네 test 파일을 함께 실행했다. **240개 통과**다. 긍정 preflight는 461개 입력을 확인했고, 7개 mutation은 각각 의도한 정확한 rejection label에서 실패했다. 진단 테스트는 predictor·decoder·truth·reference·scorer 함수와 역사 ZIP 열기를 실패 함수로 교체해 해당 경로를 호출하지 않음을 별도로 확인한다.

이 결과는 로컬 범위 검증이며 전체 제품/연구 원격 CI 성공을 대신하지 않는다. 새 연구 test 파일은 research manifest에 포함돼 기존의 모든 test 파일 분할 계약을 유지한다. 원래 66개 파일과 원본 ZIP의 SHA 보존도 확인했다.

입력 전용 진단 재실행 명령은 다음과 같다. 출력 경로는 새 경로여야 한다.

```sh
uv run --frozen --python 3.11 --with numpy==1.26.4 --with scipy==1.13.1 \
  python -m scripts.probe_research_numeric_dispatch \
  --output-directory /tmp/research-numeric-diagnostic-v2
```

위 명령은 별도 진단이며 CI의 환경 선택 명령이 아니다. 일반 CI 실행은 기존처럼 `python scripts/run_ci_test_scope.py --scope research`다. 후속 음악 실험은 실제 입력 적합성 및 원격 검증 결과를 확인한 후, 별도의 고정된 protocol/head에서 진행한다.
