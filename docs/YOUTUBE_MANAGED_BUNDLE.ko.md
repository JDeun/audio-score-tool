# YouTube 관리형 런타임 후보 조립 (Windows x86_64 / macOS arm64)

## 범위와 보안 경계

YouTube 가져오기 기능은 `yt-dlp`, `deno`, `ffmpeg`, `ffprobe` 네 개의 앱 관리형 도구가 필요합니다. 이 문서는 #29의 **배포 전 후보 아카이브 조립**만 다룹니다. 실제 다운로드·라이선스 승인·모델 성능·원본 콘텐츠 권리는 별개입니다.

`scripts/assemble_youtube_runtime_candidate.py`는 사용자가 이미 소유한 **로컬 바이너리**와 출처·라이선스 고지·FFmpeg 빌드 기록을 입력받아, 재현 가능한 ZIP과 `.pending.json` 증빙을 만듭니다.

- 지원 출력: `windows-x86_64` / `macos-aarch64`.
- Windows는 PE/AMD64, macOS는 thin ARM64 또는 ARM64 slice를 포함한 universal Mach-O 헤더가 필수입니다. **이는 형식·아키텍처 확인일 뿐 실행/서명 검증이 아닙니다.**
- 네 파일을 플랫폼별 동일한 `bin/` 폴더에 배치합니다. 따라서 packaged `--js-runtimes deno:/.../bin/deno` 및 `--ffmpeg-location /.../bin` 계약과 일치합니다.
- 각 source 파일은 미리 고정된 SHA-256과 비교하고, ZIP 작성 중 바뀌는 경우에도 거부합니다.
- 원본 도구의 license notice 네 개와 FFmpeg의 빌드 설정 증빙을 아카이브에 함께 기록합니다.
- FFmpeg `--enable-nonfree`는 거부합니다. `--enable-gpl` 사용 시 FFmpeg/ffprobe의 라이선스를 GPL로 명시해야 합니다. **플래그 검사 자체가 재배포 적법성을 승인하지는 않습니다.**
- CLI는 바이너리를 실행·다운로드하지 않고, 공식 `managed_components.py`를 격리된 임시 경로에서 호출해 ZIP 설치·무결성 검사만 리허설합니다.
- **yt-dlp/Deno 공식 원본 확인서도 필수**입니다. `verify_youtube_official_sources.py`가 생성한 `SOURCE-EVIDENCE.pending.json`을 조립 입력에 지정하며, 해당 파일이 보관된 디렉터리의 두 실행 파일, commit-tracked 릴리스 자산 pin(태그/URL/크기/SHA), 실제 추출 파일 해시가 모두 일치해야 합니다. 조립기는 확인서 원본을 `provenance/official-sources.pending.json`으로 ZIP에 포함합니다.
- **FFmpeg/ffprobe 검증 보고서가 필수**입니다. `scripts/verify_ffmpeg_build_provenance.py`가 만든 `*.pending.json`의 소스 커밋·SHA-256·license family·configure 플래그·빌드 기록이 입력 매니페스트와 정확하게 일치하지 않으면 통합 ZIP을 만들지 않습니다. 이 보고서를 아카이브의 `provenance/ffmpeg-attestation.pending.json`에도 넣습니다.
- 생성물은 언제나 `redistribution_status=pending`. 공식 `managed-component-catalog.json`을 자동 변경하지 않습니다.

## 상류 검토 후보 (2026-11-06 기준)

| 도구 | 검토 후보 | 출처와 주의사항 |
|---|---|---|
| yt-dlp | `2026.10.26` | https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26 — Windows 독립 실행 파일 `yt-dlp.exe` / macOS `yt-dlp_macos`. PyInstaller 통합 배포물은 제3자 의존성으로 GPLv3+ 조합에 해당할 수 있으며 `THIRD_PARTY_LICENSES.txt` 고지가 필수 |
| Deno | `v2.9.8` | https://github.com/denoland/deno/releases/tag/v2.9.8 — MIT. `deno-x86_64-pc-windows-msvc.zip` 및 `deno-aarch64-apple-darwin.zip`의 공식 SHA-256SUM 파일을 다운로드 파일과 직접 대조 |
| FFmpeg + ffprobe | **아직 미선정** | https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md — 동일 source revision 및 build에서 두 바이너리 제작, `configure` 플래그/컴파일러/링크한 코덱·라이브러리 증거 필수. 무작위 제3자 바이너리를 승인하지 않음 |

