# AudioScoreTool 데스크탑 릴리스 정책

이 문서는 Windows/macOS/Linux desktop artifact의 **QA, self-contained runtime, signing, notarization, updater, stable publication** 경계를 고정합니다.

> [!IMPORTANT]
> Tauri updater 코드와 signed updater artifact/manifest를 만드는 release pipeline 구조는 구현되어 있습니다. 실제 stable release는 signing credential뿐 아니라 **별도 시스템 runtime 설치가 없는 clean-machine acceptance**까지 통과해야 합니다. 운영 gate는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 1. artifact 등급

### PR/CI QA artifact

`Desktop Packages` workflow가 PR에서 생성하는 package는 **unsigned 테스트 artifact**입니다.

검증 범위:

- PyInstaller sidecar가 Windows/macOS/Linux에서 생성되는지
- packaged sidecar가 runtime loopback port와 API token 정책으로 기동하는지
- token 없는 API 요청이 거부되고 정상 token으로 health check가 성공하는지
- embedded Python dependencies가 packaged sidecar 안에서 import/실행되는지
- Tauri desktop bundle이 각 OS에서 생성되는지
- Windows NSIS `.exe`와 macOS `.dmg`가 artifact로 생성되는지

이 파일들은 개발/QA 용도이며 `release verified` 정식 배포본으로 안내하지 않습니다.

### Stable release artifact

정식 배포는 다음 신뢰 사슬을 통과해야 합니다.

```text
CI green
  ↓
3-OS packaged sidecar + bundle verification
  ↓
self-contained clean-machine acceptance
  ↓
Windows Authenticode / macOS Developer ID signing + notarization
  ↓
checksum + signed updater payload/manifest
  ↓
clean install / update / rollback acceptance
  ↓
public stable release
```

## 2. self-contained desktop 계약

일반 사용자용 release는 다음을 요구하지 않습니다.

- system Python / Node.js / Rust
- `pip`, `uv`, `uvx`, `npm`, `cargo`
- Homebrew / winget을 이용한 후설치
- MuseScore
- LilyPond / `musicxml2ly`
- PATH 수동 설정

핵심 Python runtime과 music21/Verovio/fpdf2/Hugging Face Hub client는 packaged sidecar에 포함합니다. 큰 AI runtime/model, YouTube stack, OMR, 선택 검증 도구는 [`DEPENDENCIES.ko.md`](DEPENDENCIES.ko.md)의 app-managed component 계약을 따릅니다.

packaged mode는 `AST_PACKAGED=1`로 실행되며 시스템 PATH의 executable을 fallback으로 사용하지 않습니다. command 기반 component는 AudioScoreTool app-data의 `components/bin` 아래에서만 발견되어야 합니다.

## 3. 사용자용 배포 형식

### Windows

- 주 배포: NSIS `.exe`
- 선택 배포: 조직/관리형 설치 요구가 있을 때 검증된 `.msi`
- standalone Python backend가 아니라 Tauri shell + frontend + packaged sidecar를 하나의 desktop installer로 제공

정식 release에서는 Authenticode 서명과 timestamp 검증이 필요합니다.

### macOS

- 주 배포: `.dmg`
- 내부 `.app`은 Developer ID Application signing, notarization, stapling을 통과해야 함
- arm64/x86_64를 각각 검증할 수 없다면 universal 지원을 문서로 과장하지 않음

### Linux

현재 package regression 대상으로 유지하며, 실제로 생성·검증한 형식만 Release에 노출합니다.

## 4. signing credential

credential 원문은 repository에 commit하지 않습니다.

### Windows

필요한 Actions secrets/variables:

- `WINDOWS_CERTIFICATE`
- `WINDOWS_CERTIFICATE_PASSWORD`
- `WINDOWS_CERTIFICATE_THUMBPRINT`
- `WINDOWS_TIMESTAMP_URL`

검증:

- installer/executable Authenticode signature
- timestamp
- clean Windows 환경 install/launch/remove

### macOS

필요한 Actions secrets:

