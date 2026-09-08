# v0.8 안정화 / 코드리뷰 현황

이 문서는 AudioScoreTool v0.8의 현재 안정화 상태와 남은 검증 경계를 기록합니다. 과거 리뷰의 세부 변경 이력은 Git history와 각 PR에 보존되어 있으며, 이 문서는 **현재 사실**을 우선합니다.

## 현재 자동 검증 상태

- GitHub-hosted Actions 정상 동작
- `uv.lock`, `desktop/package-lock.json`, `desktop/src-tauri/Cargo.lock` 커밋 및 frozen/locked 설치 사용
- Python lint / 전체 pytest / TypeScript·Vite build / `cargo check --locked` 실제 CI 통과
- Linux / Windows / macOS Tauri package build 실제 GitHub-hosted runner 통과
- 세 OS 모두 PyInstaller sidecar build 및 smoke test 통과
- packaged sidecar smoke는 동적 loopback port bind, token 없는 API 요청 401, 유효 token의 `/api/health` 응답을 검증

## 현재 안정화된 핵심 경계

### 저장 / 데이터 무결성
- SQLite canonical MusicXML + revision / analysis / publication state
- WAL-aware legacy DB migration
- revision CAS와 동일 곡 mutation serialization
- atomic upload / export publish / Undo / publication commit
- crash-safe Job deletion 및 startup recovery
- completed score Job은 canonical Song ingestion 확인 전 cleanup 금지

### 로컬 API / 데스크탑 경계
- packaged 실행마다 random API token
- 실제 API 요청은 GET 포함 token 필수, CORS preflight만 예외
- packaged backend는 고정 8080 대신 Rust/Tauri가 선택한 동적 loopback port 사용
- frontend는 Rust IPC로 실제 backend base URL과 token을 받아 연결
- single-instance 및 backend child lifecycle 관리

### 외부 입력 / 실행 도구
- request-size / upload-size guard
- MXL/XML entity 방어 및 managed artifact path containment
- bounded subprocess output, cancellation / process-tree 종료 정책
- YouTube URL·live·duration 제한
- 외부 네트워크 enrichment는 사용자 명시 동작에서만 실행

### 악보 backend
- MuseScore runtime dependency 제거
- OSMD preview
- music21 MIDI↔MusicXML
- LilyPond + musicxml2ly PDF
- Audiveris OMR
- PDF renderer가 없어도 MusicXML/MIDI 채보·편집 workflow는 사용 가능

## 코드에서 계속 닫아야 하는 항목

- legacy `api.py` + `api_ext.py` route composition을 단일 app factory로 단계적 통합
- 모든 background producer가 동일 admission / start-failure 정책을 사용하도록 지속 검증
- MusicXML/MIDI 직접 import와 같은 정의된 v1 입력 범위의 API/UI 계약 검증
- 접근성: modal focus trap, Escape close, focus restore 일관화
- structured/redacted sidecar diagnostics와 startup recovery 결과 UI 노출

## 실제 환경이 필요한 잔여 Release 검증

자동 CI package build는 통과했지만 다음은 실제 사용자 머신/실제 데이터가 필요합니다.

- Windows clean install / uninstall / upgrade
- macOS clean install / Gatekeeper / notarization
- Windows code signing
- 실제 MuScriptor / MT3 모델 다운로드 및 GPU·CPU 실행
- 실제 음원 Golden Set의 note/instrument/chord/lyrics 품질과 최종 수정 시간
- 실제 PDF/image OMR Golden Set 품질
- 실제 LilyPond PDF fidelity
- 강제 종료·디스크 부족·외부 도구 누락의 실기기 E2E

## 저장소 운영에서 남은 수동 설정

`main` branch protection / required CI check는 GitHub repository administration 설정입니다. 코드와 별도로 `verify` required check, PR required, force-push/branch deletion 금지를 적용하는 것이 권장됩니다.

## 릴리스 판정 규칙

```text
고위험 알려진 코드 결함 = 0
+ 전체 test/build 실제 CI 성공
+ 3 OS package build + packaged sidecar smoke 성공
+ clean-install E2E 통과
+ signing/notarization 정책 확정
+ 실제 악보 품질 Golden Set 검증
```

CI green은 코드/패키지 빌드 검증을 의미하며, 실제 설치·모델·악보 품질 검증까지 완료됐다는 의미로 사용하지 않습니다.
