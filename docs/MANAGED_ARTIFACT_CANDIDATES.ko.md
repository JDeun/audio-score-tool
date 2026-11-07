# 앱 관리형 런타임 아티팩트 준비 절차 (출시 승인 전)

이 문서는 #29의 Windows/macOS/Linux별 실제 아티팩트를 **라이선스와 출처가 검토되기 전에는 게시하지 않는** 작업 절차를 정의합니다.

## 1. 로컬 아카이브 후보 생성

공식 출처와 배포 조건을 확인한 다음 로컬 Windows/macOS/Linux 아카이브를 준비합니다. AudioScoreTool의 개발 도구는 로컬 아카이브의 SHA-256, 안전한 압축 해제, 실행 도구 상대 경로 및 설치 상태를 자체 app-data와 분리된 임시 디렉터리에서 검사할 수 있습니다.

```bash
uv run --frozen python scripts/prepare_managed_artifact_candidate.py \
  --component youtube_runtime \
  --target windows-x86_64 \
  --version REVIEWED-VERSION \
  --archive /absolute/path/to/reviewed-youtube-runtime.zip \
  --archive-format zip \
  --url https://YOUR-REVIEWED-HTTPS-ASSET-URL \
  --tool yt-dlp=bin/yt-dlp.exe \
  --tool deno=bin/deno.exe \
  --tool ffmpeg=bin/ffmpeg.exe \
  --tool ffprobe=bin/ffprobe.exe \
  --license 'REVIEWED-LICENSE-IDENTIFIERS' \
  --provenance 'PINNED-UPSTREAM-AND-LOCAL-BUILD-RECORD' \
  --upstream-revision REVIEWED-UPSTREAM-REVISION \
  --output /tmp/youtube-windows-candidate.json
```

위 값은 **명령 형식을 보여 주는 자리표시자**입니다. URL·버전·라이선스·업스트림 리비전을 실제로 확인한 값으로 바꾸기 전에는 실행 결과를 배포 승인이나 실사용 가능 증거로 간주하지 않습니다. `yt-dlp`, `deno`, `ffmpeg`, `ffprobe` 등은 실제 아카이브에 모두 있어야 합니다.

도구가 허용하는 component 이름은 `transcription_engine`, `youtube_runtime`, `audiveris`, `whisperx`, `audio_validation`뿐입니다.

## 2. 후보 파일의 의미

출력되는 JSON은 실제 릴리스 카탈로그가 아니라 **검토용 candidate + 로컬 검사 기록**입니다.

- `candidate.redistribution_status`는 언제나 `pending`입니다. CLI는 법적 검토를 통과시킬 수 없습니다.
- `candidate.artifacts[target].sha256`은 **로컬 파일의** 해시입니다. 나중에 공식 HTTPS URL로 업로드한 실제 바이트와 일치하는지는 별도 검증해야 합니다.
- `local_validation.tool_sha256`은 안전하게 압축 해제된 도구 파일의 로컬 해시입니다.
- ZIP/TAR/RAW의 위험한 경로, 링크, 손상, 누락된 도구는 기존 `managed_components.py`의 설치·무결성 규칙으로 거부됩니다.
- CLI는 **네트워크 다운로드나 도구 실행을 하지 않습니다.** `remote_artifact_verified`, `tools_executed`, `clean_machine_verified`는 항상 `false`입니다.
- 번들 `src/audio_score_tool/managed-component-catalog.json`을 자동 갱신·덮어쓰지 않습니다.

## 3. HTTPS 배포 파일의 실제 바이트 확인 (승인 대기 증빙)

로컬 후보를 생성했다고 해서 해당 URL에 **실제로 같은 ZIP/실행 파일이 게시됐다는 뜻은 아닙니다.** 배포 담당자가 출처·저작권 조건을 검토하여 업로드한 아티팩트에만 아래 명령을 사용합니다.

