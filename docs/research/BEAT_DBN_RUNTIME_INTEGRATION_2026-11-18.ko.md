# DBN 박자 runtime 분리와 제품 통합 검증

보컬의 NumPy 2.4.6과 박자의 1.26.4를 같은 실행 명령으로 요구하던 충돌을 수정했다.
`fixed_beat_cmd`/`AST_FIXED_BEAT_CMD`를 설정 API·저장·readiness·추론에 연결한다.
`beat-preflight`는 모델 실행 전에 고정 runtime·소스·native extension·체크포인트를
검증하며 실패하면 구조/분리 작업을 시작하지 않는다. 기존 보컬 명령에 박자를 우회
실행하거나 가중치/모델을 자동 대체하지 않는다.

[설치 절차](../FIXED_VOCAL_LEAD.ko.md)와 고정 requirements로 macOS arm64의 새
Python 3.11 환경을 만들었다. 공식 madmom 소스와 고정 models initializer만 설치하고
pretrained pkl은 설치하지 않았다. Beat This와 madmom의 Python tree가 기존 pin과
일치했고, native build 해시와 체크포인트를 기록했다.

[집계·출처 JSON](BEAT_DBN_RUNTIME_INTEGRATION_2026-11-18.json)은 다음 범위를 구분한다.

- **새 박자 추론:** 지정 5곡 전체 원본 WAV에서 같은 final0/DBN·CPU2·seed0 설정으로
  실행했다. 별도 runtime 명령과 receipt 검증을 통과했고 기존 동결 결과와 beat/downbeat
  배열이 5/5 정확히 같았다. 이번 실행에서 보컬·분리·S2 추론을 다시 수행하지 않았다.
- **통합 출판:** main의 화음 보존 수정 위 코드 `b1fe9dd`에서 새 박자 결과와 기존 Your
  보컬·S2 context를 사용했다. S2/LV 화성 각각 5곡의 격리된 Song 출판 10/10을 통과했다.
  canonical/출판 MusicXML의 모든 harmony를 독립 표준 의미와 대조하고 화성 이벤트,
  재연주 MIDI, 입력·소스 불변을 검사했다. API Job 5개를 새로 실행한 결과는 아니다.
- **보존 범위:** 두 경로 모두 원본 2,813음 중 2,723음을 표현하고 90음을 누락했다.
  기존 DBN의 격자·원본 ID 대응을 유지했다. 이전 S2 clock의 2,693음 대비 30음 증가를
  원곡 정확도 증가로 환산하지 않는다. 페이지는 곡 순서대로 5/7/7/5/7이다.
- **화면 확인:** LV PDF 전체 31페이지를 접촉 시트 10개로 확인했다. 확장 화음 표기는
  유지되지만 짧은 음표/쉼표 분할, 페이지 하단의 큰 여백과 짧은 마지막 페이지가 남았다.
  여백은 기존 4마디/시스템·5시스템/페이지 설정에 따른 것이며 이 변경에서 수정하지 않았다.
- **코드 검사:** 관련 검사 260개 통과, 로컬 FFmpeg 의존 1개 skip, Ruff 통과.
  로컬 locked 전체 검사는 PyPI DNS 실패 후 권한 요청이 중단돼 완료하지 못했다.
  게시한 정확한 PR head의 필수 CI 결과로 별도 검증한다.

DBN은 고정 개발 recipe v3의 clock이다. runtime/출처와 raw logits·검출은 Job 삭제 후에도
Song에 남기고 누락·해시 손상은 정리를 막는다. 최종 전체 모델, 다른 플랫폼의 native
build, 5곡 전곡 전문가 정확도와 사람의 최소 수정량·출판 품질은 미승인이다.
