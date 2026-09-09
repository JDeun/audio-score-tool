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
- packaged command resolution은 등록된 managed tool 또는 기존 app-owned `components/bin`만 사용하며 system PATH로 fallback하지 않습니다.

## 설치 트랜잭션

1. artifact를 `.download-*` 임시 파일로 제한된 크기 내에서 수신
2. SHA-256 검증
3. `.staging-*` 디렉터리에 안전하게 압축 해제
4. tool path와 root containment 검증
5. versioned install directory로 atomic rename
6. `state.json`을 fsync 후 atomic replacement
7. 실패 시 staged/download artifact 제거
8. 기존 동일-version runtime을 교체 중 실패하면 backup을 복구
9. startup/setup recovery에서 남은 `.download-*` / `.staging-*` 제거

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
      "provenance": "...",
      "artifacts": {
        "windows-x86_64": {
          "url": "https://...",
          "sha256": "64 hex chars",
          "archive": "zip",
          "tools": {
            "yt-dlp": "bin/yt-dlp.exe",
            "ffmpeg": "bin/ffmpeg.exe"
          }
        }
      }
    }
  }
}
```

artifact를 실제로 게시하기 전까지 해당 platform entry는 비워 둡니다. **존재하지 않는 binary URL이나 검증하지 않은 license를 catalog에 가정해서 넣지 않습니다.**

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
