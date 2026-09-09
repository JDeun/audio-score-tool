# AudioScoreTool 적대적 검증 기준

## 목적

AudioScoreTool은 `기능 구현 완료`와 `안정화 완료`를 같은 상태로 취급하지 않습니다.

기능이 정상 입력에서 동작하고 일반 CI가 통과하더라도 다음 질문에 답하지 못하면 release candidate가 아닙니다.

- 입력이 의도적으로 깨졌을 때 안전하게 실패하는가?
- 저장 공간, 메모리, subprocess output 같은 자원이 비정상 입력으로 고갈되지 않는가?
- 앱이 강제 종료된 직후 다시 실행해도 canonical state가 복구되는가?
- 동시에 여러 변경이 들어왔을 때 revision과 DB가 모순되지 않는가?
- local API와 artifact path가 다른 로컬 프로세스나 path traversal에 노출되지 않는가?
- optional component가 실패해도 핵심 Song/Score 상태가 손상되지 않는가?
- UI 상태가 viewport, dark mode, focus mode, reduced motion에서 복귀 가능한가?

## 위협 모델

이 문서의 `적대적`은 인터넷 서비스 수준의 원격 공격자만 의미하지 않습니다.

AudioScoreTool은 local-first desktop application이므로 다음을 포함합니다.

1. 손상되거나 비정상적으로 큰 사용자 파일
2. 악의적으로 제작된 MusicXML/MXL/PDF/image/MIDI
3. 같은 PC에서 loopback API port를 탐색하는 다른 프로세스
4. 디스크 부족, permission failure, subprocess crash
5. 앱 강제 종료/OS 재시작
6. 중복 클릭, concurrent edit, stale revision
7. 비정상 component output 또는 오래된 historical DB row
8. 매우 작은/큰 desktop viewport와 OS accessibility preference

## 검증 계층

### A. Upload / file boundary

필수 조건:

- endpoint별 상한을 stream write 단계에서 검사
- 제한 초과 시 `.uploading` temp 제거
- 부분 파일을 canonical input으로 승격하지 않음
- 지원하지 않는 확장자는 처리 전에 거부
- managed root 밖의 파일을 artifact로 노출하지 않음
- symlink escape도 managed path로 인정하지 않음

### B. MusicXML / MXL

필수 조건:

- 빈 문서 거부
- `score-partwise` / `score-timewise` 외 root 거부
- DTD/ENTITY 선언 거부
- 선언 위치가 파일 prefix 뒤에 있어도 거부
- member count 제한
- 개별 member 크기 제한
- total uncompressed size 제한
- 비정상 compression ratio 제한
- encrypted ZIP member 거부
- malformed ZIP/XML은 exception leakage 없이 domain error로 변환

### C. Local API boundary

필수 조건:

- packaged mode의 모든 실제 `/api/*` 요청에 per-launch token 요구
- token 비교는 constant-time compare 사용
- duplicate token header를 ambiguous credential로 거부
- invalid UTF-8 credential 거부
- mutation request의 untrusted Origin 거부
- CORS preflight만 예외 허용

### D. SQLite / canonical state

필수 조건:

- malformed historical JSON 한 건으로 history 전체가 중단되지 않음
- concurrent Job update가 lock/busy error로 무작위 실패하지 않음
- stale score edit은 revision conflict로 명확히 거부
- job ingestion cursor가 history UI limit과 독립적
- crash recovery 중 disposable state만 자동 제거
- canonical DB row가 남은 staged deletion은 복구
- DB delete가 commit된 staged deletion만 물리 제거
- DB corruption은 자동 삭제/초기화하지 않고 명시적으로 실패

### E. Process / managed component

필수 조건:

- shell string 실행 금지; argv 기반 실행
- stdout/stderr memory 사용량 제한
- timeout/cancel 시 process tree 종료
- packaged mode에서 system PATH fallback 금지
- component failure가 Song canonical state를 덮어쓰지 않음
- secret/token을 command log에 포함하지 않음

### F. Export / rendering

필수 조건:

- malformed MusicXML export가 기존 export를 파괴하지 않음
- staged export → atomic replacement 계약 유지
- Preview와 PDF는 같은 canonical layout state를 입력으로 사용
- PDF renderer 실패 시 MusicXML canonical state 유지
- export path는 앱 managed export root 밖으로 탈출하지 않음

### G. Desktop / UI state

필수 조건:

- 1366×768 / 1440×900 / 1920×1080에서 불필요한 page overflow 없음
- Library/Inspector hidden state에서 editor state 손실 없음
- Focus mode에서 항상 exit affordance 유지
- dark mode에서도 score paper는 print 기준 밝은 surface 유지
- `prefers-reduced-motion`에서 decorative motion 제거
- keyboard focus trap/restore 유지
- 상태는 색상만으로 전달하지 않음

## CI gate

일반 Python suite와 별도로 다음 파일을 먼저 실행합니다.

```text
tests/test_adversarial_boundaries.py
tests/test_adversarial_state_recovery.py
```

Frontend는 일반 keyboard E2E와 함께 visual contract를 실행합니다.

```text
desktop/e2e/keyboard-accessibility.spec.ts
desktop/e2e/visual-contract.spec.ts
```

Rust shell은 다음을 모두 통과해야 합니다.

```text
cargo check --locked
cargo clippy --locked -- -D warnings
```

또한 PR merge 전 Windows/macOS/Linux Desktop Packages workflow의 packaged sidecar smoke 및 bundle build가 모두 성공해야 합니다.

## Release candidate 판정

다음은 서로 다른 상태입니다.

```text
Feature complete
  ↓
Regression green
  ↓
Adversarial hardening green
  ↓
3-OS packaged acceptance green
  ↓
Signed/notarized clean-install/update acceptance
  ↓
Stable release
```

따라서 `pytest green`만으로 `안정화 완료`라고 표현하지 않습니다.

## 실기기 acceptance

자동화 이후 실제 packaged application에서 최소 다음을 반복합니다.

- 큰 audio file 취소/재시도
- malformed MusicXML/MXL import
- 앱 작업 중 강제 종료 후 재실행
- 동일 곡의 빠른 연속 edit/undo/export
- optional component 미설치/실행 실패
- disk space 부족 조건
- 긴 한국어 제목/파일명
- Windows 125% / 150% scaling
- macOS Retina
- light/dark mode
- Page/Continuous/Focus 전환

실기기 acceptance 결과가 자동 테스트와 다르면 실기기 동작을 우선하여 regression case로 추가합니다.
