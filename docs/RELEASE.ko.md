# AudioScoreTool 데스크탑 릴리스 정책

이 문서는 Windows/macOS/Linux 데스크탑 배포 artifact의 검증·서명·릴리스 기준을 고정합니다.

## 1. artifact 등급

### PR 검증 artifact

GitHub Actions의 `Desktop Packages`가 생성하는 PR artifact는 **테스트용 unsigned bundle**입니다.

목적:
- PyInstaller sidecar가 각 OS에서 생성되는지 확인
- packaged sidecar가 runtime loopback port에 실제 bind하는지 확인
- `AST_API_TOKEN`이 없으면 `/api/*` 요청이 거부되는지 확인
- token이 있으면 `/api/health`가 정상 응답하는지 확인
- Tauri bundle이 각 OS에서 실제 생성되는지 확인

이 artifact는 사용자에게 정식 배포하지 않습니다.

### Release artifact

정식 배포 artifact는 아래 신뢰 체인을 통과해야 합니다.

- Windows: Authenticode code signing
- macOS: Developer ID Application signing + Apple notarization + stapling
- Linux: CI에서 생성한 bundle checksum 제공

서명되지 않은 Windows/macOS artifact를 `release verified`로 표시하지 않습니다.

## 2. 사용자용 권장 배포 형식

소스 저장소를 직접 clone하거나 Python/Node/Rust 환경을 준비하지 않아도 사용할 수 있도록 정식 릴리스에서는 설치형 artifact를 기본 진입점으로 제공합니다.

### Windows

- **주 배포:** NSIS 기반 `.exe` installer
- **보조 배포:** 조직 배포나 관리형 설치가 필요한 경우 `.msi`
- standalone backend 실행 파일 자체가 아니라 Tauri desktop shell, frontend, packaged Python sidecar가 함께 포함된 설치 bundle을 사용자에게 제공합니다.

일반 사용자는 `.exe`를 우선 선택하도록 README와 GitHub Release에서 안내합니다.

### macOS

- **주 배포:** `.dmg`
- DMG 안의 서명·공증된 `AudioScoreTool.app`을 Applications로 복사하는 흐름을 기본으로 합니다.
- Apple Silicon과 Intel을 모두 지원할 경우 universal binary가 실제 sidecar/model runtime과 함께 검증될 때만 universal로 배포합니다. 그렇지 않으면 `arm64` / `x86_64` artifact를 명확히 분리합니다.

### Linux

Linux는 현재 package verification 대상으로 유지하며 AppImage/deb/rpm 중 실제 지원·검증한 형식만 Release에 노출합니다.

## 3. Windows 정책

정식 Windows 배포 전 필수:

1. 신뢰 가능한 코드 서명 인증서 확보
2. Tauri가 생성한 실행 파일과 installer에 Authenticode 적용
3. timestamp server를 사용해 인증서 만료 후에도 서명 유효성 유지
4. 새 Windows clean VM에서 설치/실행/제거 확인
5. SmartScreen 경고 상태를 기록하고 초기 reputation 상태와 서명 오류를 구분

CI secret에는 인증서 원문을 repository에 commit하지 않고 암호화된 secret으로만 전달합니다.

## 4. macOS 정책

정식 macOS 배포 전 필수:

1. Apple Developer Program의 Developer ID Application identity 사용
2. hardened runtime을 포함해 app/bundle 서명
3. Apple notarization 제출
4. notarization 성공 후 ticket staple
5. `spctl`/Gatekeeper 기준 검증
6. 새 macOS 사용자 환경에서 drag-install 또는 installer 실행 확인

Apple 계정 credential, App Store Connect API key 또는 notarization credential은 repository 파일에 저장하지 않습니다.

## 5. GitHub Release 및 updater 순서

자동 업데이트는 unsigned package 단계에서 바로 추가하지 않습니다. 배포 신뢰 체인을 먼저 완성한 뒤 updater를 연결합니다.

권장 순서는 다음과 같습니다.

1. Windows signing 및 macOS signing/notarization 구축
2. `v*` tag 기반으로 검증된 `.exe` / `.dmg`를 GitHub Release에 업로드
3. SHA-256 checksum과 release notes 제공
4. clean-install E2E 통과 확인
5. Tauri updater용 signed update manifest와 public key 도입
6. stable channel에서 update check를 활성화

updater metadata/signature 검증이 실패하면 기존 설치를 그대로 보존해야 하며, 업데이트 설치는 사용자가 명시적으로 실행하거나 동의하는 흐름을 기본으로 합니다.

## 6. CI 릴리스 gate

정식 release 후보는 최소 다음을 모두 만족해야 합니다.

```text
Python lock check
+ Python lint
+ Python tests
+ frontend typecheck/build
+ Cargo/Tauri check
+ Windows package build
+ macOS package build
+ Linux package build
+ packaged sidecar auth/runtime-port smoke
+ clean-install E2E
+ Windows signing 검증
+ macOS signing/notarization 검증
```

PR CI가 green이라는 이유만으로 정식 릴리스로 간주하지 않습니다.

## 7. clean-install E2E 최소 항목

### 공통

- 새 사용자 데이터 디렉터리에서 첫 실행
- backend가 고정 8080이 아닌 runtime port로 시작
- duplicate app launch가 기존 창으로 전달됨
- local API token 없는 요청 거부
- 앱 종료 시 sidecar 종료
- 앱 재실행 후 SQLite/startup recovery 정상

### 제품 흐름

- local audio import
- YouTube import
- PDF/image OMR
- MusicXML edit/revision/undo
- publication settings
- LilyPond full score/part export
- export 실패 후 기존 정상 export 보존
- LLM 완전 OFF
- 선택적 external enrichment를 사용자가 명시적으로 실행할 때만 네트워크 요청

## 8. 릴리스 상태 용어

- `static-review complete`: 정적 고위험 코드 리뷰 이슈를 닫은 상태
- `CI green`: 현재 commit의 자동 test/build가 모두 성공한 상태
- `package verified`: 지원 OS package build와 packaged-sidecar smoke가 성공한 상태
- `release candidate`: clean-install E2E까지 통과한 상태
- `release verified`: signing/notarization을 포함한 배포 신뢰 체인까지 통과한 상태

각 용어는 이전 단계를 포함하며, 실제 증거 없이 상위 상태를 사용하지 않습니다.
