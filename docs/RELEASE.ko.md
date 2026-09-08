# AudioScoreTool 데스크탑 릴리스 정책

이 문서는 Windows/macOS/Linux desktop artifact의 **QA, signing, notarization, updater, stable publication** 경계를 고정합니다.

> [!IMPORTANT]
> Tauri updater 코드와 signed updater artifact/manifest를 만드는 release pipeline 구조는 이미 구현되어 있습니다. 현재 남은 것은 실제 Windows/macOS signing credential과 Tauri private signing key를 provision하고 clean-install/update acceptance를 수행하는 운영 gate입니다. 진행 상태는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 1. artifact 등급

### PR/CI QA artifact

`Desktop Packages` workflow가 PR에서 생성하는 package는 **unsigned 테스트 artifact**입니다.

검증 범위:

- PyInstaller sidecar가 Windows/macOS/Linux에서 생성되는지
- packaged sidecar가 runtime loopback port와 API token 정책으로 기동하는지
- token 없는 API 요청이 거부되고 정상 token으로 health check가 성공하는지
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
Windows Authenticode / macOS Developer ID signing + notarization
  ↓
checksum + signed updater payload/manifest
  ↓
clean install / update / rollback acceptance
  ↓
public stable release
```

## 2. 사용자용 배포 형식

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

## 3. signing credential

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

## 4. Desktop Release workflow

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

## 5. updater 상태

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

## 6. CI / release gate

정식 release 후보는 최소 다음을 통과해야 합니다.

```text
Python lock check
+ Ruff
+ pytest
+ frontend typecheck/build
+ keyboard-only E2E
+ Cargo/Tauri check
+ Windows/macOS/Linux package build
+ packaged sidecar auth/runtime-port smoke
+ Windows signing verification
+ macOS signing/notarization verification
+ updater signature/manifest verification
+ clean-install/update acceptance
```

PR CI green이나 unsigned package 생성만으로 `release verified`라고 부르지 않습니다.

## 7. clean-install/update acceptance

### 공통 runtime

- 새 user data directory에서 첫 실행
- backend가 runtime loopback port로 시작
- API token 없는 요청 거부
- duplicate launch 처리
- 앱 종료 시 sidecar 종료
- 재실행 시 SQLite/startup recovery 정상
- startup diagnostics 노출

### 제품 flow

- local audio import
- YouTube import
- PDF/image OMR
- MusicXML/MXL 직접 import
- MIDI 직접 import
- score edit/revision/undo
- publication settings
- MusicXML/MIDI export
- LilyPond가 있는 환경에서 full score/part PDF export
- export 실패 시 이전 정상 export 보존
- LLM OFF 상태의 핵심 workflow

### updater

- 이전 stable version 설치
- 새 signed version 감지
- 사용자 동의 후 update
- relaunch 후 DB/migration 정상
- invalid signature/manifest 거부
- download/install 실패 시 기존 version 실행 가능

## 8. 상태 용어

| 용어 | 의미 |
|---|---|
| `CI green` | 현재 commit의 자동 lint/test/build 계약 성공 |
| `package verified` | 지원 OS package build + packaged sidecar smoke 성공 |
| `release candidate` | signing 준비 + clean-install acceptance 대상으로 승격된 artifact |
| `release verified` | signing/notarization/updater trust chain과 clean-install/update acceptance까지 성공 |

증거 없이 상위 상태를 사용하지 않습니다.

## 9. 현재 v0.8 상태

- CI: 구현 및 반복 검증됨
- Windows/macOS/Linux package regression: 구현됨
- Windows `.exe` / macOS `.dmg` unsigned QA artifact: 생성 가능
- Tauri updater integration: 구현됨
- signed updater artifact/manifest pipeline: 구현됨
- 실제 signing credential provisioning: **미완료 (#22)**
- signed clean-install/update acceptance: **미완료 (#22)**
- 공식 `release verified` stable publication: **#22 완료 후**