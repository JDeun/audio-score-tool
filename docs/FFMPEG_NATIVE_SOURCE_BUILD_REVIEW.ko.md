# FFmpeg/ffprobe 공식 소스 네이티브 빌드 검증 (승인 전)

## 목적과 범위

[#29](https://github.com/JDeun/audio-score-tool/issues/29)의 Windows x86_64 및 Apple Silicon macOS용 FFmpeg·ffprobe 배포 후보는 **아직 승인되지 않았습니다.** 기존 [FFmpeg 출처·라이선스 검증](FFMPEG_BUILD_PROVENANCE.ko.md)은 임의로 제출된 버전 텍스트를 바이너리와 직접 연결할 수 없었습니다.

이를 보완하기 위해 `.github/workflows/ffmpeg-native-build-review.yml`은 **실제 GitHub-hosted Windows/macOS 환경**에서 FFmpeg 공식 소스의 정확한 릴리스 커밋을 checkout하여 ffmpeg·ffprobe를 컴파일하고, 생성된 실행 파일의 CLI 출력과 로컬 오디오 변환 기능을 검증합니다. 모델 추론/YouTube 네트워크 다운로드/데스크톱 패키지 빌드는 포함하지 않습니다.

## 고정된 공식 후보

- 릴리스: FFmpeg `n9.0.2` (2026-09-18), 공식 커밋 `946fcce07b6dcd0331c8cc609192aeff5e1924f8`
- 출처: <https://github.com/FFmpeg/FFmpeg/commit/946fcce07b6dcd0331c8cc609192aeff5e1924f8>
- 입력: `release/review/ffmpeg-native-source-pin-2026-11-07.json`
- 대상: `windows-2025` x86_64 (MSYS2 UCRT64), `macos-15` ARM64
- 구성: `--disable-gpl --disable-nonfree --disable-version3 --disable-autodetect`, 내장 ffmpeg·ffprobe / static FFmpeg libs, 사전 검토한 configure flags
- 예상 선언 라이선스 계열: `LGPL-2.1-or-later`. 이 분류는 **자동 법률 승인 또는 전체 의존성 라이선스 감사가 아닙니다.**
- FFmpeg 공식 [라이선스](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md) 및 [재배포 체크리스트](https://ffmpeg.org/legal.html) 참고.

OS별 컴파일러/링크 의존성, 플래그, 실행 파일 해시는 대상 러너의 실제 결과로부터 수집하며 **미리 가정한 SHA-256으로 채우지 않습니다.**

## 검증 경계

1. `actions/checkout`으로 `n9.0.2` checkout 후 `git rev-parse HEAD`를 고정 커밋에 대조합니다.
2. `./configure`에 고정된 LGPL 검토용 설정을 전달하여 각 OS에서 `ffmpeg`·`ffprobe`를 **실제로 빌드**합니다. FFmpeg 소스 및 의존 라이브러리를 `Desktop Packages` 워크플로의 빌드에 혼합하지 않습니다.
3. `scripts/verify_ffmpeg_native_build.py`는 운영체제/CPU와 PE 또는 Mach-O 파일 형식을 확인하고 SHA-256을 기록한 뒤, 두 바이너리를 **절대 경로, 빈 PATH, shell 미사용, timeout 적용** 조건으로 각각 `-version` 실행합니다.
4. 실제 stdout의 버전·컴파일러·`configuration:` 플래그를 원본 pin과 교차 검증합니다. 실행 전후 SHA-256이 바뀌면 실패합니다.
5. FFmpeg에서 **자체 합성 440 Hz 사인파**를 WAV/PCM 44.1 kHz로 생성하고, ffprobe에서 오디오 코덱·샘플레이트를 다시 검사합니다. 저작권 음원이나 YouTube 콘텐츠를 수집하지 않습니다.
6. 이 결과의 `NATIVE-FFMPEG-EVIDENCE.pending.json`과 기존 오프라인 검증기의 `FFMPEG-BUILD-REVIEW.pending.json`, 빌드 기록·실제 `-version` 보고서 **텍스트만** CI artifact로 업로드합니다. GitHub Actions public artifact로 실행파일·소스 archive를 업로드하지 않습니다.

이 검증은 업스트림 GPG/PQ 서명 독립 검증, 외부 codec/shared dependency의 전체 링크 검사, 제3자 라이선스 고지/소스 배포 준수, 독립된 두 번째 빌드를 통한 reproducible rebuild, 코드 서명/공증, 실제 YouTube 다운로드를 증명하지 않습니다. 결과 및 catalog 상태는 계속 `pending`입니다.

## 일반 개발 CI와 분리

이 워크플로는 `workflow_dispatch` 또는 소스 pin·검증기·전용 테스트·워크플로가 바뀐 PR에서만 실행합니다. 일반 코드 PR의 필수 `CI / verify`에 Windows/macOS 컴파일 단계를 추가하지 않습니다. 스모크가 성공하더라도 단일 FFmpeg·ffprobe 런타임이 상용/배포 승인됐다고 간주하지 않습니다.

## 실제 #29 완료까지 남는 단계

- 이 검증에서 생성한 파일과 빌드 재현 입력/소스·라이선스 의무를 대상으로 보안·법적 검토
- macOS codesign/notarization과 Windows 재배포 가능한 toolchain/DLL 포함 여부 확인
- 최종 FFmpeg/ffprobe 후보의 결정된 바이너리 해시·빌드 설정을 검토 후 동결, 동일 파일에 대한 추가 검증
- [YouTube 런타임 후보 조립](YOUTUBE_MANAGED_BUNDLE.ko.md)에 yt-dlp·Deno·FFmpeg·ffprobe 네 개를 통합하고 전체 license notices/source/provenance 검사
- 승인된 파일을 HTTPS로 게시한 뒤 다운받은 실제 바이트·무결성 및 클린 머신 Setup Center 설치→YouTube 입력→FFmpeg 실행→MusicXML 파이프라인 검증

**`managed-component-catalog.json`은 계속 `artifacts: {}`로 유지합니다.** 위 절차는 법적 배포 승인을 대체하지 않습니다.
