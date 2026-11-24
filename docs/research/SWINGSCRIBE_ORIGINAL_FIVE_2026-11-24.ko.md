# SwingScribe 원본 5곡 결과와 단일 구현 경로

## 결정

보컬 리드 시트의 구현 경로는 `vocal_lead_v1` recipe v3 하나로 고정한다.
분리는 고정 4-stem htdemucs, 보컬은 YourMT3+ 한 checkpoint, 화음·조성은 공식
SheetSage2, 박자는 Beat This! final0 + DBN, 음정 검수 보조는 Tiny 한 설정이다.
원본 관측을 보존하고 Tiny 경고로 음높이를 자동 덮어쓰지 않는다. 곡마다 모델이나
설정을 바꾸지 않는다. 모델·runtime 검증은 `fixed_lead_recipe.py`와 기존 recipe 경로를 따른다.

이번에 실제 실행한 SwingScribe 고정 CPU 설정은 대체 경로로 채택하지 않는다.
이 결정은 **구현 경로를 하나로 정하는 것**이다. 원곡에 대한 최소 수정 상용 품질과
최종 출시 승인은 여전히 미달·미검증이다. 낮은 기준선보다 후보가 나쁘다는 사실이
기준선의 합격을 입증하지 않는다.

## 실행과 검증

[공개 집계 JSON](SWINGSCRIBE_ORIGINAL_FIVE_2026-11-24.json)은 원본
`elkayem/swingscribe` revision `0a2d2ebb933d5ee190487a314a962d7355de394a`의
5곡 전체 길이 CPU 실행 결과다. 원본 9단계를 곡마다 새 캐시에서 완료했고,
5/5 exit 0, 실패·fallback 없음, 입력·고정 source·weights 불변을 확인했다.
CPU2threads/seed0, 4-stem htdemucs, final0 minimal decoder, full CREPE와 원래의
Basic Pitch horn-fill을 썼다. 곡별 crop·박자 힌트·결과를 본 설정 변경은 없었다.
상류가 검증했다고 명시하지 않은 macOS 실행환경의 실험이며 upstream의 동일 플랫폼
지원이나 완전한 dependency lock을 입증하지 않는다.

평가 프로토콜은 예측을 열기 전에 고정했다. 5곡 생산자의 terminal 보고서와
`frozen_unchanged` 이후 평가기를 한 번 실행했다. 수행 음표는 원본 JSON의
초 단위 onset/duration/pitch이며, helper MIDI나 XML의 재생 시각으로 대체하지 않았다.
71개 사용 파일의 전후 hash 검증과 별도 원본 생산자·출력 검증을 통과했다.
공개 파일에는 집계·hash만 포함하며 원음, 가사, 개별 음표 배열, 악보와 가중치는 넣지 않았다.

| 곡 | Your 원본 음표 | Swing 원본 음표 | Swing 전체 경로 실행 시간 |
| --- | ---: | ---: | ---: |
| American Idiot | 311 | 359 | 63.3분 |
| Me So Bad | 564 | 749 | 60.4분 |
| FANCY | 710 | 905 | 86.3분 |
| 나의 노래 | 605 | 1,184 | 71.9분 |
| 사건의 지평선 | 623 | 714 | 76.3분 |

실행 시간은 분리·여러 모델·기보를 포함한 이 CPU 환경의 전체 경로 값이다.
격리된 모델 속도 비교나 다른 장비의 처리 시간으로 일반화하지 않는다.
음표 수 증가만으로 과검출을 확정하지 않는다.

## 원곡에 연결된 비교 범위

음높이와 onset을 함께 보는 F1이며, onset+release는 종료 허용오차
`max(50ms, reference duration의 20%)`를 추가한다. 아래는 50ms onset 기준이다.

| 참고 범위 | onset F1 Your / Swing | onset+release F1 Your / Swing |
| --- | ---: | ---: |
| American community 보컬 310음 | 68.599 / 38.864% | 56.683 / 14.350% |
| Me 후렴, 작성자 끝점 투영 | 12.632 / 3.125% | 8.421 / 1.562% |
| Me 같은 구간, 고정 BPM 투영 | 25.263 / 4.688% | 10.526 / 0% |
| FANCY 4구간, 작성자 끝점 투영 | 10.695 / 6.790% | 5.704 / 1.543% |
| FANCY 같은 구간, 고정 BPM 투영 | 24.242 / 12.654% | 14.260 / 5.556% |

100ms의 모든 해당 비교에서도 Your 경로가 높았다. American은 기존 drum-only
정합을 유지했고, 보컬 예측에 맞춰 shift·tempo를 다시 맞추지 않았다. 나머지 두 곡은
작성자 timing이 근사인 부분 채보라 수치가 투영에 민감하며 전곡 정확도가 아니다.
서로 다른 분모의 결과를 5곡 평균으로 합치지 않는다.

American의 악보상 quarter 위치는 원본 XML·캐시 기보·native 첫 마디와 독립 원점을
대조한 뒤 붙임줄을 합쳐 비교했다. 310음 중 정확한 음높이+시작은
Your+S2 clock 63개, Your+DBN 157개, Swing 151개다. 음가까지 같은 것은
각각 39/95/78개다. 수행 시각 F1과 기보 위치 정확도를 같은 지표로 취급하지 않는다.

나의 노래의 짧은 7음 preview에서는 pitch-order LCS가 Your5/7, Swing7/7이다.
같은 창의 예측 수는 10/16개이며 timing·추가 음표의 정확도는 검증하지 않는다.
윤하의 두 9음 preview에서는 양쪽 모두 각각8/9다. 이 짧은 model-clock 보조 비교를
한국어 두 곡의 전곡 정답이나 사람의 수정량으로 확대하지 않는다.

## 출력과 남은 품질 조건

이번 Swing native MusicXML은 곡마다 단일 파트이고 4/4다. 화음 기호·재생 tempo는
없고, native PDF도 없다. 이를 기존 화음·조성·출판 PDF의 개선 근거로 쓸 수 없다.
실제 출력이 있다는 사실과 모든 음표·마디·키·메타데이터의 정확도는 별개다.

기존 화음 후보 비교에서 LV는 FANCY 일부 구간을 개선했지만 Me의 두 투영에서는
결과가 갈렸고 American의 strict power 구성음 정답은 S2·LV 모두 0이었다.
따라서 이번 보컬 비교를 근거로 화음 모델까지 함께 바꾸지 않는다.
[기존 화성·박자 판단](MODEL_DECISIONS_2026-11-18.ko.md)과 분모·제외 구간을 유지한다.

남은 작업은 고정된 경로의 음표 분할·경계·누락·기보 해석 오류를 수정하고,
5곡 전곡의 독립적인 멜로디·화음·박자·키 대조와 실제 사람의 수정 횟수·시간,
최종 PDF 전 페이지 가독성을 입증하는 것이다. 이 보고서로 #200/#34/#172 또는
#217의 전체 범위를 완료 처리하지 않는다. checkpoint 권리와 패키지 설치·배포 인수도
별도 조건이다.