```bash
# 기본값: 후보 메타데이터만 확인, 네트워크 없음
uv run --frozen python scripts/verify_managed_artifact_publication.py \
  /private/youtube-windows-candidate.json

# 명시적 --fetch 지정 시에만 해당 HTTPS URL에서 배포 바이트를 수신
uv run --frozen python scripts/verify_managed_artifact_publication.py \
  /private/youtube-windows-candidate.json \
  --fetch \
  --local-archive /private/youtube-windows-reviewed.zip \
  --output /private/youtube-windows-remote.pending.json
```

검증기는 다음 모두를 실제 설치 루틴과 공유합니다.

- 후보의 component·platform·tool mapping, upstream revision, operator-reviewed license 문자열, local SHA-256과 미승인(`pending`) 상태를 먼저 검사합니다.
- 지정된 공개 HTTPS 아티팩트를 크기 제한 내에서 스트리밍 수신하고 원래 로컬 후보의 archive SHA-256와 재대조합니다. `--local-archive`를 지정하면 해당 파일도 다시 해시합니다.
- 실제 다운로드 바이트를 별도의 임시 앱 관리 루트에 설치하여 안전한 압축 해제와 **모든 도구 SHA-256**를 검증합니다.
- 완료된 보고서에는 URL 원문/바이너리/임시 경로를 넣지 않고 URL의 해시, archive SHA-256/크기, 도구별 SHA-256와 확인 시각을 기록합니다.
- 다운로드/아카이브/도구가 서로 다르거나 검증이 실패하면 성공 보고서가 생성되지 않습니다.
- 보고서는 반드시 `redistribution_status=pending`, `approval_required=true`, `tools_executed=false`, `clean_machine_verified=false`로 유지됩니다. **재배포 승인, 서명, 원격 URL 불변성, 상용 모델 사용권, clean-machine 실동작은 별도의 검토 단계입니다.**
- `managed-component-catalog.json`에 자동으로 아티팩트를 추가하거나 배포 상태를 승인으로 전환하지 않습니다.

로컬 체크섬은 후보 생성기에서, 실제 URL 바이트 체크섬은 이 검증기에서 별도로 획득하고 두 증거를 연결해야 카탈로그 검토 단계로 진행합니다. HTTP 리다이렉트나 잘못된 출처 정책을 우회해 임의 시스템 파일을 설치하는 도구가 아닙니다.

## 4. 실제 게시 이전 필수 검토

- [ ] 정확한 upstream version·commit·모델 weight revision·포함 라이브러리 목록/해시 확정
- [ ] Windows/macOS용 실행 파일과 runtime/JRE/FFmpeg build flags 검토, 권리 증거 저장
- [ ] 라이선스와 제3자 고지/소스 제공 의무를 배포 artifact 수준에서 검토
- [ ] 재배포 승인 절차를 별도로 완료 (`pending` → 검토된 `approved`)
- [ ] HTTPS 게시 위치의 아티팩트를 실제 다운로드하고 로컬 원본과 SHA-256 대조
- [ ] Windows/macOS clean-machine에서 app-managed 설치·복구·런타임 시작 확인
- [ ] 직접 재설치, 중단된 다운로드, checksum mismatch, 기존 설치 rollback 인수시험
- [ ] Setup Center가 실제 출고 카탈로그와 설치 상태를 정확히 표시하는지 확인
- [ ] 요구되는 real-music 평가 및 commercial 모델 선정은 별도 #34 완료 조건으로 유지

메타데이터의 `approved` 문자열만으로 실제 바이너리 설치 및 clean-machine 검증까지 수행했다고 주장하지 않습니다. 최종 릴리스에는 `scripts/check_managed_publication.py --require-ready`와 실물/법적 검증 증거가 모두 필요합니다.

자세한 신뢰 경계 및 배포 승인 요건은 [MANAGED_RUNTIME.ko.md](MANAGED_RUNTIME.ko.md), [THIRD_PARTY_LICENSES.ko.md](THIRD_PARTY_LICENSES.ko.md), [#29](https://github.com/JDeun/audio-score-tool/issues/29)을 참조하십시오.