위 값은 **조립을 위한 출처 후보**이지 번들 카탈로그로 등록된 릴리스 핀이나 재배포 승인 기록이 아닙니다. 특히 FFmpeg는 정확한 빌드 플래그를 검토하기 전에는 `approved`로 전환할 수 없습니다. 최신 버전은 정식 아티팩트 publication 직전에 다시 확인해야 합니다.

FFmpeg/ffprobe의 로컬 바이너리와 버전 출력에서 실제 configure 플래그가 일치하는지 확인하는 도구는 [FFmpeg 빌드 출처 검증](FFMPEG_BUILD_PROVENANCE.ko.md)에 정리합니다. 이 검증은 별도 license 승인을 대체하지 않으며, 단독 통합 ZIP을 합법적 배포물로 만들지 않습니다.

## 공식 배포물 원본 검증 (FFmpeg 조립 이전)

위 후보의 GitHub API 자산 SHA-256과 공식 upstream 체크섬 텍스트가 서로 일치하는지는 [공식 릴리스 출처 검증 절차](YOUTUBE_UPSTREAM_RELEASE_EVIDENCE.ko.md)의 `collect_youtube_upstream_release_evidence.py`로 재확인할 수 있습니다. 이는 바이너리를 직접 내려받아 확인하는 단계보다 앞선 검토용 증거이며, 카탈로그 승인과는 분리합니다.

수동으로 다운로드한 공식 upstream 바이너리는 조립 전에 **release asset 자체의 SHA-256와 크기**부터 검증합니다. 리뷰용 정확한 핀 목록은 [release/review/youtube-official-source-pins-2026-11-06.json](../release/review/youtube-official-source-pins-2026-11-06.json)에 저장되어 있습니다.

- yt-dlp `2026.10.26`: Windows `yt-dlp.exe`, macOS `yt-dlp_macos`
- Deno `v2.9.8`: Windows `deno-x86_64-pc-windows-msvc.zip`, macOS `deno-aarch64-apple-darwin.zip`

이 SHA-256는 공식 GitHub 릴리스 API의 **배포 자산 메타데이터**에서 확인한 것이며, 원본 파일 자체를 아직 다운로드/검증했다는 뜻이 아닙니다.

현재 리포지토리에는 별도 `YouTube Official Source Bytes and Native CLI (review only)` GitHub Actions 워크플로가 있습니다(`.github/workflows/youtube-official-source-bytes.yml`). 공식 GitHub 릴리스의 **실제 Windows/macOS 대상 원본 파일**을 각각 **Windows x86_64(`windows-2025`), macOS ARM64(`macos-15`) 러너**에 내려받아 위 검증기와 고정된 SHA-256·파일 크기로 대조합니다. 검증된 원본에서 추출한 yt-dlp·Deno만 **절대 경로·PATH 비움·shell 비활성화**로 `--version` 실행하여 고정한 릴리스 버전과 비교합니다(`scripts/verify_youtube_native_cli.py`). 결과는 `SOURCE-EVIDENCE.pending.json`과 그 해시에 연결된 `NATIVE-CLI-EVIDENCE.pending.json`으로 기록합니다. 일반 PR의 데스크톱 패키지 빌드와 무관하게 관련 소스/핀을 변경한 PR 또는 수동 요청에만 실행됩니다. 저장소에 실행 파일을 커밋하거나 공개 Actions 아티팩트로 업로드하지 않고 **pending JSON 메타데이터만** 업로드합니다. `--version` 성공은 정상 다운로드·JS challenge·FFmpeg·서명/공증·Windows/macOS 클린 머신 설치·재배포 권리를 증명하지 않습니다.

