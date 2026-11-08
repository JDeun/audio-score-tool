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


## 실제 모델 체크포인트를 설치한 관리형 MT3 추론 검토 (#29, 2026-11-08)

`.github/workflows/tier2-actual-models.yml`의 각 MR-MT3/YourMT3 CPU 검증은 공식 `mt3-infer[torch]==0.2.0` 런타임으로 먼저 실제 추론에 성공한 후, `MT3_CHECKPOINT_DIR`에 내려받은 **같은 실제 체크포인트 파일**을 별도의 임시 ZIP에 넣고 앱의 `install_component_artifact()`로 설치해 다시 추론합니다. 관리형 버전별 SHA-256 전체 파일 검증과 `registered_managed_tool`이 연결된 뒤 `AST_PACKAGED=1`, `PATH=\"\"`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`로 실행합니다. 실행 후에도 설치된 불변 파일의 해시 검증에 통과해야 성공합니다.

검증 종료 시 `managed-real-checkpoint.pending.json`에는 각 체크포인트 상대 경로/해시, 임시 ZIP SHA-256, 실제 추론의 MIDI/MusicXML 해시 및 note count만 기록합니다. **실제 체크포인트 바이트와 관리형 ZIP은 GitHub Actions artifact로 업로드하지 않습니다.**

**제약:** 이 Linux CI 전용 QA는 기존 러너의 Python과 기설치 `mt3-infer` 진입점 스크립트를 ZIP 안에 복사해서 사용합니다. 따라서 호스트 Python/라이브러리 없이 구동하는 frozen Windows/macOS 채보 런타임을 증명하지 않습니다. 결과에도 `qa_launcher_requires_host_python=true`, `clean_windows_macos_verified=false`, `model_redistribution_rights_verified=false`를 명시합니다. 모델 weight 정확한 권리·동일한 checkpoint 내용과 상용 품질 선정(#34), Windows/macOS self-contained executable 패키징 및 #29의 실제 게시/법적 승인은 계속 별도 필요합니다.


### MT3-Infer `--no-download` 명시적 강제

실제 CPU 모델 CI가 제공하는 `mt3-infer transcribe --help`에서 `--no-download` 옵션을 확인했습니다. 패키지 모드의 채보 실행은 기존 `MT3_CHECKPOINT_DIR`의 앱 관리형 절대 경로 및 Hugging Face/Transformers offline 환경변수뿐 아니라 **CLI의 `--no-download`**도 반드시 전달합니다. 체크포인트가 누락된 경우 외부 다운로더로 대체할 수 없으며, 개발 모드에서는 기존 upstream 동작을 유지합니다. Windows/macOS의 독립 실행형 frozen runtime과 상업용 가중치 배포 권리는 여전히 별도 #29 출고 조건입니다.

### Windows 패키지 MT3 CLI의 UTF-8 출력 (#29)

공식 MT3-Infer CLI는 채보 진행 및 모델 목록에 체크표시·화살표 등 유니코드를 출력합니다. Windows에서 백엔드가 자식 프로세스 stdout을 파일로 리다이렉트할 때 기존 사용자 코드 페이지(cp1252 등)를 사용하면 `UnicodeEncodeError`로 정상 명령이 실패할 수 있습니다. 앱의 **패키지 모드 MT3 채보 실행**은 `PYTHONIOENCODING=utf-8`과 `PYTHONUTF8=1`을 자식 프로세스에 명시적으로 전달해 결과 인코딩을 표준화합니다. 개발 모드의 사용자 Python 환경은 변경하지 않습니다. 네이티브 얼리 QA 실행기에도 같은 환경을 적용해 실물 빌드에서 검증합니다.

PyInstaller frozen 실행 파일의 Python 인터프리터는 일반 Python과 달리 `PYTHONIOENCODING`·`PYTHONUTF8` 환경 설정을 따르지 않을 수 있습니다. 따라서 실제 Windows 독립 실행형 빌드는 `scripts/mt3_frozen_entry.py`에서 stdout/stderr를 직접 UTF-8로 설정하며, 빈 PATH와 오프라인 상태의 네이티브 실행 시험으로 이를 검증합니다. 이 단계는 체크포인트 포함·실제 모델 추론을 대신하지 않습니다.

## Windows/macOS MT3 PyInstaller 독립 실행형 기동 QA (#29, 2026-11-08)

이전의 Linux 실물 체크포인트 추론 시험은 러너의 Python/Torch 환경에서 `mt3-infer` 진입점 스크립트를 실행하므로 Windows/macOS 사용자 설치본을 증명하지 못합니다. 새로운 `.github/workflows/mt3-frozen-native-review.yml`은 해당 OS의 고정 Python 3.11 빌더에서 **MT3-Infer 0.2.0, PyTorch/torchaudio 2.7.1, Transformers 4.57.6, PyInstaller 6.17.0**을 설치하고, `mt3_infer.cli`와 MR-MT3 동적 T5 어댑터 및 모델 registry YAML을 포함하는 실제 **onefile 네이티브 실행 파일**을 빌드합니다.

검증은 파일명만 보고 완료로 판단하지 않습니다. 빌드된 바이너리를 임시 ZIP에 넣고 **제품의 `install_component_artifact()`**를 호출하여 아카이브·전체 파일 SHA-256을 확인합니다. `AST_PACKAGED=1`, `PATH=\"\"` 하에서 앱 관리형 등록 실행 파일을 사용해 `--version`, `list`, `transcribe --help`를 실행하고, `--no-download`로 모델이 없는 경우 **체크포인트 미존재 때문에** 실패하는지 확인합니다. 단순한 Torch/동적 import 오류는 성공으로 인정하지 않습니다.

