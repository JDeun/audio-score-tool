# FFmpeg/ffprobe 빌드 출처·라이선스 검증 (승인 전)

이 문서는 #29의 YouTube 관리형 런타임을 구성하는 FFmpeg/ffprobe 바이너리의 **동일 소스 버전·빌드 설정·파일 해시·외부 라이브러리 선언**을 검사하는 방법을 정리합니다.

공식 기준: [FFmpeg LICENSE](https://github.com/FFmpeg/FFmpeg/blob/master/LICENSE.md), [FFmpeg 라이선스 및 배포 준수 안내](https://ffmpeg.org/legal.html), [FFmpeg INSTALL](https://github.com/FFmpeg/FFmpeg/blob/master/INSTALL.md).

## 검증 조건

- Windows x86_64의 PE/AMD64 또는 macOS ARM64의 Mach-O 헤더 및 각 로컬 바이너리 SHA-256 확인
- 정확히 40자리 FFmpeg upstream commit SHA와 해당 공식 GitHub commit URL
- 같은 `version`의 `ffmpeg -version`과 `ffprobe -version` 출력에서 한 줄의 `configuration:`을 각각 추출하고, 두 결과와 입력 매니페스트의 `configure_flags`가 일치해야 함
- `--enable-nonfree`, 모순된 GPL/version3 설정, 필수 `ffmpeg`/`ffprobe` 프로그램 비활성화 금지
- `--enable-lib*` 외부 라이브러리별 license/version/upstream pin/HTTPS URL 및 검토 대기 `review_status=pending` 요구
- GPL 라이브러리와 `--enable-gpl`, LGPLv3 또는 GPLv3 조건이 있는 라이브러리와 `--enable-version3` 규칙 대조
- 바이너리·각 버전 리포트·라이선스 고지·빌드 기록의 파일 해시를 보고서에 기록

**중요:** 이 도구는 외부 실행파일을 실행하지 않습니다. 명령의 **실제 출력이라고 주장하는 텍스트 파일**을 검사할 뿐입니다. 이 텍스트가 해당 바이너리에서 생성됐다는 사실을 암호학적으로 증명하지 못하며, 라이브러리 링크 목록도 바이너리에서 직접 추출하지 않습니다. 실물 빌드 재현과 법적 배포 승인은 별도 acceptance로 남겨 둡니다.

## 빌드 담당자가 준비할 자료

공식 FFmpeg source의 정확한 commit에서 Windows/macOS 빌드를 수행하고, 해당 운영체제에서 아래 자료를 수집합니다.

```bash
ffmpeg -version > /absolute/work/reports/ffmpeg-version.txt
ffprobe -version > /absolute/work/reports/ffprobe-version.txt
```

라이선스 notice, `configure` 실행 내역, compiler/linker 버전, 대상 triple, 사용한 외부 라이브러리·버전·소스 링크·라이선스, 재빌드 입력 자료를 별도 `ffmpeg-build-record.txt`에 보존합니다. 위 명령의 stdout은 **바이너리 실제 실행이 허용된 격리된 빌드/검증 환경에서** 수집하고, 이 증거 검증기는 따로 실행합니다.

## 매니페스트 예제

```json
{
  "schema": 1,
  "target": "windows-x86_64",
  "version": "EXACT_REVIEWED_FFMPEG_VERSION",
  "source_revision": "0000000000000000000000000000000000000000",
  "source_url": "https://github.com/FFmpeg/FFmpeg/commit/0000000000000000000000000000000000000000",
  "toolchain": "EXACT_COMPILER_LINKER_TARGET",
  "license_notice": "/absolute/work/notices/ffmpeg-license.txt",
  "build_record": "/absolute/work/reports/ffmpeg-build-record.txt",
  "configure_flags": [
    "--disable-nonfree",
    "--disable-autodetect",
    "--disable-doc"
  ],
  "external_libraries": {},
  "tools": {
    "ffmpeg": {
      "file": "/absolute/work/bin/ffmpeg.exe",
      "sha256": "REPLACE_WITH_REAL_FFMPEG_SHA256",
      "version_report": "/absolute/work/reports/ffmpeg-version.txt",
      "license": "LGPL-2.1-or-later"
    },
    "ffprobe": {
      "file": "/absolute/work/bin/ffprobe.exe",
      "sha256": "REPLACE_WITH_REAL_FFPROBE_SHA256",
      "version_report": "/absolute/work/reports/ffprobe-version.txt",
      "license": "LGPL-2.1-or-later"
    }
  }
}
```

**예시의 commit/버전/해시/빌드 플래그는 실물 검증값이 아닙니다.** 실제 출력된 `configuration:` 항목을 가공하거나 생략하지 말고 그대로 명시해야 하며, 외부 라이브러리가 있으면 그 이름을 `external_libraries`에 모두 기록해야 합니다.

## 사용법

```bash
uv run --frozen python scripts/verify_ffmpeg_build_provenance.py \
  --manifest /absolute/work/ffmpeg-build-manifest.json \
  --output /absolute/work/ffmpeg-build-review.pending.json
```

결과의 `local_binary_sha256_verified`는 로컬 파일과 입력 해시가 일치한다는 의미입니다. `supplied_version_reports_consistent`는 제공된 두 텍스트 보고서와 설정 매니페스트의 내용이 일치한다는 의미입니다. 그러나 아래 항목은 **항상 false**입니다.

- `version_reports_cryptographically_bound_to_binaries`
- `binary_execution_verified`
- `reproducible_rebuild_verified`
- `linked_libraries_independently_inspected`

검증된 로컬 후보에 대해서도 `redistribution_status=pending`과 `legal_review_status=pending`을 유지합니다. 그다음 [YouTube 런타임 통합 ZIP 조립](YOUTUBE_MANAGED_BUNDLE.ko.md)과 [#29](https://github.com/JDeun/audio-score-tool/issues/29)의 승인 절차로 넘깁니다.

## 배포 전 별도 확인 항목

- 정확한 FFmpeg 소스 제공 방식, LGPL/GPL 고지·저작권 및 수정 패치 제공, 설치 패키지와 일치하는 소스 재현
- 사용한 외부 라이브러리의 license/linked dependencies와 빌드 플래그 교차 검토
- 실제 빌드 머신의 `ffmpeg -version`/`ffprobe -version`, 사용 가능한 codec·format 및 유효한 파일 변환 실행
- Windows/macOS 서명·공증 및 clean-machine 입력/출력 동작
- ZIP 통합 아티팩트의 원격 게시 바이트/SHA-256 대조와 관리형 런타임 설치·복구 시험

이 스크립트는 **라이선스 판정 자동화가 아니라 기술적 부정합 검출 도구**입니다. `--enable-nonfree` 배포를 금지하고 주요 GPL/v3 조건을 찾아내지만, 모든 라이선스 결합 및 법적 의무를 완전하게 증명하지는 않습니다.
