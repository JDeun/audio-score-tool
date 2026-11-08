# AudioScoreTool 데스크탑 릴리스 정책

이 문서는 Windows/macOS/Linux desktop artifact의 **QA, self-contained runtime, signing, notarization, updater, stable publication** 경계를 고정합니다.

> [!IMPORTANT]
> Tauri updater 코드와 signed updater artifact/manifest를 만드는 release pipeline 구조는 구현되어 있습니다. 실제 stable release는 signing credential뿐 아니라 **별도 시스템 runtime 설치가 없는 clean-machine acceptance**까지 통과해야 합니다. 운영 gate는 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 1. artifact 등급

### 수동·태그 기반 QA artifact

`Desktop Packages` workflow는 일반 코드 PR마다 패키지를 생성하지 않습니다. 수동 실행(`workflow_dispatch`) 또는 `v*` 태그에서 만드는 package는 **unsigned QA 테스트 artifact**입니다. 일반 PR의 필수 코드 검증은 `CI / verify`가 담당합니다.

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
2. Windows/macOS의 frozen sidecar에서 승인된 AMT·YouTube·OMR 관리형 구성요소를 실제 설치·검증하고, 원본 WAV 채보·PDF OMR·검토된 YouTube→Song 기능 인수시험 통과
3. Windows `.exe` build/sign/timestamp/verification
4. macOS `.app/.dmg` sign/notarize/staple/verification
5. updater archive와 `.sig` 생성
6. `latest.json`에 실제 signature와 platform URL 기록
7. `SHA256SUMS.txt` 생성
8. release artifacts를 동일 draft에 집계
9. 양쪽 주요 플랫폼 gate가 모두 성공한 경우에만 stable publication 허용

서명 배포의 `Desktop Release`는 별도 `Desktop Packages` 실행 결과에 의존하지 않고, **서명 전 동일한 `smoke_packaged_sidecar.py --require-managed-delivery` 인수시험을 각 플랫폼에서 직접 실행**합니다. `YOUTUBE_QA_SOURCE_REVIEW_JSON` 검토 기록 또는 승인된 런타임이 없으면 공개 배포가 차단됩니다. 이 시험은 frozen sidecar에서 실행하지만 설치된 DMG/NSIS를 깨끗한 사용자 컴퓨터에서 검증하는 단계 자체를 대체하지는 않습니다(#22).

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

## 설치형 라이선스 고지 계약

- 원저작물 `LICENSE`와 `NOTICE`는 Tauri `bundle.resources`에 포함되어 설치된 앱에서 읽을 수 있어야 합니다.
- 설정 화면에서는 두 파일의 전문을 **오프라인으로** 확인할 수 있어야 합니다. 소스 GitHub 링크만 제공하는 것은 이 계약의 대체가 아닙니다.
- `LICENSE`/`NOTICE` 고지는 AudioScoreTool 자체 코드에 대한 것이며, 실제 포함한 모델·binary·폰트 등 제3자 고지/SBOM을 별도로 검토해야 합니다. 이번 구조 테스트가 설치본의 실물 라이선스 인벤토리 검수를 완료했다는 뜻은 아닙니다.
## 7. CI / release gate

일반 PR CI와 패키징·보안 감사의 실행 조건은 [CI 실행 전략](CI_STRATEGY.ko.md)을 따릅니다. Python/프런트엔드/Tauri의 빠른 코드 검증은 `verify`에 집계하고, 패키지·보안/권리·클린 머신·서명은 독립 출시 게이트로 유지합니다.

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

### 실제 managed component 설치를 수반하는 패키지 smoke

일반 코드 PR에서는 Windows/macOS/Linux 패키지 빌드를 실행하지 않습니다. `Desktop Packages`를 수동 실행할 때 `require_managed_delivery` 옵션을 활성화하거나 `v1*` 릴리스 태그를 발행하면 **Windows/macOS**에서 별도의 managed-delivery smoke가 실행됩니다(Linux는 패키지 자체 회귀 범위 유지).

이 강화 smoke는 배포된 PyInstaller sidecar를 독립된 임시 `AST_COMPONENT_DIR`로 실행하고, 앱이 실제 번들한 승인 카탈로그를 조회합니다. 각 필수 `transcription_engine`, `youtube_runtime`, `audiveris`에 대해 **실제 `POST /api/setup/install` HTTPS 다운로드·SHA-256 설치 검증**을 수행합니다. 설치된 도구의 관리 루트 containment 및 Setup Center verified 상태를 재검사합니다. YouTube 4종(`yt-dlp`, `deno`, `ffmpeg`, `ffprobe`)은 `BUNDLE-INVENTORY.json`의 경로·버전·해시와 실제 실행 결과가 일치해야 합니다. `PATH`를 비워 호스트 도구로 우회하지 못하게 합니다.

이후 **자체 생성 WAV → 실제 MT3 모델 추론 → note-on MIDI/MusicXML**, **Verovio PDF → 관리형 Audiveris/내장 JRE → 정규 Song → PDF/MIDI/파트 출력**, 그리고 **권한 검토된 실제 단일 YouTube URL → 관리형 오디오 가져오기 → MT3 → Song**을 인증된 packaged API에서 시험합니다. 실제 HTTPS 구성요소 다운로드와 검토된 YouTube 영상 다운로드가 발생하므로 **`YOUTUBE_QA_SOURCE_REVIEW_JSON` Repository Variable에 운영자가 검토한 영상/권리/길이 제한의 영수증**이 있어야 하며, 권리 확인이 없으면 다운로드 전에 fail-closed 합니다. 원본 영상과 가중치는 공개 CI 아티팩트로 올리지 않습니다.

이 시험은 **실제 모델을 실행하는 기능 인수시험**이지만 #34의 실음원 품질 평가나 제3자 재배포 권리 승인, Windows/macOS 설치본의 clean-machine 설치·업데이트·서명 수락을 대체하지 않습니다. 현시점 카탈로그의 `artifacts: {}`와 승인 목록이 비어 있어 강화 옵션은 의도대로 실패합니다. 미게시 상태에서도 기본 unsigned QA package smoke만 별도로 실행할 수 있습니다.

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