출력은 `MT3-FROZEN-NATIVE-QA-<target>.pending.json`만 공개 CI 아티팩트로 보존합니다. 이 증빙에는 빌드 라이브러리 버전, 네이티브 실행 파일과 ZIP 해시, 실제 앱 관리형 등록/기동 결과가 포함됩니다. **실제 exe/onefile 바이너리·모델 가중치·ZIP은 업로드하지 않습니다.** Python이 CI 빌더에는 필요하지만, 실행 시험은 시스템 Python/개발 도구 PATH를 비우고 진행합니다.

이 작업은 **MR-MT3 한 모델 어댑터의 기동과 모델 다운로드 차단에 한정**되며, 실제 MR-MT3 가중치를 포함하거나 해당 바이너리로 악보 채보를 완료한 시험은 아닙니다. YourMT3의 별도 Transformers 버전, 모델·서드파티 라이선스/상업용 배포권, 앱 설치 이후 Windows/macOS 클린 머신 인수시험, 코드 서명·공증(#22)은 별도입니다. 정식 배포 카탈로그 및 승인 기록은 빈 상태로 유지하고 #29를 닫지 않습니다.

## Windows/macOS 실제 frozen MR-MT3 모델 추론 QA (#29, pending)

이제 `.github/workflows/mt3-frozen-native-review.yml`은 두 실제 네이티브 러너(Windows x86_64, macOS arm64)에서 MT3-Infer v0.2.0의 **실제 MR-MT3 `mt3.pth`**를 각 러너 임시 디렉터리에 내려받고 정확한 SHA-256 `b8a3807ed265059abd25ad7f68142c06c35e8f6144dcaa45bd55946a3745398f`를 **두 차례 검증**하도록 구성합니다. 출처는 해당 버전 checkpoint registry의 `gudgud1014/MR-MT3` 리비전 미고정 URL이며, SHA가 조금이라도 다르면 inference를 수행하지 않습니다. 오래된 `torch.load(weights_only=False)` 포맷에 대한 임의 파일 실행은 금지합니다.

검증기는 먼저 frozen CLI만 보유한 초기 구성요소를 설치하고 체크포인트 미존재·다운로드 차단을 확인합니다. 이후 같은 PyInstaller 실행 파일과 검증된 실제 가중치를 담은 **러너 로컬 임시 ZIP**으로 제품의 `install_component_artifact()` 업데이트를 진행합니다. `AST_PACKAGED=1`, `PATH=""`, 오프라인 Hugging Face 환경에서 **제품의 `MT3InferEngine.transcribe()`**를 호출해 프로젝트 자체 합성 16초 음원으로 MIDI 및 MusicXML을 생성하고, music21로 양쪽 파일을 다시 읽어 실제 음표·파트가 존재하는지 확인합니다. 실행 후에도 전체 설치 payload 해시가 유지돼야 통과합니다. CPU 처리이며, 벤치마크 정확도·음악적 품질의 보증은 아닙니다.

업로드되는 파일은 버전·입출력 및 체크포인트 SHA-256, 음표 수 등을 기록한 `*.pending.json` 하나뿐입니다. **실제 모델 가중치, 실행 파일, ZIP, MIDI, MusicXML은 공개 업로드하지 않습니다.** 다음 조건은 여전히 미충족입니다: 원본 revision/재배포 및 상업 사용권·외부 notice/source 승인, 실사용 HTTPS 아티팩트, 모델별 품질 기준(#34), Windows/macOS 앱 인스톨러 전체 설치·업데이트 및 OS 독립 clean-machine 검증, 서명·공증(#22). `managed-component-catalog.json`의 `artifacts: {}`와 `managed-release-approvals.json`의 `approvals: {}`는 그대로 둡니다. 네이티브 QA가 성공하기 전에는 성공했다고 문서화하지 않습니다.

## 실제 MR-MT3 네이티브 ZIP의 로컬 후보 보존 (#29)

`scripts/verify_mt3_frozen_native.py`는 Windows x86_64/macOS arm64 실제 체크포인트 검증·관리형 설치·채보·MusicXML 확인을 완료한 후, 기본 동작에서는 모든 바이너리/모델 ZIP을 임시 공간에서 삭제합니다. 정식 출고 검토자가 그 **동일하게 검증된 ZIP 바이트**를 후속 후보 검토에 사용할 필요가 있을 때만 선택적 `--private-candidate-dir` 인자를 지원합니다.

- 이 인자는 체크포인트가 없는 기동 검증에서는 거부하며, 사전에 만들어 둔 **Git 저장소 외부의 일반 디렉터리**만 허용합니다. 모든 경로 조상의 심볼릭 링크와 기존 ZIP 파일 덮어쓰기를 거부합니다.
- `GITHUB_ACTIONS=true`에서는 무조건 거부하므로 기존 공개 저장소 CI가 가중치나 실행 바이너리를 실수로 보존/업로드하지 않습니다. CI는 기존처럼 증빙 `*.pending.json`만 보관합니다.
- 실제 네이티브 채보와 전체 payload 검증, 원본 ZIP SHA-256 재검증 **이후** 사설 폴더에 임시 파일을 쓰고 SHA-256을 다시 확인한 뒤 원자적 hard-link 생성으로 결과 이름을 등록합니다. POSIX 파일 권한은 owner-only입니다. 파일이 이미 있거나 부분 복사·무결성 문제가 발생하면 기존 파일을 변경하지 않고 임시 파일을 정리합니다.
- 파일명은 `MT3-MRMT3-<target>-UNAPPROVED.zip`입니다. 내부에는 frozen `mt3-infer`, SHA-256이 고정된 `checkpoints/mr_mt3/mt3.pth`, `pending` provenance만 있습니다. **상업 사용/재배포 권한이 승인됐다는 의미가 아니므로 어떤 공개 저장소, GitHub artifact, 클라우드 배포 URL에도 자동 게시하지 않습니다.**

운영자가 승인 대기 자료를 오프라인으로 검토할 때만 다음처럼 실행합니다.

```bash
# 대상 OS의 고정 Python/PyInstaller/torch/MT3-Infer 빌더 환경에서 실행
# 저장 경로와 체크포인트는 git checkout 밖에 사전 준비
python scripts/verify_mt3_frozen_native.py \
  --target macos-aarch64 \
  --checkpoint-dir /private/reviewed-mrmt3-checkpoints \
  --private-candidate-dir /private/release-review \
  --output /private/release-review/mt3-native.pending.json
```

Windows에서는 `--target windows-x86_64`, Windows 전용 사설 절대 경로를 사용합니다. 정확한 빌더 의존성은 `.github/workflows/mt3-frozen-native-review.yml`에서 확인합니다. 이 출력은 임의 외부 배포 권한을 대체하지 않으며, 유효한 `--url`/라이선스/업스트림 revision과 실제 소스·고지를 따로 검토한 다음 `prepare_managed_artifact_candidate.py` 및 `verify_managed_artifact_publication.py`의 기존 출고 절차로 진행합니다. 최종 승인은 독립적인 담당자의 서명/라이선스 판단과 clean-machine 테스트까지 요구합니다.

## v1 게시된 관리형 런타임의 실제 packaged API 인수시험 (#29)

기존 `Desktop Packages`의 `--require-managed-delivery` 검사는 앱 관리형 AMT/YouTube/Audiveris ZIP을 설치하고 체크섬·등록상태를 확인했지만, YouTube 네이티브 CLI 외에는 **실제 채보 Job/MIDI/MusicXML이나 Audiveris JRE 실행**을 확인하지 않았습니다. 승인·출고된 안정형 Windows x86_64/macOS ARM64 runtime에서만 실행되는 동일 옵션의 수동 QA/v1 태그 경로를 보강했습니다.

`scripts/smoke_packaged_sidecar.py --require-managed-delivery`는 이제 **관리형 설치가 승인된 플랫폼**에서 아래를 추가로 검사합니다.

1. 독립 임시 `AST_DATA_DIR`·`AST_COMPONENT_DIR`에 패키지 백엔드 사이드카를 실행하고, **사이드카의 `PATH=""`**로 시스템 Python/FFmpeg/Java/yt-dlp 우회 사용을 제한합니다. 기존 일반 unsigned/PR 패키지 smoke는 외부 모델 게시를 요구하지 않습니다.
2. 기존 게시 승인/원격 아카이브/전체 파일 무결성 검증과 YouTube 4도구 버전 기동, 설치 후 Setup Center 상태 재조회가 통과해야 다음 단계로 진행합니다.
3. 동일한 **패키지 백엔드의 인증 HTTP API**에서 `/api/engines`를 실제로 읽고 테스트 전용 임시 설정을 상용 모드 MT3-Infer로 변경합니다. 시험 대상 모델은 제품에서 선택된 `mt3_model`을 사용하며, 의도적으로 특정 리뷰 모델만 시험할 때는 `--managed-mt3-model mr_mt3` 또는 `yourmt3`로 명시할 수 있습니다. 이것은 상업용 모델 라이선스 승인이 아닙니다.
4. 프로젝트가 직접 생성한 16초 다성 WAV를 `POST /api/jobs`로 올려 **패키지 백엔드 → 실제 앱 관리형 MT3 실행 파일 → 검증된 가중치 → 결과 처리 파이프라인**을 통과한 `done` 상태를 기다립니다. 실패·취소·타임아웃은 거부하며, 타임아웃 시 해당 작업을 취소하도록 요청합니다. `GET /api/jobs/{id}/files/{midi,musicxml}`에서 각각 MIDI **실제 note-on 이벤트** 및 MusicXML **유효한 음표·파트**를 표준 라이브러리로 검사합니다. 호스트 Python의 추론 라이브러리나 외부 음악 파일은 필요하지 않습니다.
5. 설치된 `audiveris` 관리형 실행 파일이 `GET /api/omr/status`에 정확히 바인딩됐는지 확인하고, 해당 배포판의 **번들된 Java**를 시스템 PATH/JAVA_HOME 없이 `-version`으로 기동합니다. 이어서 직접 생성한 12마디 MusicXML을 **패키지 백엔드의 `/api/import/notation`**으로 올려 Song으로 등록하고, **패키지의 `/api/songs/{id}/export-to`**에서 Verovio/fpdf2로 실제 PDF를 조판합니다. 그 PDF를 **`POST /api/import/score`**로 다시 업로드해 관리형 Audiveris OMR Job 완료·인식된 pitched note 4개 이상·MusicXML 파일과 canonical SQLite Song을 확인한 뒤, 해당 Song의 MusicXML/PDF/MIDI/파트 최종 출판을 재검증합니다. 단순 별도 개발용 Python renderer/가짜 OMR 완료로 통과하지 않습니다.
6. 테스트 입력과 SQLite, 출력은 전용 임시 앱 데이터에 보관하고 종료 후 삭제합니다. **실제 PDF OMR 기능 인수시험이 성공해도** 이것이 법적 재배포 허가, OMR 인식 정확도 벤치마크, Windows/macOS의 깨끗한 사용자 OS에 설치한 Tauri 데스크톱 UI/업데이트·서명·공증 acceptance를 대신하지는 않습니다.

기존 관리형 카탈로그 `artifacts: {}` 및 출고 승인 `approvals: {}`인 현재에는 위 고비용 테스트가 **합법적인 실제 출고 URL을 마련하기 전에는 통과할 수 없도록** 설계되었습니다. 이 기능 때문에 CI에 모델 바이너리를 추가 업로드하거나 라이선스/게시를 자동 승인하지 않습니다.

```bash
# 이미 심사·게시된 Windows/macOS 런타임이 있는 수동 QA 환경에서만 실행
uv run --frozen --extra desktop python scripts/smoke_packaged_sidecar.py \
  --require-managed-delivery \
  --managed-mt3-model mr_mt3
```

`desktop-packages.yml`의 수동 `require_managed_delivery` 입력 및 v1 태그 인수시험은 새로운 경로를 포함합니다. 별도의 실제 모델 품질·사용자 수정 시간 선정은 #34, 유효한 코드 서명·공증·업데이터 인수시험은 #22에서 처리합니다.

## 승인된 YouTube 영상의 실제 packaged 입력→악보 인수시험 (#29)

이제 수동 `Desktop Packages --require-managed-delivery` 및 `v1*` 태그 배포의 **전체 관리형 기능 인수시험**에는 실제 YouTube URL의 채보 경로도 포함됩니다. 사전에 게시·승인된 Windows/macOS managed `yt-dlp`/Deno/FFmpeg/ffprobe 및 AMT 체크포인트가 필요하며, 출고 검토자가 **소유하거나 적법하게 QA 처리 허가를 받은 짧은 공개 영상 한 개**를 직접 제공해야 합니다.

**기본 테스트 영상·외부 음악 링크는 없습니다.** CI가 임의로 제3자 음악을 다운로드하지 않도록, 별도 사람이 확인한 `AST_YOUTUBE_QA_RECEIPT_JSON`이 없으면 사이드카 기동/관리형 구성요소 다운로드 **이전**에 오류로 종료합니다. 검토 기록의 필드는 다음과 같습니다.

```json
{
  "schema": 1,
  "purpose": "owned-youtube-automated-release-qa-v1",
  "source_url": "https://www.youtube.com/watch?v=<REPLACE_WITH_OWNED_11_CHAR_VIDEO_ID>",
  "video_id": "<REPLACE_WITH_OWNED_11_CHAR_VIDEO_ID>",
  "rights_basis": "original-owned",
  "authorized_for_automated_download_and_transcription": true,
  "may_publish_source_media_as_ci_artifact": false,
  "redistribution_status": "pending",
  "reviewer": "<YOUR_RELEASE_REVIEWER>",
  "rights_evidence_reference": "<YOUR_INTERNAL_OWNERSHIP_OR_WRITTEN_LICENSE_REFERENCE>",
  "reviewed_at": "2026-11-08T09:00:00+00:00",
  "max_duration_seconds": 60
}
```

위 값들은 *형식 예시*이며 유효한 영상·승인 증빙이 아닙니다. `rights_basis`는 `original-owned` 또는 `separately-licensed-for-qa` 중 하나만 허용하며, 검토 기준일은 시간대가 명시되고 180일 이내여야 합니다. URL은 YouTube 단일 영상에 대한 정확한 `https://www.youtube.com/watch?v=<11자리 ID>`만 허용합니다. `max_duration_seconds`는 5~180초이며 실제 yt-dlp metadata의 영상 길이가 이를 초과하거나 조회 불가능하면 테스트를 중단합니다. 영상의 소유/사용권은 이 도구가 **법적으로 독립 검증하는 것이 아니므로**, 출고 담당자가 실제 법적 권리를 따로 확인해야 합니다.

GitHub Actions의 운영자 설정 **Repository Variable `YOUTUBE_QA_SOURCE_REVIEW_JSON`**에 검토된 JSON을 등록하면, `.github/workflows/desktop-packages.yml`이 **수동 관리형 배포 검증 또는 v1 태그 실행에서만** 이 값을 QA 런처의 `AST_YOUTUBE_QA_RECEIPT_JSON`에 전달합니다. 패키지 백엔드 자식 프로세스에는 검토 JSON 원문을 전달하지 않고, API의 통상적인 인증된 JSON 요청에 영상 URL만 전달합니다. 로컬 수동 QA에서는 실행 환경에 `AST_YOUTUBE_QA_RECEIPT_JSON`을 직접 설정할 수 있습니다. 민감한 소유권 문서·원본 영상·음원·인증 토큰은 저장소나 CI 아티팩트에 업로드하지 않습니다.

**실제 전체 검증:** `/api/sources/youtube/status`로 관리형 네 도구 준비 확인 → 인증 `POST /api/sources/youtube/inspect`로 해당 영상 ID/길이 대조 → `POST /api/jobs/youtube`에 명시적으로 `authorized=true` 제출 → 실제 `yt-dlp`/Deno/FFmpeg 입력·MT3 AMT 완료 → MIME이 아닌 **MIDI note-on/MusicXML pitched notes** 검사 → `GET /api/songs`에서 `source_kind=youtube`인 canonical Song이 정확히 하나 기록됐는지 확인합니다. 관련 `source_kind`는 이제 JobStore의 명시적인 SQLite 컬럼으로 지속 저장하며, 영상 제목에 `.mp3`처럼 확장자가 있어도 로컬 입력으로 오분류되지 않습니다. 구버전 Job은 `NULL`로 유지하고 추정으로 원본 권리를 생성하지 않습니다.

이 경로의 성공은 **실제 허가된 영상에 대한 제품 입력 기능**을 확인하는 것이지 YouTube 서비스 약관, 모델/바이너리 상용 재배포 라이선스, 독립적인 저작권 승인, clean-machine GUI 설치·업데이트, 음악 정확도(#34)를 통과했다는 뜻이 아닙니다. 출시 후보 구성요소 카탈로그 `artifacts: {}` 및 승인 기록 `approvals: {}`가 비어 있는 동안에도 자동 실행/출시 승인은 금지됩니다.

## 게시된 모델과 데스크톱 기본 선택 연결 (#29)

관리형 배포가 실제로 승인되기 전에는 기존 source/development 모델 선택을 유지하며, 미게시 MR-MT3를 자동 준비 완료로 표시하지 않습니다. `AST_PACKAGED=1`에서 해당 플랫폼 `transcription_engine`이 **독립 승인 기록까지 통과하여 게시된 경우에만**, `model_identity.model_key=mr_mt3`를 새 설치의 AMT 기본 모델로 채택합니다. 개인 모드 새 설치에서도 제공되지 않는 MuScriptor 대신 게시된 MT3를 기본 선택합니다. 과거 설정에 YourMT3가 남아 있더라도 지원되지 않는 모델 파일을 실행하려 하지 않고 승인된 모델을 유효 선택으로 사용합니다(사용자 저장 파일 자체는 임의 수정하지 않음). 배포판 UI는 미포함 모델 선택을 비활성화하고 API는 직접 잘못된 요청을 HTTP 422로 거부합니다.

이 기본값 배선은 게시 승인·SHA/서명·실제 추론 품질의 **대체가 아닙니다**. `managed_mt3_model` API 값이 `null`이면 독립 승인된 릴리스 모델이 없다는 의미입니다. 다음 단계에서는 실제 Windows/macOS 승인 아티팩트로 설정→설치→음원 채보·출력까지 검증해야 합니다.
