# YouTube 런타임 공식 릴리스 출처 및 체크섬 확인

이 문서는 #29에서 Windows x86_64 / macOS ARM64용 **yt-dlp + Deno**의 공식 upstream 자산을 선택하기 위한 증거 수집 절차입니다. FFmpeg/ffprobe 바이너리 빌드·라이선스 심사와 최종 통합 패키징은 별도이며, 여기 나온 해시는 **GitHub 릴리스 API 메타데이터**입니다.

## 공식 릴리스 API 확인 (2026-11-06 UTC)

| 구성요소 | 태그 | 대상 | GitHub 릴리스 자산 | GitHub API에 기재된 SHA-256 |
|---|---|---|---|---|
| yt-dlp | `2026.10.26` | Windows x86_64 | `yt-dlp.exe` | `f5389d3698ecde4ef06f4e6b1ce0294fe9ac1396228c8990b8d3416d6d177a7d` |
| yt-dlp | `2026.10.26` | macOS Universal | `yt-dlp_macos` | `0f922c15ccc0b83eefa1c8bc9104e434318c4bf16e408e1ee93b7745a6efe0aa` |
| Deno | `v2.9.8` | Windows x86_64 | `deno-x86_64-pc-windows-msvc.zip` | `cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf` |
| Deno | `v2.9.8` | macOS ARM64 | `deno-aarch64-apple-darwin.zip` | `9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e` |

공식 릴리스 메타데이터:
- https://api.github.com/repos/yt-dlp/yt-dlp/releases/tags/2026.10.26
- https://api.github.com/repos/denoland/deno/releases/tags/v2.9.8

**주의:** 위 네 해시는 실제 바이너리 바이트와 대조한 결과가 아닙니다. GitHub API의 `assets[].digest` 값이며, 배포 적법성·코드 서명·실행 안전성·FFmpeg 조합 확인을 의미하지 않습니다. 태그는 재현성을 위한 후보 핀이고 자동으로 최신 버전을 추종하지 않습니다.

## 자동 증거 수집

`scripts/collect_youtube_upstream_release_evidence.py`는 두 공식 저장소의 **태그를 지정한** GitHub API만 조회합니다. 각 목표 운영체제에 맞는 정확한 자산명과 API SHA-256, 크기, 다운로드 URL을 확인하고, 가능하면 작은 upstream 체크섬 텍스트 파일도 가져와 내용과 자산 SHA-256을 상호 대조합니다.

```bash
uv run --frozen python scripts/collect_youtube_upstream_release_evidence.py \
  --target windows-x86_64 \
  --yt-dlp-tag 2026.10.26 \
  --deno-tag v2.9.8 \
  --output /tmp/youtube-upstream-windows.pending.json

uv run --frozen python scripts/collect_youtube_upstream_release_evidence.py \
  --target macos-aarch64 \
  --yt-dlp-tag 2026.10.26 \
  --deno-tag v2.9.8 \
  --output /tmp/youtube-upstream-macos.pending.json
```

검증용 텍스트 파일:
- yt-dlp: 동일 태그의 `SHA2-256SUMS`; 대상 실행 파일명에 대응하는 체크섬이 정확히 하나 존재해야 함
- Deno: 각 OS별 `deno-*.zip.sha256sum`; ZIP의 SHA-256과 일치해야 함
- 텍스트 파일 자체의 SHA-256도 GitHub API의 `assets[].digest`와 대조합니다.

검증이 실패하면 산출물 생성에 실패합니다. 외부 URL 우회, 자산명 변조, 체크섬 내용 불일치, 사전 출시 버전 또는 단순 `latest` 표기는 허용하지 않습니다. **서명 검증은 별개입니다.** yt-dlp의 `SHA2-256SUMS.sig`에 대한 GPG 서명 검증은 이 스크립트의 범위가 아니며, 공식 신뢰 키 검증 절차와 함께 추가로 수행해야 합니다.

네트워크가 체크섬 파일을 제공하지 않을 때는 `--metadata-only`로 API 메타데이터만 수집할 수 있으나 `checksum_file_verified=false`를 명시하여 확정 증거로 사용하지 않습니다.

## 공식 파일 직접 수신·네이티브 실행 검토 (#117)

