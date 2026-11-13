# 프로젝트 완성도와 v1 인수 우산

- 기준일: 2026-11-13
- 기준 main: `97cb7b4263d1cc49ec8f4b6045f0e8ed9128d96e` (PR #297 병합)
- 실제 버전: **0.8.0, 개발·QA 단계**. 향후 0.9.x beta 계획과 구분한다.
- 관리 우산: [#36](https://github.com/JDeun/audio-score-tool/issues/36)
- 기존 release 계약: [V1_READINESS.ko.md](V1_READINESS.ko.md)

곡 관리·악보 편집·저장·출력의 기반과 연구 검증 체계는 갖춰져 있다. 실제 음원에서 좋은 악보 초안을 얻어 적은 수정으로 출판하는 품질, 지원 OS의 자체 실행 환경과 서명 배포 인수는 남아 있다. 구현된 기능, 회귀 검사, 연구 결과, 제품 인수는 각각의 근거로 판정한다. 이슈 개수나 테스트 개수를 완성도 백분율로 바꾸지 않는다.

## 관리 구조

기존 #36의 P0/P1/P2/P3 구조를 유지하고 이번 평가에서 찾은 빈 부분을 연결했다. 목표 마일스톤은 **v1.0 — 최소 수정 출판 악보와 설치·업데이트 인수**다. 기한은 품질·배포 근거에 맞춰 정한다.

2026-11-13 관리 정리 시점에는 GitHub Milestone 객체가 없었다(open/closed 모두 0). 이슈 연결과 완료 조건은 등록했으며, 실제 Milestone 객체 생성·배정은 아직 미완료다. 현재 연결의 이슈 생성/편집 기능에는 milestone 생성이 없고 브라우저 작업에는 로그인이 필요하다. 이를 이미 생성한 milestone으로 표현하지 않는다.

| 트랙 | 관리 이슈 | 종료에 필요한 근거 |
|---|---|---|
| P0 실제 음악·최종 후보 선정 | [#34](https://github.com/JDeun/audio-score-tool/issues/34), 후보 우산 [#172](https://github.com/JDeun/audio-score-tool/issues/172) | 같은 manifest의 전체 후보 비교, 음악 오류·기보·수정 비용, 모델/권리/runtime 일치, 최종 승인 |
| P0 평가 자료 분리 | [#57](https://github.com/JDeun/audio-score-tool/issues/57) | 재사용 개발 자료와 미사용 실제 평가 자료, 주석/권리/버전/중복/전체 분모 |
| P0 공통 기보·곡 구조 | [#200](https://github.com/JDeun/audio-score-tool/issues/200), [#281](https://github.com/JDeun/audio-score-tool/issues/281) | 같은 기보의 표현 연주 불변성, 다른 기보 대조군, 원래 수행 시간 보존, rhythm/meter/rest/voices/parts 검수 |
| P0 원음 동기 검수 | **[#299](https://github.com/JDeun/audio-score-tool/issues/299)** | 반복 청취·대응 음표 선택·수정·전후 확인, 실제 수정 시간과 잔여 오류 |
| P0 분석 근거와 편집 계약 | **[#300](https://github.com/JDeun/audio-score-tool/issues/300)**, 설계 [#288](https://github.com/JDeun/audio-score-tool/issues/288) | 버전 schema, 시간 의미·불확실성·계보·사용자 patch, 저장/마이그레이션/편집 연결 |
| P0 박자 후보 실행·통합 | [#219](https://github.com/JDeun/audio-score-tool/issues/219), draft [#236](https://github.com/JDeun/audio-score-tool/pull/236) | 분리 runtime 실행/설치/preflight, 최신 main 통합, 음악·편집 인수 |
| P1 자체 실행 환경 | [#29](https://github.com/JDeun/audio-score-tool/issues/29) | 실제 승인 artifact와 지원 OS clean-machine 실행 |
| P2 서명 설치·업데이트 | [#22](https://github.com/JDeun/audio-score-tool/issues/22) | 서명/공증, 설치→실행→업데이트→재실행, 변조 거절 |
| P3 별도 확장 | [#35](https://github.com/JDeun/audio-score-tool/issues/35) | 별도 판단; 모든 탐색 모델/DAW/재합성/cloud/mobile 기능을 v1 필수로 넣지 않음 |

## 갖춘 기반과 그 근거의 한계

### 곡·악보 편집과 출력

WAV/MP3, YouTube, PDF/이미지 OMR, MusicXML/MIDI 입력 경로, SQLite의 Song/revision/canonical MusicXML, OSMD 미리보기, 음정·음가·쉼표·마디·조성·레이아웃 편집, Undo, 명시적 최종 출력 코드가 있다. [편집 계약](EDITOR.ko.md)은 revision 충돌, atomic 수정, 출력 무효화와 표현할 수 없는 리듬 요청의 처리를 정의한다.

실행 경로가 있다는 사실만으로 모든 외부 엔진이 추가 설치 없이 제공되는 것은 아니다. 본문 마지막의 P1/P2를 별도 인수한다. 음악적으로 잘못된 자동 초안도 형식상 정상 MusicXML/PDF로 출력할 수 있으므로 export 성공과 음악 품질을 분리한다.

### 데이터 보존

[MIDI/MusicXML fidelity 계약](MIDI_MUSICXML_FIDELITY.ko.md)은 ticks/onset/duration, 겹친 성부, ties, 악기·drum, tempo/meter 변경 등을 다룬다. 정해진 허용 오차의 roundtrip 성공은 원래 음원에서 음표를 올바르게 추정했다는 증거가 아니다. Pitch bend·CC·sustain의 음향 효과를 최종 기보로 해석하는 문제도 별도다.

### 연구와 통합 검증

[#297](https://github.com/JDeun/audio-score-tool/pull/297)은 원본 두 실패와 최종 성공 receipt, frozen source, private/public 감사와 모든 실제 녹음의 손상을 남겼다. 실제 main `97cb7b4`의 9개 job이 통과했고 제품 2,119개, 연구 2,218개, 프런트엔드 69개 검사와 Python 3.11/3.12 호환성, Tauri check/clippy를 확인했다. 기존 Rust 경고 13건은 이전 main과 같으며, 이를 경고가 전혀 없다고 표현하지 않는다.

이 검사는 코드·계약 통합의 근거다. 사람의 음악적 검수나 서명된 설치 패키지 인수를 대신하지 않는다.

## 실험이 드러낸 현재 빈 부분

### 경계 회복과 기존 정답 보존

[#296/#297 결과](research/NOTE_BOUNDARY_READOUT_RESULTS_2026-11-13.md)에서 고정 G 경로에 raw-pitch cut을 추가하면 붙은 반음 합성 6개를 회복하고 이전 G 성공 221개를 보존한다. 그러나 실제 40개 offset-inclusive F1은 **24.270837%→16.279944%**, onset F1은 **57.225361%→35.916666%**로 악화했다. 짧아 삭제한 조각은 13→1,682개, 출력 시간은 68.677875초 줄었다. 이 arm은 기각됐다.

[#298 사전 정의](research/NOTE_BOUNDARY_PARENT_GUARD_PROTOCOL_2026-11-13.md)는 모든 자식이 기존 readout을 통과할 때만 전체 분할하고, 하나라도 실패하면 원래 G 음표를 복원한다. [완료 결과](research/NOTE_BOUNDARY_PARENT_GUARD_RESULTS_2026-11-13.md)는 40개 실제 녹음과 461개 합성 입력에서 G의 출력 구간 합집합 보존을 확인했다. 그러나 실제 offset F1은 **24.270837%→23.113588%**, onset F1은 **57.225361%→53.469785%**로 내려가 두 최소 검토 조건을 충족하지 못했다. 기존 반음6개/성공221개는 보존됐지만 새 단일 표현음108개 중12개가 잘못 분할됐다. 출력 길이 보존과 올바른 음표 경계 판정은 별도의 문제다. 실제 원본·감사·개발 자료 재사용의 한계는 #301과 결과 문서에 기록한다.

### 공통 written rhythm

[#281](https://github.com/JDeun/audio-score-tool/issues/281)의 목표는 같은 악보를 swing·미세 timing·강약을 달리해 연주해도 공통 기보를 복원하는 것이다. 수행 시간/velocity 보존은 필요한 계약이지만 이 목표 자체의 완료는 아니다. [repeat-context 결과](research/REPEAT_CONTEXT_RESULTS_2026-11-13.md)의 실제 8개 수행에는 반복 연결이 하나도 만들어지지 않아 목표 개선도 없었다. Supplied clock/alignment 조건, 저작 예제와 실제 인간 연주의 기보 인수를 나누어야 한다.

### 후보 모델과 전체 음악 품질

[GAME CPU 결과](research/GAME_VOCAL_CPU_RESULTS_2026-11-13.md)는 같은 40개에서 fractional CSV와 integer MIDI가 다른 pitch 정확도를 보일 수 있음을 드러낸다. 기존 context를 재사용한 실제 Song 출판 성공도 tempo·meter·화성·성부·가독성이 모두 맞는다는 뜻은 아니다. 일부 곡의 219 BPM/N.C. context와 보존되지 않은 source event도 남아 있다. 현재 개발 baseline과 최종 상용 배포 후보를 구분하고 #34에서 최종 인수한다.

## 지금 채워야 할 제품 계약

### 실제 수정 시간

최상위 KPI인 `time_to_publish_seconds`와 편집 행동 telemetry는 이미 구현되어 있다. 유효한 사용자 변경만 세고 전체 형식의 최종 파일 복사가 성공해야 완료 시간을 기록한다. 남은 것은 같은 manifest·같은 초기 악보에서 실제 작업자가 오류를 찾고 고치는 campaign이다. 실패/중단/재시도를 포함하고 잔여 음악 오류와 읽기 쉬운 기보를 함께 평가한다. 기준 main에는 `release/v1-quality-approval.json`이 없다.

### 원음에 가까운 검수 흐름

기준 desktop 코드 검토에서는 synchronized 원음/악보 playhead, loop 청취, 파형 또는 시간축에서 경계 오류를 확인·수정하는 완결된 흐름을 확인하지 못했다. #299는 의심 구간→반복 청취→해당 음표→수정→전후 확인을 연결하고 기존 수정 telemetry로 효과를 측정한다. full DAW나 오디오 재합성을 만들어야만 이 작업을 시작할 수 있는 것은 아니다.

### 관측·음표·기보의 연결

#300은 이미 보관하는 원본과 수행 데이터를 바탕으로 continuous F0/voicing, 경계 후보, 수행 음표, written score와 사용자 수정의 버전 계약을 만든다. Acoustic onset, perceptual onset, performed time, score-grid time과 불확실성을 구분하고, 분할/병합/삭제/보류의 계보를 남긴다. #288의 공개 설계 조사를 상용 도구 내부 알고리즘을 재현했다는 주장으로 확대하지 않는다.

## 배포에서 남은 일

기준 main의 [managed catalog](../src/audio_score_tool/managed-component-catalog.json)는 6개 component 모두 `artifacts: {}`이고 [managed approvals](../src/audio_score_tool/managed-release-approvals.json)는 `approvals: {}`다. 실제 artifact URL/SHA/revision/OS·arch/tool map, 배포 권리와 승인을 채워야 한다. P0에서 최종 선정할 engine identity도 일치해야 한다. 현재 자동 P0↔P1 검증은 frozen MR-MT3 경로만 지원하므로 다른 후보 승격에는 계약 검토가 필요하다.

Windows x86_64/macOS arm64의 clean-machine 입력, 실제 서명/공증, 업데이트 인수는 #29/#22가 담당한다. 현재는 source와 unsigned QA package 단계다. 이번 평가는 signing credentials/secrets의 현재 값을 조회하지 않았으며 #22의 과거 점검을 새 점검으로 간주하지 않는다.

## 실행 순서와 완료 판정

1. #298의 사전 정의된 guard 한 요인 실험은 완료됐다. 원본 성공 receipt, 정확 재현, 손상과 후보 기각을 #301에 기록하며 최종 head와 실제 main 인수를 별도로 확인한다. 다음 연구는 표현음과 실제 경계를 구별하는 근거를 다루고, 단순 길이 임계값 탐색으로 제품 gate를 대신하지 않는다.
2. #300의 데이터·편집 계약과 #299의 원음 검수 흐름을 연결한다.
3. #57/#281의 실제 평가 분리와 공통 기보 요구를 #34의 음악·수정 비용 인수로 연결한다.
4. P1/P2 artifact·지원 OS·서명 준비는 음악 연구와 병행한다.
5. P0/P1/P2가 같은 release 후보에서 모두 인수되고 문서/계약이 일치한 뒤 `1.0.0`을 만든다.

실패한 연구도 결과가 고정·감사·병합되면 연구 이슈를 닫을 수 있다. 제품 품질 이슈는 해당 사용자 인수를 만족해야 닫는다. 다음 우선순위는 새 모델/규칙의 수가 아니라 줄어든 음악 오류와 실제 수정 비용으로 정한다.
