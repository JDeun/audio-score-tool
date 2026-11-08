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

패키지된 백엔드의 실제 진입점은 `scripts/backend_entry.py → audio_score_tool.api.run()`입니다. 이 시작 함수는 Song/Job 복구에 이어 `recover_component_staging()`을 **서버 수신 시작 전** 실행하고, 결과를 `GET /api/startup-diagnostics`의 `recovery.managed_components`에 기록합니다. 복구에 실패하면 오류 유형을 진단에 보존하되 MusicXML/MIDI/PDF 내장 편집 기능은 계속 제공하며, 등록되지 않거나 checksum이 맞지 않는 외부 런타임 실행은 계속 차단합니다. Setup Center의 `POST /api/setup/recover`는 사용자가 요청하는 독립적인 재시도 경로입니다.

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


## 2026-11-08 — 이름이 겹치는 실행 도구의 소유 컴포넌트 분리 (#29)

`youtube_runtime`과 `audio_validation`은 모두 FFmpeg를 포함할 수 있습니다. 기존 상태 파일 순회 순서에 의존하면 YouTube가 `audio_validation`의 FFmpeg를 선택하여 `yt-dlp`·`deno`·`ffmpeg`·`ffprobe`의 동일 번들 계약을 깨뜨릴 수 있었습니다.

이제 packaged YouTube 실행 경로는 네 도구를 모두 **`youtube_runtime`이 소유한, 현재 SHA-256 검증된 경로**로 조회합니다. 다른 컴포넌트의 실행 파일은 빠진 YouTube 도구를 대체할 수 없습니다. 일반적인 FFmpeg 조회도 YouTube 번들을 우선 선택하지만, 명시적으로 지정된 별도 컴포넌트의 정상 실행 경로까지 차단하지 않습니다. 관리 상태의 `root`는 `installed/<component>/<version>`과 일치해야 하고, 다른 컴포넌트의 경로를 소유물로 위장한 기록은 거부합니다.

검증은 로컬 합성 ZIP과 Setup Center/YouTube API 회귀 테스트로 수행합니다. 실제 배포 가능한 아티팩트가 카탈로그에 게시됐다는 뜻이 아니므로, `managed-component-catalog.json`의 비어 있는 `artifacts`는 그대로 두며 배포 승인·라이선스 게이트는 #29에 남습니다.

## 이전 버전으로 명시적 롤백 (#29, 2026-11-08)

동일 버전의 중단된 재설치 자동 복구와 **서로 다른 버전 간 롤백**은 구별합니다.

- `1 → 2` 업그레이드: 기존 버전 1의 앱 소유 설치 경로, 등록 실행 파일 상대 경로 및 SHA-256·archive hash를 검증하고, 새 버전의 `state.json`에 **한 단계만** `rollback` 기록으로 보존합니다. 출처 불명·변조된 이전 버전은 롤백 대상에 등록하지 않습니다.
- 업그레이드 파일은 기존과 마찬가지로 새 버전 디렉터리에 준비한 뒤 원자적으로 `state.json`을 교체합니다. 설치 실패·SHA mismatch·state write 중단 시 기존 활성 버전과 이전 롤백 기록은 바뀌지 않습니다.
- Setup Center의 `managed_status.rollback.available`은 **현재 이전 버전의 실행 파일 해시를 재검증했을 때만** `true`가 됩니다. POST `/api/setup/rollback`은 명시적인 사용자 동작이며 검증된 이전 버전으로 `state.json`의 활성 포인터를 원자적으로 전환합니다. 네트워크나 외부 PATH 호출을 하지 않습니다.
- 사용 중인 최신 버전 실행 파일이 손상돼도 이전 버전의 SHA-256이 일치하면 롤백할 수 있습니다. 반대로 이전 버전 자체가 변조되거나 경로가 symlink/소유 범위 밖이면 UI는 롤백을 제공하지 않고 API도 HTTP 409로 차단합니다.
- 롤백은 성공 후 더 최신 버전을 자동 재활성화하지 않습니다. 변경 전의 실행 파일은 삭제하지 않지만 `state.json`에 등록되지 않아 packaged 모드에서 사용되지 않습니다. 이전 버전 디렉터리는 조사·재설치 또는 앱 관리 제거 작업 시 처리합니다. **자동 장기 보관/정리나 임의 다단계 롤백은 제공하지 않습니다.**
- SHA 검증은 **등록된 실행 명령의 바이트**를 확인하는 현재 관리형 설치 계약입니다. JRE/모델 데이터 전체 파일의 재검증, 런타임 실제 실행 검증 및 플랫폼별 패키지 출고 승인은 별도 #29 gate입니다.
- 아직 승인·게시되지 않은 런타임의 설치 버튼이 없어도, 이미 설치된 유효한 이전 버전이 있으면 롤백 경로는 독립적으로 사용할 수 있습니다.


## 전체 런타임 파일 SHA-256 검증 (#29, 2026-11-08)

이전의 등록 실행 파일만 해시하는 정책에서는 Audiveris의 **내장 JVM**, AMT **모델 가중치**, 리소스 또는 동적 라이브러리를 설치 후 변경해도 런처 파일이 정상인 것처럼 표시될 수 있었습니다.

