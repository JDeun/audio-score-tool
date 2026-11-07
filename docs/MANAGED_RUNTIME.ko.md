# Managed Runtime 배포 계약

## 목적

AudioScoreTool packaged desktop은 사용자의 시스템 PATH, Homebrew, winget, pip, npm, uvx에 핵심 기능을 의존하지 않습니다.

대형 third-party runtime/model을 설치 파일 안에 직접 넣기 어려운 경우에는 앱 데이터 영역의 **managed component**로 설치하며, 설치 자체도 AudioScoreTool이 소유합니다.

## 신뢰 경계

- packaged mode는 번들된 `managed-component-catalog.json`만 신뢰합니다.
- packaged mode에서 `AST_COMPONENT_CATALOG` 외부 override는 무시합니다.
- artifact URL은 credential이 없는 HTTPS만 허용합니다.
- artifact는 catalog에 고정된 SHA-256과 일치해야 합니다.
- component archive의 절대경로, `..`, symlink/hardlink/device member를 거부합니다.
- 압축 해제 member 수와 총 uncompressed bytes에 상한을 둡니다.
- component executable은 managed install root 내부의 regular file만 인정합니다.
- packaged command resolution은 `state.json`에 등록되고 SHA-256이 검증된 managed tool만 허용합니다. 기존 `components/bin`의 미등록 파일과 system PATH는 실행할 수 없습니다.

## 설치 트랜잭션

1. artifact를 `.download-*` 임시 파일로 제한된 크기 내에서 수신
2. SHA-256 검증
3. `.staging-*` 디렉터리에 안전하게 압축 해제
4. tool path와 root containment 검증
5. versioned install directory로 atomic rename
6. `state.json`을 fsync 후 atomic replacement
7. 실패 시 staged/download artifact 제거
8. 기존 동일-version runtime 교체는 `installed/<component>/.previous-<token>`에 이전 설치를 격리한 뒤 `state.json`을 commit
9. 프로세스 강제 종료·전원 중단 이후 startup/setup recovery는 **커밋된 state의 tool SHA-256과 이전 설치 백업 모두를 재검증**합니다. 이전 state가 가리키는 실행 파일이 사라졌거나 변조된 경우, 해시가 일치하는 백업으로 원복합니다
10. 새 설치가 state와 일치하면 사용하지 않는 `.previous-*` 백업만 정리합니다. 백업 손상·state 손상·symlink·경로 이상은 임의 삭제하지 않고 보호하며, 관련 재설치도 차단합니다
11. 남은 `.download-*` / `.staging-*`를 정리하되 원복할 수 있는 `.previous-*`를 지우지 않습니다

`state.json`이 손상되면 앱은 component를 사용하지 않고 fail-closed 합니다.

## Catalog publication

catalog의 component entry는 platform/architecture 별 artifact를 명시합니다.

```json
{
  "schema": 1,
  "components": {
    "youtube_runtime": {
      "version": "...",
      "license": "...",
      "provenance": "fixed upstream release/build evidence",
      "upstream_revision": "reviewed-version-or-commit",
      "redistribution_status": "approved",
      "artifacts": {
        "windows-x86_64": {
          "url": "https://...",
          "sha256": "64 hex chars",
          "archive": "zip",
          "tools": {
            "yt-dlp": "bin/yt-dlp.exe",
            "deno": "bin/deno.exe",
            "ffmpeg": "bin/ffmpeg.exe",
            "ffprobe": "bin/ffprobe.exe"
          }
        }
      }
    }
  }
}
```

artifact를 실제로 게시하기 전까지 해당 platform entry는 비워 둡니다. **존재하지 않는 binary URL이나 검증하지 않은 license를 catalog에 가정해서 넣지 않습니다.** 위 JSON은 필수 필드 구조만 설명하는 예시이며 실제 게시·라이선스 승인 기록이 아닙니다.

### 설치 가능 여부와 재배포 승인 기준

Setup Center의 `catalog.published` 및 `auto_install`은 별도 릴리스 게이트 `check_publication(component, platform)`와 동일한 판정을 사용합니다. 버전과 다운로드 URL이 그럴듯하거나 `artifacts[platform]`이 빈 객체로 존재하는 것만으로는 설치 버튼을 노출하지 않습니다.