수동 다운로드 대신 `scripts/fetch_youtube_official_assets.py`로 위 **고정 핀 파일**의 공식 Windows/macOS 배포 파일 두 개를 직접 가져와 바이트 단위로 대조할 수 있습니다. 정확한 upstream 태그·자산명·URL·크기·SHA-256만 허용하고, 리디렉션은 GitHub 소유 HTTPS 다운로드 도메인에서만 추적합니다. 잘못된 크기/해시·압축 파일·CPU 아키텍처에서 실패하면 완성된 출력 폴더를 만들지 않습니다.

```bash
python scripts/fetch_youtube_official_assets.py \
  --target windows-x86_64 \
  --output-dir /absolute/work/windows-official-reviewed

# 일치하는 대상 OS의 격리된 검증 환경에서만:
python scripts/fetch_youtube_official_assets.py \
  --target macos-aarch64 \
  --output-dir /absolute/work/macos-official-reviewed \
  --execute-native
```

- `--execute-native`는 해당 OS/아키텍처에서만 `yt-dlp --ignore-config --no-remote-components --version`과 `deno --version`을 실행하고, 고정된 태그 버전과 실제 출력을 비교합니다. 일반 검증은 바이너리를 실행하지 않습니다.
- 출력에는 `SOURCE-EVIDENCE.pending.json`과 `DOWNLOAD-EVIDENCE.pending.json`이 들어갑니다. 공식 파일을 가져왔고 SHA-256이 일치한 것과, **실제 영상 다운로드가 성공한 것**은 분명히 다릅니다.
- `yt-dlp.exe` 및 `yt-dlp_macos` 같은 공식 PyInstaller 독립 실행 파일에는 upstream의 `yt-dlp-ejs`가 포함됩니다(https://github.com/yt-dlp/yt-dlp/wiki/EJS). 이 후보는 외부 Deno를 명시적으로 연결하되 실행 중 `--no-remote-components`를 사용합니다. EJS 관련 별도 원격 다운로드 승인을 암묵적으로 허용하지 않습니다.
- [검토 전용 GitHub Actions](../.github/workflows/youtube-official-native-review.yml)은 Windows x86_64/macOS ARM64 호스팅 러너에서 각 버전을 검증합니다. 일반 PR의 필수 CI, Windows/macOS/Linux 데스크톱 패키지 빌드와 분리됩니다. CI 아티팩트는 `*.pending.json` 증빙만 올리며, 라이선스 승인 전 **실행 파일/ZIP을 업로드하거나 공개하지 않습니다**.
- SHA-256가 공식 release API/체크섬 정보와 같다는 증거는 바이너리 서명·GPG 서명 검증이나 제3자 라이선스 승인을 대체하지 않습니다. FFmpeg/ffprobe는 별도 빌드/검토가 필요하고 `managed-component-catalog.json`의 `artifacts`는 계속 비어 있습니다.

## 이후 실제 배포까지 남는 단계

1. 위 보고서로 공식 파일을 내려받고 **실제 바이트의 SHA-256**과 비교합니다.
2. Windows/macOS 대상에 맞는 실행 파일/ZIP 내부 실행 파일을 추출해 PE/Mach-O 아키텍처를 검증합니다.
3. yt-dlp PyInstaller 조합의 `THIRD_PARTY_LICENSES`와 Deno MIT 고지를 확인합니다.
4. 별도 FFmpeg/ffprobe 자체 빌드 또는 검증된 제공자 빌드의 정확한 revision·configure flags·linked libraries·재배포 조건을 확정합니다.
5. [YouTube 통합 번들 조립 절차](YOUTUBE_MANAGED_BUNDLE.ko.md)로 네 도구의 해시·라이선스 고지·빌드 증거를 통합해 `pending` ZIP을 만듭니다.
6. 법적·기술적 검토와 실제 HTTPS 파일 해시 검증을 거친 이후에만 `managed-component-catalog.json`에 등록하고, Windows/macOS managed-delivery smoke 및 클린 머신 기능 검증을 수행합니다.

이 증거 수집 절차는 실제 YouTube 영상 다운로드를 하지 않으며, #34의 AMT 모델 품질·최종 모델 결정을 포함하지 않습니다.