Windows 원본 파일을 별도로 확보한 뒤:

```bash
uv run --frozen python scripts/verify_youtube_official_sources.py \
  --target windows-x86_64 \
  --yt-dlp-asset /absolute/work/downloaded/yt-dlp.exe \
  --deno-zip /absolute/work/downloaded/deno-x86_64-pc-windows-msvc.zip \
  --output-dir /absolute/work/verified-windows
```

macOS arm64의 경우 `--target macos-aarch64`, `yt-dlp_macos`, `deno-aarch64-apple-darwin.zip`으로 변경합니다.

실행 결과에는 원본 SHA-256·크기·ZIP 내부의 Deno 추출 파일 해시가 기록됩니다. Deno ZIP은 루트의 단일 `deno`/`deno.exe` 파일 외의 항목, 심볼릭 링크 및 비정상적으로 큰 압축 해제 결과를 거부합니다. **원본 파일을 실행하지 않고 네트워크를 사용하지 않습니다.**

산출 디렉터리의 `yt-dlp[.exe]`와 `deno[.exe]`는 아래 조립 매니페스트의 `tools[].file`로 사용합니다. `SOURCE-EVIDENCE.pending.json`도 `official_sources_evidence`로 반드시 지정합니다. 조립기는 이 문서와 파일을 신뢰하는 대신 실제 로컬 바이트와 commit-tracked 핀을 다시 대조합니다. 임의 폴더로 실행 파일을 복사했거나 태그/URL/버전을 바꾼 경우 검증에 실패합니다. FFmpeg/ffprobe는 아직 승인된 소스·빌드가 없으므로 별도 제공·검증이 필요합니다.

이 검증은 GitHub 릴리스 checksum/signature의 독립 검증, 실행 파일 서명/공증, 재배포 법률 검토를 완료한 것으로 간주할 수 없습니다.

