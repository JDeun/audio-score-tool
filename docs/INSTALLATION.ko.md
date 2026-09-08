# 설치 및 첫 실행 설계

AudioScoreTool의 설치 목표는 다음입니다.

> **새 PC에서 설치 파일 하나를 실행한 뒤, CLI 지식 없이 첫 악보를 만들 수 있어야 합니다.**

## 현재 배포 상태

설치 방법은 세 등급을 구분합니다.

| 등급 | 용도 | 상태 |
|---|---|---|
| source/development | 개발·기여 | 사용 가능 |
| unsigned Desktop Packages | Windows/macOS/Linux QA | CI에서 생성 가능 |
| signed stable installer | 일반 사용자 공식 배포 | signing/acceptance 전 (#22) |

GitHub Actions가 만드는 Windows `.exe`와 macOS `.dmg`를 사용할 수는 있지만, signing/notarization이 완료되기 전에는 **공식 release verified 설치본으로 안내하지 않습니다.** 실제 stable distribution activation은 [Issue #22](https://github.com/JDeun/audio-score-tool/issues/22)에서 추적합니다.

## 사용자에게 요구하지 않는 것

일반 사용자는 다음을 알 필요가 없어야 합니다.

- `pip`, `uv`, `npm`, `cargo` 사용법
- Python/Node/Rust 개발환경 구성
- PATH 수동 편집
- 개별 Python package의 가상환경 관리

Desktop package는 Tauri app과 Python orchestration sidecar를 함께 배포합니다. repository 개발 명령은 일반 사용자 설치 절차가 아닙니다.

## 입력별 최소 요구사항

| 입력/기능 | 추가 요구사항 |
|---|---|
| MusicXML/XML/MXL 직접 import | 기본 앱 |
| MIDI 직접 import | 기본 dependency의 music21 |
| 음원/YouTube 자동 채보 | 선택한 transcription engine/model |
| PDF/이미지 OMR | Audiveris |
| MusicXML/MIDI 편집·export | 기본 앱 |
| PDF/파트 PDF export | LilyPond + `musicxml2ly` |
| 가사 인식/정렬 | WhisperX |

즉 Audiveris나 LilyPond가 없다는 이유로 MusicXML/MIDI 기반 핵심 workflow까지 `준비 안 됨`으로 처리하지 않습니다.

## Setup Center

첫 실행 온보딩이 끝난 뒤 기본 채보 환경이 준비되지 않았다면 Setup Center가 순차적으로 열립니다. 이후 앱의 설치 도우미에서 다시 열 수 있습니다.

구성요소를 기능 영향도에 따라 구분합니다.

### 필수 — 자동 채보를 사용할 때

```text
음원 → 자동 채보 → 편집 가능한 MusicXML
```

- 선택된 transcription engine
- 필요 시 관리형 `uv/uvx` runtime
- MuScriptor 사용 시 Hugging Face 인증과 모델 준비

MusicXML/MXL/MIDI 직접 import만 사용하는 경우 transcription model은 필수가 아닙니다.

### 권장

```text
기본 악보 workflow + 가사 + PDF 출판
```

- WhisperX: 가사 인식/정렬
- LilyPond + `musicxml2ly`: PDF 생성

### 선택

- Audiveris: PDF/이미지 OMR
- FFmpeg + FluidSynth + SoundFont: audio evidence 검증
- LLM/Vision API: 보조 검증
- Chromaprint/fpcalc: 사용자가 요청한 원음 fingerprint 기반 곡 식별

이 기능들의 부재가 무관한 입력/편집 workflow를 차단해서는 안 됩니다.

## MuseScore 비의존 정책

AudioScoreTool은 MuseScore 실행 파일이나 MuseScore CLI를 핵심 runtime/fallback으로 호출하지 않습니다.

```text
앱 내 미리보기        OSMD
MIDI ↔ MusicXML       music21
MusicXML → PDF         LilyPond + musicxml2ly
PDF/이미지 → MusicXML  Audiveris
파트 분리              AudioScoreTool 자체 MusicXML 처리
```

따라서 MuseScore 설치 여부는 readiness에 영향을 주지 않습니다.

## 자동 설치 정책

앱이 사용자 입력을 섞은 임의 shell command를 조합해 실행하지 않습니다. 운영체제별로 검토된 고정 package-manager recipe만 사용합니다.

### macOS

Homebrew가 이미 설치되어 있을 때 검토된 구성요소를 Setup Center에서 준비할 수 있습니다.

```bash
brew install uv
brew install ffmpeg
brew install fluid-synth
brew install lilypond
```

Finder에서 실행한 GUI app은 terminal PATH와 다를 수 있으므로 `/opt/homebrew/bin`, `/usr/local/bin` 같은 일반 설치 위치도 탐색합니다.

### Windows

`winget`을 사용할 수 있을 때 검증된 package ID만 자동 설치 대상으로 둡니다. package ID와 공급망을 고정하지 못한 구성요소를 임의 검색·설치하지 않습니다.

### Linux

배포판 차이가 크므로 단일 package manager recipe를 강제하지 않습니다. 공식 다운로드 또는 사용 중인 배포판 package manager를 사용합니다.

## AI 모델 관리자

앱의 AI 모델 관리 UI는 모델 크기, 예상/실제 cache, 선택 상태, 디스크 공간, 라이선스와 상용 모드 허용 여부를 보여주는 것을 목표로 합니다.

기본 정책:

```text
자동 다운로드 = OFF
명시적 사용자 동의 후 다운로드
상용 모드에서 비상업 weights 차단
```

MuScriptor 공개 weights는 CC BY-NC 4.0이므로 personal/non-commercial mode에서만 허용합니다. 모델 license 수락이나 authentication이 필요한 경우 공식 provider flow를 사용하고 AudioScoreTool DB에 token 값을 직접 저장하지 않습니다.

## Hugging Face 인증

gated weights가 필요한 경우 사용자가 공식 browser/device authentication을 수행하게 합니다.

```text
1. 모델 라이선스 확인/수락
2. 공식 인증 시작
3. browser/device flow 완료
4. 앱에서 readiness 재검사
5. 사용자가 선택한 모델 준비
```

token 저장은 Hugging Face tooling의 책임으로 유지합니다.

## 외부 도구 fallback

자동 설치를 지원하지 않는 항목은 공식 배포 페이지로 연결하고 설치 후 `다시 검사`로 readiness를 평가합니다.

- uv: `https://docs.astral.sh/uv/getting-started/installation/`
- LilyPond: `https://lilypond.org/download.html`
- Audiveris: `https://audiveris.github.io/audiveris/`
- FFmpeg: `https://ffmpeg.org/download.html`
- FluidSynth: `https://www.fluidsynth.org/download/`
- Hugging Face: `https://huggingface.co/`

## LLM은 필수 설치 항목이 아님

LLM/Vision validator는 기본 OFF인 선택 기능입니다.

```text
Local OpenAI-compatible endpoint
또는
HTTPS hosted OpenAI-compatible API
```

LLM을 사용하지 않아도 ingest → edit → deterministic validation → export 핵심 workflow가 동작해야 합니다.

## 개발자 설치

```bash
git clone https://github.com/JDeun/audio-score-tool.git
cd audio-score-tool
uv sync --extra dev

cd desktop
npm ci
npm run desktop:dev
```

CI와 동일한 검증 명령은 [`../CONTRIBUTING.md`](../CONTRIBUTING.md)를 참조하십시오.

## stable installer 활성화 전 남은 운영 작업

코드 구현과 package build 외에 실제 배포 계정/credential이 필요한 단계입니다.

1. Windows Authenticode certificate provisioning
2. macOS Developer ID signing/notarization credential provisioning
3. Tauri updater private signing key/public key 설정
4. clean Windows/macOS install → launch → update → relaunch acceptance
5. invalid updater signature/manifest rejection 확인
6. stable Release artifact/checksum/manifest 검증

이 작업은 [#22](https://github.com/JDeun/audio-score-tool/issues/22)에서만 완료로 판정합니다.

외부 GPL/AGPL binary를 installer에 직접 bundle하기 전에는 해당 배포 의무를 별도로 검토합니다.