- 관리형 ZIP/TAR/RAW를 완전히 해제하고 등록된 명령의 실행 권한을 확정한 다음 **모든 일반 파일**의 상대 경로와 SHA-256을 `state.json`의 `payload_files` 필드에 기록합니다. 전송 아카이브 자체의 SHA-256도 계속 별도 보존합니다.
- 설치·상태 확인·실행 파일 등록 해석·중단된 동일 버전 교체 복구·업그레이드 및 **이전 버전 롤백**은 해당 파일 목록과 실제 설치 디렉터리를 다시 확인합니다. 파일 누락, 예상하지 못한 새 파일, 바이트 변조, 심볼릭 링크·장치 파일·파이프 및 안전하지 않은 경로는 모두 사용 불가 상태로 처리합니다.
- 롤백 스냅샷은 실행 파일뿐 아니라 **직전 세대의 `payload_files`**도 유지합니다. 내장 Java 파일 또는 checkpoint 중 하나라도 손상됐으면 이전 버전은 자동 복원 대상으로 제시하지 않습니다.
- **구버전 상태 파일 호환성:** 과거 `payload_files`가 없는 구성요소는 읽을 수 있지만 `payload-manifest-missing`으로 안전하게 비활성화하며, 출처가 검증된 아카이브를 다시 설치해 전체 파일 인벤토리를 생성해야 합니다. 알 수 없는 기존 바이너리를 단순히 재해시해 새 신뢰 상태로 자동 승격하지 않습니다.
- 대용량 모델을 매 요청마다 다시 읽지 않도록, 최초 SHA-256 대조에 성공한 **현재 프로세스 안에서만** 각 파일의 경로·장치·inode·크기·mode·mtime·ctime을 검사하여 변화가 없는 경우 이전 검증을 재사용합니다. 파일 변화·새 파일·삭제·프로세스 재시작 시에는 재검증합니다. 파일 변경 정보가 바뀌지 않는 특권적 조작이나 검사 시점 이후 변경까지 방지하는 코드 서명 기능은 아닙니다.
- 검증 범위는 **설치된 component 디렉터리의 일반 파일 전체**입니다. 실행 중 앱이 해당 디렉터리를 임의 변경하면 검증 실패가 발생하므로 모델 캐시·로그 등의 가변 데이터는 별도 app-data 디렉터리로 분리해야 합니다.
- 이는 실제 게시 파일의 법적 승인, 가중치의 상업용 사용권, 깨끗한 Windows/macOS 설치 성공, 코드 서명 및 런타임 정상 작동을 대신하지 않습니다. 승인 전 `artifacts: {}` 상태를 유지하고 #29는 미완료로 둡니다.


## 별도 원격 바이트·제3자 라이선스 승인 기록 (#29, 2026-11-08)

카탈로그에 `redistribution_status=approved`와 정상 형태의 HTTPS URL·SHA-256이 있어도 **이것만으로는 설치할 수 없습니다**. 동일한 sidecar에 번들된 `managed-release-approvals.json`에서 정확한 플랫폼·전체 항목 해시와 다운로드 검증 보고서, 별도의 사람에 의한 라이선스/소스 제공 위치 검토가 확인돼야 Setup Center와 API에 설치가 허용됩니다. 기록 누락은 `approval-receipt-missing`, 변경된 카탈로그는 `approval-catalog-drift`, 실제 게시 바이트 증빙 누락·불일치는 `remote-evidence-missing` / `remote-evidence-mismatch`, 라이선스 검토 누락은 `license-review-missing` 등으로 fail-closed 처리합니다.

이 승인 기록은 패키지의 로컬 메타데이터이므로 독립된 암호학적 서명을 대체하지 않습니다. 브랜치 보호 및 실제 검토자의 승인, 모델 상업 사용권 판단, Windows/macOS 클린 머신 인수시험은 별도입니다. 자세한 절차는 [MANAGED_RELEASE_APPROVALS.ko.md](MANAGED_RELEASE_APPROVALS.ko.md)를 참조하세요.


## 관리형 MT3-Infer 체크포인트 실행 경로 (#29, 2026-11-08)

이전 구현은 `mt3-infer` 실행 파일만 앱 관리형 경로에서 검사했지만, 상위 모델 라이브러리가 기본 체크포인트 디렉터리 또는 외부 캐시에서 모델을 자동 다운로드할 가능성은 차단하지 못했습니다.

패키지 실행 `AST_PACKAGED=1`에서는 `transcription_engine`의 **검증된 전체 아카이브** 안에 모델별 가중치가 있어야 채보 엔진을 준비 완료로 표시합니다. 필수 번들 구조는 다음과 같습니다.

```text
installed/transcription_engine/<version>/
  bin/mt3-infer[.exe]
  checkpoints/mr_mt3/<model-weight>.safetensors | .pt | .pth | .ckpt | .bin
  checkpoints/yourmt3/<model-weight>...
```

두 모델을 모두 제공할 필요는 없지만, 실제 선택된 `Settings.mt3_model`의 모델 디렉터리에 **검증된 비어 있지 않은 체크포인트 파일**이 하나 이상 있어야 합니다. 런타임은 구성요소 전체 SHA-256을 검사한 뒤 이 디렉터리만 `MT3_CHECKPOINT_DIR`에 전달합니다. 패키지 하위 프로세스에는 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`을 명시적으로 주입하여 사용자 `HOME`/기본 캐시로 모델을 다운받거나 시스템 파일을 빌려오지 않게 합니다. 개발 모드의 기존 환경변수/설치 경로 동작은 변경하지 않습니다.

체크포인트가 누락·변조되거나 선택한 모델과 불일치하면 엔진 `ready=false`이고 Setup Center의 관리형 런타임 복구 안내가 유지되며, 추론 프로세스는 시작하지 않습니다. 모델이 실제로 올바른 내용을 가진 채보 가중치인지, 해당 배포·상업 사용권이 있는지 및 원본 오디오에서 정확하게 추론하는지는 **추가 필수 증빙**입니다. 파일명과 정상 SHA 만으로 #29의 상용 AMT 후보가 승인되는 것은 아닙니다.
