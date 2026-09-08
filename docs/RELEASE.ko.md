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
- Windows `AudioScoreTool-Windows-Setup-EXE-unsigned` artifact에서 NSIS `.exe`를 바로 내려받을 수 있는지 확인
- macOS `AudioScoreTool-macOS-DMG-unsigned` artifact에서 `.dmg`를 바로 내려받을 수 있는지 확인

이 artifact는 설치/QA 용도이며 사용자에게 `release verified` 정식 배포로 안내하지 않습니다.

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

`Desktop Release` workflow에서 사용하는 값:

- GitHub secret `WINDOWS_CERTIFICATE`: base64 인코딩한 `.pfx`
- GitHub secret `WINDOWS_CERTIFICATE_PASSWORD`: `.pfx` export password
- GitHub secret `WINDOWS_CERTIFICATE_THUMBPRINT`: certificate thumbprint
- repository variable `WINDOWS_TIMESTAMP_URL`: 인증서 발급기관이 권장하는 timestamp URL

CI secret에는 인증서 원문을 repository에 commit하지 않고 암호화된 secret으로만 전달합니다.

## 4. macOS 정책

정식 macOS 배포 전 필수:

1. Apple Developer Program의 Developer ID Application identity 사용
2. hardened runtime을 포함해 app/bundle 서명
3. Apple notarization 제출
4. notarization 성공 후 ticket staple
5. `spctl`/Gatekeeper 기준 검증
6. 새 macOS 사용자 환경에서 drag-install 또는 installer 실행 확인

`Desktop Release` workflow에서 사용하는 값:

- GitHub secret `APPLE_CERTIFICATE`: Developer ID Application `.p12`의 base64 값
- GitHub secret `APPLE_CERTIFICATE_PASSWORD`
- GitHub secret `APPLE_ID`
- GitHub secret `APPLE_PASSWORD`: app-specific password
- GitHub secret `APPLE_TEAM_ID`
- GitHub secret `KEYCHAIN_PASSWORD`: CI 임시 keychain password

Apple 계정 credential, App Store Connect key 또는 notarization credential은 repository 파일에 저장하지 않습니다.

## 5. GitHub Release 동작

`.github/workflows/desktop-release.yml`은 `v*` tag에서 실행됩니다.

### 서명 준비 전

repository variable `RELEASE_SIGNING_READY`가 `true`가 아니면:

1. Windows NSIS `.exe` 빌드
2. macOS ad-hoc signed `.dmg` 빌드
3. 두 파일을 Actions artifact로 업로드
4. **공개 GitHub Release는 만들지 않음**

즉, 개발/QA 설치 파일은 받을 수 있지만 정식 배포로 오인되지 않습니다.

### 서명 준비 후

`RELEASE_SIGNING_READY=true`이면:

1. draft GitHub Release 생성
2. Windows 인증서를 runner certificate store에 import
3. NSIS `.exe` Authenticode signing + timestamp
4. `Get-AuthenticodeSignature`로 signature 검증
5. macOS Developer ID certificate를 임시 keychain에 import
6. `.app` signing + Apple notarization + stapling을 포함한 DMG build
7. `codesign`, `spctl`, `stapler validate` 검증
8. `.exe` / `.dmg`를 draft Release에 업로드
9. 두 플랫폼 build가 모두 성공한 경우에만 draft를 공개 Release로 전환

한 플랫폼이라도 실패하면 Release는 draft 상태로 남습니다.

## 6. updater 도입 순서

자동 업데이트는 unsigned package 단계에서 바로 추가하지 않습니다. 배포 신뢰 체인을 먼저 완성한 뒤 updater를 연결합니다.

권장 순서는 다음과 같습니다.

1. Windows signing 및 macOS signing/notarization 구축
2. `v*` tag 기반 검증된 `.exe` / `.dmg` GitHub Release
3. SHA-256 checksum과 release notes 제공
4. clean-install E2E 통과 확인
5. Tauri updater용 `createUpdaterArtifacts`와 signed update manifest/public key 도입
6. stable channel에서 update check 활성화

updater metadata/signature 검증이 실패하면 기존 설치를 그대로 보존해야 하며, 업데이트 설치는 사용자가 명시적으로 실행하거나 동의하는 흐름을 기본으로 합니다.

## 7. CI 릴리스 gate

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

## 8. clean-install E2E 최소 항목

### 공통

- 새 사용자 데이터 디렉터리에서 첫 실행
- backend가 고정 8080이 아닌 runtime port로 시작
- duplicate app launch가 기존 창으로 전달됨
- local API token 없는 요청 거부
- 앱 종료 시 sidecar 종료
- 앱 재실행 후 SQLite/startup recovery 정상
- startup diagnostics에 recovery/ingestion 결과 노출

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

## 9. 릴리스 상태 용어

- `static-review complete`: 정적 고위험 코드 리뷰 이슈를 닫은 상태
- `CI green`: 현재 commit의 자동 test/build가 모두 성공한 상태
- `package verified`: 지원 OS package build와 packaged-sidecar smoke가 성공한 상태
- `release candidate`: clean-install E2E까지 통과한 상태
- `release verified`: signing/notarization을 포함한 배포 신뢰 체인까지 통과한 상태

각 용어는 이전 단계를 포함하며, 실제 증거 없이 상위 상태를 사용하지 않습니다.