공식 자산 검증기를 수동 다운로드에 의존하지 않고 실행하려면 [공식 파일 직접 수신 및 Windows/macOS 네이티브 버전 검증](YOUTUBE_UPSTREAM_RELEASE_EVIDENCE.ko.md#공식-파일-직접-수신네이티브-실행-검토-117) 절차를 사용합니다. 해당 절차는 정확한 파일 해시와 실행 시 버전만 검증하며 YouTube 실영상 추출 성공, FFmpeg 통합, 법적 배포 승인이나 전체 clean-machine 설치 검증을 주장하지 않습니다.

## 매니페스트 형식

아래 파일을 `youtube-review-input.json` 같은 외부 작업 경로에 작성합니다. 실제 시스템에 있는 바이너리/라이선스 고지/빌드 기록의 **절대 경로**와 업스트림에서 확인한 SHA-256로 채웁니다. 자리표시자를 그대로 실행하지 않습니다.

```json
{
  "schema": 1,
  "target": "windows-x86_64",
  "version": "youtube-reviewed-candidate-1",
  "official_sources_evidence": "/absolute/work/verified-windows/SOURCE-EVIDENCE.pending.json",
  "bundle_license": "Multiple: GPL-3.0-or-later / MIT / FFmpeg-reviewed-license",
  "bundle_provenance": "Pinned upstream releases and reviewed FFmpeg build records",
  "tools": {
    "yt-dlp": {
      "file": "/absolute/work/verified-windows/yt-dlp.exe",
      "sha256": "REPLACE_WITH_UPSTREAM_VERIFIED_SHA256",
      "version": "2026.10.26",
      "upstream_revision": "2026.10.26",
      "upstream_url": "https://github.com/yt-dlp/yt-dlp/releases/tag/2026.10.26",
      "license": "GPL-3.0-or-later",
      "license_notice": "/absolute/work/notices/yt-dlp.txt"
    },
    "deno": {
      "file": "/absolute/work/verified-windows/deno.exe",
      "sha256": "REPLACE_WITH_UPSTREAM_VERIFIED_SHA256",
      "version": "2.9.8",
      "upstream_revision": "v2.9.8",
      "upstream_url": "https://github.com/denoland/deno/releases/tag/v2.9.8",
      "license": "MIT",
      "license_notice": "/absolute/work/notices/deno.txt"
    },
    "ffmpeg": {
      "file": "/absolute/work/ffmpeg.exe",
      "sha256": "REPLACE_WITH_BUILD_VERIFIED_SHA256",
      "version": "YOUR_REVIEWED_FFMPEG_VERSION",
      "upstream_revision": "YOUR_EXACT_FFMPEG_SOURCE_COMMIT",
      "upstream_url": "https://github.com/FFmpeg/FFmpeg",
      "license": "LGPL-2.1-or-later",
      "license_notice": "/absolute/work/notices/ffmpeg.txt"
    },
    "ffprobe": {
      "file": "/absolute/work/ffprobe.exe",
      "sha256": "REPLACE_WITH_BUILD_VERIFIED_SHA256",
      "version": "YOUR_REVIEWED_FFMPEG_VERSION",
      "upstream_revision": "YOUR_EXACT_FFMPEG_SOURCE_COMMIT",
      "upstream_url": "https://github.com/FFmpeg/FFmpeg",
      "license": "LGPL-2.1-or-later",
      "license_notice": "/absolute/work/notices/ffprobe.txt"
    }
  },
  "ffmpeg_build": {
    "configure_flags": ["--disable-nonfree", "--disable-autodetect"],
    "toolchain": "EXACT_BUILD_COMPILER_AND_VERSION",
    "build_record": "/absolute/work/ffmpeg-build-and-linked-libraries.txt",
    "attestation_file": "/absolute/work/ffmpeg-build-review.pending.json"
  }
}
```

macOS 빌드는 `target=macos-aarch64`로 변경하고 `*.exe` 대신 ARM64/Universal Mach-O 실행 파일 경로를 입력합니다. FFmpeg 빌드 설정도 **실제 결과물** 기준으로 기록해야 하며, 위 `configure_flags` 예시는 검토 전 확정된 설정이 아닙니다.

## 조립과 후속 승인

```bash
uv run --frozen python scripts/assemble_youtube_runtime_candidate.py \
  --manifest /absolute/work/youtube-review-input.json \
  --output /absolute/work/youtube-runtime-windows.zip
```

출력:

- `youtube-runtime-windows.zip`: `bin/{yt-dlp,deno,ffmpeg,ffprobe}.exe`, 4개 license notice, **공식 원본 확인서**, FFmpeg 빌드 기록/attestation, `BUNDLE-INVENTORY.json`.
- `youtube-runtime-windows.zip.pending.json`: 각 원본·최종 ZIP SHA-256, revision, 로컬 설치 검증 결과, **승인 대기** 상태.
- 기존 아티팩트/증빙 파일이 있으면 덮어쓰지 않습니다.

**선행 조건:** ① `verify_youtube_official_sources.py`의 공식 yt-dlp/Deno 자산 검증 결과 및 commit-tracked pin 일치, ② FFmpeg의 동일 파일·버전·소스 revision·configure/라이선스에 대한 `verify_ffmpeg_build_provenance.py` 보고서가 모두 준비돼야 ZIP 조립을 시작할 수 있습니다. 

후속 승인 순서는 [로컬 아티팩트 후보 관리](MANAGED_ARTIFACT_CANDIDATES.ko.md)의 URL·SHA-256 확인 → 라이선스/재배포 승인 → 배포 카탈로그 작성 → Windows/macOS `Desktop Packages` 수동 `require_managed_delivery` → 실제 YouTube 처리·복구·클린 머신 smoke입니다.

**현재 릴리스 차단 상태:** 네 개 도구를 하나의 승인된 바이너리 조합으로 게시하지 않았으므로 #29는 계속 open이며, 모델 비교(#34)와 라이선스 판단을 대신하지 않습니다.