- `APPLE_CERTIFICATE`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_ID`
- `APPLE_PASSWORD`
- `APPLE_TEAM_ID`
- `KEYCHAIN_PASSWORD`

검증:

- `codesign`
- Apple notarization
- stapling
- `spctl` / Gatekeeper
- clean macOS drag-install/launch

### Tauri updater

필요한 값:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (암호화된 key를 사용하는 경우)
- `TAURI_UPDATER_PUBKEY`

private key는 CI secret에만 저장하고 public key만 application configuration에서 사용합니다.

## 5. Desktop Release workflow

`v*` tag release workflow는 signing readiness에 따라 동작을 구분합니다.

### signing 준비 전

- Windows/macOS package를 QA artifact로 만들 수 있음
- 공개 stable Release를 신뢰 가능한 공식 배포본으로 publish하지 않음
- updater stable channel metadata를 공식 release로 활성화하지 않음

### signing 준비 후

`RELEASE_SIGNING_READY=true`와 필요한 credential이 모두 준비된 경우:

1. draft Release 준비
2. Windows `.exe` build/sign/timestamp/verification
3. macOS `.app/.dmg` sign/notarize/staple/verification
4. updater archive와 `.sig` 생성
5. `latest.json`에 실제 signature와 platform URL 기록
6. `SHA256SUMS.txt` 생성
7. release artifacts를 동일 draft에 집계
8. 양쪽 주요 플랫폼 gate가 모두 성공한 경우에만 stable publication 허용

플랫폼 하나라도 실패하면 불완전한 artifact를 stable release로 홍보하지 않습니다.

## 6. updater 상태

updater는 **향후 구현 항목이 아니라 구현된 기능**입니다.

현재 코드 계약:

- Tauri updater plugin으로 update metadata 확인
- signed updater artifact와 `.sig` 사용
- 사용자 확인 없이 강제로 업데이트하지 않음
- install/update 실패가 기존 설치를 손상시키지 않아야 함

아직 남은 운영 계약:

- 실제 signing key/certificate provisioning
- 실제 GitHub stable Release에서 `latest.json` 및 signature 검증
- clean Windows/macOS에서 install → update → relaunch
- 변조된 manifest/signature 거부
- 한 플랫폼 실패 시 stable publication 차단

즉 **updater implementation complete ≠ trusted stable update channel activated**입니다.

## 7. CI / release gate

정식 release 후보는 최소 다음을 통과해야 합니다.

```text
Python lock check
+ Ruff
+ pytest
+ embedded Verovio/fpdf2 PDF test
+ packaged-runtime PATH isolation tests
+ frontend typecheck/build
+ keyboard-only E2E
+ Cargo/Tauri check
+ Windows/macOS/Linux package build
+ packaged sidecar auth/runtime-port smoke
+ embedded dependency smoke
+ self-contained clean-machine acceptance
+ Windows signing verification
+ macOS signing/notarization verification
+ updater signature/manifest verification
+ clean-install/update acceptance
```

PR CI green이나 unsigned package 생성만으로 `release verified`라고 부르지 않습니다.

## 8. clean-install/update acceptance

### 공통 runtime

- 새 user data directory에서 첫 실행
- system Python/Node/Rust/uv/pip가 설치되지 않은 환경
- MuseScore/LilyPond가 설치되지 않은 환경
- Homebrew/winget 후설치 없이 진행
- backend가 runtime loopback port로 시작
- `AST_PACKAGED=1` 및 app-managed component root 적용
- 시스템 PATH executable fallback이 발생하지 않음
- API token 없는 요청 거부
- duplicate launch 처리
- 앱 종료 시 sidecar 종료
- 재실행 시 SQLite/startup recovery 정상

### 핵심 제품 flow

- MusicXML/MXL 직접 import
- MIDI 직접 import
- score edit/revision/undo
- publication settings
- MusicXML/MIDI export
- **embedded Verovio/fpdf2 full score PDF export**
- **embedded Verovio/fpdf2 part PDF export**
- export 실패 시 이전 정상 export 보존
- LLM OFF 상태의 핵심 workflow

### managed component flow

stable에서 공식 지원한다고 선언한 기능만 acceptance에 포함합니다.

- local audio AMT: app-managed inference runtime/model 준비 → transcription
- YouTube: app-managed ingest stack 준비 → import
- PDF/image OMR: app-managed OMR component 준비 → import
- optional lyrics/audio validation: 해당 component 준비 시 정상 동작

managed delivery가 아직 구현되지 않은 기능을 사용자에게 수동 설치시키는 것으로 acceptance를 대체하지 않습니다.

### updater

- 이전 stable version 설치
- 새 signed version 감지
- 사용자 동의 후 update
- relaunch 후 DB/migration 정상
- invalid signature/manifest 거부
- download/install 실패 시 기존 version 실행 가능

## 9. 상태 용어

| 용어 | 의미 |
|---|---|
| `CI green` | 현재 commit의 자동 lint/test/build 계약 성공 |
| `package verified` | 지원 OS package build + packaged sidecar smoke 성공 |
| `self-contained core verified` | 외부 개발/runtime 설치 없는 clean machine에서 핵심 import/edit/export 성공 |
| `release candidate` | self-contained gate + signing 준비 + clean-install acceptance 대상으로 승격된 artifact |
| `release verified` | signing/notarization/updater trust chain과 clean-install/update acceptance까지 성공 |

증거 없이 상위 상태를 사용하지 않습니다.

## 10. 현재 v0.8 상태

- CI: 구현 및 반복 검증됨
- Windows/macOS/Linux package regression: 구현됨
- Windows `.exe` / macOS `.dmg` unsigned QA artifact: 생성 가능
- external notation renderer 제거: 구현됨, 이번 dependency refactor의 package 검증 필요
- packaged runtime의 system PATH isolation: 구현됨, package 검증 필요
- managed Hugging Face model download transport: Python API로 전환됨, package 검증 필요
- AMT/YouTube/OMR/optional native component의 완전한 managed delivery: **추가 구현/검증 필요**
- Tauri updater integration: 구현됨
- signed updater artifact/manifest pipeline: 구현됨
- 실제 signing credential provisioning: **미완료 (#22)**
- signed clean-install/update acceptance: **미완료 (#22)**
- 공식 `release verified` stable publication: **self-contained + #22 완료 후**