- 안전한 component/version, HTTPS URL, SHA-256, archive 종류, managed root 내부 tool 경로 검증
- `license`, `provenance`, 고정된 `upstream_revision`, `redistribution_status=approved`
- 구성요소별 필수 실행 명령: AMT(`mt3-infer`), YouTube(`yt-dlp`·`deno`·`ffmpeg`·`ffprobe`), OMR(`audiveris`). 실제 모델/배포 공급자 결정은 별도 승인 (#34)
- UI에 '재배포 승인 대기', '필수 실행 도구 구성 누락', '배포 파일 미게시' 등을 구분해 표시
- 수동으로 `POST /api/setup/install`을 호출해도 같은 승인을 통과하지 못하면 HTTP 409로 거부. 사용자는 임의 URL이나 checksum으로 카탈로그 승인을 우회할 수 없음

**중요:** `published=true`는 *카탈로그 메타데이터가 승인 기준을 충족했다*는 뜻이며, 실제 파일을 다운로드했거나 실행이 검증됐다는 뜻이 아닙니다. 실물 SHA-256 일치, 실행 파일 및 해당 의존성 확인, Windows/macOS clean-machine acceptance는 #29에 계속 남아 있습니다.

## Release gate

코드-level managed runtime gate:

- checksum mismatch가 기존 runtime을 교체하지 않음
- traversal/symlink archive 거부
- corrupt state fail-closed
- partial install recovery idempotent
- 반복 install soak 성공
- packaged mode catalog override 차단
- large subprocess output bounded
- subprocess timeout/cancel tree termination
- shell metacharacter가 argv로만 전달됨
- SQLite corruption이 자동 삭제/재초기화되지 않음
- concurrent DB updates soak 성공
- Windows/macOS/Linux packaged sidecar가 managed catalog/integrity policy를 실제 보고

실제 third-party runtime artifact publication은 각 artifact의 재배포 라이선스와 provenance를 확인한 뒤 수행합니다. 코드가 installer를 지원한다는 이유만으로 unpublished artifact를 `ready`로 보고하지 않습니다.

## Setup Center 배선 감사 (2026-11-05, PR #63)

이 항목은 설치/복구 UI와 백엔드 API의 **코드 연결 상태**를 기록합니다. 실제 바이너리 발행 및 상용 서비스 품질 확인이 아닙니다.

| 동작 | 호출 경로 | 설치 파일 검증/제약 |
|---|---|---|
| 구성요소 상태 조회 | `GET /api/setup/center` | 상태와 대상 OS/아키텍처 표시 |
| 설치·동일 구성요소 갱신 | `POST /api/setup/install` | 게시된 catalog artifact에만 사용자 클릭 제공, 서버에서 SHA-256·tool path 검증 |
| 앱 관리 구성요소 제거 | `POST /api/setup/remove` | 앱이 소유한 설치 디렉터리와 등록 상태를 확인 후 제거, 실패/중단 복구 지원 |
| 다운로드·설치 잔여물 복구 | `POST /api/setup/recover` | 임시 파일 정리, 동일 버전 재설치 중단의 SHA-256 검증 기반 이전 설치 원복, 중단된 removal 원복 및 불명확 백업 보존 |

- 설치 버튼은 trust policy에 따라 `catalog.published == true`일 때만 노출하고, 클라이언트는 주소·해시·경로를 제공하지 않습니다.
- `managed_status.ready`는 실제 설치 파일의 무결성이 확인된 상태이며, 관련 실행 명령의 서비스 준비 상태(`component.ready`)와 구분됩니다.
- 데스크톱 Playwright 테스트는 공개 catalog의 설치 가능 여부를 모의 응답으로 확인합니다. 이 테스트가 실제 배포 파일을 발행하거나 라이선스를 승인하지는 않습니다.
- **현시점 번들 catalog의 다섯 component 모두 `artifacts: {}`** 입니다. 따라서 Windows/macOS의 실사용 AMT/YouTube/OMR 런타임을 준비했다고 선언할 수 없습니다. 게시 아티팩트의 라이선스·checksum·패키징을 확인하는 #29와 정식 서명/업데이트 인수시험 #22는 별도로 필요합니다.
